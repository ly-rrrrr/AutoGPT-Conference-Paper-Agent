import os

import uvicorn

from backend.conference_paper_bridge.app import create_app


def main() -> None:
    host = os.getenv("CONFERENCE_PAPER_BRIDGE_HOST", "127.0.0.1")
    port = int(os.getenv("CONFERENCE_PAPER_BRIDGE_PORT", "8765"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
