"""PDF text extraction in a disposable, resource-limited child process.

PDFs are untrusted input and the parser is native code, so a hostile file must
not be able to hang or exhaust the server: the child gets a wall-clock
deadline, a page ceiling, a text limit and a hard memory ceiling. Where no
memory ceiling can be enforced, extraction is refused unless explicitly allowed.
"""

import json
import os
import subprocess
import sys

PDF_TIMEOUT_S = 10
PDF_MAX_PAGES = 100
PDF_MEMORY_LIMIT_BYTES = 768 * 1024 * 1024
_UNSAFE_OPT_OUT = "COUNCIL_PDF_ALLOW_UNLIMITED_MEMORY"


class PdfExtractionError(Exception):
    pass


def extract_pdf_text(raw: bytes, text_limit: int) -> str:
    """Return up to text_limit characters of text from the first PDF_MAX_PAGES pages."""
    command = [sys.executable, os.path.abspath(__file__), str(text_limit), str(PDF_MAX_PAGES),
               str(PDF_MEMORY_LIMIT_BYTES)]
    try:
        result = subprocess.run(command, input=raw, capture_output=True, timeout=PDF_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise PdfExtractionError(f"PDF extraction exceeded {PDF_TIMEOUT_S} seconds and was stopped.") from None
    try:
        reply = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Killed by the memory ceiling or crashed inside the native parser.
        raise PdfExtractionError("PDF could not be processed within the memory and safety limits.") from None
    if "error" in reply:
        raise PdfExtractionError(reply["error"])
    text = reply["text"]
    if reply.get("more_pages"):
        text += f"\n...[only the first {PDF_MAX_PAGES} pages were read]"
    return text


# ---------------------------------------------------------------- child side

def _limit_memory_posix(limit: int) -> bool:
    if sys.platform == "darwin":
        return False  # macOS does not enforce RLIMIT_AS
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    return True


def _limit_memory_windows(limit: int) -> bool:
    import ctypes
    from ctypes import wintypes

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    job_object_limit_process_memory = 0x100
    job_object_extended_limit_information = 9
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = job_object_limit_process_memory
    info.ProcessMemoryLimit = limit
    configured = kernel32.SetInformationJobObject(
        job, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info))
    assigned = configured and kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())
    return bool(assigned)


def apply_memory_limit(limit: int) -> bool:
    """Cap this process's memory; False when the platform cannot enforce it."""
    try:
        return _limit_memory_windows(limit) if os.name == "nt" else _limit_memory_posix(limit)
    except Exception:
        return False


def _reply(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    text_limit, max_pages, memory_limit = (int(value) for value in argv[1:4])
    raw = sys.stdin.buffer.read()  # read before the cap so the input itself always fits
    if not apply_memory_limit(memory_limit) and os.getenv(_UNSAFE_OPT_OUT, "").lower() != "true":
        _reply({"error": "PDF extraction is disabled: this platform cannot enforce a memory limit on the "
                         f"parser. Set {_UNSAFE_OPT_OUT}=true to allow it anyway."})
        return 0
    import fitz  # PyMuPDF, imported only inside the limited process

    try:
        with fitz.open(stream=raw, filetype="pdf") as doc:
            parts, remaining = [], text_limit + 1
            for index, page in enumerate(doc):
                if index >= max_pages or remaining <= 0:
                    break
                text = page.get_text()[:remaining]
                parts.append(text)
                remaining -= len(text)
            more_pages = doc.page_count > max_pages
    except Exception as exc:
        _reply({"error": f"PDF could not be read: {exc}"})
        return 0
    _reply({"text": "".join(parts), "more_pages": more_pages})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
