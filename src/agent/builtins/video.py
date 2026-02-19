"""Video editing tools for the Ruby Agent."""

import os
import logging
import numpy as np
from typing import List, Optional
from moviepy import VideoFileClip, concatenate_videoclips, AudioFileClip, TextClip, CompositeVideoClip
import yt_dlp
from src.agent.tools import FunctionTool

logger = logging.getLogger(__name__)

DEBUG_LOG = r"C:\Users\grind\Desktop\video_debug.txt"

def log_debug(msg: str):
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{msg}\n")

async def concatenate_videos(video_paths: List[str], output_path: str) -> str:
    """Combine multiple video files into one.
    
    Args:
        video_paths: List of absolute paths to video files.
        output_path: Absolute path for the resulting video.
        
    Returns:
        Confirmation message.
    """
    try:
        log_debug(f"Concatenating: {video_paths} -> {output_path}")
        clips = [VideoFileClip(path) for path in video_paths]
        final_clip = concatenate_videoclips(clips, method="compose")
        final_clip.write_videofile(output_path)
        
        # Close clips to free resources
        for clip in clips:
            clip.close()
            
        return f"Successfully combined {len(video_paths)} videos into {output_path}"
    except Exception as e:
        import traceback
        log_debug(f"ERROR: {e}\n{traceback.format_exc()}")
        logger.error(f"Failed to concatenate videos: {e}")
        return f"Error combining videos: {str(e)}"

async def trim_video(input_path: str, output_path: str, start_sec: float, end_sec: float) -> str:
    """Cut a specific segment from a video.
    
    Args:
        input_path: Absolute path to the source video.
        output_path: Absolute path for the clipped video.
        start_sec: Start time in seconds.
        end_sec: End time in seconds.
        
    Returns:
        Confirmation message.
    """
    try:
        log_debug(f"Trimming: {input_path} ({start_sec} - {end_sec}) -> {output_path}")
        with VideoFileClip(input_path) as video:
            trimmed = video.subclipped(start_sec, end_sec)
            trimmed.write_videofile(output_path)
        return f"Successfully trimmed video to {output_path} ({start_sec}s to {end_sec}s)"
    except Exception as e:
        import traceback
        log_debug(f"ERROR: {e}\n{traceback.format_exc()}")
        logger.error(f"Failed to trim video: {e}")
        return f"Error trimming video: {str(e)}"

async def add_audio_overlay(video_path: str, audio_path: str, output_path: str) -> str:
    """Add or replace audio in a video file.
    
    Args:
        video_path: Absolute path to the video.
        audio_path: Absolute path to the audio file.
        output_path: Absolute path for the new video.
        
    Returns:
        Confirmation message.
    """
    try:
        log_debug(f"Audio Overlay: {video_path} + {audio_path} -> {output_path}")
        with VideoFileClip(video_path) as video:
            with AudioFileClip(audio_path) as audio:
                # Set audio to video (this replaces existing if any)
                final_video = video.with_audio(audio)
                final_video.write_videofile(output_path)
        return f"Successfully added audio overlay to {output_path}"
    except Exception as e:
        import traceback
        log_debug(f"ERROR: {e}\n{traceback.format_exc()}")
        logger.error(f"Failed to add audio overlay: {e}")
        return f"Error adding audio: {str(e)}"

async def add_text_overlay(
    video_path: str, 
    text: str, 
    output_path: str, 
    font_size: int = 70, 
    color: str = 'white', 
    position: str = 'center',
    duration: Optional[float] = None
) -> str:
    """Overlay text onto a video file.
    
    Args:
        video_path: Absolute path to the source video.
        text: The text to display.
        output_path: Absolute path for the resulting video.
        font_size: Size of the font (default 70).
        color: Color of the text (default 'white').
        position: Position ('center', 'top', 'bottom', etc. or (x, y)).
        duration: How long to show text (default is full video).
        
    Returns:
        Confirmation message.
    """
    try:
        log_debug(f"Text Overlay: '{text}' on {video_path} -> {output_path}")
        with VideoFileClip(video_path) as video:
            # Create text clip
            txt_clip = TextClip(
                text=text, 
                font_size=font_size, 
                color=color,
                # method='label' is often safer for simple overlays
                method='caption',
                size=(video.w * 0.8, None) # Wrap at 80% width
            )
            
            # Set duration and position
            txt_clip = txt_clip.with_duration(duration or video.duration)
            txt_clip = txt_clip.with_position(position)
            
            # Overlay on video
            result = CompositeVideoClip([video, txt_clip])
            result.write_videofile(output_path)
            
            return f"Successfully added text '{text}' to {output_path}"
    except Exception as e:
        import traceback
        log_debug(f"ERROR: {e}\n{traceback.format_exc()}")
        logger.error(f"Failed to add text overlay: {e}")
        return f"Error adding text overlay: {str(e)}\n\nNote: This tool may require ImageMagick installed on the system."

