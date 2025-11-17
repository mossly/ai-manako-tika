"""FastAPI app for Cook Islands Legislation RAG Chat Service."""
from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect, HTTPException, Header, Depends
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from loguru import logger
import os
import json
from typing import Optional, List, Dict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .tools.ingest import ingest_pdf, ingest_all_pdfs, ingest_from_url
from .tools.scraper import scrape_legislation
from .tools.legislation_tools import create_tool_definitions, execute_tool
from .rag.indexer import store
from .config import legislation_config
from .mcp_server import mcp

# Import OpenAI for chat
from openai import AsyncOpenAI
from pathlib import Path

# Load system prompt from markdown file
def load_system_prompt() -> str:
    """Load system prompt from app/system_prompt.md file."""
    prompt_path = Path(__file__).parent / "system_prompt.md"
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        logger.error(f"System prompt file not found: {prompt_path}")
        # Fallback to basic prompt
        return "You are a helpful assistant specializing in Cook Islands legislation."

# Create MCP ASGI app
mcp_app = mcp.http_app()

# Initialize FastAPI app with MCP lifespan
app = FastAPI(
    title="Cook Islands Legislation RAG",
    version="1.0.0",
    description="Semantic search and chat interface for Cook Islands legislation",
    lifespan=mcp_app.lifespan
)

# Session middleware
APP_SECRET = os.getenv('APP_SECRET', 'change-this-secret-key-in-production')
app.add_middleware(
    SessionMiddleware,
    secret_key=APP_SECRET,
    session_cookie="session",
    max_age=3600,
    same_site="lax",
    https_only=os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
)

# API Key authentication dependency
async def verify_api_key(authorization: str = Header(None)):
    """Verify API key from Authorization header."""
    api_key = os.getenv('API_KEY')
    if not api_key:
        # If no API_KEY is set, allow access
        logger.warning("API_KEY not set - endpoint is unprotected")
        return

    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Use: Authorization: Bearer <API_KEY>"
        )

    provided_key = authorization.replace('Bearer ', '', 1)
    if provided_key != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")


# Mount static files and templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Mount PDFs directory for direct access
LEGISLATION_DIR = os.getenv('LEGISLATION_DIR', 'data/legislation')
if os.path.exists(LEGISLATION_DIR):
    app.mount("/pdfs", StaticFiles(directory=LEGISLATION_DIR), name="pdfs")
    logger.info(f"Mounted PDF directory: {LEGISLATION_DIR}")
else:
    logger.warning(f"PDF directory not found: {LEGISLATION_DIR}")


@app.get('/', response_class=PlainTextResponse)
async def index():
    """Root endpoint showing service status."""
    chunks = len(store.chunks)
    vectors = len(store.vectors) if store.vectors is not None else 0

    # Get unique acts
    act_names = set()
    for chunk in store.chunks:
        act_name = chunk.meta.get('act_name')
        if act_name:
            act_names.add(act_name)

    unique_acts = len(act_names)

    return f"""Cook Islands Legislation RAG Service

Status:
  Chunks: {chunks}
  Vectors: {vectors}
  Unique Acts: {unique_acts}

Endpoints:
  GET  /                   - This status page
  GET  /chat               - Web chat interface
  WS   /ws/chat            - WebSocket chat endpoint
  POST /ingest/pdf         - Ingest PDF by file path
  POST /ingest/url         - Ingest PDF from URL
  POST /ingest/all         - Ingest all PDFs in legislation directory
  POST /scrape             - Scrape and download legislation
  GET  /stats              - Get RAG statistics
  GET  /health             - Health check
  *    /mcp                - MCP server (SSE transport)

MCP Tools:
  search_legislation_tool  - Vector search over legislation
  get_legislation_stats    - Get RAG store statistics

Web Interface:
  Visit /chat for interactive chat with legislation RAG
"""


@app.get('/chat', response_class=HTMLResponse)
async def chat_page():
    """Serve chat interface HTML."""
    from fastapi import Request
    # We'll create this template next
    return templates.TemplateResponse("chat.html", {"request": {}})


class ChatMessage(BaseModel):
    role: str
    content: str


