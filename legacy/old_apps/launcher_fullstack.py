from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import time
import webbrowser
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def wait_for_port(host: str, port: int, timeout: float = 25.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.25)
    return False


def serve() -> None:
    root = project_root()
    os.chdir(root)
    from fullstack_local_backend_app import app
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


def main() -> None:
    p = multiprocessing.Process(target=serve, daemon=True)
    p.start()

    if not wait_for_port("127.0.0.1", 8000):
        print("Server failed to start on http://127.0.0.1:8000")
        p.terminate()
        p.join(5)
        sys.exit(1)

    webbrowser.open("http://127.0.0.1:8000")
    print("Cognitive Nexus running at http://127.0.0.1:8000")
    print("Press Ctrl+C in this window to stop.")

    try:
        while p.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if p.is_alive():
            p.terminate()
            p.join(5)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
