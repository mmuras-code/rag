# Decisions

Architecture decision records for choices that affect more than one service. A decision that
affects only one service goes in that service's `docs/decisions/`.

## Format

File name: `NNNN-short-title.md`, numbered in order and never reused.

```
# NNNN: Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD
- Scope: which services

## Context          why a decision was needed
## Decision         what was chosen
## Alternatives considered
## Consequences     good and bad, including what it constrains later
## Open details     only if something is still undecided
```

Do not edit an accepted decision to change it. Write a new one that supersedes it, and update
the old one's status.

## Index

| # | Decision | Status |
|---|---|---|
| 0001 | Protobuf contracts, JSON over HTTP at first | accepted; transport superseded by 0005 |
| 0002 | `just` as the task runner | accepted |
| 0003 | Python for everything in `rag/` | accepted |
| 0004 | FastAPI for HTTP layers, `Depends` for wiring | accepted |
| 0005 | gRPC between services, through clients generated from the `.proto` contracts | accepted |
