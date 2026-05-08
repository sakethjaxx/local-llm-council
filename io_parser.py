import re
import json
import httpx
from bs4 import BeautifulSoup
import fitz  # PyMuPDF

url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w.-]*')
TEXT_CHAR_LIMIT = 12000


def _truncate(value: str, limit: int = TEXT_CHAR_LIMIT) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


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
    
    scraped_data = []
    for url in urls:
        print(f"\n[🔍 I/O Parser] Scraping URL: {url}")
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                
                # Check if PDF
                if url.lower().endswith(".pdf") or resp.headers.get("content-type", "").startswith("application/pdf"):
                    print("[🔍 I/O Parser] Detected PDF document.")
                    doc = fitz.open(stream=resp.content, filetype="pdf")
                    pdf_text = ""
                    for page in doc:
                        pdf_text += page.get_text()
                    scraped_data.append(f"--- CONTENT FROM {url} ---\n{pdf_text[:10000]}") # limit 10k chars
                else:
                    soup = BeautifulSoup(resp.content, "html.parser")
                    # kill all script and style elements
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.extract()
                    page_text = soup.get_text(separator="\n", strip=True)
                    scraped_data.append(f"--- CONTENT FROM {url} ---\n{page_text[:10000]}")
        except Exception as e:
            scraped_data.append(f"--- FAILED TO SCRAPE {url}: {str(e)} ---")
            print(f"[❌ I/O Parser Failed]: {e}")
            
    if scraped_data:
        appended_text = "\n\n".join(scraped_data)
        return text + "\n\n[System Extracted Content]:\n" + appended_text
    return text
