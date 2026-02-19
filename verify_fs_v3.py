import os

def _resolve_path(path: str) -> str:
    expanded = os.path.expanduser(path)
    common_folders = ["Downloads", "Documents", "Desktop", "Pictures", "Videos", "Music"]
    if path.lower() in [f.lower() for f in common_folders]:
        folder_name = next(f for f in common_folders if f.lower() == path.lower())
        home = os.path.expanduser("~")
        potential_path = os.path.join(home, folder_name)
        if os.path.exists(potential_path):
            expanded = potential_path
            
    if os.name == 'nt':
        home = os.path.expanduser("~")
        onedrive_root = os.path.join(home, "OneDrive")
        if os.path.exists(onedrive_root):
            for folder in ["Desktop", "Documents", "Downloads"]:
                standard_path = os.path.join(home, folder)
                onedrive_path = os.path.join(onedrive_root, folder)
                abs_expanded = os.path.abspath(expanded)
                if abs_expanded.startswith(os.path.abspath(standard_path)):
                    if not os.path.exists(standard_path) and os.path.exists(onedrive_path):
                        return abs_expanded.replace(os.path.abspath(standard_path), os.path.abspath(onedrive_path))
    
    return os.path.abspath(expanded)

test_paths = ["downloads", "DESKTOP", "Documents/somefile.txt"]
for p in test_paths:
    print(f"Path: {p} -> Resolved: {_resolve_path(p)}")
