"""Utilities for parsing prompt pack TXT files into structured components.

This module provides functions to parse prompt pack TXT format into separate
components (embeddings, LoRAs, text, negatives) for structured editing in the GUI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Regex patterns from existing parser
EMBEDDING_TAG_RE = re.compile(r"<embedding:([^>]+)>")
LORA_TAG_RE = re.compile(r"<lora:([^:>]+):([^>]+)>")


@dataclass
class ParsedPromptComponents:
    """Structured components from a parsed prompt pack TXT."""
    
    positive_embeddings: list[str]
    positive_text: str
    loras: list[tuple[str, float]]
    negative_embeddings: list[str]
    negative_text: str


def parse_prompt_txt_to_components(text: str) -> ParsedPromptComponents:
    """Parse a prompt pack TXT format into structured components.
    
    Expected TXT format:
        <embedding:positive_embed>
        (masterpiece, best quality) [[job]] in [[environment]]
        <lora:add-detail-xl:0.65>
        neg: <embedding:negative_hands>
        neg: bad quality, blurry
    
    Args:
        text: Raw prompt text in TXT format
        
    Returns:
        ParsedPromptComponents with separated embeddings, text, LoRAs, and negatives
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    positive_embeddings: list[str] = []
    positive_text_lines: list[str] = []
    loras: list[tuple[str, float]] = []
    negative_embeddings: list[str] = []
    negative_text_lines: list[str] = []
    
    in_negative_section = False
    
    for line in lines:
        # Skip comments
        if line.startswith('#'):
            continue
        
        # Check if this is a negative line
        if line.startswith('neg:'):
            in_negative_section = True
            # Remove "neg:" prefix and process
            content = line[4:].strip()
            
            # Extract embeddings from negative line
            neg_embeds = EMBEDDING_TAG_RE.findall(content)
            negative_embeddings.extend(neg_embeds)
            
            # Remove embeddings to get pure text
            clean_text = EMBEDDING_TAG_RE.sub('', content).strip()
            if clean_text:
                negative_text_lines.append(clean_text)
            
            continue
        
        # Check if line contains only embeddings (positive section)
        embeddings_in_line = EMBEDDING_TAG_RE.findall(line)
        if embeddings_in_line and not in_negative_section:
            # Check if line is ONLY embeddings
            temp = EMBEDDING_TAG_RE.sub('', line).strip()
            if not temp or temp == '':
                # Pure embedding line
                positive_embeddings.extend(embeddings_in_line)
                continue
        
        # Check if line contains only LoRAs
        loras_in_line = LORA_TAG_RE.findall(line)
        if loras_in_line and not in_negative_section:
            # Check if line is ONLY LoRAs
            temp = LORA_TAG_RE.sub('', line).strip()
            if not temp or temp == '':
                # Pure LoRA line
                for lora_name, weight_str in loras_in_line:
                    try:
                        weight = float(weight_str)
                    except ValueError:
                        weight = 1.0
                    loras.append((lora_name, weight))
                continue
        
        # If we reach here, it's a text line (positive prompt)
        if not in_negative_section:
            positive_text_lines.append(line)
    
    # Join text lines
    positive_text = '\n'.join(positive_text_lines)
    negative_text = ', '.join(negative_text_lines)  # Negative typically comma-separated
    
    return ParsedPromptComponents(
        positive_embeddings=positive_embeddings,
        positive_text=positive_text,
        loras=loras,
        negative_embeddings=negative_embeddings,
        negative_text=negative_text
    )


def assemble_prompt_txt_from_components(components: ParsedPromptComponents) -> str:
    """Assemble structured components back into prompt pack TXT format.
    
    Args:
        components: ParsedPromptComponents with separated fields
        
    Returns:
        Assembled TXT format string
    """
    lines: list[str] = []
    
    # Add positive embeddings
    if components.positive_embeddings:
        embedding_line = ' '.join(f'<embedding:{e}>' for e in components.positive_embeddings)
        lines.append(embedding_line)
    
    # Add positive text
    if components.positive_text:
        lines.append(components.positive_text)
    
    # Add LoRAs
    if components.loras:
        lora_line = ' '.join(f'<lora:{name}:{weight}>' for name, weight in components.loras)
        lines.append(lora_line)
    
    # Add negative embeddings
    if components.negative_embeddings:
        neg_embed_line = 'neg: ' + ' '.join(f'<embedding:{e}>' for e in components.negative_embeddings)
        lines.append(neg_embed_line)
    
    # Add negative text
    if components.negative_text:
        lines.append(f'neg: {components.negative_text}')
    
    return '\n'.join(lines)


def parse_multi_slot_txt(text: str) -> list[ParsedPromptComponents]:
    """Parse a multi-slot TXT file into a list of ParsedPromptComponents.
    
    Slots are separated by double newlines (blank lines).
    
    Args:
        text: Raw prompt text with multiple slots
        
    Returns:
        List of ParsedPromptComponents, one per slot
    """
    # Split by double newlines to get individual slots
    slot_texts = re.split(r'\n\s*\n', text.strip())
    
    # Parse each slot
    components_list = []
    for slot_text in slot_texts:
        if slot_text.strip():  # Skip empty slots
            components = parse_prompt_txt_to_components(slot_text)
            components_list.append(components)
    
    return components_list
