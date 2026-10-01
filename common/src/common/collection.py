"""The note collections search indexes: each is a top-level folder of the vault root."""

from enum import StrEnum


class Collection(StrEnum):
    ML = "ml"  # machine-learning notes
    TEST = "test"  # made-up facts about the user, for testing routing and retrieval (e.g. the eval canary)
