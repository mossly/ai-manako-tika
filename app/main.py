"""FastAPI app for Cook Islands Legislation RAG Chat Service."""
from fastapi import FastAPI, Form, WebSocket, WebSocketDisconnect, HTTPException, Header, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse, RedirectResponse
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

# Use absolute imports that work both locally and in Docker
try:
    from .tools.ingest import ingest_pdf, ingest_all_pdfs, ingest_from_url
    from .tools.scraper import scrape_legislation
    from .tools.legislation_tools import create_tool_definitions, execute_tool
    from .rag.indexer import store
    from .config import legislation_config
    from .mcp_server import mcp
    from .db.metadata import metadata_db
except ImportError:
    # Fallback for running directly as a script (local development)
    from tools.ingest import ingest_pdf, ingest_all_pdfs, ingest_from_url
    from tools.scraper import scrape_legislation
    from tools.legislation_tools import create_tool_definitions, execute_tool
    from rag.indexer import store
    from config import legislation_config
    from mcp_server import mcp
    from db.metadata import metadata_db

# Import OpenAI-compatible client for OpenRouter
from openai import AsyncOpenAI
from pathlib import Path
import secrets
from datetime import datetime, timedelta

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


@app.get('/')
async def index(request: Request):
    """Root endpoint - redirects browsers to /chat, shows status for API clients."""
    # Check if request is from a browser
    accept_header = request.headers.get('accept', '')
    if 'text/html' in accept_header:
        # Browser request - redirect to chat
        return RedirectResponse(url='/chat', status_code=302)

    # API request - return status as plain text
    stats = store.get_stats()
    return PlainTextResponse(f"""Cook Islands Legislation RAG Service

Status:
  Chunks: {stats['total_chunks']}
  Vectors: {stats['total_vectors']}
  Unique Acts: {stats['unique_acts']}

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
""")


@app.get('/chat', response_class=HTMLResponse)
async def chat_page():
    """Serve chat interface HTML."""
    from fastapi import Request
    # We'll create this template next
    return templates.TemplateResponse("chat.html", {"request": {}})


class AuthRequest(BaseModel):
    code: str


class SessionResponse(BaseModel):
    session_id: str
    expires_at: str


@app.post('/auth/login', response_model=SessionResponse)
async def login(auth_request: AuthRequest):
    """Authenticate with code and create session."""
    # Check auth code
    expected_code = os.getenv('AUTH_CODE', 'strategyday')

    if auth_request.code != expected_code:
        raise HTTPException(status_code=401, detail="Invalid authentication code")

    # Generate session
    session_id = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=24)

    # Store session in database
    metadata_db.create_session(
        session_id=session_id,
        auth_code=auth_request.code,
        expires_at=expires_at.isoformat()
    )

    logger.info(f"Created session {session_id}")

    return SessionResponse(
        session_id=session_id,
        expires_at=expires_at.isoformat()
    )


@app.post('/auth/validate')
async def validate_session(session_id: str = Form(...)):
    """Validate a session token."""
    session = metadata_db.get_session(session_id)

    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    return {"valid": True, "session_id": session_id}


class ConversationCreate(BaseModel):
    session_id: str
    title: Optional[str] = None


class ConversationUpdate(BaseModel):
    title: Optional[str] = None


