import httpx
import pytest
from orchestrator.client import OrchestratorClient


@pytest.fixture(scope="session")
def orchestrator():
    """The running orchestrator (ORCHESTRATOR_URL, default http://127.0.0.1:8000). Fails once,
    clearly, if it is not up or refuses us, instead of every question failing on its own."""
    client = OrchestratorClient()
    url = client.http.base_url
    try:
        client.models()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        hint = (" Check that ORCHESTRATOR_API_KEY matches the orchestrator's (orchestrator/.env)."
                if status == 401 else "")
        pytest.exit(f"orchestrator on {url} answered {status} {e.response.reason_phrase}.{hint}", returncode=1)
    except httpx.HTTPError as e:
        pytest.exit(f"orchestrator not answering on {url} ({type(e).__name__}). Run `just up` from rag/.",
                    returncode=1)
    return client
