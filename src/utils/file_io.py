"""File I/O utilities with UTF-8 support"""

import base64
import logging
from io import BytesIO
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)


def save_image_from_base64(base64_str: str, output_path: Path) -> bool:
    """
    Save base64 encoded image to file.

    Args:
        base64_str: Base64 encoded image string
        output_path: Path to save the image

    Returns:
        True if saved successfully
    """
    try:
        # Remove data URL prefix if present
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]

        image_data = base64.b64decode(base64_str)
        image = Image.open(BytesIO(image_data))

        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        image.save(output_path)
        logger.info(f"Saved image: {output_path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return False


def load_image_to_base64(image_path: Path) -> str | None:
    """
    Load image and convert to base64.

    Args:
        image_path: Path to the image

    Returns:
        Base64 encoded image string
    """
    try:
        with Image.open(image_path) as img:
            buffered = BytesIO()
            img.save(buffered, format=img.format or "PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        logger.info(f"Loaded image to base64: {image_path.name}")
        return img_str
    except Exception as e:
        logger.error(f"Failed to load image: {e}")
        return None


def read_text_file(file_path: Path) -> str | None:
    """
    Read text file with UTF-8 encoding.

    Args:
        file_path: Path to the text file

    Returns:
        File contents as string
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()
        logger.info(f"Read text file: {file_path.name}")
        return content
    except Exception as e:
        logger.error(f"Failed to read text file: {e}")
        return None


def write_text_file(file_path: Path, content: str) -> bool:
    """
    Write text file with UTF-8 encoding.

    Args:
        file_path: Path to save the file
        content: Content to write

    Returns:
        True if saved successfully
    """
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Wrote text file: {file_path.name}")
        return True
    except Exception as e:
        logger.error(f"Failed to write text file: {e}")
        return False


def read_prompt_pack(pack_path: Path) -> list[dict[str, str]]:
    """
    Read prompt pack from .txt or .tsv file with UTF-8 safety.

    Supports:
    - Line-based .txt files with blank line separators
    - Tab-separated .tsv files
    - 'neg:' prefix for negative prompts
    - Comments starting with #

    Args:
        pack_path: Path to the prompt pack file

    Returns:
        List of prompt dictionaries with 'positive' and 'negative' keys
    """
    try:
        if not pack_path.exists():
            logger.error(f"Prompt pack not found: {pack_path}")
            return []

        # Read file with UTF-8 encoding
        with open(pack_path, encoding="utf-8") as f:
            content = f.read()

        prompts = []

        if pack_path.suffix.lower() == ".tsv":
            # Tab-separated format
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split("\t", 1)
                positive = parts[0].strip()
                negative = parts[1].strip() if len(parts) > 1 else ""

                prompts.append({"positive": positive, "negative": negative})
        else:
            # Block-based .txt format
            blocks = content.split("\n\n")

            for block in blocks:
                if not block.strip():
                    continue

                lines = [line.strip() for line in block.strip().splitlines()]
                lines = [line for line in lines if line and not line.startswith("#")]

                if not lines:
                    continue

                positive_parts = []
                negative_parts = []

                for line in lines:
                    if line.startswith("neg:"):
                        negative_parts.append(line[4:].strip())
                    else:
                        positive_parts.append(line)

                positive = " ".join(positive_parts)
                negative = " ".join(negative_parts)

                prompts.append({"positive": positive, "negative": negative})

        logger.info(f"Read {len(prompts)} prompts from {pack_path.name}")
        return prompts

    except Exception as e:
        logger.error(f"Failed to read prompt pack {pack_path.name}: {e}")
        return []


def get_prompt_packs(packs_dir: Path) -> list[Path]:
    """
    Get list of available prompt pack files.

    Args:
        packs_dir: Directory containing prompt packs

    Returns:
        List of prompt pack file paths
    """
    try:
        if not packs_dir.exists():
            packs_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created packs directory: {packs_dir}")
            return []

        pack_files = []
        for ext in ["*.txt", "*.tsv"]:
            pack_files.extend(packs_dir.glob(ext))

        pack_files.sort()
        logger.info(f"Found {len(pack_files)} prompt packs in {packs_dir}")
        return pack_files

    except Exception as e:
        logger.error(f"Failed to scan prompt packs directory: {e}")
        return []


def get_safe_filename(name: str) -> str:
    """
    Convert string to safe filename by removing/replacing invalid characters.

    Args:
        name: Input string

    Returns:
        Safe filename string
    """
    # Replace invalid characters
    invalid_chars = '<>:"/\\|?*'
    safe_name = name

    for char in invalid_chars:
        safe_name = safe_name.replace(char, "_")

    # Remove leading/trailing whitespace and dots
    safe_name = safe_name.strip(" .")

    # Limit length
    if len(safe_name) > 200:
        safe_name = safe_name[:200]

    return safe_name or "unnamed"
