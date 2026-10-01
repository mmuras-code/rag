import hmac
import os

from fastapi import Header, HTTPException


def check_key(authorization: str | None = Header(default=None)) -> None:
    """Requires `Bearer $ORCHESTRATOR_API_KEY` when that variable is set; open otherwise."""
    key = os.environ.get("ORCHESTRATOR_API_KEY")
    # Constant time, so the response time does not reveal how much of the key matched.
    if key and not hmac.compare_digest((authorization or "").encode(), f"Bearer {key}".encode()):
        raise HTTPException(status_code=401, detail="invalid api key")
