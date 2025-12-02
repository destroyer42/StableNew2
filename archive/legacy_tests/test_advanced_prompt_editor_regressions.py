"""RED regression tests for Advanced Prompt Editor issues tracked in sprint.
Created: 2025-11-02 22:31:47
"""

import pytest

AdvancedPromptEditor = pytest.importorskip("src.gui.advanced_prompt_editor").AdvancedPromptEditor


def test_status_text_widget_exists_and_updates(tk_root):
    class DummyConfigManager:
        pass

    editor = AdvancedPromptEditor(tk_root, DummyConfigManager())
    assert hasattr(editor, "status_text"), "Editor should define status_text label during init"
    editor.status_text.config(text="Refreshing models...")


def test_angle_brackets_do_not_crash_validation(tk_root):
    class DummyConfigManager:
        pass

    editor = AdvancedPromptEditor(tk_root, DummyConfigManager())
    sample = "<embedding:foo> <lora:Bar:0.7> some text"
    if not hasattr(editor, "validate_prompt"):
        pytest.xfail("validate_prompt not exposed yet")
    else:
        result = editor.validate_prompt(sample)
        assert getattr(result, "is_valid", True), "Angle brackets should be tolerated and not crash"


def test_name_metadata_prefixes_filename_logic_unit():
    from src.utils._extract_name_prefix import extract_name_prefix

    name = "Sorceress_02"
    base = "02NOV2025_135722"
    expected_prefix = f"{name}_{base}"
    actual = extract_name_prefix(name, base)
    assert actual == expected_prefix, f"Expected {expected_prefix}, got {actual}"
