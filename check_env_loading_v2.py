import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from dotenv import load_dotenv
load_dotenv()

key = os.getenv("ANTHROPIC_API_KEY")
print(f"ANTHROPIC_API_KEY loaded: {bool(key)}")
if key:
    print(f"Key length: {len(key)}")
    print(f"Key start: {key[:10]}...")

from src.server.api import get_agent
from config.settings import get_settings

# Force switch via direct instantiation interaction isn't easy without running server
# But we can check what settings loaded
settings = get_settings()
print(f"Settings Provider: {settings.llm_provider}")
print(f"Settings Model: {settings.llm_model}")
