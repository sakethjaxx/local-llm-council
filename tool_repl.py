import subprocess
import os
import tempfile
import uuid

from logging_utils import get_logger


logger = get_logger(__name__)

EXEC_TIMEOUT_S = 10


def execute_python(code: str) -> str:
    logger.info("python_tool_execution_started")

    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]

    code = code.strip()

    # Unique per-invocation file in a temp dir so concurrent council runs never
    # share (and cannot execute each other's) sandbox code.
    temp_file = os.path.join(tempfile.gettempdir(), f"council_sandbox_{uuid.uuid4().hex}.py")
    with open(temp_file, "w") as f:
        f.write(code)

    try:
        abs_path = os.path.abspath(temp_file)
        result = subprocess.run(
            [
                "docker", "run", "--rm", "--network", "none",
                "--memory", "256m", "--cpus", "1", "--pids-limit", "128",
                "--read-only", "--security-opt", "no-new-privileges",
                "--user", "65534:65534",
                "-v", f"{abs_path}:/sandbox.py:ro",
                "python:3.11-slim",
                "python", "/sandbox.py"
            ],
            capture_output=True,
            text=True,
            timeout=EXEC_TIMEOUT_S
        )
        output = result.stdout
        if result.stderr:
            output += "\n[Error]\n" + result.stderr

        if not output.strip():
            output = "[Success: Code executed with no output]"

        return output.strip()
    except subprocess.TimeoutExpired:
        return f"[Error: Code execution timed out after {EXEC_TIMEOUT_S} seconds]"
    except Exception as e:
        return f"[Error: {str(e)}]"
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)
