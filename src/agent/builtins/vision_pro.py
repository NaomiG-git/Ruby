"""Advanced vision and data extraction tools for the Ruby Agent."""

import os
import logging
import json
import mimetypes
import base64
from pathlib import Path
from src.agent.tools import FunctionTool

logger = logging.getLogger(__name__)

async def extract_colors(image_path: str, num_colors: int = 5) -> str:
    """Extract dominant colors from an image, including Hex, RGB, and pigment suggestions.
    
    Args:
        image_path: Path to the image file.
        num_colors: Number of dominant colors to extract (default 5).
    """
    try:
        import colorgram
        from PIL import Image

        if not os.path.exists(image_path):
            return f"Error: Image not found at {image_path}"

        colors = colorgram.extract(image_path, num_colors)
        
        # Simple pigment database (mockup - can be expanded)
        PIGMENT_MAP = {
            "#ff0000": "Cadmium Red",
            "#00ff00": "Cobalt Green",
            "#0000ff": "Ultramarine Blue",
            "#ffffff": "Titanium White",
            "#000000": "Ivory Black",
            "#ffff00": "Cadmium Yellow",
            "#ffa500": "Yellow Ochre",
            "#8b4513": "Burnt Sienna",
            "#a52a2a": "Venetian Red"
        }

        def closest_pigment(hex_code):
            # Very simple match for now
            return PIGMENT_MAP.get(hex_code.lower(), "Unknown Pigment")

        results = []
        for color in colors:
            rgb = color.rgb
            hex_code = '#%02x%02x%02x' % (rgb.r, rgb.g, rgb.b)
            results.append({
                "hex": hex_code,
                "rgb": f"rgb({rgb.r}, {rgb.g}, {rgb.b})",
                "pigment": closest_pigment(hex_code),
                "proportion": round(color.proportion, 3)
            })

        payload = {
            "type": "color_palette",
            "colors": results
        }

        # Return as JSON string with a special flag for the controller
        return json.dumps({"__canvas__": payload})
    except Exception as e:
        logger.error(f"Color extraction failed: {e}")
        return f"Error extracting colors: {str(e)}"

async def ocr_image(image_path: str) -> str:
    """Extract text from an image using OCR.
    
    Args:
        image_path: Path to the image file.
    """
    try:
        import pytesseract
        from PIL import Image
        import shutil

        # Check if tesseract is installed
        tesseract_cmd = shutil.which("tesseract")
        if not tesseract_cmd:
            # Try common Windows path
            common_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            if os.path.exists(common_path):
                pytesseract.pytesseract.tesseract_cmd = common_path
            else:
                return "Error: Tesseract-OCR is not installed on this system. Please install it from https://github.com/UB-Mannheim/tesseract/wiki"

        if not os.path.exists(image_path):
            return f"Error: Image not found at {image_path}"

        text = pytesseract.image_to_string(Image.open(image_path))
        
        payload = {
            "type": "ocr",
            "text": text.strip()
        }

        return json.dumps({"__canvas__": payload})
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return f"Error reading text: {str(e)}"

VISION_PRO_TOOLS = [
    FunctionTool(
        func=extract_colors,
        name="extract_colors",
        description="Analyzes an image and returns a palette of dominant colors with Hex, RGB, and pigment names. Ideal for artists and designers."
    ),
    FunctionTool(
        func=ocr_image,
        name="ocr_image",
        description="Uses Optical Character Recognition (OCR) to read text from an image or screenshot."
    )
]
