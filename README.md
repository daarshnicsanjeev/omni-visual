# Omni-Visual Accessibility Navigator

AI agent for blind users with **Google Maps MCP** integration + visual exploration.

## ✨ Features

- **Dual-mode vision**: Overhead (satellite/roadmap) + Street View imagery
- **360° panoramic capture**: Parallel processing for fast "look around" queries
- **Accessibility-first responses**: Clock positions, landmarks, hazards
- **Caching**: Avoid redundant API calls for repeated queries
- **Observability**: Metrics, logging, and tracing

## Tools Available

| Tool Type | Tools | Purpose |
|-----------|-------|---------| 
| **MCP** | `maps_search_places`, `maps_get_directions`, `maps_geocode` | Search, routes, geocoding |
| **Vision** | `get_overhead_view`, `get_street_view`, `explore_panoramic` | Satellite/Street View images |

## Setup

```bash
cd omni-visual
uv sync
copy .env.example .env   # Add your API keys
```

### Required Environment Variables

```env
# Required
GOOGLE_API_KEY=your-gemini-api-key
GOOGLE_MAPS_API_KEY=your-maps-api-key

# Optional
OMNI_VISUAL_MULTI_AGENT=false   # Enable multi-agent architecture
OMNI_VISUAL_FAST_MODEL=gemini-2.0-flash
OMNI_VISUAL_VISION_MODEL=gemini-3.0-pro
AGENT_VOICE=Puck
AGENT_LANGUAGE=en-US
```

## Run

**Option 1: ADK Web UI**
```bash
cd src
adk web
```

**Option 2: FastAPI Server**
```bash
uv run uvicorn server.main:app --reload
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info |
| `/health` | GET | Health check |
| `/metrics` | GET | Performance metrics & cache stats |
| `/metrics/reset` | POST | Reset metrics |
| `/cache/clear` | POST | Clear all caches |
| `/ws/{user_id}` | WebSocket | Real-time chat |

## Example Queries

- "Find coffee shops near Times Square and show me what's there"
- "Get directions from Central Park to Empire State Building"
- "Is there a crosswalk at this intersection?" *(uses zoom=20 satellite)*
- "Look around and describe what you see" *(parallel panoramic)*

## Architecture

```
omni-visual/
├── src/omni_visual/
│   ├── agent.py          # Agent definitions (single or multi-agent)
│   ├── prompts.py        # Structured prompts with examples
│   ├── cache.py          # In-memory caching layer
│   ├── observability.py  # Logging, metrics, tracing
│   └── tools/
│       └── vision.py     # Vision tools with retries & pooling
└── server/
    └── main.py           # FastAPI WebSocket server
```

## Performance Optimizations

| Feature | Benefit |
|---------|---------|
| HTTP Connection Pooling | ~200ms faster per request |
| Parallel Panoramic | 4x faster "look around" queries |
| Response Caching | Instant repeated queries |
| Retry with Backoff | Better reliability |
| Image Compression | Optional smaller payloads |

## Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `OMNI_VISUAL_MULTI_AGENT` | `false` | Enable coordinator + specialist agents |
| `OMNI_VISUAL_FAST_MODEL` | `gemini-2.0-flash` | Model for coordinator (if multi-agent) |
| `OMNI_VISUAL_VISION_MODEL` | `gemini-3.0-pro` | Model for vision tasks |
