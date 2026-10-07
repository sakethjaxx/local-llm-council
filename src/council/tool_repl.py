"""Opt-in Python sandbox: one disposable, network-less Docker container per call."""

import asyncio
import shutil
import subprocess
import threading
import uuid

from logging_utils import get_logger

logger = get_logger(__name__)

EXEC_TIMEOUT_S = 10
MAX_OUTPUT_BYTES = 64 * 1024
SANDBOX_IMAGE = "python:3.11-slim"


def is_docker_available() -> bool:
    """Check whether docker CLI is present and the daemon is reachable."""
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(["docker", "info"], capture_output=True, timeout=2)
        return res.returncode == 0
    except Exception:
        return False


def _strip_fences(code: str) -> str:
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    return code.strip()


def _sandbox_command(name: str) -> list[str]:
    return [
        "docker", "run", "--rm", "-i", "--name", name, "--pull", "never",
        "--network", "none", "--memory", "256m", "--cpus", "1", "--pids-limit", "128",
        "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        "--user", "65534:65534",
        SANDBOX_IMAGE, "python", "-I", "-",  # code arrives on stdin: no temp file, no bind mount
    ]


def _remove_container(name: str) -> None:
    """Killing the docker CLI does not stop the container; remove it explicitly."""
    try:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
    except Exception:
        logger.warning("python_tool_cleanup_failed", extra={"container": name})


def _stop(name: str, handle: dict) -> None:
    proc = handle.get("proc")
    _remove_container(name)
    if proc and proc.poll() is None:
        proc.kill()


def _run_sandbox(code: str, name: str, handle: dict) -> tuple[bytes, bool, bool]:
    """Run one container; returns (output, truncated, timed_out). Always removes the container."""
    proc = subprocess.Popen(_sandbox_command(name), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    handle["proc"] = proc
    expired = threading.Event()

    def expire():
        expired.set()
        _stop(name, handle)  # ends the container, which unblocks the read below

    timer = threading.Timer(EXEC_TIMEOUT_S, expire)
    timer.start()
    try:
        try:
            proc.stdin.write(code.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass  # the container died early; its output says why
        data = bytearray()
        while len(data) <= MAX_OUTPUT_BYTES:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data[:MAX_OUTPUT_BYTES]), len(data) > MAX_OUTPUT_BYTES, expired.is_set()
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        _remove_container(name)


async def execute_python(code: str) -> str:
    logger.info("python_tool_execution_started")
    if not shutil.which("docker"):
        return "[Error: Docker is not installed or not found in PATH. The Python sandbox requires Docker.]"

    name = f"council-sandbox-{uuid.uuid4().hex}"
    handle: dict = {}
    try:
        raw, truncated, timed_out = await asyncio.to_thread(_run_sandbox, _strip_fences(code), name, handle)
    except asyncio.CancelledError:
        # The worker thread cannot be cancelled; stop the container now instead of at the deadline.
        threading.Thread(target=_stop, args=(name, handle), daemon=True).start()
        raise
    except Exception as e:
        return f"[Error: {e}]"

    output = raw.decode("utf-8", errors="replace").strip()
    if timed_out:
        return f"[Error: Code execution timed out after {EXEC_TIMEOUT_S} seconds]"
    if "No such image" in output or "Unable to find image" in output:
        return f"[Error: The sandbox image is missing. Run `docker pull {SANDBOX_IMAGE}` once, then retry.]"
    if truncated:
        output += f"\n...[output truncated at {MAX_OUTPUT_BYTES // 1024} KiB]"
    return output or "[Success: Code executed with no output]"
