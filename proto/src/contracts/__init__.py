"""Service contracts. Each service's `.proto` lives in `<service>/v1/`, next to the code generated
from it (`just proto generate`, never edited by hand): messages in `*_pb2.py`, the gRPC stub and
servicer base in `*_pb2_grpc.py`. `<service>/client.py` wraps the stub for callers; `channel.py`
builds the channel every wrapper uses, with the caller's interceptors.
"""
