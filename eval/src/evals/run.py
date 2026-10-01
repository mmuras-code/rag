"""Runs a dataset against the running orchestrator as a Phoenix experiment.

    uv run python -m evals.run [--dataset datasets/golden.jsonl] [--name haiku-baseline] [--strict]

Each case is asked through `OrchestratorClient` (the same path Open WebUI uses), then scored by
the evaluators in evaluators.py. The experiment appears in Phoenix under Datasets, next to earlier
runs on the same dataset, with each case's answer, scores, cost and a link to its trace.

With `--strict`, every case must pass every check (`failed_checks`); the run lists the cases that
did not and exits 1. `just grounding` runs datasets/grounding.jsonl this way.
"""

import argparse
import os
import statistics
import subprocess
from collections import Counter
from pathlib import Path

from orchestrator.client import OrchestratorClient
from phoenix.client import Client
from phoenix.client.experiments import run_experiment

from evals import dataset
from evals.evaluators import (
    TraceUsage,
    expected_words,
    failed_checks,
    note_cited,
    trace_evaluators,
    usage_evaluators,
)

PHOENIX_URL = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=dataset.DATASETS / "golden.jsonl")
    parser.add_argument("--name", help="experiment name, e.g. what you changed (default: Phoenix picks one)")
    parser.add_argument("--description", help="free text shown with the experiment")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 unless every case passes every check (words, note retrieved, "
                             "in context, cited, judged)")
    args = parser.parse_args()

    phoenix = Client(base_url=PHOENIX_URL)
    orchestrator = OrchestratorClient()
    usage = TraceUsage(phoenix)

    def task(input, expected):
        reply = orchestrator.reply([{"role": "user", "content": input["question"]}])
        # `expected` rides along so --strict can check each case after the run.
        return {"answer": reply.text, "trace_id": reply.trace_id, "question": input["question"],
                "expected": expected}

    experiment = run_experiment(
        dataset=dataset.upload(phoenix, args.dataset),
        task=task,
        evaluators={"expected_words": expected_words, "note_cited": note_cited, **trace_evaluators(usage),
                    **usage_evaluators(usage)},
        experiment_name=args.name,
        experiment_description=args.description,
        experiment_metadata={"dataset_file": args.dataset.name, "git_commit": git_commit(),
                             "orchestrator_url": str(orchestrator.http.base_url)},
        timeout=300,  # one agent request makes several model calls
        client=phoenix,
    )

    runs = [usage(r["output"]["trace_id"]) for r in experiment["task_runs"] if r.get("output")]
    if runs:
        costs = [u["cost_usd"] for u in runs]
        models = sorted({m for u in runs for m in u["models"]})
        print(f"\n{len(runs)} cases, models {models}: total ${sum(costs):.4f}, "
              f"median ${statistics.median(costs):.5f} per case, max ${max(costs):.5f}")
        endings = Counter(u["termination_reason"] for u in runs)
        print("Endings: " + ", ".join(f"{reason} {n}" for reason, n in endings.most_common()))
        if endings["judge_unavailable"]:
            print(f"  {endings['judge_unavailable']} answers were accepted unjudged (the judge failed): "
                  f"not passes. Filter on judged=false in Phoenix to see them.")
    print(f"Experiment: {phoenix.experiments.get_experiment_url(dataset_id=experiment['dataset_id'], experiment_id=experiment['experiment_id'])}")

    if args.strict:
        outputs = [r.get("output") for r in experiment["task_runs"]]
        failures = [(o["question"], failed_checks(o, o["expected"], usage(o["trace_id"])))
                    for o in outputs if o]
        failures = [(q, failed) for q, failed in failures if failed]
        errored = sum(o is None for o in outputs)  # the task raised: no answer at all
        if failures or errored:
            for question, failed in failures:
                print(f"FAIL {question!r}: {', '.join(failed)}")
            if errored:
                print(f"FAIL {errored} cases got no answer (the request failed)")
            raise SystemExit(1)
        print(f"PASS all {len(outputs)} cases passed every check")


if __name__ == "__main__":
    main()
