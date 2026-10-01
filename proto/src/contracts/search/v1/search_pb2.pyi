from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class QueryRequest(_message.Message):
    __slots__ = ("query", "k", "collection")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    K_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_FIELD_NUMBER: _ClassVar[int]
    query: str
    k: int
    collection: str
    def __init__(self, query: _Optional[str] = ..., k: _Optional[int] = ..., collection: _Optional[str] = ...) -> None: ...

class QueryResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[Result]
    def __init__(self, results: _Optional[_Iterable[_Union[Result, _Mapping]]] = ...) -> None: ...

class Result(_message.Message):
    __slots__ = ("path", "score", "content", "similarity", "bm25")
    PATH_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    SIMILARITY_FIELD_NUMBER: _ClassVar[int]
    BM25_FIELD_NUMBER: _ClassVar[int]
    path: str
    score: float
    content: str
    similarity: float
    bm25: float
    def __init__(self, path: _Optional[str] = ..., score: _Optional[float] = ..., content: _Optional[str] = ..., similarity: _Optional[float] = ..., bm25: _Optional[float] = ...) -> None: ...
