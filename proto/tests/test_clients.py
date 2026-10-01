"""The wrappers and interceptors against an in-process gRPC server with fake servicers."""

import socket
import threading
import time
from concurrent import futures

import grpc
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from contracts.agent import AgentClient
from contracts.agent.v1 import agent_pb2, agent_pb2_grpc
from contracts.interceptors import Request, Retry, chain
from contracts.search import SearchClient
from contracts.search.v1 import search_pb2, search_pb2_grpc

USER = agent_pb2.Message(role=agent_pb2.ROLE_USER, content="hi")


class FakeSearch(search_pb2_grpc.SearchServicer):
    def __init__(self):
        self.failures = []  # status codes to fail the next calls with, in order
        self.calls = 0

    def Query(self, request, context):
        self.calls += 1
        self.seen, self.metadata = request, dict(context.invocation_metadata())
        if self.failures:
            context.abort(self.failures.pop(0), "flaky")
        if request.k > 50:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "k must be 1 to 50")
        return search_pb2.QueryResponse(results=[search_pb2.Result(path="rag/a.md", score=0.9, content="alpha")])


class FakeAgent(agent_pb2_grpc.AgentServicer):
    def __init__(self):
        self.failures = []  # fail before the first event
        self.fail_after_first = False
        self.calls = 0

    def Run(self, request, context):
        self.calls += 1
        self.seen, self.metadata = request, dict(context.invocation_metadata())
        if self.failures:
            context.abort(self.failures.pop(0), "flaky")
        yield agent_pb2.RunEvent(progress=agent_pb2.Progress(tick=1))
        if self.fail_after_first:
            context.abort(grpc.StatusCode.UNAVAILABLE, "lost midway")
        yield agent_pb2.RunEvent(answer=agent_pb2.Answer(text="hello"))


def start(search, agent, port=0):
    s = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    search_pb2_grpc.add_SearchServicer_to_server(search, s)
    agent_pb2_grpc.add_AgentServicer_to_server(agent, s)
    port = s.add_insecure_port(f"127.0.0.1:{port}")
    s.start()
    return s, port


@pytest.fixture
def server():
    search, agent = FakeSearch(), FakeAgent()
    s, port = start(search, agent)
    yield f"127.0.0.1:{port}", search, agent
    s.stop(None)


def no_sleep(seconds):
    pass


# The wrappers


def test_search_query(server):
    address, search, _ = server
    results = SearchClient(address).query("what is rag", k=3)
    assert [(r.path, r.score, r.content) for r in results] == [("rag/a.md", 0.9, "alpha")]
    assert (search.seen.query, search.seen.k) == ("what is rag", 3)


def test_search_error_is_rpc_error(server):
    with pytest.raises(grpc.RpcError) as e:
        SearchClient(server[0]).query("x", k=51)
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_search_down_is_unavailable():
    with pytest.raises(grpc.RpcError) as e:
        SearchClient("127.0.0.1:1", timeout=5).query("x")
    assert e.value.code() == grpc.StatusCode.UNAVAILABLE


def test_address_from_env(monkeypatch):
    monkeypatch.setenv("SEARCH_ADDRESS", "elsewhere:9")
    monkeypatch.setenv("AGENT_ADDRESS", "agent:7")
    assert SearchClient().address == "elsewhere:9"
    assert AgentClient().address == "agent:7"


def test_agent_run_streams_events(server):
    address, _, agent = server
    events = list(AgentClient(address).run([USER]))
    assert [e.WhichOneof("event") for e in events] == ["progress", "answer"]
    assert events[-1].answer.text == "hello"
    assert list(agent.seen.messages) == [USER]


def test_agent_run_closed_early_cancels_the_call(server):
    stream = AgentClient(server[0]).run([USER])
    next(stream)
    stream.close()  # the caller went away mid-stream


def test_calls_carry_the_current_trace(server):
    address, search, agent = server
    with TracerProvider().get_tracer("test").start_as_current_span("caller") as span:
        SearchClient(address).query("x")
        list(AgentClient(address).run([USER]))
    trace_id = trace.format_trace_id(span.get_span_context().trace_id)
    assert trace_id in search.metadata["traceparent"]
    assert trace_id in agent.metadata["traceparent"]


# The interceptor interface


