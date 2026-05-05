"""
LLM Council - Local multi-model decision engine
FastAPI backend with SSE streaming for real-time council progress
"""

import asyncio
import base64
import json
import os
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from orchestrator import CouncilOrchestrator

load_dotenv()

app = FastAPI(title="LLM Council", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html") as f:
        return f.read()


@app.post("/council/stream")
async def council_stream(
    topic_text: str = Form(""),
    council_config: str = Form(None),
    image: Optional[UploadFile] = File(None),
):
    """
    SSE endpoint — streams council events as they happen.
    """
    image_data: Optional[str] = None
    image_mime: Optional[str] = None

    if image and image.filename:
        raw = await image.read()
        image_data = base64.b64encode(raw).decode()
        image_mime = image.content_type or "image/png"

    config_dict = None
    if council_config:
        try:
            config_dict = json.loads(council_config)
        except:
            pass

    orchestrator = CouncilOrchestrator()

    async def event_generator():
        try:
            async for event in orchestrator.run(topic_text, image_data, image_mime, config_dict):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)  # yield to event loop
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

from pydantic import BaseModel
from typing import List

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    member_id: str
    messages: List[ChatMessage]
    council_config: Optional[dict] = None

@app.post("/council/chat")
async def council_chat(req: ChatRequest):
    """
    Interactive Debate Mode — stream a reply from a specific member
    """
    orchestrator = CouncilOrchestrator()
    
    async def chat_stream():
        try:
            async for chunk in orchestrator.chat_with_member(req.member_id, req.messages, req.council_config):
                yield f"data: {json.dumps({'type': 'chat_token', 'chunk': chunk})}\n\n"
            yield f"data: {json.dumps({'type': 'chat_done'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        chat_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


from memory_graph import memory_engine

@app.get("/council/memory")
async def get_memory():
    return memory_engine.get_graph_data()

@app.get("/health")
async def health():
    keys = {
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY")),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "groq": bool(os.getenv("GROQ_API_KEY")),
    }
    return {"status": "ok", "keys_configured": keys}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
