# integration_tests

Smoke test of the whole running system: asks the orchestrator a set of questions, the way Open
WebUI would, and checks that sensible answers come back. If these pass, the path orchestrator →
agent → search → model works.

Requires the stack running with `OR_KEY` set in `orchestrator/.env`. Every run spends
OpenRouter credit (see below).

## Run

Start the stack first (`just up` from `rag/`), then:

```
just integration_tests test     # from rag/; or `just test` here
```

The questions run 4 at a time (`pytest -n 4`), about 20 seconds in all. The orchestrator is checked
once before any question: if it is not answering, the run stops at once and says to run `just up`;
if it answers with an error status, the run stops and reports it (for 401, check that
`ORCHESTRATOR_API_KEY` matches the orchestrator's).

## Questions

`questions.json`: each entry is a `question`, the words a correct answer must `expect`
(case-insensitive, whole words) and optionally a `difficulty` (0–100). Add entries there. Pick questions with short, unambiguous answers:
a failure should mean the system is broken, not that an answer was mediocre. Answer quality is
scored by `eval/`, not here. Include some that need the notes (e.g. the RRF constant) so search is
exercised too.

## How it talks to the orchestrator

Through `OrchestratorClient` from `../orchestrator/src/orchestrator/client.py`, the same client
`eval/` uses. `ORCHESTRATOR_URL` (default `http://127.0.0.1:8000`) and `ORCHESTRATOR_API_KEY`
point it elsewhere; `just` loads them from a `.env` here (git-ignored) if there is one.

Each question runs the whole agent: several model calls through OpenRouter, billed per token.
Every request is also a trace in Phoenix.