async def remove_silence(
    video_path: str, 
    output_path: str, 
    threshold: float = 0.03, 
    min_silence_len: float = 0.5
) -> str:
    """Automatically find and remove silent segments from a video.
    
    Args:
        video_path: Absolute path to the source video.
        output_path: Absolute path for the resulting video.
        threshold: Volume threshold (0.0 to 1.0) below which is considered silence.
        min_silence_len: Minimum duration of silence in seconds to be cut.
        
    Returns:
        Confirmation message.
    """
    try:
        log_debug(f"Removing Silence: {video_path} -> {output_path} (Threshold: {threshold})")
        
        with VideoFileClip(video_path) as video:
            if video.audio is None:
                return "Error: Video has no audio track to detect silence."
            
            audio = video.audio
            # Sampling rate and chunk size (0.1s chunks)
            chunk_duration = 0.1
            fps = audio.fps
            n_chunks = int(video.duration / chunk_duration)
            
            active_intervals = []
            start_time = None
            
            # Analyze audio chunks
            for i in range(n_chunks):
                t = i * chunk_duration
                # Get a small slice of audio
                chunk = audio.subclipped(t, min(t + chunk_duration, video.duration))
                
                # Check volume (RMS)
                # MoviePy v2.x subclips return a clip. To get data, we use to_soundarray
                samples = chunk.to_soundarray(fps=fps)
                if samples.size > 0:
                    volume = np.sqrt(np.mean(samples**2))
                else:
                    volume = 0
                
                is_silent = volume < threshold
                
                if not is_silent and start_time is None:
                    start_time = t
                elif is_silent and start_time is not None:
                    # End of active segment
                    if t - start_time >= 0.1: # Min clip length
                        active_intervals.append((start_time, t))
                    start_time = None
            
            # Final segment
            if start_time is not None:
                active_intervals.append((start_time, video.duration))
            
            if not active_intervals:
                return "Error: The entire video appears to be silent below the threshold."
            
            # Build list of active clips
            clips = [video.subclipped(s, e) for s, e in active_intervals]
            final_clip = concatenate_videoclips(clips)
            final_clip.write_videofile(output_path)
            
            # Clean up subclips
            for c in clips:
                c.close()
                
            removed_count = n_chunks - len(active_intervals)
            return f"Successfully removed dead spaces from {video_path}. Created {len(active_intervals)} segments in {output_path}"
            
    except Exception as e:
        import traceback
        log_debug(f"ERROR: {e}\n{traceback.format_exc()}")
        logger.error(f"Failed to remove silence: {e}")
        return f"Error removing silence: {str(e)}"

async def remove_static_segments(
    video_path: str, 
    output_path: str, 
    threshold: float = 1.0, 
    min_duration: float = 0.5,
    sample_rate: float = 2.0
) -> str:
    """Find and remove segments of a video where the image is static (no movement).
    
    This is ideal for cutting out loading screens or "frozen" moments in silent demos.
    
    Args:
        video_path: Absolute path to the source video.
        output_path: Absolute path for the resulting video.
        threshold: Sensitivity for "staticness" (default 1.0). Lower is more sensitive.
        min_duration: Minimum duration of a static segment to be cut.
        sample_rate: How many frames per second to sample for analysis (default 2.0).
        
    Returns:
        Confirmation message.
    """
    try:
        log_debug(f"Removing Static Segments: {video_path} -> {output_path}")
        
        with VideoFileClip(video_path) as video:
            duration = video.duration
            # We'll sample frames at 'sample_rate' intervals
            times = np.arange(0, duration, 1.0 / sample_rate)
            
            active_intervals = []
            segment_start = 0
            
            prev_frame = None
            
            # Analyze motion by comparing consecutive sampled frames
            for t in times:
                frame = video.get_frame(t)
                # Convert to grayscale for faster comparison if needed, 
                # but simple mean absolute difference on RGB is fine too.
                
                if prev_frame is not None:
                    # Calculate Mean Absolute Difference (MAD)
                    diff = np.mean(np.abs(frame.astype(float) - prev_frame.astype(float)))
                    
                    is_static = diff < threshold
                    
                    if is_static:
                        # If we just hit a static point, close the current active segment
                        if t - segment_start >= 0.1: # Min segment length
                            # But only if the segment between segment_start and t wasn't empty
                            # Wait, logic is slightly flipped here. 
                            # We want to KEEP segments that have MOVEMENT.
                            pass
                
                prev_frame = frame

            # Revised Logic: Identify "Moving" vs "Static" segments
            moving_segments = []
            current_start = 0
            is_currently_static = False
            static_start_time = None
            
            prev_frame = video.get_frame(0)
            
            for t in times[1:]:
                frame = video.get_frame(t)
                diff = np.mean(np.abs(frame.astype(float) - prev_frame.astype(float)))
                is_static = diff < threshold
                
                if is_static:
                    if not is_currently_static:
                        is_currently_static = True
                        static_start_time = t
                else:
                    if is_currently_static:
                        # End static segment
                        static_duration = t - static_start_time
                        if static_duration >= min_duration:
                            # This was a significant static segment. 
                            # Save the active segment from current_start up to where static started.
                            if static_start_time - current_start > 0.1:
                                moving_segments.append((current_start, static_start_time))
                            current_start = t
                        is_currently_static = False
                
                prev_frame = frame
                
            # Final segment
            if not is_currently_static:
                if duration - current_start > 0.1:
                    moving_segments.append((current_start, duration))
            elif static_start_time - current_start > 0.1:
                # If the video ends with a static segment, keep everything before it
                moving_segments.append((current_start, static_start_time))

            if not moving_segments:
                return "Error: The entire video appears to be static. Try lowering the threshold."

            # Create clips
            clips = [video.subclipped(s, e) for s, e in moving_segments]
            final_clip = concatenate_videoclips(clips)
            
            # If the original video had audio (even if silent), keep it for the new segments
            # concat handles subclips which keep their audio.
            
            final_clip.write_videofile(output_path)
            
            for c in clips:
                c.close()
                
            total_cut = duration - final_clip.duration
            return f"Successfully removed {total_cut:.1f}s of static segments. Saved to {output_path}"
            
    except Exception as e:
        import traceback
        log_debug(f"ERROR: {e}\n{traceback.format_exc()}")
        logger.error(f"Failed to remove static segments: {e}")
        return f"Error removing static segments: {str(e)}"

