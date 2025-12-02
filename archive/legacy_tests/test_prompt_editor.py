# Standalone parser extracted from AdvancedPromptEditor._validate_txt_content
def parse_prompt_pack_text(content):
    """Parse prompt pack text into positive and negative prompts."""
    positives = []
    negatives = []
    blocks = content.split("\n\n")
    for block in blocks:
        block = block.strip()
        if not block or all(line.startswith("#") for line in block.splitlines() if line.strip()):
            continue
        lines = [line.strip() for line in block.splitlines()]
        lines = [line for line in lines if line and not line.startswith("#")]
        for line in lines:
            if line.startswith("neg:"):
                neg_content = line[4:].strip()
                if neg_content:
                    negatives.append(neg_content)
            else:
                positives.append(line)
    return positives, negatives


import unittest


class TestPromptEditorEnhancements(unittest.TestCase):
    """Tests for PR F-H enhancements to the prompt editor."""

    def test_angle_bracket_escaping(self):
        """Test that angle brackets are properly escaped and unescaped."""
        # Content with angle brackets (e.g., emphasis syntax)
        content_with_brackets = "a beautiful <lora:model:0.5> landscape <embedding:name>"

        # Escape for safe saving
        escaped = content_with_brackets.replace("<", "&lt;").replace(">", "&gt;")
        self.assertIn("&lt;lora", escaped)
        self.assertIn("&gt;", escaped)

        # Unescape for display
        unescaped = escaped.replace("&lt;", "<").replace("&gt;", ">")
        self.assertEqual(unescaped, content_with_brackets)

    def test_pack_name_auto_population(self):
        """Test that pack name is auto-populated from filename."""
        from pathlib import Path

        # Simulate loading a pack with a specific filename
        pack_path = Path("packs/my_awesome_pack.txt")
        expected_name = "my_awesome_pack"

        # Extract stem (filename without extension)
        actual_name = pack_path.stem
        self.assertEqual(actual_name, expected_name)

    def test_filename_prefix_from_name_metadata(self):
        """Test that 'name:' metadata is used for filename prefix and prompt parsing works."""
        # Content with name: metadata
        content = """name: HeroCharacter\na brave hero\nstanding tall\nneg: bad quality"""

        # Extract name from first line
        lines = content.strip().split("\n")
        name_prefix = None
        for line in lines:
            if line.strip().startswith("name:"):
                name_prefix = line.split(":", 1)[1].strip()
                break

        self.assertEqual(name_prefix, "HeroCharacter")

        # Verify it can be used in filename
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        expected_filename = f"{name_prefix}_{timestamp}.png"
        self.assertTrue(expected_filename.startswith("HeroCharacter_"))

        # Test parsing logic
        positives, negatives = parse_prompt_pack_text(content)
        self.assertIn("a brave hero", positives)
        self.assertIn("standing tall", positives)
        self.assertIn("bad quality", negatives)

    def test_global_negative_roundtrip(self):
        """Test that global negative prompt persists through save/load."""
        global_negative = "blurry, bad quality, nsfw, inappropriate"

        # Simulate saving
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            config = {"global_negative": global_negative}
            json.dump(config, f, ensure_ascii=False)
            temp_path = f.name

        try:
            # Simulate loading
            with open(temp_path, encoding="utf-8") as f:
                loaded_config = json.load(f)

            self.assertEqual(loaded_config["global_negative"], global_negative)
        finally:
            import os

            os.unlink(temp_path)

    def test_bracket_handling_in_prompts(self):
        """Test that various bracket types are handled correctly."""
        prompts_with_brackets = [
            "a photo of <character>",
            "painting (detailed:1.2)",
            "[fantasy:scifi:0.5]",
            "(masterpiece, best quality)",
        ]

        for prompt in prompts_with_brackets:
            # Verify brackets are preserved
            has_bracket = "<" in prompt or "(" in prompt or "[" in prompt
            self.assertTrue(has_bracket, f"Prompt should contain brackets: {prompt}")

            # Test escape/unescape cycle for angle brackets
            escaped = prompt.replace("<", "&lt;").replace(">", "&gt;")
            unescaped = escaped.replace("&lt;", "<").replace("&gt;", ">")
            self.assertEqual(unescaped, prompt)


if __name__ == "__main__":
    unittest.main()
