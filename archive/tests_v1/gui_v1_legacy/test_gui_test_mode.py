from types import SimpleNamespace


def _enable_test_mode(monkeypatch):
    monkeypatch.setenv("STABLENEW_GUI_TEST_MODE", "1")
    from src.gui import main_window

    main_window.enable_gui_test_mode()
    return main_window


def test_unapplied_changes_confirmation_auto_accepts(monkeypatch):
    main_window = _enable_test_mode(monkeypatch)

    called = {}

    def fake_askyesno(*_args, **_kwargs):
        called["hit"] = True
        return False

    monkeypatch.setattr(main_window.messagebox, "askyesno", fake_askyesno)

    dummy = SimpleNamespace(_config_dirty=True)

    try:
        assert main_window.StableNewGUI._confirm_run_with_dirty(dummy) is True
        assert not called
    finally:
        main_window.reset_gui_test_mode()


def test_new_features_dialog_skipped_in_test_mode(monkeypatch):
    main_window = _enable_test_mode(monkeypatch)

    invoked = {}

    monkeypatch.setattr(
        main_window.StableNewGUI,
        "_show_new_features_dialog",
        lambda self: invoked.setdefault("called", True),
        raising=False,
    )

    dummy = SimpleNamespace(_new_features_dialog_shown=False)
    try:
        main_window.StableNewGUI._maybe_show_new_features_dialog(dummy)
        assert not invoked
    finally:
        main_window.reset_gui_test_mode()
