import re
import json
import os
import socket
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import fitz  # PyMuPDF

from logging_utils import get_logger

logger = get_logger(__name__)
url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w.-]*')
TEXT_CHAR_LIMIT = 12000
MAX_FETCH_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TEXT_EXTENSIONS = {".md", ".txt", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml"}


def _truncate(value: str, limit: int = TEXT_CHAR_LIMIT) -> str:
    return value if len(value) <= limit else value[:limit] + "\n...[truncated]"


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.hostname.lower() == "localhost":
            return False
        resolved = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        return bool(resolved) and all(
            entry[4] and ipaddress.ip_address(entry[4][0]).is_global
            for entry in resolved
        )
    except Exception:
        return False


async def _fetch_url_bytes(client: httpx.AsyncClient, url: str) -> tuple[bytes, httpx.Headers, str] | None:
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        if not _is_safe_url(current_url):
            logger.warning("url_fetch_blocked", extra={"url": current_url})
            return None

        async with client.stream("GET", current_url, follow_redirects=False) as resp:
            if 300 <= resp.status_code < 400:
                location = resp.headers.get("location")
                if not location:
                    resp.raise_for_status()
                current_url = urljoin(str(resp.url), location)
                continue

            resp.raise_for_status()
            content_length = resp.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_FETCH_BYTES:
                        logger.warning("url_fetch_oversized", extra={"url": current_url, "content_length": int(content_length)})
                        return None
                except ValueError:
                    pass

            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_FETCH_BYTES:
                    logger.warning("url_fetch_aborted_oversized", extra={"url": current_url, "bytes": len(body)})
                    return None

            return bytes(body), resp.headers, current_url

    logger.warning("url_fetch_redirect_limit", extra={"url": url, "max_redirects": MAX_REDIRECTS})
    return None


def parse_uploaded_file(filename: str, content_type: str, raw: bytes) -> dict:
    normalized_name = (filename or "attachment").lower()
    normalized_type = (content_type or "application/octet-stream").lower()
    safe_name = filename or "attachment"

    try:
        if normalized_type.startswith("image/"):
            return {
                "kind": "image",
                "filename": filename or "image",
                "content_type": normalized_type,
                "summary": f"Image attachment: {filename or 'image'} ({normalized_type})",
            }

        if normalized_name.endswith(".pdf") or normalized_type == "application/pdf":
            doc = fitz.open(stream=raw, filetype="pdf")
            pdf_text = "".join(page.get_text() for page in doc)
            return {
                "kind": "text",
                "filename": filename or "document.pdf",
                "content_type": normalized_type,
                "text": _truncate(pdf_text.strip()),
            }

        if normalized_name.endswith(".json") or "json" in normalized_type:
            decoded = raw.decode("utf-8", errors="replace")
            try:
                pretty = json.dumps(json.loads(decoded), indent=2)
            except Exception:
                pretty = decoded
            return {
                "kind": "text",
                "filename": filename or "data.json",
                "content_type": normalized_type,
                "text": _truncate(pretty.strip()),
            }

        if normalized_name.endswith(tuple(TEXT_EXTENSIONS)) or normalized_type.startswith("text/"):
            decoded = raw.decode("utf-8", errors="replace")
            return {
                "kind": "text",
                "filename": filename or "document.txt",
                "content_type": normalized_type,
                "text": _truncate(decoded.strip()),
            }
    except Exception as exc:
        return {
            "kind": "unsupported",
            "filename": safe_name,
            "content_type": normalized_type,
            "summary": f"Failed to parse attachment {safe_name}: {exc}",
        }

    return {
        "kind": "unsupported",
        "filename": safe_name,
        "content_type": normalized_type,
        "summary": f"Unsupported attachment kept as metadata only: {safe_name} ({normalized_type})",
    }


def format_attachments_for_prompt(attachments: list[dict], max_total_chars: int = 16000) -> str:
    if not attachments:
        return ""

    text_attachments = [att for att in attachments if att.get("kind") == "text" and att.get("text")]
    total_raw_len = sum(len(att.get("text", "")) for att in text_attachments)
    scale = max_total_chars / total_raw_len if total_raw_len > max_total_chars else 1.0

    parts = ["[Uploaded Attachments]"]
    for att in attachments:
        kind, fname, ctype = att.get("kind"), att.get("filename", "attachment"), att.get("content_type", "unknown")
        if kind == "text":
            content = att.get("text", "")
            if scale < 1.0 and len(content) > 200:
                budget = max(200, int(len(content) * scale))
                content = content[:budget] + "\n...[proportionally budget-truncated]"
            parts.append(f"--- FILE: {fname} ({ctype}) ---\n{content}")
        elif kind == "image":
            parts.append(f"--- IMAGE: {fname} ({ctype}) ---")
        else:
            parts.append(f"--- ATTACHMENT: {att.get('summary', fname)} ---")
    return "\n\n".join(parts).strip()


async def parse_input(text: str) -> str:
    urls = url_pattern.findall(text)
    if not urls or os.getenv("COUNCIL_ALLOW_URL_FETCH", "false").strip().lower() != "true":
        return text

    scraped_data = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for url in urls:
            if not _is_safe_url(url):
                logger.warning("url_fetch_blocked", extra={"url": url})
                continue

            logger.info("url_fetch_started", extra={"url": url})
            try:
                fetched = await _fetch_url_bytes(client, url)
                if not fetched:
                    continue
                body, headers, final_url = fetched
                content_type = headers.get("content-type", "").lower()

                if final_url.lower().endswith(".pdf") or content_type.startswith("application/pdf"):
                    doc = fitz.open(stream=body, filetype="pdf")
                    pdf_text = "".join(page.get_text() for page in doc)
                    scraped_data.append(f"--- CONTENT FROM {final_url} ---\n{pdf_text[:10000]}")
                else:
                    soup = BeautifulSoup(body, "html.parser")
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.extract()
                    page_text = soup.get_text(separator="\n", strip=True)
                    scraped_data.append(f"--- CONTENT FROM {final_url} ---\n{page_text[:10000]}")
            except Exception as e:
                scraped_data.append(f"--- FAILED TO SCRAPE {url}: {str(e)} ---")
                logger.exception("url_fetch_failed", extra={"url": url, "error": str(e)})

    return text + "\n\n[System Extracted Content]:\n" + "\n\n".join(scraped_data) if scraped_data else text


SKIP_INGEST_DIRS = {".git", "venv", "node_modules", "__pycache__", "dist", "build", ".env", "env"}


def ingest_folder(folder_path: str, max_files: int = 50) -> list[dict]:
    """Bulk ingest a local directory, parsing up to max_files supported attachments.
    Uses Ponytail (KISS/YAGNI) rules to skip build noise, auto-truncate text,
    and output clean prompt-ready attachment representations."""
    root = os.path.abspath(folder_path)
    if not os.path.exists(root) or not os.path.isdir(root):
        logger.warning("ingest_folder_not_found", extra={"folder_path": folder_path})
        return []

    attachments = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_INGEST_DIRS]
        for fname in sorted(files):
            if len(attachments) >= max_files:
                break
            full_path = os.path.join(dirpath, fname)
            rel_name = os.path.relpath(full_path, root)
            try:
                with open(full_path, "rb") as f:
                    raw = f.read()
                ext = os.path.splitext(fname)[1].lower()
                ctype = "application/json" if ext == ".json" else ("application/pdf" if ext == ".pdf" else "text/plain")
                parsed = parse_uploaded_file(rel_name, ctype, raw)
                if parsed.get("kind") != "unsupported":
                    attachments.append(parsed)
            except Exception as exc:
                logger.warning("ingest_folder_file_error", extra={"file": rel_name, "error": str(exc)})
        if len(attachments) >= max_files:
            break

    logger.info("ingest_folder_completed", extra={"folder_path": root, "file_count": len(attachments)})
    return attachments

