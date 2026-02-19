
import asyncio
import sys
import os
import time
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add src to path
sys.path.append(os.getcwd())

from src.agent.builtins.web import search_web

async def main():
    query = "weather in Sedgewick Alberta"
    logger.info(f"Starting test search for: '{query}'")
    
    start_time = time.time()
    try:
        # Check if search_web is actually awaiting
        logger.info("Calling search_web...")
        result_json = await search_web(query)
        
        duration = time.time() - start_time
        logger.info(f"Search completed in {duration:.2f} seconds")
        
        if result_json:
            print("\nRESULT RECEIVED (preview):")
            print(result_json[:500])
        else:
            print("\nNO RESULT returned.")
            
    except asyncio.TimeoutError:
        logger.error("❌ Outer execution timed out!")
    except Exception as e:
        logger.error(f"❌ Exception during search: {e}", exc_info=True)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
