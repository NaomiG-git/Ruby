from PIL import Image
import os

def convert_to_ico(source_path, dest_path):
    try:
        img = Image.open(source_path)
        # Convert to RGBA if not already
        img = img.convert("RGBA")
        
        # Save as ICO with multiple sizes for best quality
        icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        img.save(dest_path, format='ICO', sizes=icon_sizes)
        print(f"Successfully converted {source_path} to {dest_path}")
        return True
    except Exception as e:
        print(f"Error converting to ICO: {e}")
        return False

# Path to the generated image (User needs to move it or we find it)
# We'll assume I can find it in the artifacts folder or I'll move it.
# For now, let's assume I'll place it at 'ruby_gem_icon.png' in the root.

if __name__ == "__main__":
    # Check if we have the file
    if os.path.exists("ruby_gem_icon.png"):
        convert_to_ico("ruby_gem_icon.png", "ruby.ico")
    else:
        print("ruby_gem_icon.png not found")
