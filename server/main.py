"""
FastAPI Server for Omni-Visual Accessibility Navigator.

Real-time WebSocket server supporting both text and audio input.
No video - agent uses tools to fetch Google Maps imagery.

Optimized with:
- Metrics endpoint
- Cache statistics
- Proper shutdown cleanup
"""

import json
import asyncio
import base64
import os
import sys
import logging
from datetime import datetime
from contextlib import asynccontextmanager

from dotenv import load_dotenv

from google.genai.types import Part, Content, Blob
from google.adk.runners import InMemoryRunner
from google.adk.agents import LiveRequestQueue
from google.adk.agents.run_config import RunConfig
from google.genai import types

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnect

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omni_visual.agent import root_agent, cleanup
from omni_visual.cache import get_all_cache_stats, clear_all_caches
from omni_visual.observability import metrics, setup_logging

load_dotenv()

# Setup logging with observability features
setup_logging(level=logging.INFO)
logger = logging.getLogger("omni-visual")


# =============================================================================
# Lifespan Management
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    # Startup
    logger.info("Omni-Visual server starting up...")
    yield
    # Shutdown
    logger.info("Omni-Visual server shutting down...")
    await cleanup()
    logger.info("Cleanup complete")


# =============================================================================
# Session Management
# =============================================================================


async def start_agent_session(user_id: str):
    """Starts an agent session with text + audio support."""

    runner = InMemoryRunner(
        app_name=os.getenv("APP_NAME", "omni-visual"), agent=root_agent
    )

    session = await runner.session_service.create_session(
        app_name=os.getenv("APP_NAME", "omni-visual"),
        user_id=user_id,
    )

    live_request_queue = LiveRequestQueue()

    # RunConfig for real-time audio + text (no video)
    run_config = RunConfig(
        streaming_mode="bidi",
        session_resumption=types.SessionResumptionConfig(transparent=True),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                prefix_padding_ms=0,
                silence_duration_ms=0,
            )
        ),
        response_modalities=["AUDIO"],  # Agent responds with audio
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=os.getenv("AGENT_VOICE", "Puck")
                )
            ),
            language_code=os.getenv("AGENT_LANGUAGE", "en-US"),
        ),
        output_audio_transcription={},
        input_audio_transcription={},
    )

    live_events = runner.run_live(
        session=session,
        live_request_queue=live_request_queue,
        run_config=run_config,
    )
    return live_events, live_request_queue


# =============================================================================
# Console Logging Utilities
# =============================================================================

# Track agent state for better visibility
_agent_state = {
    "last_activity": None,
    "pending_tools": set(),
    "turn_start": None,
}


