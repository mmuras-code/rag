"""Datasets are JSON Lines files in ../../datasets/, the source of truth, kept in git.

Each line is one case: `question`, `expect` (words or phrases a good answer contains,
case-insensitive) and `notes` (vault paths the answer should cite; empty when the question needs
no notes). Phoenix gets a copy named `<file stem>-<content hash>`, so editing the file makes a new
Phoenix dataset instead of silently changing the one earlier experiments ran on.
"""

import hashlib
import json
from pathlib import Path

DATASETS = Path(__file__).resolve().parents[2] / "datasets"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def phoenix_name(path: Path) -> str:
    return f"{path.stem}-{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}"


def upload(client, path: Path):
    """The Phoenix dataset for this file, created on first use."""
    name = phoenix_name(path)
    try:
        return client.datasets.get_dataset(dataset=name)
    except Exception:  # not found: the client raises an HTTP error
        cases = load(path)
        return client.datasets.create_dataset(
            name=name,
            inputs=[{"question": c["question"]} for c in cases],
            outputs=[{"expect": c["expect"], "notes": c["notes"]} for c in cases],
            dataset_description=f"{path.name} from rag/eval/datasets",
        )
