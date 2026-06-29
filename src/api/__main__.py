"""Run the API with: ``python -m src.api`` (uvicorn)."""

from __future__ import annotations

from src.api import settings


def main() -> None:
    import uvicorn

    uvicorn.run(
        "src.api.app:app",
        host=settings.api_host(),
        port=settings.api_port(),
        reload=settings.api_reload_enabled(),
    )


if __name__ == "__main__":
    main()
