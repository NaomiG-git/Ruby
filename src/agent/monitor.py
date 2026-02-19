"""Module for self-monitoring and streaming Ruby's screen context."""

import asyncio
import base64
import io
import logging
import time
import os
from typing import Callable, Optional
import mss
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

class RubyMonitor:
    """Monitors the agent's environment and streams a visual feed with HUD."""

    def __init__(self, event_callback: Optional[Callable] = None):
        self._event_callback = event_callback
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        # State for HUD
        self.current_goal = "Standing By"
        self.next_tool = "Ready"
        self.memu_context = "Waiting for input..."
        
        # Performance
        self.fps = 5.0
        self._sct = mss.mss()

    async def start(self):
        """Start the monitoring loop."""
        if self._running:
            return
        
        self._running = True
        logger.info("RubyMonitor started.")
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("RubyMonitor stopped.")

    def update_state(self, goal: str = None, tool: str = None, context: str = None):
        """Update the HUD state."""
        if goal: self.current_goal = goal
        if tool: self.next_tool = tool
        if context: self.memu_context = context

    async def _loop(self):
        """Main capture and stream loop."""
        logger.info("Monitor loop active.")
        while self._running:
            try:
                start_time = time.time()
                
                # Run sync screen grab in executor to avoid blocking main loop
                img_str = await asyncio.to_thread(self._capture_frame)
                
                if img_str and self._event_callback:
                    # Send a special 'canvas_update' type that the frontend understands
                    payload = {
                       "type": "monitor_stream",
                       "image": f"data:image/jpeg;base64,{img_str}",
                       "goal": self.current_goal,
                       "tool": self.next_tool,
                       "context": self.memu_context
                    }
                    # We send this as a canvas update event
                    self._event_callback("canvas_update", payload)
                
                # Frame Pacing
                elapsed = time.time() - start_time
                wait = max(0, (1.0 / self.fps) - elapsed)
                await asyncio.sleep(wait)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(1)

    def _capture_frame(self) -> str:
        """Capture screen, draw HUD, and return base64 string."""
        with mss.mss() as sct:
            try:
                # 1. Capture Screen
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                # Resize for performance (Height 720p)
                scale = 720 / float(img.height)
                new_width = int(img.width * scale)
                img = img.resize((new_width, 720), Image.Resampling.BILINEAR)
                
                # 2. Draw HUD
                self._draw_hud(img)
                
                # 3. Encode
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=60) # Low quality for stream speed
                return base64.b64encode(buffer.getvalue()).decode()
            except Exception as e:
                logger.error(f"Frame capture failed: {e}")
                return ""

    def _draw_hud(self, img: Image):
        """Draw the semi-transparent HUD overlay."""
        draw = ImageDraw.Draw(img, "RGBA")
        width, height = img.size
        
        # HUD Colors
        COLOR_GOAL = (34, 197, 94, 255)   # Green
        COLOR_TOOL = (59, 130, 246, 255)  # Blue
        COLOR_MEMU = (168, 85, 247, 255)  # Purple
        BG_COLOR = (20, 20, 30, 200)      # Dark semi-transparent
        
        items = [
            ("GOAL", self.current_goal, COLOR_GOAL),
            ("TOOL", self.next_tool, COLOR_TOOL),
            ("MEMU", self.memu_context, COLOR_MEMU)
        ]
        
        # Measurements
        padding = 15
        box_height = 50
        box_width = 400
        start_y = height - (len(items) * (box_height + 10)) - padding
        
        # Load Font
        try:
            # Try efficient system font path
            font_path = "C:\\Windows\\Fonts\\arialbd.ttf"
            font = ImageFont.truetype(font_path, 20)
            label_font = ImageFont.truetype(font_path, 12)
        except:
            font = ImageFont.load_default()
            label_font = ImageFont.load_default()

        current_y = start_y
        
        for label, text, color in items:
            # Draw Box
            draw.rectangle(
                [padding, current_y, padding + box_width, current_y + box_height],
                fill=BG_COLOR,
                outline=color,
                width=2
            )
            
            # Draw Label (Mini)
            draw.text((padding + 10, current_y + 4), label, font=label_font, fill=color)
            
            # Draw Content (Truncate)
            if len(text) > 35:
                text = text[:32] + "..."
            draw.text((padding + 10, current_y + 20), text, font=font, fill=(255, 255, 255, 255))
            
            current_y += box_height + 10

    async def capture_high_res(self) -> str:
        """Capture and save a high-res screenshot."""
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"monitor_autosave_{ts}.png"
        
        path = await asyncio.to_thread(self._save_high_res_sync, filename)
        return path

    def _save_high_res_sync(self, filename: str) -> str:
        """Sync high-res save."""
        try:
            monitor = self._sct.monitors[1]
            sct_img = self._sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            # Ensure directory
            save_dir = os.path.join(os.getcwd(), "data", "screenshots")
            os.makedirs(save_dir, exist_ok=True)
            
            path = os.path.join(save_dir, filename)
            img.save(path, "PNG")
            return path
        except Exception as e:
            logger.error(f"High-res save failed: {e}")
            return ""
