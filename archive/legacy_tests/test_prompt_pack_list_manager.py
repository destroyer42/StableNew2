import json
import os

# Ensure the src directory is in the Python path
import sys
import unittest
from pathlib import Path

if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gui.prompt_pack_list_manager import PromptPackListManager


class TestPromptPackListManager(unittest.TestCase):
    """Tests for the PromptPackListManager class."""

    def setUp(self):
        """Set up a temporary test file path."""
        self.test_file = "test_custom_lists.json"
        # Clean up any previous test files
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def tearDown(self):
        """Clean up the test file after each test."""
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_initialization_no_file(self):
        """Test initialization when the JSON file does not exist."""
        manager = PromptPackListManager(file_path=self.test_file)
        self.assertEqual(manager.lists, {})
        self.assertFalse(Path(self.test_file).exists())

    def test_initialization_with_existing_file(self):
        """Test initialization with a pre-existing and valid JSON file."""
        initial_data = {"My Favorites": ["pack1.txt", "pack2.txt"]}
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        manager = PromptPackListManager(file_path=self.test_file)
        self.assertEqual(manager.lists, initial_data)

    def test_initialization_with_empty_file(self):
        """Test initialization with an empty JSON file."""
        Path(self.test_file).touch()
        manager = PromptPackListManager(file_path=self.test_file)
        self.assertEqual(manager.lists, {})

    def test_initialization_with_invalid_json(self):
        """Test initialization with a file containing invalid JSON."""
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("{'invalid_json':}")

        manager = PromptPackListManager(file_path=self.test_file)
        self.assertEqual(manager.lists, {})

    def test_save_list_new(self):
        """Test saving a new list."""
        manager = PromptPackListManager(file_path=self.test_file)
        packs = ["landscape.txt", "portraits.txt"]
        result = manager.save_list("Nature", packs)

        self.assertTrue(result)
        self.assertIn("Nature", manager.lists)
        self.assertEqual(manager.lists["Nature"], sorted(packs))

        # Verify file content
        with open(self.test_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data, {"Nature": sorted(packs)})

    def test_save_list_update_existing(self):
        """Test updating an existing list."""
        initial_data = {"Nature": ["landscape.txt"]}
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        manager = PromptPackListManager(file_path=self.test_file)
        new_packs = ["landscape.txt", "portraits.txt", "architecture.txt"]
        result = manager.save_list("Nature", new_packs)

        self.assertTrue(result)
        self.assertEqual(manager.lists["Nature"], sorted(new_packs))

    def test_save_list_invalid_input(self):
        """Test saving with invalid input."""
        manager = PromptPackListManager(file_path=self.test_file)
        self.assertFalse(manager.save_list("", ["pack.txt"]))
        self.assertFalse(manager.save_list("Test", None))
        self.assertFalse(Path(self.test_file).exists())

    def test_delete_list_existing(self):
        """Test deleting an existing list."""
        initial_data = {"List1": ["a.txt"], "List2": ["b.txt"]}
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        manager = PromptPackListManager(file_path=self.test_file)
        result = manager.delete_list("List1")

        self.assertTrue(result)
        self.assertNotIn("List1", manager.lists)
        self.assertIn("List2", manager.lists)

        with open(self.test_file, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data, {"List2": ["b.txt"]})

    def test_delete_list_non_existent(self):
        """Test deleting a list that does not exist."""
        manager = PromptPackListManager(file_path=self.test_file)
        manager.save_list("Existing List", ["pack.txt"])

        result = manager.delete_list("Non Existent List")
        self.assertFalse(result)
        self.assertIn("Existing List", manager.lists)

    def test_get_list_names(self):
        """Test retrieving the names of all lists."""
        manager = PromptPackListManager(file_path=self.test_file)
        manager.save_list("List C", [])
        manager.save_list("List A", [])
        manager.save_list("List B", [])

        self.assertEqual(manager.get_list_names(), ["List A", "List B", "List C"])

    def test_get_list(self):
        """Test retrieving a specific list by name."""
        packs = ["pack1.txt", "pack2.txt"]
        manager = PromptPackListManager(file_path=self.test_file)
        manager.save_list("My List", packs)

        self.assertEqual(manager.get_list("My List"), sorted(packs))
        self.assertIsNone(manager.get_list("Non Existent List"))

    def test_refresh(self):
        """Test refreshing the lists from the file."""
        manager = PromptPackListManager(file_path=self.test_file)
        manager.save_list("Initial List", ["a.txt"])

        # Modify the file externally
        with open(self.test_file, "w", encoding="utf-8") as f:
            json.dump({"External List": ["b.txt"]}, f)

        manager.refresh()
        self.assertEqual(manager.lists, {"External List": ["b.txt"]})
        self.assertEqual(manager.get_list_names(), ["External List"])


if __name__ == "__main__":
    unittest.main()
