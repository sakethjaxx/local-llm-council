import re
import json
import os
import socket
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import fitz  # PyMuPDF

from llm_council.logging_utils import get_logger


logger = get_logger(__name__)
url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w.-]*')
TEXT_CHAR_LIMIT = 12000
MAX_FETCH_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5


def _truncate(value: str, limit: int = TEXT_CHAR_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def _is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False

        hostname = parsed.hostname
        if not hostname:
            return False
        if hostname.lower() == "localhost":
            return False

        resolved = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        if not resolved:
            return False

        for entry in resolved:
            sockaddr = entry[4]
            if not sockaddr:
                return False
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                return False
        return True
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

        if normalized_name.endswith((".md", ".txt", ".py", ".js", ".ts", ".html", ".css", ".yaml", ".yml")) or normalized_type.startswith("text/"):
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
            "filename": filename or "attachment",
            "content_type": normalized_type,
            "summary": f"Failed to parse attachment {filename or 'attachment'}: {exc}",
        }

    return {
        "kind": "unsupported",
        "filename": filename or "attachment",
        "content_type": normalized_type,
        "summary": f"Unsupported attachment kept as metadata only: {filename or 'attachment'} ({normalized_type})",
    }


def format_attachments_for_prompt(attachments: list[dict]) -> str:
    if not attachments:
        return ""

    parts = ["[Uploaded Attachments]"]
    for attachment in attachments:
        kind = attachment.get("kind")
        filename = attachment.get("filename", "attachment")
        content_type = attachment.get("content_type", "unknown")
        if kind == "text":
            parts.append(f"--- FILE: {filename} ({content_type}) ---\n{attachment.get('text', '')}")
        elif kind == "image":
            parts.append(f"--- IMAGE: {filename} ({content_type}) ---")
        else:
            parts.append(f"--- ATTACHMENT: {attachment.get('summary', filename)} ---")
    return "\n\n".join(parts).strip()

async def parse_input(text: str) -> str:
    urls = url_pattern.findall(text)
    if not urls:
        return text

    if os.getenv("COUNCIL_ALLOW_URL_FETCH", "false").strip().lower() != "true":
        logger.info("url_fetch_disabled")
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
                    logger.info("url_fetch_pdf_detected", extra={"url": final_url})
                    doc = fitz.open(stream=body, filetype="pdf")
                    pdf_text = ""
                    for page in doc:
                        pdf_text += page.get_text()
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
            
    if scraped_data:
        appended_text = "\n\n".join(scraped_data)
        return text + "\n\n[System Extracted Content]:\n" + appended_text
    return text
