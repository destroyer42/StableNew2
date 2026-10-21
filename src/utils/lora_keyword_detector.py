"""LoRA keyword detection from metadata files.

This module detects trigger words/keywords for LoRAs by scanning:
1. .civitai.info files (JSON with trained_words)
2. .txt files (plain text metadata)
3. README files (markdown documentation)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class LoRAMetadata:
    """Metadata extracted from LoRA files."""

    name: str
    path: Path | None = None
    keywords: list[str] = field(default_factory=list)
    source: Literal["civitai", "txt", "readme", "none"] = "none"
    description: str = ""
    errors: tuple[str, ...] = ()


def detect_lora_keywords(
    lora_name: str,
    webui_root: Path | str | None = None,
    lora_folders: list[Path] | None = None,
    *,
    lora_path: Path | None = None,
) -> LoRAMetadata:
    """Detect keywords for a LoRA by scanning metadata files.

    Args:
        lora_name: Name of the LoRA (without extension)
        webui_root: Root path to Stable Diffusion WebUI (will check models/Lora/)
        lora_folders: Additional folders to search for LoRA files

    Returns:
        LoRAMetadata with detected keywords
    """
    metadata = LoRAMetadata(name=lora_name)

    # Build search paths
    search_paths: list[Path] = []

    if webui_root:
        webui_path = Path(webui_root)
        search_paths.append(webui_path / "models" / "Lora")
        search_paths.append(webui_path / "models" / "LyCORIS")

    if lora_folders:
        search_paths.extend(lora_folders)

    # Search for LoRA file
    lora_file = lora_path or _find_lora_file(lora_name, search_paths)
    if not lora_file:
        return metadata

    metadata.path = lora_file

    errors: list[str] = []
    candidates = (
        (lora_file.with_name(lora_file.name + ".civitai.info"), "civitai"),
        (lora_file.with_suffix(".civitai.info"), "civitai"),
        (lora_file.with_suffix(".txt"), "txt"),
        (lora_file.parent / "README.md", "readme"),
        (lora_file.parent / "README.txt", "readme"),
    )
    for candidate, source in candidates:
        try:
            # No sidecar may escape the adapter's own directory via a symlink/junction.
            if not candidate.resolve().is_relative_to(lora_file.parent.resolve()):
                raise ValueError("sidecar outside local directory")
            with candidate.open("rb") as stream:
                raw = stream.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError("sidecar exceeds read limit")
            text = raw.decode("utf-8")
            keywords: list[str] = []
            description = text
            if source == "civitai":
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ValueError("sidecar is not an object")
                model = data.get("model")
                model = model if isinstance(model, dict) else {}
                words = data.get("trainedWords") or model.get("trainedWords") or []
                if isinstance(words, list):
                    keywords = [str(word).strip()[:256] for word in words[:100] if word]
                description = str(data.get("description") or model.get("description") or "")
            if not keywords:
                keywords = _extract_trigger_words_from_text(
                    _extract_lora_section(description, lora_name) or description
                    if source == "readme"
                    else description
                )
            if not metadata.keywords and keywords:
                metadata.keywords = keywords
                metadata.source = source  # type: ignore[assignment]
            # Keep all local descriptions for content-visibility classification, even without triggers.
            metadata.description += "\n" + description[:8192]
        except FileNotFoundError:
            continue
        except (OSError, ValueError, TypeError):
            errors.append("Local keyword metadata unavailable")
    metadata.errors = tuple(dict.fromkeys(errors))
    return metadata


def _find_lora_file(lora_name: str, search_paths: list[Path]) -> Path | None:
    """Find LoRA file in search paths."""
    extensions = [".safetensors", ".pt", ".ckpt"]

    for folder in search_paths:
        if not folder.exists():
            continue

        # Try exact match
        for ext in extensions:
            lora_file = folder / f"{lora_name}{ext}"
            if lora_file.exists():
                return lora_file

        # Try case-insensitive search
        try:
            for item in folder.iterdir():
                if item.is_file() and item.stem.lower() == lora_name.lower():
                    if item.suffix.lower() in extensions:
                        return item
        except Exception:
            pass

    return None


def _extract_keywords_from_civitai(civitai_info: Path) -> list[str]:
    """Extract trained_words from .civitai.info JSON."""
    try:
        with open(civitai_info, encoding="utf-8") as f:
            data = json.load(f)

        # Check for trained_words (common in CivitAI metadata)
        trained_words = data.get("trainedWords", [])
        if isinstance(trained_words, list) and trained_words:
            return [str(w).strip() for w in trained_words if w]

        # Alternative: check model.trainedWords
        model = data.get("model", {})
        if isinstance(model, dict):
            trained_words = model.get("trainedWords", [])
            if isinstance(trained_words, list) and trained_words:
                return [str(w).strip() for w in trained_words if w]

        # Alternative: check description for trigger words
        description = data.get("description", "") or model.get("description", "")
        if description:
            keywords = _extract_trigger_words_from_text(description)
            if keywords:
                return keywords

    except Exception:
        pass

    return []


def _extract_keywords_from_txt(txt_file: Path) -> tuple[list[str], str]:
    """Extract keywords from .txt metadata file."""
    try:
        with open(txt_file, encoding="utf-8") as f:
            content = f.read()

        # Look for common patterns
        keywords = _extract_trigger_words_from_text(content)

        # Extract description (first 200 chars)
        description = content[:200].strip()

        return keywords, description

    except Exception:
        pass

    return [], ""


def _extract_keywords_from_readme(readme_file: Path, lora_name: str) -> list[str]:
    """Extract keywords from README file."""
    try:
        with open(readme_file, encoding="utf-8") as f:
            content = f.read()

        # Look for section mentioning this LoRA
        lora_section = _extract_lora_section(content, lora_name)
        if lora_section:
            content = lora_section

        return _extract_trigger_words_from_text(content)

    except Exception:
        pass

    return []


def _extract_trigger_words_from_text(text: str) -> list[str]:
    """Extract trigger words from text using pattern matching."""
    keywords: list[str] = []

    # Pattern 1: "trigger word(s): word1, word2, word3"
    trigger_pattern = r"(?:trigger\s+words?|keywords?|activation\s+words?)\s*[:\-]\s*([^\n\.]+)"
    matches = re.findall(trigger_pattern, text, re.IGNORECASE)
    for match in matches:
        words = [w.strip() for w in re.split(r"[,;]", match) if w.strip()]
        keywords.extend(words)

    # Pattern 2: Words in backticks or quotes
    quoted_pattern = r"[`'\"]([a-zA-Z0-9_\-\s]{2,30})[`'\"]"
    quoted_words = re.findall(quoted_pattern, text)
    if quoted_words and len(keywords) < 3:
        # Only add if we don't have many keywords yet
        keywords.extend([w.strip() for w in quoted_words[:5]])

    # Pattern 3: "Use: word" or "Keyword: word"
    use_pattern = r"(?:use|keyword|token)\s*[:\-]\s*([a-zA-Z0-9_\-]+)"
    use_matches = re.findall(use_pattern, text, re.IGNORECASE)
    if use_matches:
        keywords.extend(use_matches)

    # Clean and deduplicate
    cleaned = []
    seen = set()
    for kw in keywords:
        kw = kw.strip()
        kw_lower = kw.lower()
        if kw and len(kw) > 1 and kw_lower not in seen:
            # Filter out common words
            if not _is_common_word(kw_lower):
                cleaned.append(kw)
                seen.add(kw_lower)

    return cleaned[:10]  # Limit to 10 keywords


def _extract_lora_section(content: str, lora_name: str) -> str:
    """Extract section of README relevant to specific LoRA."""
    # Try to find section with LoRA name
    pattern = rf"(?:^|\n)##?\s*.*{re.escape(lora_name)}.*?\n((?:(?!^##?\s).*\n)*)"
    match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1)

    return ""


def _is_common_word(word: str) -> bool:
    """Check if word is too common to be a useful trigger word."""
    common_words = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "this",
        "that",
        "these",
        "those",
        "here",
        "there",
        "where",
        "when",
        "how",
        "why",
        "what",
        "which",
        "lora",
        "model",
        "trained",
        "checkpoint",
        "safetensors",
        "civitai",
        "download",
        "link",
        "file",
        "folder",
        "directory",
    }
    return word.lower() in common_words
