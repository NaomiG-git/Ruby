
import asyncio
import logging
from src.agent.controller import AgentController
from config.settings import get_settings

logging.basicConfig(level=logging.INFO)

async def verify_video_tools():
    print("Verifying Video Editing Skills...")
    settings = get_settings()
    agent = AgentController(settings)
    
    video_tools = [name for name in agent._tool_map if any(k in name for k in ["video", "trim", "audio"])]
    print(f"Detected Video Tools: {video_tools}")
    
    expected_tools = ["concatenate_videos", "trim_video", "add_audio_overlay"]
    all_present = all(t in agent._tool_map for t in expected_tools)
    
    if all_present:
        print("SUCCESS: All video tools successfully registered!")
    else:
        missing = [t for t in expected_tools if t not in agent._tool_map]
        print(f"FAILURE: Missing tools: {missing}")
        
    try:
        import moviepy
        print(f"✅ MoviePy version {moviepy.__version__} is available.")
    except ImportError:
        print("❌ MoviePy NOT found in environment.")

if __name__ == "__main__":
    asyncio.run(verify_video_tools())
