"""Built-in filesystem tools."""

import os
import logging
from typing import List
from src.agent.tools import FunctionTool

logger = logging.getLogger(__name__)


def _resolve_path(path: str) -> str:
    """Resolve homedir, environment variables, and OneDrive redirects."""
    # --- DEBUG LOGGING ---
    debug_log = os.path.join(os.path.expanduser("~"), "ruby_fs_debug.log")
    with open(debug_log, "a") as f:
        import datetime
        f.write(f"[{datetime.datetime.now()}] Resolving: {path}\n")
    # ---------------------

    expanded = os.path.expanduser(path)
    
    # Handle common folder names - prioritize user home over CWD (Case-insensitive)
    common_folders = ["Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music"]
    
    # Normalize path separators and lower for comparison
    normalized_path = expanded.replace('\\', '/').lower()
    
    for folder in common_folders:
        folder_lower = folder.lower()
        # Match if path is exactly the folder name or starts with "folder/"
        if normalized_path == folder_lower or normalized_path.startswith(folder_lower + "/"):
            home = os.path.expanduser("~")
            system_folder = os.path.join(home, folder)
            
            if os.path.exists(system_folder):
                # Reconstruct path using the correct system folder case
                if normalized_path == folder_lower:
                    expanded = system_folder
                else:
                    relative_part = expanded[len(folder):].lstrip('\\/')
                    expanded = os.path.join(system_folder, relative_part)
                break
            
    with open(debug_log, "a") as f:
        f.write(f"  -> Expanded: {expanded}\n")
    
    # Check for OneDrive redirects on Windows
    if os.name == 'nt':
        home = os.path.expanduser("~")
        onedrive_root = os.path.join(home, "OneDrive")
        
        if os.path.exists(onedrive_root):
            # Check for Desktop, Documents, or Downloads redirection
            for folder in ["Desktop", "Documents", "Downloads"]:
                standard_path = os.path.join(home, folder)
                onedrive_path = os.path.join(onedrive_root, folder)
                
                # If the path starts with the standard path but standard doesn't exist/is empty,
                # or if the OneDrive path is the one that actually exists, redirect.
                abs_expanded = os.path.abspath(expanded)
                if abs_expanded.startswith(os.path.abspath(standard_path)):
                    if not os.path.exists(standard_path) and os.path.exists(onedrive_path):
                        resolved = abs_expanded.replace(os.path.abspath(standard_path), os.path.abspath(onedrive_path))
                        with open(debug_log, "a") as f:
                            f.write(f"  -> OneDrive Redirect: {resolved}\n")
                        return resolved
    
    final_path = os.path.abspath(expanded)
    with open(debug_log, "a") as f:
        f.write(f"  -> Final: {final_path}\n")
    return final_path

def list_directory_contents(path: str = ".") -> str:
    """List files and folders in a directory with details.
    
    Args:
        path: Path to the directory (default: current directory)
    """
    try:
        real_path = _resolve_path(path)
        items = os.listdir(real_path)
        results = []
        for item in items:
            full_path = os.path.join(real_path, item)
            kind = "DIR" if os.path.isdir(full_path) else "FILE"
            try:
                size = os.path.getsize(full_path) if kind == "FILE" else "-"
            except:
                size = "unknown"
            results.append(f"[{kind}] {item} ({size} bytes)")
        
        return f"Contents of {real_path}:\n" + "\n".join(results)
    except Exception as e:
        return f"Error listing contents of {path}: {e}"


def create_directory(path: str) -> str:
    """Create a new directory (and any necessary parent directories).
    
    Args:
        path: Path to the directory to create
    """
    try:
        real_path = _resolve_path(path)
        os.makedirs(real_path, exist_ok=True)
        return f"Successfully created directory: {real_path}"
    except Exception as e:
        return f"Error creating directory {path}: {e}"


def search_files_by_name(directory: str, pattern: str) -> str:
    """Search for files matching a pattern in a directory (recursive).
    
    Args:
        directory: The root directory to search in.
        pattern: The filename pattern to look for (case-insensitive).
    """
    results = []
    try:
        real_path = _resolve_path(directory)
        for root, _, files in os.walk(real_path):
            for file in files:
                if pattern.lower() in file.lower():
                    results.append(os.path.join(root, file))
        
        if not results:
            return f"No files found matching '{pattern}' in {real_path}"
        
        return f"Found {len(results)} files matching '{pattern}':\n" + "\n".join(results[:20]) # Limit to 20
    except Exception as e:
        return f"Error searching files: {e}"


def read_file(path: str) -> str:
    """Read the contents of a file.
    
    Args:
        path: Path to the file to read
    """
    try:
        real_path = _resolve_path(path)
        with open(real_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file.
    
    Args:
        path: Path to the file to write
        content: Content to write to the file
    """
    try:
        real_path = _resolve_path(path)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {real_path}"
    except Exception as e:
        return f"Error writing file: {e}"


def delete_item(path: str, confirmed: bool = False) -> str:
    """Delete a file or an entire directory (recursive).
    
    Args:
        path: Path to the file or folder to delete
        confirmed: Must be True to proceed with deletion.
    """
    import shutil
    try:
        real_path = _resolve_path(path)
        if not os.path.exists(real_path):
            return f"Error: {real_path} does not exist."
            
        if not confirmed:
            return f"SAFEGUARD: Deletion of '{real_path}' was requested but NOT confirmed. I have blocked the action. Please ask the user for confirmation first."

        if os.path.isdir(real_path):
            shutil.rmtree(real_path)
            return f"Successfully deleted directory: {real_path}"
        else:
            os.remove(real_path)
            return f"Successfully deleted file: {real_path}"
    except Exception as e:
        return f"Error deleting {path}: {e}"


def launch_application(path: str) -> str:
    """Launch an application or open a file with the default system handler.
    
    Args:
        path: Path to the application or file to launch/open.
    """
    try:
        real_path = _resolve_path(path)
        if not os.path.exists(real_path):
            return f"Error: {real_path} does not exist."
            
        if os.name == 'nt':
            os.startfile(real_path)
        else:
            # macOS/Linux fallback (though this agent seems Windows-specific)
            import subprocess
            opener = 'open' if os.sys.platform == 'darwin' else 'xdg-open'
            subprocess.call([opener, real_path])
            
        return f"Successfully launched: {real_path}"
    except Exception as e:
        return f"Error launching {path}: {e}"


FILESYSTEM_TOOLS = [
    FunctionTool(list_directory_contents),
    FunctionTool(create_directory),
    FunctionTool(search_files_by_name),
    FunctionTool(read_file),
    FunctionTool(write_file),
    FunctionTool(delete_item),
    FunctionTool(launch_application),
]
