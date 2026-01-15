# Contributing to Omni-Visual

Thank you for your interest in contributing to Omni-Visual! We welcome contributions to improve accessibility for blind and low-vision users.

## Development Setup

1. **Prerequisites**
   - Python 3.11+
   - `uv` (for dependency management)
   - Google Cloud Project with:
     - Gemini API enabled
     - Google Maps Platform APIs enabled (Maps Static, Street View Static, Geocoding, Places, Directions)

2. **Installation**
   ```bash
   # Clone the repository
   git clone <repository_url>
   cd omni-visual

   # Install dependencies
   uv sync
   ```

3. **Configuration**
   Copy `.env.example` to `.env` and fill in your API keys:
   ```env
   GOOGLE_API_KEY=your-gemini-key
   GOOGLE_MAPS_API_KEY=your-maps-key
   ```

## Code Style

- **Type Hints**: All function signatures must have type hints.
- **Docstrings**: Use Google-style docstrings for all modules, classes, and functions.
- **Formatting**: The project uses standard Python formatting. Run `uv run ruff format .` before committing.
- **Linting**: Run `uv run ruff check .` to catch issues.

## Architecture Guidelines

- **Agent Logic**: Keep `agent.py` clean. Move complex logic to tools or helper modules.
- **Tools**: New tools should be added to `src/omni_visual/tools/`.
- **Caching**: Use `src/omni_visual/cache.py` for any expensive API calls.
- **Observability**: Instrument key functions with `@timed` or `@counted` from `src/omni_visual/observability.py`.

## Pull Request Process

1. Fork the repository and create a new branch.
2. Make your changes, ensuring robust error handling.
3. Test your changes locally.
4. Submit a Pull Request with a clear description of the problem and solution.

## Testing

Currently, we rely on manual verification and the `test_connectivity.py` script for network checks.
To test connectivity:
```bash
python test_connectivity.py
```