def _timestamp() -> str:
    """Get formatted timestamp for console output."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _log(icon: str, label: str, message: str, color_code: str = ""):
    """Print a formatted log line with timestamp."""
    ts = _timestamp()
    reset = "\033[0m" if color_code else ""
    print(f"{color_code}[{ts}] [{icon} {label}] {message}{reset}")


def log_user_input(text: str, is_final: bool):
    """Log user speech/text input."""
    status = "FINAL" if is_final else "partial"
    truncated = text[:80] + "..." if len(text) > 80 else text
    _log("🎤", f"USER {status}", truncated, "\033[96m")  # Cyan


def log_model_output(text: str, is_final: bool):
    """Log model text output."""
    if not is_final:
        return  # Skip streaming partials to reduce noise
    truncated = text[:120] + "..." if len(text) > 120 else text
    _log("🤖", "MODEL", truncated, "\033[92m")  # Green


def log_tool_start(name: str, args: dict):
    """Log when a tool call starts."""
    _agent_state["pending_tools"].add(name)
    _agent_state["last_activity"] = datetime.now()
    args_str = str(args)[:100] + "..." if len(str(args)) > 100 else str(args)
    _log("⚡", "TOOL START", f"{name}({args_str})", "\033[93m")  # Yellow


def log_tool_done(name: str, result_size: int):
    """Log when a tool call completes successfully."""
    _agent_state["pending_tools"].discard(name)
    _log("✅", "TOOL DONE", f"{name} → {result_size} chars", "\033[92m")  # Green


def log_tool_error(name: str, error: str):
    """Log when a tool call fails."""
    _agent_state["pending_tools"].discard(name)
    _log("❌", "TOOL ERROR", f"{name}: {error}", "\033[91m")  # Red


def log_turn_complete(author: str):
    """Log turn completion."""
    elapsed = ""
    if _agent_state["turn_start"]:
        elapsed_sec = (datetime.now() - _agent_state["turn_start"]).total_seconds()
        elapsed = f" ({elapsed_sec:.1f}s)"
    _log("🔄", "TURN DONE", f"by {author}{elapsed}", "\033[95m")  # Magenta
    _agent_state["turn_start"] = None


def log_turn_start():
    """Log turn start (when user input is received)."""
    _agent_state["turn_start"] = datetime.now()
    _log("▶️", "TURN START", "Processing...", "\033[95m")  # Magenta


def log_thinking():
    """Log that model is thinking (no tools, no output yet)."""
    pending = list(_agent_state["pending_tools"])
    if pending:
        _log("⏳", "WAITING", f"Pending tools: {pending}", "\033[90m")  # Gray
    else:
        _log("🧠", "THINKING", "Model is processing...", "\033[90m")  # Gray


def log_interrupted():
    """Log when agent is interrupted."""
    _log("⚠️", "INTERRUPTED", "User interrupted the agent", "\033[91m")  # Red


# =============================================================================
# WebSocket Handlers
# =============================================================================


async def agent_to_client_messaging(websocket: WebSocket, live_events):
    """Agent to client: sends audio + text transcriptions."""
    async for event in live_events:
        try:
            message_to_send = {
                "author": event.author or "agent",
                "is_partial": event.partial or False,
                "turn_complete": event.turn_complete or False,
                "interrupted": event.interrupted or False,
                "parts": [],
                "input_transcription": None,
                "output_transcription": None,
            }

            # [OBSERVABILITY] Log turn state changes
            if event.turn_complete:
                log_turn_complete(event.author or "agent")
            if event.interrupted:
                log_interrupted()

            if not event.content:
                if message_to_send["turn_complete"] or message_to_send["interrupted"]:
                    await websocket.send_text(json.dumps(message_to_send))
                continue

            transcription_text = "".join(
                part.text for part in event.content.parts if part.text
            )

            if hasattr(event.content, "role") and event.content.role == "user":
                if transcription_text:
                    # [OBSERVABILITY] Log user input and start turn timer
                    is_final = not event.partial
                    log_user_input(transcription_text, is_final)
                    if is_final:
                        log_turn_start()
                    
                    message_to_send["input_transcription"] = {
                        "text": transcription_text,
                        "is_final": is_final,
                    }

            elif hasattr(event.content, "role") and event.content.role == "model":
                if transcription_text:
                    # [OBSERVABILITY] Log model output
                    is_final = not event.partial
                    log_model_output(transcription_text, is_final)
                    
                    message_to_send["output_transcription"] = {
                        "text": transcription_text,
                        "is_final": is_final,
                    }
                    message_to_send["parts"].append(
                        {"type": "text", "data": transcription_text}
                    )

                for part in event.content.parts:
                    if part.inline_data and part.inline_data.mime_type.startswith(
                        "audio/pcm"
                    ):
                        audio_data = part.inline_data.data
                        encoded_audio = base64.b64encode(audio_data).decode("ascii")
                        message_to_send["parts"].append(
                            {"type": "audio/pcm", "data": encoded_audio}
                        )

                    elif part.function_call:
                        # [OBSERVABILITY] Log tool call start
                        func_name = part.function_call.name
                        func_args = part.function_call.args or {}
                        log_tool_start(func_name, func_args)
                        
                        message_to_send["parts"].append(
                            {
                                "type": "function_call",
                                "data": {
                                    "name": func_name,
                                    "args": func_args,
                                },
                            }
                        )

                    elif part.function_response:
                        # [OBSERVABILITY] Log tool result
                        func_name = part.function_response.name
                        func_response = part.function_response.response or {}
                        
                        # Check for errors in response
                        if isinstance(func_response, dict) and (
                            func_response.get("error") or 
                            func_response.get("success") is False
                        ):
                            error_msg = func_response.get("error", "Unknown error")
                            log_tool_error(func_name, error_msg)
                        else:
                            # Calculate result size
                            result_str = str(func_response)
                            result_size = len(result_str)
                            log_tool_done(func_name, result_size)
                        
                        message_to_send["parts"].append(
                            {
                                "type": "function_response",
                                "data": {
                                    "name": func_name,
                                    "response": func_response,
                                },
                            }
                        )

            if (
                message_to_send["parts"]
                or message_to_send["turn_complete"]
                or message_to_send["interrupted"]
                or message_to_send["input_transcription"]
                or message_to_send["output_transcription"]
            ):
                await websocket.send_text(json.dumps(message_to_send))

        except Exception as e:
            logger.error(f"Error in agent_to_client_messaging: {e}")


async def client_to_agent_messaging(
    websocket: WebSocket, live_request_queue: LiveRequestQueue
):
    """Client to agent: handles text and audio input (no video)."""
    while True:
        try:
            message_json = await websocket.receive_text()
            message = json.loads(message_json)
            mime_type = message.get("mime_type", "text/plain")

            if mime_type == "text/plain":
                data = message.get("data", "")
                content = Content(role="user", parts=[Part.from_text(text=data)])
                live_request_queue.send_content(content=content)

            elif mime_type == "audio/pcm":
                data = message.get("data", "")
                decoded_data = base64.b64decode(data)
                live_request_queue.send_realtime(
                    Blob(data=decoded_data, mime_type=mime_type)
                )

            # Note: video (image/jpeg) intentionally NOT supported
            else:
                logger.warning(f"Unsupported mime type: {mime_type}")

        except WebSocketDisconnect:
            logger.info("Client disconnected.")
            break
        except Exception as e:
            logger.error(f"Error in client_to_agent_messaging: {e}")


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Omni-Visual Accessibility Navigator",
    description="Voice + text agent that fetches and describes Google Maps imagery",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "name": "Omni-Visual",
        "version": "0.2.0",
        "input": "text or audio (no video)",
        "output": "audio + transcription",
        "websocket": "/ws/{user_id}",
        "endpoints": {
            "health": "/health",
            "metrics": "/metrics",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/metrics")
async def get_metrics():
    """
    Return service metrics including API performance and cache statistics.
    
    Useful for monitoring and debugging.
    """
    return {
        "api_metrics": metrics.summary(),
        "cache": get_all_cache_stats(),
    }


@app.post("/metrics/reset")
async def reset_metrics():
    """Reset all metrics counters."""
    metrics.reset()
    return {"status": "metrics reset"}


@app.post("/cache/clear")
async def clear_cache():
    """Clear all caches."""
    clear_all_caches()
    return {"status": "caches cleared"}


@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket for text + audio chat (no video)."""
    await websocket.accept()
    logger.info(f"Client #{user_id} connected")

    live_events, live_request_queue = await start_agent_session(str(user_id))

    agent_to_client_task = asyncio.create_task(
        agent_to_client_messaging(websocket, live_events)
    )
    client_to_agent_task = asyncio.create_task(
        client_to_agent_messaging(websocket, live_request_queue)
    )

    await asyncio.wait(
        [agent_to_client_task, client_to_agent_task],
        return_when=asyncio.FIRST_EXCEPTION,
    )

    live_request_queue.close()
    logger.info(f"Client #{user_id} disconnected")
