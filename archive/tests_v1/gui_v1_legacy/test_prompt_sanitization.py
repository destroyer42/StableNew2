from src.gui.main_window import sanitize_prompt


def test_sanitize_prompt_removes_matrix_and_wildcard_tokens():
    dirty = "Epic [[lighting]] portrait of __mood__ warrior [[style]]"
    clean = sanitize_prompt(dirty)
    assert "[[" not in clean
    assert "__" not in clean
    assert "  " not in clean


def test_sanitize_prompt_handles_empty_text():
    assert sanitize_prompt("") == ""
    assert sanitize_prompt(None) is None
