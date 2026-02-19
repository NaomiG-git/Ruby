"""Vision and screen capture tools for the Ruby Agent."""

import os
import logging
import uuid
from datetime import datetime
from pathlib import Path
from src.agent.tools import FunctionTool

logger = logging.getLogger(__name__)

async def take_screenshot(save_dir: str | None = None) -> str:
    """Take a screenshot of the primary monitor and save it.
    
    Args:
        save_dir: Optional directory to save the image. Defaults to './data/screenshots'.
        
    Returns:
        Absolute path to the saved screenshot or error message.
    """
    try:
        import mss
        import os
        import uuid
        from datetime import datetime
        from PIL import Image

        # Setup directory
        if not save_dir:
            save_dir = os.path.join(os.getcwd(), "data", "screenshots")
        
        os.makedirs(save_dir, exist_ok=True)
        
        # Filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}_{str(uuid.uuid4())[:8]}.png"
        filepath = os.path.join(save_dir, filename)

        with mss.mss() as sct:
            # Take screenshot of first monitor
            monitor = sct.monitors[1]
            sct_img = sct.grab(monitor)
            
            # Convert to PIL Image and save
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            img.save(filepath)

        logger.info(f"Screenshot saved to {filepath}")
        return f"Screenshot successfully captured and saved to: {filepath}"
    except Exception as e:
        logger.error(f"Failed to take screenshot: {e}")
        return f"Error taking screenshot: {str(e)}"

VISION_TOOLS = [
    FunctionTool(
        func=take_screenshot,
        name="take_screenshot",
        description="Captures a screenshot of the user's primary screen and saves it as a PNG file. Use this when the user asks 'what's on my screen' or wants you to see something they are looking at."
    )
]
