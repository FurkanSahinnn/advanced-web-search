"""Command-line entrypoint: `advanced-web-search` / `python -m advanced_web_search`.

Boots the FastAPI app with uvicorn and (unless --no-browser) opens the default
web browser at the app URL once the server has had a moment to start.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser

from .config import get_settings


def _banner(url: str) -> None:
    line = "=" * 56
    print(line)
    print("  Advanced Web Search — local-first multi-agent deep research")
    print(f"  Open:  {url}")
    print("  Press Ctrl+C to stop.")
    print(line)


def main() -> None:
    settings = get_settings()

    parser = argparse.ArgumentParser(
        prog="advanced-web-search",
        description="Advanced Web Search — local-first multi-agent deep-research workbench.",
    )
    parser.add_argument("--host", default=settings.host, help="Bind host (default: %(default)s)")
    parser.add_argument(
        "--port", type=int, default=settings.port, help="Bind port (default: %(default)s)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open a web browser on start."
    )
    parser.add_argument(
        "--reload", action="store_true", help="Auto-reload on code changes (development)."
    )
    args = parser.parse_args()

    # The URL the user should open. Bind host 0.0.0.0 -> browse via localhost.
    browse_host = "localhost" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{browse_host}:{args.port}"

    _banner(url)

    if not args.no_browser:
        def _open() -> None:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Timer(1.5, _open).start()

    import uvicorn

    if args.reload:
        uvicorn.run(
            "advanced_web_search.api.main:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_level=settings.log_level,
            # Force-close lingering connections (the long-lived SSE research
            # stream never ends on its own) so Ctrl+C always exits promptly.
            timeout_graceful_shutdown=5,
        )
    else:
        from .api.main import create_app

        uvicorn.run(
            create_app(),
            host=args.host,
            port=args.port,
            log_level=settings.log_level,
            # Force-close lingering connections (the long-lived SSE research
            # stream never ends on its own) so Ctrl+C always exits promptly.
            timeout_graceful_shutdown=5,
        )


if __name__ == "__main__":
    main()
