import os
from config.settings import get_settings

def test_config():
    settings = get_settings()
    print("--- Loaded Settings ---")
    print(f"LLM_PROVIDER: {settings.llm_provider}")
    print(f"LLM_MODEL: {settings.llm_model}")
    print(f"GOOGLE_API_KEY: {settings.google_api_key[:10]}...")
    print(f"OPENAI_API_KEY: {settings.openai_api_key[:10]}...")
    
    print("\n--- Environment Variables (directly) ---")
    print(f"LLM_PROVIDER: {os.environ.get('LLM_PROVIDER')}")
    print(f"LLM_MODEL: {os.environ.get('LLM_MODEL')}")

if __name__ == "__main__":
    test_config()
