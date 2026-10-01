"""`@timed(name)`: the run time of any function, as one shared histogram.

    @timed("search.embed")
    def embed(texts): ...

    @timed("agent.plan", model="haiku")
    async def plan(state): ...

Every call records its wall time, in seconds, into `ml.time` (in Prometheus
`ml_time_seconds_{bucket,sum,count}`) with the attribute `function` = `name`, plus any static
attributes given to the decorator. The name is given, not taken from the function, so renaming the
function does not rename the series. A call that raises is timed too; the outcome is not recorded
(that is what `operation` is for).

It works on plain functions, `async def`, generators and async generators. For a coroutine it
times the await, for a generator the whole iteration: from the first item asked for until it is
exhausted, raises or is closed, including the time the consumer spends between items.

Until `setup_metrics` (and with METRICS_ENABLED=false) recording does nothing. Names and
attributes are in ../../docs/telemetry.md.
"""

import functools
import inspect
import time

from observability.metrics import DURATION_BUCKETS, _meter

TIME = "ml.time"
FUNCTION = "function"

_time = _meter.create_histogram(
    TIME, unit="s", description="Run time of a @timed function, by function",
    explicit_bucket_boundaries_advisory=DURATION_BUCKETS)


def timed(name: str, **attributes: str):
    """Decorator: record each call's run time into `ml.time` as `function` = `name`. Keep
    attribute values to a small fixed set: each combination is a separate Prometheus series."""
    if callable(name):
        raise TypeError('@timed needs a name: @timed("<service>.<thing>")')
    attrs = {**attributes, FUNCTION: name}

    def record(start: float) -> None:
        _time.record(time.perf_counter() - start, attrs)

    def decorate(func):
        if inspect.isasyncgenfunction(func):
            @functools.wraps(func)
            async def async_gen_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    async for item in func(*args, **kwargs):
                        yield item
                finally:
                    record(start)
            return async_gen_wrapper

        if inspect.isgeneratorfunction(func):
            @functools.wraps(func)
            def gen_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return (yield from func(*args, **kwargs))
                finally:
                    record(start)
            return gen_wrapper

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    record(start)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                record(start)
        return wrapper

    return decorate
