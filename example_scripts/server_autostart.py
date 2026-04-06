import atexit
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib import error, request
from urllib.parse import urlparse


_SERVER_PROCESS: Optional[subprocess.Popen] = None


def _healthcheck(base_url: str, timeout_seconds: float = 1.0) -> bool:
    """Checks whether the poker server is reachable and healthy.

    Args:
        base_url (str): Server base URL.
        timeout_seconds (float): Request timeout.

    Returns:
        bool: True when health endpoint responds with HTTP 200.
    """
    url = f"{base_url.rstrip('/')}/health"
    req = request.Request(url=url, method="GET")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return response.status == 200
    except (error.URLError, error.HTTPError):
        return False


def _build_uvicorn_command(base_url: str) -> list[str]:
    """Builds a uvicorn command matching the configured base URL.

    Args:
        base_url (str): Server base URL.

    Returns:
        list[str]: Command arguments for subprocess.Popen.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 8000)
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "server.run_poker_server:app",
        "--host",
        host,
        "--port",
        str(port),
    ]


def _terminate_server() -> None:
    """Stops the spawned server process when the script exits."""
    global _SERVER_PROCESS
    if _SERVER_PROCESS is None:
        return
    if _SERVER_PROCESS.poll() is not None:
        _SERVER_PROCESS = None
        return

    _SERVER_PROCESS.terminate()
    try:
        _SERVER_PROCESS.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        _SERVER_PROCESS.kill()
    finally:
        _SERVER_PROCESS = None


def ensure_server_running(
    base_url: str,
    *,
    startup_timeout_seconds: float = 15.0,
) -> None:
    """Ensures the server is running for local example scripts.

    Args:
        base_url (str): Configured server base URL.
        startup_timeout_seconds (float): Max wait for health readiness.

    Returns:
        None: This function does not return a value.
    """
    global _SERVER_PROCESS

    if _healthcheck(base_url):
        print("[example] Server already running.")
        return

    if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is None:
        # Process is still booting or running; continue to readiness wait.
        pass
    else:
        project_root = Path(__file__).resolve().parents[1]
        command = _build_uvicorn_command(base_url)
        print("[example] Server not reachable; starting local uvicorn process...")
        _SERVER_PROCESS = subprocess.Popen(
            command,
            cwd=project_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        atexit.register(_terminate_server)

    deadline = time.time() + startup_timeout_seconds
    while time.time() < deadline:
        if _SERVER_PROCESS is not None and _SERVER_PROCESS.poll() is not None:
            raise RuntimeError("Server process exited before becoming healthy")
        if _healthcheck(base_url):
            print("[example] Server is healthy and ready.")
            return
        time.sleep(0.2)

    raise RuntimeError(
        f"Server did not become healthy within {startup_timeout_seconds} seconds"
    )