@app.post('/conversations')
async def create_conversation(conversation: ConversationCreate):
    """Create a new conversation."""
    # Validate session
    session = metadata_db.get_session(conversation.session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Generate conversation ID
    conversation_id = secrets.token_urlsafe(16)

    # Create conversation
    metadata_db.create_conversation(
        conversation_id=conversation_id,
        session_id=conversation.session_id,
        title=conversation.title
    )

    return {
        "conversation_id": conversation_id,
        "title": conversation.title or "New Conversation"
    }


@app.get('/conversations')
async def list_conversations(session_id: str):
    """List all conversations for a session."""
    # Validate session
    session = metadata_db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    conversations = metadata_db.list_conversations(session_id)
    return {"conversations": conversations}


@app.get('/conversations/{conversation_id}')
async def get_conversation(conversation_id: str, session_id: str):
    """Get a specific conversation."""
    # Validate session
    session = metadata_db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    conversation = metadata_db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify conversation belongs to this session
    if conversation['session_id'] != session_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return conversation


@app.patch('/conversations/{conversation_id}')
async def update_conversation_title(conversation_id: str, update: ConversationUpdate, session_id: str = Form(...)):
    """Update conversation title."""
    # Validate session
    session = metadata_db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    conversation = metadata_db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify conversation belongs to this session
    if conversation['session_id'] != session_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Update title
    if update.title:
        metadata_db.update_conversation(
            conversation_id=conversation_id,
            messages=conversation['messages'],
            title=update.title
        )

    return {"success": True}


@app.delete('/conversations/{conversation_id}')
async def delete_conversation(conversation_id: str, session_id: str):
    """Delete a conversation."""
    # Validate session
    session = metadata_db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    conversation = metadata_db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify conversation belongs to this session
    if conversation['session_id'] != session_id:
        raise HTTPException(status_code=403, detail="Access denied")

    metadata_db.delete_conversation(conversation_id)
    return {"success": True}


class ChatMessage(BaseModel):
    role: str
    content: str


@app.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time chat with OpenRouter models and legislation RAG."""
    await websocket.accept()
    logger.info("WebSocket chat connection established")

    # Wait for initial message with session and conversation ID
    try:
        initial_data = await websocket.receive_json()
        session_id = initial_data.get('session_id')
        conversation_id = initial_data.get('conversation_id')

        if not session_id:
            await websocket.send_json({
                'type': 'error',
                'content': 'Session ID required'
            })
            await websocket.close()
            return

        # Validate session
        session = metadata_db.get_session(session_id)
        if not session:
            await websocket.send_json({
                'type': 'error',
                'content': 'Invalid or expired session'
            })
            await websocket.close()
            return

        logger.info(f"Session validated: {session_id}")

        # If no conversation ID provided, create a new one
        if not conversation_id:
            conversation_id = secrets.token_urlsafe(16)
            metadata_db.create_conversation(
                conversation_id=conversation_id,
                session_id=session_id,
                title="New Conversation"
            )
            logger.info(f"Created new conversation: {conversation_id}")
            # Send conversation ID to client
            await websocket.send_json({
                'type': 'conversation_created',
                'conversation_id': conversation_id
            })
        else:
            # Validate conversation exists and belongs to session
            conversation = metadata_db.get_conversation(conversation_id)
            if not conversation or conversation['session_id'] != session_id:
                await websocket.send_json({
                    'type': 'error',
                    'content': 'Invalid conversation'
                })
                await websocket.close()
                return

    except Exception as e:
        logger.error(f"Session validation failed: {e}")
        await websocket.send_json({
            'type': 'error',
            'content': 'Authentication required'
        })
        await websocket.close()
        return

    # Get OpenRouter configuration
    openrouter_api_key = os.getenv('OPENROUTER_API_KEY')
    logger.info(f"OpenRouter API key loaded: {bool(openrouter_api_key)}")
    if not openrouter_api_key:
        logger.error("OPENROUTER_API_KEY not found in environment")
        await websocket.send_json({
            'type': 'error',
            'content': 'OPENROUTER_API_KEY not configured'
        })
        await websocket.close()
        return

    # Default model (will be overridden by client selection)
    default_model = os.getenv('OPENROUTER_CHAT_MODEL', 'google/gemini-3-pro-preview')

    # Initialize OpenRouter client (OpenAI-compatible)
    client = AsyncOpenAI(
        api_key=openrouter_api_key,
        base_url="https://openrouter.ai/api/v1"
    )

    # Load system prompt from file
    system_prompt = load_system_prompt()
    logger.info(f"Loaded system prompt: {len(system_prompt)} characters")

    # Restore or initialize conversation history
    saved_messages = metadata_db.get_conversation_messages(conversation_id)
    if saved_messages and saved_messages != "[]":
        messages = json.loads(saved_messages)
        logger.info(f"Restored {len(messages)} messages from conversation {conversation_id}")
        # Send restored history to client
        await websocket.send_json({
            'type': 'history_restored',
            'messages': messages
        })
    else:
        # New conversation - initialize with system prompt
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

            # Handle ping/pong for keep-alive
            if data.get('type') == 'ping':
                await websocket.send_json({'type': 'pong'})
                metadata_db.update_session_activity(session_id)
                continue

            user_message = data.get('content', '')
            selected_model = data.get('model', default_model)  # Get model from client

            if not user_message.strip():
                continue

            logger.info(f"User message: {user_message}")
            logger.info(f"Selected model: {selected_model}")

            # Add to conversation history
            messages.append({"role": "user", "content": user_message})

            # Call OpenAI with function calling (agentic loop)
            try:
                # Define all available tools
                tools = create_tool_definitions()

                # Agentic loop: allow multiple tool calls before final response
                max_iterations = int(os.getenv('MAX_TOOL_ITERATIONS', '10'))
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1
                    logger.info(f"Agentic loop iteration {iteration}/{max_iterations}")

                    # API call with tools
                    response = await client.chat.completions.create(
                        model=selected_model,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        stream=False
                    )

                    assistant_message = response.choices[0].message

                    # Check if model wants to call tools
                    if assistant_message.tool_calls:
                        # Log if model incorrectly included content with tool calls
                        if assistant_message.content:
                            logger.warning(f"Model returned content with tool_calls (will be stripped): {assistant_message.content[:200]}")

                        # Add assistant message to history
                        # Clear content field to prevent tool call leakage into output
                        assistant_dict = assistant_message.model_dump()
                        assistant_dict['content'] = None  # Tool-calling messages should have no content
                        messages.append(assistant_dict)

                        logger.info(f"Processing {len(assistant_message.tool_calls)} tool call(s)")

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
                        logger.info("No tool calls detected, generating final response")

                        # Check if assistant message has content (edge case handling)
                        if assistant_message.content:
                            logger.info(f"Assistant message has content: {assistant_message.content[:100]}")

                        # Stream final response
                        final_response = await client.chat.completions.create(
                            model=selected_model,
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

                        # Save conversation to database
                        # Generate title from first user message if this is the first response
                        conversation = metadata_db.get_conversation(conversation_id)
                        title = conversation['title']
                        if title == "New Conversation" and len(messages) >= 3:
                            # Use first user message as title (truncated)
                            first_user_msg = next((m['content'] for m in messages if m['role'] == 'user'), None)
                            if first_user_msg:
                                title = first_user_msg[:50] + ('...' if len(first_user_msg) > 50 else '')

                        metadata_db.update_conversation(
                            conversation_id=conversation_id,
                            messages=json.dumps(messages),
                            title=title
                        )
                        metadata_db.update_session_activity(session_id=session_id)

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
    stats = store.get_stats()
    return {
        "ok": True,
        **stats
    }


@app.get('/health')
async def health():
    """Health check endpoint."""
    stats = store.get_stats()
    return {
        "ok": True,
        "service": "cook-islands-legislation-rag",
        "chunks": stats['total_chunks'],
        "vectors": stats['total_vectors'],
    }


# Mount MCP server at /mcp (must be last to avoid catching other routes)
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5500)
