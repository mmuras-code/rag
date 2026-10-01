import os

import uvicorn

if __name__ == "__main__":
    # log_config=None: keep common.log's config (set up by orchestrator.app), not uvicorn's own.
    uvicorn.run("orchestrator.app:app", host="0.0.0.0", port=int(os.environ.get("ORCHESTRATOR_PORT", "8000")),
                log_config=None)
