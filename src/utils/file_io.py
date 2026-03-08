"""File I/O utilities with UTF-8 support"""

import base64
import hashlib
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from PIL import Image

logger = logging.getLogger(__name__)


def save_image_from_base64(
    base64_str: str,
    output_path: Path,
    metadata_builder: Callable[[Image.Image], dict[str, str] | None] | None = None,
) -> Path | None:
    """
    Save base64 encoded image to file.

    Args:
        base64_str: Base64 encoded image string
        output_path: Path to save the image
        metadata_builder: Optional function to build metadata for embedding

    Returns:
        Path of saved image if successful, None otherwise
    """
    try:
        # Ensure we have a Path object
        if isinstance(output_path, str):
            output_path = Path(output_path)
        
        # Resolve to absolute path for clearer error messages
        output_path = output_path.resolve()
        
        # Remove data URL prefix if present
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]

        image_data = base64.b64decode(base64_str)
        image = Image.open(BytesIO(image_data))

        # Ensure parent directory exists
        parent_dir = output_path.parent
        logger.debug(f"Ensuring parent directory exists: {parent_dir}")
        parent_dir.mkdir(parents=True, exist_ok=True)
        
        # Verify directory was created
        if not parent_dir.exists():
            logger.error(f"Failed to create directory: {parent_dir}")
            return None

        image.save(output_path)
        if metadata_builder is not None:
            try:
                from src.utils.image_metadata import write_image_metadata
                metadata_kv = metadata_builder(image)
                if metadata_kv:
                    write_image_metadata(output_path, metadata_kv)
            except Exception as exc:
                logger.debug("Failed to embed image metadata: %s", exc)
        logger.info(f"Saved image: {output_path.name}")
        return output_path
    except Exception as e:
        logger.error(f"Failed to save image to {output_path}: {e}")
        return None


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
            # Log image dimensions and file size for diagnostics
            img_width, img_height = img.size
            file_size_mb = image_path.stat().st_size / (1024 * 1024)
            
            buffered = BytesIO()
            img.save(buffered, format=img.format or "PNG")
            base64_bytes = buffered.getvalue()
            base64_size_mb = len(base64_bytes) / (1024 * 1024)
            img_str = base64.b64encode(base64_bytes).decode("utf-8")
            
            # Warn if base64 payload is large (may cause timeouts)
            if base64_size_mb > 10.0:
                logger.warning(
                    f"Large image loaded: {image_path.name} {img_width}×{img_height} "
                    f"file={file_size_mb:.1f}MB base64={base64_size_mb:.1f}MB"
                )
            else:
                logger.info(
                    f"Loaded image: {image_path.name} {img_width}×{img_height} "
                    f"base64={base64_size_mb:.1f}MB"
                )
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

        logger.debug(f"Read {len(prompts)} prompts from {pack_path.name}")
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
        logger.debug(f"Found {len(pack_files)} prompt packs in {packs_dir}")
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


def build_safe_image_name(
    base_prefix: str,
    matrix_values: dict[str, Any] | None = None,
    seed: int | None = None,
    batch_index: int | None = None,
    pack_name: str | None = None,
    max_length: int = 120,
    use_one_based_indexing: bool = True,
) -> str:
    """
    Build a safe, filesystem-compatible image name with human-readable identifiers.
    
    Prevents Windows MAX_PATH issues by:
    - Limiting filename length based on max_length parameter
    - Using pack name or hash for uniqueness when truncating
    - Sanitizing all characters for filesystem compatibility
    
    Args:
        base_prefix: Prefix with prompt/variant indices (e.g., "txt2img_p01_v01")
        matrix_values: Optional matrix slot values for hash uniqueness
        seed: Optional seed value for hash uniqueness
        batch_index: Optional batch index (0-based internally, converted to 1-based in filename)
        pack_name: Optional prompt pack name (first 10 chars used, sanitized)
        max_length: Maximum filename length (default 120, safe for Windows)
        use_one_based_indexing: Convert batch_index to 1-based in filename (default True)
    
    Returns:
        Safe filename string (without extension)
    
    Example (new format):
        build_safe_image_name(
            "txt2img_p01_v01",
            pack_name="Fantasy_Heroes_v2",
            batch_index=0
        )
        → "txt2img_p01_v01_FantasyHer_batch1"
    """
    # Start with sanitized base prefix
    safe_prefix = get_safe_filename(base_prefix)
    
    # Build identifier: prefer pack name over hash
    identifier = ""
    if pack_name and pack_name.strip():
        # Sanitize and truncate pack name to 10 chars max
        safe_pack = get_safe_filename(pack_name.strip())[:10]
        if safe_pack:
            identifier = safe_pack
    
    # Fallback to hash if no pack name
    if not identifier:
        hash_input_parts = [safe_prefix]
        if matrix_values:
            # Stable ordering for consistent hashing
            matrix_str = "_".join(f"{k}={v}" for k, v in sorted(matrix_values.items()))
            hash_input_parts.append(matrix_str)
        if seed is not None:
            hash_input_parts.append(f"seed={seed}")
        hash_input = "|".join(hash_input_parts)
        identifier = hashlib.md5(hash_input.encode("utf-8")).hexdigest()[:8]
    
    # Add timestamp suffix for uniqueness (MMDDhhmmss format, 10 chars)
    from datetime import datetime
    timestamp = datetime.now().strftime("%m%d%H%M%S")
    timestamp_suffix = f"_{timestamp}"
    
    # Build batch suffix with 1-based indexing
    batch_suffix = ""
    if batch_index is not None:
        display_index = batch_index + 1 if use_one_based_indexing else batch_index
        batch_suffix = f"_batch{display_index}"
    
    # Calculate space: prefix + "_" + identifier + timestamp_suffix + batch_suffix + ".png"
    reserved = len("_") + len(identifier) + len(timestamp_suffix) + len(batch_suffix) + len(".png")
    max_prefix_len = max_length - reserved
    
    if len(safe_prefix) > max_prefix_len:
        safe_prefix = safe_prefix[:max_prefix_len]
    
    # Build final name
    final_name = f"{safe_prefix}_{identifier}{timestamp_suffix}{batch_suffix}"
    
    return final_name


