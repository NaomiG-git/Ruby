from config.settings import get_settings
from src.llm.factory import ProviderFactory

def main():
    settings = get_settings()
    print(f"LLM_PROVIDER: {settings.llm_provider}")
    print(f"LLM_MODEL: {settings.llm_model}")
    print(f"GOOGLE_API_KEY: {'[SET]' if settings.google_api_key else '[MISSING]'}")
    
    provider = ProviderFactory.create(settings=settings)
    print(f"Created provider name: {provider.name}")
    print(f"Current model in provider: {provider.current_model}")

if __name__ == "__main__":
    main()
