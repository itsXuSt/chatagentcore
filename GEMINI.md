# ChatAgentCore

## Project Overview

ChatAgentCore is a middleware service designed to bridge Qt-based AI applications with major Chinese enterprise chat platforms (Feishu, WeCom, DingTalk). It acts as a unified interface layer, allowing AI applications to interact with these platforms without handling platform-specific protocols directly.

**Key Features:**
*   **Multi-Platform Support:** Currently supports Feishu (Lark), with planned support for WeCom and DingTalk.
*   **WebSocket Long Connection:** Uses official SDKs (e.g., `lark-oapi`) to establish persistent WebSocket connections (SSE), eliminating the need for public IPs or complex network tunneling (like Cloudflare Tunnel).
*   **Unified Interface:** Provides a standard HTTP API for sending messages and a WebSocket interface for receiving events/messages in real-time.
*   **Configuration Driven:** Fully configurable via YAML, supporting dynamic hot-reloading.
*   **Local Deployment:** Optimized for running on personal computers or local servers alongside the AI application.

## Architecture

The system follows a layered architecture:

1.  **Interface Layer (`api/`)**:
    *   **HTTP API (FastAPI):** Handles synchronous requests (e.g., sending messages) from the AI application.
    *   **WebSocket Server:** Pushes real-time events (incoming messages) to the AI application.

2.  **Core Service Layer (`core/`)**:
    *   **Router:** Routes incoming messages to the Event Bus and outgoing messages to the appropriate Platform Adapter.
    *   **Event Bus:** Publishes message events to subscribers (Loggers, WebSocket clients).
    *   **Config Manager:** Manages configuration loading and validation with hot-reload support.

3.  **Platform Adapter Layer (`adapters/`)**:
    *   **Base Adapter:** Defines the abstract interface for all platform adapters.
    *   **Feishu Adapter:** Implements the Feishu protocol using `lark-oapi` with WebSocket support.

## Building and Running

### Prerequisites

*   Python 3.10+
*   Feishu App Credentials (App ID, App Secret) with appropriate permissions.

### Installation

1.  **Create Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # or venv\Scripts\activate on Windows
    ```

2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Install Package in Editable Mode:**
    ```bash
    pip install -e .
    ```

### Configuration

Copy the example configuration and edit it:

```bash
cp config/config.yaml.example config/config.yaml
```

**Key Configuration Fields (`config/config.yaml`):**
*   `platforms.feishu.enabled`: Set to `true`.
*   `platforms.feishu.config.app_id`: Your Feishu App ID.
*   `platforms.feishu.config.app_secret`: Your Feishu App Secret.
*   `server.host` / `server.port`: API server settings.

### Running the Service

```bash
# Run the main application
python -c "
import sys
sys.path.insert(0, '.')
from chatagentcore.api.main import app
import uvicorn
uvicorn.run(app, host='0.0.0.0', port=8000)
"
```

### Verification & Testing

Use the interactive CLI tool to verify the Feishu connection and send/receive messages:

```bash
python cli/test_feishu_ws.py
```

*   **Commands inside CLI:**
    *   Type text to reply to the last sender.
    *   `/status`: Check connection status.
    *   `/set <open_id>`: Set a specific recipient.

## Development Conventions

*   **Code Style:** Follows PEP 8. Format with `black` and lint with `ruff`.
*   **Type Hinting:** Extensive use of Python type hints (`mypy` enabled).
*   **AsyncIO:** The core is built on `asyncio`. Ensure all I/O operations are non-blocking.
*   **Logging:** Uses `loguru` for structured logging.
*   **Testing:** Uses `pytest` with `pytest-asyncio`. Run tests via `pytest`.

## Key Files & Directories

*   `chatagentcore/api/main.py`: Application entry point.
*   `chatagentcore/core/config_manager.py`: Configuration logic.
*   `chatagentcore/adapters/feishu/client.py`: Feishu WebSocket client implementation.
*   `docs/architecture/system-design.md`: Detailed system architecture documentation.
*   `cli/test_feishu_ws.py`: Main tool for verifying platform integration.
