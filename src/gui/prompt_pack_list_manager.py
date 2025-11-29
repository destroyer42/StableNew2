"""
Manages loading, saving, and editing custom prompt pack lists.
"""

import json
from pathlib import Path


class PromptPackListManager:
    """Manages loading, saving, and editing custom prompt pack lists."""

    def __init__(self, file_path: str = "custom_pack_lists.json"):
        """
        Initializes the list manager.

        Args:
            file_path: The path to the JSON file storing the lists.
        """
        self.file_path = Path(file_path)
        self.lists: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        """Loads the lists from the JSON file if it exists."""
        if self.file_path.exists():
            try:
                with self.file_path.open("r", encoding="utf-8") as f:
                    # Ensure we handle empty files
                    content = f.read()
                    if not content:
                        return {}
                    return json.loads(content)
            except (OSError, json.JSONDecodeError):
                # If file is corrupted or unreadable, start fresh
                return {}
        return {}

    def _save(self) -> bool:
        """Saves the current lists to the JSON file."""
        try:
            with self.file_path.open("w", encoding="utf-8") as f:
                json.dump(self.lists, f, indent=2, ensure_ascii=False)
            return True
        except OSError:
            return False

    def get_list_names(self) -> list[str]:
        """Returns a sorted list of all custom list names."""
        return sorted(self.lists.keys())

    def get_list(self, name: str) -> list[str] | None:
        """
        Retrieves a specific list of packs by its name.

        Args:
            name: The name of the list to retrieve.

        Returns:
            A list of pack names, or None if the list doesn't exist.
        """
        return self.lists.get(name)

    def save_list(self, name: str, packs: list[str]) -> bool:
        """
        Saves or updates a list of packs.

        Args:
            name: The name of the list.
            packs: A list of pack file names.

        Returns:
            True if saving was successful, False otherwise.
        """
        if not name or not isinstance(packs, list):
            return False
        self.lists[name] = sorted(packs)  # Store sorted for consistency
        return self._save()

    def delete_list(self, name: str) -> bool:
        """
        Deletes a list by its name.

        Args:
            name: The name of the list to delete.

        Returns:
            True if the list was deleted and saved, False otherwise.
        """
        if name in self.lists:
            del self.lists[name]
            return self._save()
        return False

    def refresh(self):
        """Reloads the lists from the file."""
        self.lists = self._load()
