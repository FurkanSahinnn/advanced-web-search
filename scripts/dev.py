#!/usr/bin/env python3
"""Run both dev servers concurrently (backend + frontend) with hot reload.

  * Backend:  uvicorn advanced_web_search.api.main:app --reload  (http://127.0.0.1:8787)
  * Frontend: pnpm --dir frontend dev (Vite, http://localhost:5173, proxies /api)

Open the app at http://localhost:5173 during development — Vite proxies /api
to the backend. Ctrl+C terminates both processes.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BACKEND_CMD = [
    sys.executable,
    "-m",
    "uvicorn",
    "advanced_web_search.api.main:app",
    "--reload",
    "--host",
    "127.0.0.1",
    "--port",
    "8787",
    # Bound graceful shutdown so the long-lived SSE research stream can't keep
    # the backend alive after Ctrl+C.
    "--timeout-graceful-shutdown",
    "5",
]
FRONTEND_CMD = ["pnpm", "--dir", "frontend", "dev"]


def _stream(proc: subprocess.Popen, prefix: str) -> None:
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, ""):
        if not raw:
            break
        sys.stdout.write(f"[{prefix}] {raw}")
        sys.stdout.flush()


def _spawn(cmd: list[str], prefix: str) -> subprocess.Popen:
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def main() -> int:
    print("=" * 56)
    print("  Advanced Web Search — development servers")
    print("  App (dev):  http://localhost:5173")
    print("  API:        http://127.0.0.1:8787/api/health")
    print("  Press Ctrl+C to stop both.")
    print("=" * 56)

    procs: list[subprocess.Popen] = []
    try:
        backend = _spawn(BACKEND_CMD, "backend")
        procs.append(backend)
        try:
            frontend = _spawn(FRONTEND_CMD, "frontend")
            procs.append(frontend)
        except FileNotFoundError:
            print("ERROR: 'pnpm' not found. Install Node 18+ and pnpm to run the frontend.")
            backend.terminate()
            backend.wait()
            return 1

        threads = [
            threading.Thread(target=_stream, args=(p, name), daemon=True)
            for p, name in ((backend, "backend"), (frontend, "frontend"))
        ]
        for t in threads:
            t.start()

        # Wait until either process exits.
        while True:
            for p in procs:
                rc = p.poll()
                if rc is not None:
                    print(f"\n==> A dev server exited (code {rc}); shutting down the other.")
                    return rc or 0
            for t in threads:
                t.join(timeout=0.25)
    except KeyboardInterrupt:
        print("\n==> Ctrl+C received; stopping dev servers...")
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                try:
                    if os.name == "nt":
                        p.terminate()
                    else:
                        p.send_signal(signal.SIGINT)
                except Exception:
                    pass
        for p in procs:
            try:
                p.wait(timeout=8)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