@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time chat with GPT-5.1 and legislation RAG."""
    await websocket.accept()
    logger.info("WebSocket chat connection established")

    # Get OpenAI configuration
    openai_api_key = os.getenv('OPENAI_API_KEY')
    logger.info(f"OpenAI API key loaded: {bool(openai_api_key)}")
    if not openai_api_key:
        logger.error("OPENAI_API_KEY not found in environment")
        await websocket.send_json({
            'type': 'error',
            'content': 'OPENAI_API_KEY not configured'
        })
        await websocket.close()
        return

    openai_model = os.getenv('OPENAI_CHAT_MODEL', 'GPT-5.1')
    client = AsyncOpenAI(api_key=openai_api_key)

    # Load system prompt from file
    system_prompt = load_system_prompt()
    logger.info(f"Loaded system prompt: {len(system_prompt)} characters")

    # Conversation history
    messages: List[Dict[str, str]] = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            user_message = data.get('content', '')

            if not user_message.strip():
                continue

            logger.info(f"User message: {user_message}")

            # Add to conversation history
            messages.append({"role": "user", "content": user_message})

            # Call OpenAI with function calling (agentic loop)
            try:
                # Define all available tools
                tools = create_tool_definitions()

                # Agentic loop: allow multiple tool calls before final response
                max_iterations = 10
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1
                    logger.info(f"Agentic loop iteration {iteration}/{max_iterations}")

                    # API call with tools
                    response = await client.chat.completions.create(
                        model=openai_model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        stream=False
                    )

                    assistant_message = response.choices[0].message

                    # Check if model wants to call tools
                    if assistant_message.tool_calls:
                        # Add assistant message to history
                        messages.append(assistant_message.model_dump())

                        # Execute all tool calls for this turn
                        for tool_call in assistant_message.tool_calls:
                            tool_name = tool_call.function.name
                            args = json.loads(tool_call.function.arguments)

                            # Send tool use notification to client
                            await websocket.send_json({
                                'type': 'tool_use',
                                'content': f'Using {tool_name}...'
                            })

                            # Execute tool
                            tool_result = await execute_tool(tool_name, args)

                            # Send results to client for UI display
                            if tool_result.get('success') and tool_result.get('results'):
                                await websocket.send_json({
                                    'type': 'search_results',
                                    'content': tool_result['results']
                                })

                            # Add tool response to messages
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": json.dumps(tool_result)
                            })

                        # Continue loop to allow model to make more tool calls
                        continue

                    else:
                        # No more tool calls - model is ready to respond
                        # Stream final response
                        final_response = await client.chat.completions.create(
                            model=openai_model,
                            messages=messages,
                            stream=True
                        )

                        full_response = ""
                        async for chunk in final_response:
                            if chunk.choices[0].delta.content:
                                content = chunk.choices[0].delta.content
                                full_response += content
                                await websocket.send_json({
                                    'type': 'content_delta',
                                    'content': content
                                })

                        # Add to history
                        messages.append({"role": "assistant", "content": full_response})

                        # Signal completion
                        await websocket.send_json({'type': 'done'})
                        break

                # Safety: if we hit max iterations without completion
                if iteration >= max_iterations:
                    logger.warning(f"Agentic loop reached max iterations ({max_iterations})")
                    await websocket.send_json({
                        'type': 'error',
                        'content': 'Reached maximum tool iterations. Please try a simpler question.'
                    })

            except Exception as e:
                logger.exception(f"OpenAI API error: {e}")
                await websocket.send_json({
                    'type': 'error',
                    'content': f'Error: {str(e)}'
                })

    except WebSocketDisconnect:
        logger.info("WebSocket chat connection closed")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@app.post('/ingest/pdf', dependencies=[Depends(verify_api_key)])
async def api_ingest_pdf(pdf_path: str = Form(...), act_name: str = Form(None)):
    """Ingest a PDF from file path (requires API key)."""
    try:
        chunks = await ingest_pdf(pdf_path, act_name=act_name)
        return JSONResponse({"ok": True, "chunks": chunks, "pdf_path": pdf_path})
    except Exception as e:
        logger.exception(f"Ingest failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post('/ingest/url', dependencies=[Depends(verify_api_key)])
async def api_ingest_url(url: str = Form(...), act_name: str = Form(...)):
    """Ingest a PDF from URL (requires API key)."""
    try:
        chunks = await ingest_from_url(url, act_name=act_name)
        return JSONResponse({"ok": True, "chunks": chunks, "url": url})
    except Exception as e:
        logger.exception(f"Ingest from URL failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post('/ingest/all', dependencies=[Depends(verify_api_key)])
async def api_ingest_all():
    """Ingest all PDFs in legislation directory (requires API key)."""
    try:
        stats = await ingest_all_pdfs()
        return JSONResponse({"ok": True, **stats})
    except Exception as e:
        logger.exception(f"Batch ingest failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post('/scrape', dependencies=[Depends(verify_api_key)])
async def api_scrape(limit: int = Form(None)):
    """Scrape and download legislation from Cook Islands API (requires API key).

    Args:
        limit: Optional limit on number of PDFs to download (for testing)
    """
    try:
        stats = await scrape_legislation(limit=limit)
        # Update config with scrape stats
        legislation_config.update_scrape_stats(stats)
        return JSONResponse({"ok": True, **stats})
    except Exception as e:
        logger.exception(f"Scrape failed: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get('/stats')
async def api_stats():
    """Get RAG store statistics."""
    # Get unique acts
    act_names = set()
    for chunk in store.chunks:
        act_name = chunk.meta.get('act_name')
        if act_name:
            act_names.add(act_name)

    return {
        "ok": True,
        "total_chunks": len(store.chunks),
        "total_vectors": len(store.vectors) if store.vectors else 0,
        "unique_acts": len(act_names),
        "sample_acts": sorted(list(act_names))[:20]
    }


@app.get('/health')
async def health():
    """Health check endpoint."""
    return {
        "ok": True,
        "service": "cook-islands-legislation-rag",
        "chunks": len(store.chunks),
        "vectors": len(store.vectors) if store.vectors is not None else 0,
    }


# Mount MCP server at /mcp (must be last to avoid catching other routes)
app.mount("/mcp", mcp_app)
