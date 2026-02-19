import asyncio
import sys
import os
import json

# Add project root to path
sys.path.append(os.getcwd())

from src.agent.builtins.web import search_web

async def test_canvas_output():
    print("Calling search_web...")
    result = await search_web("python release date")
    
    print("\nResult Type:", type(result))
    print("Result Preview (first 500 chars):")
    print(str(result)[:500])
    
    try:
        data = json.loads(result)
        if "__canvas__" in data:
            print("\nSUCCESS: Found __canvas__ key.")
            print("Canvas Data Type:", data["__canvas__"].get("type"))
            print("Number of results:", len(data["__canvas__"].get("results", [])))
        else:
            print("\nFAILURE: JSON parsed but no __canvas__ key.")
    except json.JSONDecodeError:
        print("\nFAILURE: Result is not valid JSON.")
    except Exception as e:
        print(f"\nFAILURE: Error parsing JSON: {e}")

if __name__ == "__main__":
    asyncio.run(test_canvas_output())