def get_unique_output_path(
    base_path: Path,
    max_attempts: int = 100
) -> Path:
    """
    Ensure output path is unique by appending _copy1, _copy2, etc. if needed.
    
    This failsafe prevents silent overwrites if filename generation somehow
    produces duplicates. Normal operation should never trigger this.
    
    Args:
        base_path: Desired output path
        max_attempts: Maximum collision resolution attempts
    
    Returns:
        Unique path that doesn't exist
    
    Raises:
        ValueError: If max_attempts exceeded (indicates serious bug)
    
    Example:
        path = Path("output/image.png")  # exists
        unique = get_unique_output_path(path)
        # → Path("output/image_copy1.png")
    """
    if not base_path.exists():
        return base_path
    
    logger = logging.getLogger(__name__)
    logger.warning(
        "[COLLISION] Output file already exists: %s (this indicates a filename generation bug)",
        base_path
    )
    
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    
    for i in range(1, max_attempts + 1):
        candidate = parent / f"{stem}_copy{i}{suffix}"
        if not candidate.exists():
            logger.warning("[COLLISION] Using unique filename: %s", candidate.name)
            return candidate
    
    raise ValueError(
        f"Could not find unique filename after {max_attempts} attempts for {base_path}. "
        "This indicates a serious filename generation bug."
    )


def build_safe_image_stem(
    base_name: str,
    *,
    output_dir: Path,
    extension: str = ".png",
    unique_token: str | None = None,
    max_path_len: int | None = None,
    hash_len: int = 8,
) -> str:
    """
    Build a deterministic, path-safe filename stem for image outputs.

    The stem is sanitized, length-bounded for the output_dir, and can embed
    a short unique token. If it still exceeds limits, it is truncated with
    a deterministic hash suffix while preserving batch/img suffixes.
    """
    if isinstance(output_dir, str):
        output_dir = Path(output_dir)

    if not extension.startswith("."):
        extension = f".{extension}"

    safe_base = get_safe_filename(base_name)

    tail = ""
    tail_match = re.search(r"(_batch\\d+|_img\\d+)$", safe_base)
    if tail_match:
        tail = tail_match.group(1)
        root = safe_base[: -len(tail)]
    else:
        root = safe_base

    token_suffix = ""
    if unique_token:
        token_safe = get_safe_filename(str(unique_token))
        token_short = token_safe[:8]
        if token_short:
            token_suffix = f"__{token_short}"

    candidate = f"{root}{token_suffix}{tail}"

    if max_path_len is None:
        max_path_len = 240 if os.name == "nt" else 255

    try:
        output_dir = output_dir.resolve()
    except Exception:
        output_dir = Path(str(output_dir))

    base_len = len(str(output_dir)) + 1 + len(extension)
    max_stem_len = max(1, max_path_len - base_len)

    if len(candidate) <= max_stem_len:
        return candidate

    hash_source = f"{root}|{tail}|{unique_token or ''}"
    hash_value = hashlib.sha1(hash_source.encode("utf-8")).hexdigest()[:hash_len]
    hash_suffix = f"__{hash_value}{tail}"
    max_root_len = max_stem_len - len(hash_suffix)

    if max_root_len < 1:
        hash_suffix = f"__{hash_value}"
        max_root_len = max_stem_len - len(hash_suffix)
        if max_root_len < 1:
            return hash_suffix.strip("_")[:max_stem_len]

    return f"{root[:max_root_len]}{hash_suffix}"
