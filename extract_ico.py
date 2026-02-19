from PIL import Image
import os

import sys

def extract_ico(ico_path, out_prefix):
    try:
        img = Image.open(ico_path)
        img.save(f"{out_prefix}.png", format="PNG")
        print(f"Saved {ico_path} to {out_prefix}.png")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python extract_ico.py <input.ico> <output_prefix>")
    else:
        extract_ico(sys.argv[1], sys.argv[2])
