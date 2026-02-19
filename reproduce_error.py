import asyncio
import os
import logging
from dotenv import load_dotenv
from src.llm.providers.google_provider import GoogleProvider

# Configure logging to see what's happening
logging.basicConfig(level=logging.INFO)

async def main():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found")
        return

    provider = GoogleProvider(api_key=api_key)
    messages = [
        {"role": "user", "content": "Hello, how are you?"}
    ]
    
    print(f"Testing chat with model: {provider.current_model}")
    try:
        response = await provider.chat(messages)
        print(f"Response: {response.content}")
    except Exception as e:
        print(f"Caught exception: '{e}'")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