async def watch_video(url: str) -> str:
    """Download a video from a URL (YouTube, Vimeo, etc.) to watch and analyze it.
    
    CRITICAL: Use this tool if the user provides a video URL and wants you to "watch", "see", "summarize", or "analyze" the visual content.
    This is the ONLY tool that allows you to see the actual video frames. Do NOT use `browse_url` or `search_web` for videos if visual analysis is required.
    
    Args:
        url: The URL of the video to watch.
    """
    try:
        import json
        save_dir = os.path.join(os.getcwd(), "data", "videos")
        os.makedirs(save_dir, exist_ok=True)
        
        log_debug(f"Watching Video: {url}")
        
        ydl_opts = {
            'format': 'best[height<=480]', # Limit to 480p for efficiency
            'outtmpl': os.path.join(save_dir, '%(title)s_%(id)s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_path = ydl.prepare_filename(info)
            
            # Ensure path is absolute
            video_path = os.path.abspath(video_path)
            
            log_debug(f"Video downloaded to: {video_path}")
            
            # Construct special response for the controller to handle binary attachment
            return json.dumps({
                "__llm_content__": f"Successfully downloaded and processed video: '{info.get('title')}' for visual analysis. I am now looking at the actual frames.",
                "__media__": {
                    "path": video_path,
                    "type": "video"
                },
                "__canvas__": {
                    "type": "ocr",
                    "text": f"Watching Video: {info.get('title')}\nSource: {url}\nStatus: Processing frames..."
                }
            })
            
    except Exception as e:
        import traceback
        log_debug(f"ERROR downloading video: {e}\n{traceback.format_exc()}")
        return f"Error downloading video for analysis: {str(e)}"

VIDEO_TOOLS = [
    FunctionTool(
        func=concatenate_videos,
        name="concatenate_videos",
        description="Combines multiple video files into a single video."
    ),
    FunctionTool(
        func=trim_video,
        name="trim_video",
        description="Cuts a segment from a video file between start and end seconds."
    ),
    FunctionTool(
        func=add_audio_overlay,
        name="add_audio_overlay",
        description="Adds or replaces the audio track of a video with an external audio file."
    ),
    FunctionTool(
        func=add_text_overlay,
        name="add_text_overlay",
        description="Overlays text onto a video file at a specified position."
    ),
    FunctionTool(
        func=remove_silence,
        name="remove_silence",
        description="Automatically finds and removes silent 'dead space' segments from a video."
    ),
    FunctionTool(
        func=remove_static_segments,
        name="remove_static_segments",
        description="Automatically finds and removes visually static segments (loading screens, etc.) where nothing is changing on screen."
    ),
    FunctionTool(
        func=watch_video,
        name="watch_video",
        description="Analyzes the visual frames of a video URL (YouTube, Vimeo, etc.). CRITICAL: You MUST use this tool to see what is happening in a video link."
    )
]
