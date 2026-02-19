"""Application Entry Point."""

import asyncio
import logging
from ui.cli import CLI

# Configure logging
logging.basicConfig(
    level=logging.WARNING,  # Default to warning to keep CLI clean
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Silence noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

async def main():
    """Run the application."""
    import sys
    
    # Simple arg check for now
    if "--cli" in sys.argv:
        cli = CLI()
        await cli.start()
    else:
        # Run Web Server
        import uvicorn
        print("Starting Web UI at http://localhost:8000")
        config = uvicorn.Config("src.server.api:app", host="127.0.0.1", port=8000, reload=True)
        server = uvicorn.Server(config)
        await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
