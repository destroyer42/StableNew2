#!/usr/bin/env python3
"""
Simple debug script to check pack files
"""
from pathlib import Path


def simple_pack_debug():
    """Simple debug to check pack files"""
    packs_dir = Path("packs")

    print("Checking packs directory...")
    if not packs_dir.exists():
        print(f"ERROR: {packs_dir} does not exist!")
        return

    pack_files = list(packs_dir.glob("*.txt"))
    print(f"Found {len(pack_files)} .txt files:")

    for i, pack_file in enumerate(pack_files):
        print(f"{i+1}. {pack_file.name}")

        try:
            with open(pack_file, encoding="utf-8") as f:
                content = f.read()
                print(f"   Size: {len(content)} characters")

                # Count lines
                lines = content.splitlines()
                print(f"   Lines: {len(lines)}")

                # Check for blocks (separated by blank lines)
                blocks = content.split("\n\n")
                blocks = [block.strip() for block in blocks if block.strip()]
                print(f"   Blocks: {len(blocks)}")

        except Exception as e:
            print(f"   ERROR reading file: {e}")

    print("\nDebug complete!")


if __name__ == "__main__":
    simple_pack_debug()
