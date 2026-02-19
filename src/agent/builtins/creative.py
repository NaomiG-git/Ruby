"""Creative tools for Ruby Agent (Apps, Websites, Pinterest)."""

import os
import json
import logging
from PIL import Image, ImageDraw, ImageFont
from src.agent.tools import FunctionTool
from src.agent.builtins.canvas import render_to_canvas

logger = logging.getLogger(__name__)

async def create_web_project(project_name: str, html: str, css: str = "", js: str = "") -> str:
    """Creates a complete web project folder on the Desktop with index.html, style.css, and app.js.
    
    Args:
        project_name: Descriptive name for the project folder.
        html: Full HTML content for index.html.
        css: CSS content for style.css.
        js: Javascript content for app.js.
    """
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    project_dir = os.path.join(desktop, project_name.replace(" ", "_"))
    
    try:
        os.makedirs(project_dir, exist_ok=True)
        
        # Write files
        with open(os.path.join(project_dir, "index.html"), "w", encoding="utf-8") as f:
            # Ensure CSS and JS are linked if not already
            if "style.css" not in html:
                html = html.replace("</head>", '    <link rel="stylesheet" href="style.css">\n</head>')
            if "app.js" not in html:
                html = html.replace("</body>", '    <script src="app.js"></script>\n</body>')
            f.write(html)
            
        with open(os.path.join(project_dir, "style.css"), "w", encoding="utf-8") as f:
            f.write(css)
            
        with open(os.path.join(project_dir, "app.js"), "w", encoding="utf-8") as f:
            f.write(js)
            
        # Also render a live preview to the Canvas
        preview_data = {
            "type": "web_preview",
            "title": project_name,
            "html": html.replace('href="style.css"', '').replace('src="app.js"', '') + f"<style>{css}</style><script>{js}</script>"
        }
        await render_to_canvas(preview_data)
        
        return f"Web project '{project_name}' created successfully on your Desktop at {project_dir}. I've also showing you a live preview in the Canvas!"
    except Exception as e:
        logger.error(f"Failed to create web project: {e}")
        return f"Error creating web project: {str(e)}"

async def compose_pinterest_pin(base_image_path: str, title: str, subtitle: str = "", logo_text: str = "Ruby Design") -> str:
    """Designs a professional Pinterest Pin (2:3 ratio) with text overlays.
    
    Args:
        base_image_path: Path to the background image.
        title: Main catchy title for the pin.
        subtitle: Optional secondary text or call to action.
        logo_text: Branding text for the bottom of the pin.
    """
    try:
        img = Image.open(base_image_path)
        
        # Target 2:3 Pinterest Ratio (e.g. 1000x1500)
        target_w = 1000
        target_h = 1500
        
        # Resize/Crop to ratio
        img = img.convert("RGBA")
        img_w, img_h = img.size
        
        # Calculate crop
        aspect = target_w / target_h
        if img_w / img_h > aspect:
            # Too wide
            new_w = int(img_h * aspect)
            left = (img_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, img_h))
        else:
            # Too tall
            new_h = int(img_w / aspect)
            top = (img_h - new_h) // 2
            img = img.crop((0, top, img_w, top + new_h))
            
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        # Overlay Layer
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Lower text box (semi-transparent dark gradient/box)
        draw.rectangle([0, target_h - 400, target_w, target_h], fill=(0, 0, 0, 180))
        
        # Load fonts (fallback to default if needed)
        try:
            # Common Windows font paths
            font_path = "C:\\Windows\\Fonts\\arialbd.ttf"
            title_font = ImageFont.truetype(font_path, 80)
            sub_font = ImageFont.truetype(font_path, 40)
            logo_font = ImageFont.truetype(font_path, 30)
        except:
            title_font = ImageFont.load_default()
            sub_font = ImageFont.load_default()
            logo_font = ImageFont.load_default()
            
        # Draw Text
        draw.text((50, target_h - 350), title.upper(), font=title_font, fill=(255, 255, 255, 255))
        draw.text((50, target_h - 220), subtitle, font=sub_font, fill=(255, 255, 255, 200))
        draw.text((target_w - 250, target_h - 80), logo_text, font=logo_font, fill=(255, 77, 77, 255)) # Ruby Red logo
        
        # Composite
        out = Image.alpha_composite(img, overlay)
        out = out.convert("RGB")
        
        # Save near original
        base, _ = os.path.splitext(base_image_path)
        out_path = f"{base}_PIN.jpg"
        out.save(out_path, "JPEG", quality=95)
        
        # Show in Canvas
        # Use file:// URL for local images in Electron
        preview_url = f"file:///{out_path.replace(os.sep, '/')}"
        preview_data = {
            "type": "pin_preview",
            "title": title,
            "url": preview_url
        }
        await render_to_canvas(preview_data)
        
        return f"Pinterest Pin created! I've styled your image with the title '{title}' and saved it to {out_path}."
        
    except Exception as e:
        logger.error(f"Failed to compose pinterest pin: {e}")
        return f"Error creating pin: {str(e)}"

# Export tools
CREATIVE_TOOLS = [
    FunctionTool(create_web_project),
    FunctionTool(compose_pinterest_pin),
]
