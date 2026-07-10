import subprocess
import os

from llm_council.logging_utils import get_logger


logger = get_logger(__name__)


def execute_python(code: str) -> str:
    logger.info("python_tool_execution_started")
    
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
        
    code = code.strip()
    
    temp_file = "sandbox_temp.py"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(code)
        
    try:
        abs_path = os.path.abspath(temp_file)
        result = subprocess.run(
            [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{abs_path}:/sandbox.py:ro",
                "python:3.11-slim",
                "python", "/sandbox.py"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout
        if result.stderr:
            output += "\n[Error]\n" + result.stderr
            
        if not output.strip():
            output = "[Success: Code executed with no output]"
            
        return output.strip()
    except subprocess.TimeoutExpired:
        return "[Error: Code execution timed out after 5 seconds]"
    except Exception as e:
        return f"[Error: {str(e)}]"
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)