class Recorder:
    """A caller's interceptor: records each request and adds `x-caller` to its metadata."""

    def __init__(self, log, name="recorder"):
        self.log, self.name = log, name

    def intercept(self, request, proceed):
        self.log.append((self.name, request.method, request.streaming, request.timeout))
        return proceed(request.replace(metadata=(*request.metadata, ("x-caller", self.name))))


def test_interceptors_see_every_call_and_can_change_it(server):
    address, search, agent = server
    log = []
    with TracerProvider().get_tracer("test").start_as_current_span("caller"):
        SearchClient(address, timeout=7, interceptors=[Recorder(log)]).query("x")
        list(AgentClient(address, timeout=9, interceptors=[Recorder(log)]).run([USER]))
    assert log == [("recorder", "/search.v1.Search/Query", False, 7),
                   ("recorder", "/agent.v1.Agent/Run", True, 9)]
    for metadata in (search.metadata, agent.metadata):
        assert metadata["x-caller"] == "recorder" and "traceparent" in metadata  # the trace is kept


def test_chain_runs_outermost_first():
    log = []
    handler = chain([Recorder(log, "a"), Recorder(log, "b")], lambda request: request.metadata)
    assert handler(Request("/m", search_pb2.QueryRequest())) == (("x-caller", "a"), ("x-caller", "b"))
    assert [name for name, *_ in log] == ["a", "b"]


# Retry


def test_retry_repeats_a_unary_call_until_it_succeeds(server):
    address, search, _ = server
    search.failures = [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.UNAVAILABLE]
    waits = []
    client = SearchClient(address, interceptors=[Retry(max_attempts=3, sleep=waits.append)])
    assert [r.path for r in client.query("x")] == ["rag/a.md"]
    assert search.calls == 3 and len(waits) == 2 and waits[0] < waits[1] * 2  # backing off


def test_retry_gives_up_after_max_attempts(server):
    address, search, _ = server
    search.failures = [grpc.StatusCode.UNAVAILABLE] * 3
    with pytest.raises(grpc.RpcError) as e:
        SearchClient(address, interceptors=[Retry(max_attempts=3, sleep=no_sleep)]).query("x")
    assert e.value.code() == grpc.StatusCode.UNAVAILABLE and search.calls == 3


def test_retry_passes_other_codes_through(server):
    address, search, _ = server
    with pytest.raises(grpc.RpcError) as e:
        SearchClient(address, interceptors=[Retry(sleep=no_sleep)]).query("x", k=51)
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT and search.calls == 1


def test_retry_repeats_a_stream_that_fails_before_its_first_message(server):
    address, _, agent = server
    agent.failures = [grpc.StatusCode.UNAVAILABLE]
    events = list(AgentClient(address, interceptors=[Retry(sleep=no_sleep)]).run([USER]))
    assert events[-1].answer.text == "hello" and agent.calls == 2


def test_retry_does_not_repeat_a_stream_after_its_first_message(server):
    address, _, agent = server
    agent.fail_after_first = True
    stream = AgentClient(address, interceptors=[Retry(sleep=no_sleep)]).run([USER])
    assert next(stream).progress.tick == 1
    with pytest.raises(grpc.RpcError):
        list(stream)
    assert agent.calls == 1


def test_retry_rides_out_a_server_restart():
    with socket.socket() as s:  # a free port, so the server can come back on the same one
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    search = FakeSearch()
    restarted = []

    def restart_after_first_wait(seconds):
        if not restarted:
            restarted.append(start(search, FakeAgent(), port)[0])
        time.sleep(seconds)  # real waits: the channel's reconnect backoff has to pass

    client = SearchClient(f"127.0.0.1:{port}", timeout=5,
                          interceptors=[Retry(max_attempts=5, sleep=restart_after_first_wait)])
    try:
        assert [r.path for r in client.query("x")] == ["rag/a.md"]  # first attempt: nothing listening
    finally:
        for s in restarted:
            s.stop(None)
    assert search.calls == 1


def test_wrappers_are_safe_to_share_between_threads(server):
    address, _, _ = server
    client = SearchClient(address, interceptors=[Retry(sleep=no_sleep)])
    results = []
    threads = [threading.Thread(target=lambda: results.append(client.query("x"))) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 8
