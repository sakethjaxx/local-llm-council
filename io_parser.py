import re
import httpx
from bs4 import BeautifulSoup
import fitz  # PyMuPDF

url_pattern = re.compile(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/\w.-]*')

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
