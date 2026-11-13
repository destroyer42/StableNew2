"""Deterministic regressions for the PromptPack Add to Job boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.controller.app_controller import AppController
from src.gui.app_state_v2 import AppStateV2
from src.gui.stage_cards_v2.advanced_txt2img_stage_card_v2 import AdvancedTxt2ImgStageCardV2
from src.utils.prompt_packs import PromptPackInfo

SAVED = {"txt2img": {"seed": -1, "subseed": 44, "subseed_strength": 0.75}}


class SeedCard:
    """Use the real stage-card parser with Tk-like variables confined to the owner thread."""

    _parse_seed = staticmethod(AdvancedTxt2ImgStageCardV2._parse_seed)

    def __init__(self, seed, subseed="", strength=""):
        self.owner = get_ident()
        self.seed_var = self._var(seed)
        self.seed_section = SimpleNamespace(
            subseed_var=self._var(subseed), subseed_strength_var=self._var(strength)
        )

    def _var(self, value):
        var = SimpleNamespace(value=value)

        def read():
            assert get_ident() == self.owner
            return var.value

        var.get = read
        return var

    def to_config_dict(self):
        return {"txt2img": AdvancedTxt2ImgStageCardV2._seed_config(self)}


def make_app(card, *, override=True, manager=None, app_state=None):
    app = AppController.__new__(AppController)
    app.main_window = None
    app.app_state = app_state if app_state is not None else AppStateV2()
    app.state = SimpleNamespace(current_config=app.app_state.current_config)
    app.threaded = False
    app.override_pack_config_enabled = override
    app._get_stage_cards_panel = lambda: SimpleNamespace(txt2img_card=card)
    app._append_log = Mock()
    app._mark_ui_dirty = Mock()
    app._config_manager = manager
    return app


@pytest.mark.parametrize(
    ("seed", "subseed", "strength", "expected"),
    [
        ("535291198", "", "", (535291198, -1, 0.0)),
        ("0", "0", "0", (0, 0, 0.0)),
        (" ", " ", " ", (-1, -1, 0.0)),
        ("-1", "34", "0.25", (-1, 34, 0.25)),
        ("4294967295", "-1", "1", (4294967295, -1, 1.0)),
    ],
)
def test_override_snapshot_uses_typed_stage_values(seed, subseed, strength, expected):
    app = make_app(SeedCard(seed, subseed, strength))
    merged = app._capture_pack_draft_config().merge(SAVED)
    assert merged["seed"] == expected[0]
    assert tuple(merged["txt2img"][k] for k in ("seed", "subseed", "subseed_strength")) == expected
    assert SAVED["txt2img"] == {"seed": -1, "subseed": 44, "subseed_strength": 0.75}


def test_override_off_keeps_saved_values_without_reading_stage_card():
    card = Mock()
    app = make_app(card, override=False)
    merged = app._capture_pack_draft_config().merge(SAVED)
    card.to_config_dict.assert_not_called()
    assert merged["txt2img"] == SAVED["txt2img"]


@pytest.mark.parametrize(
    ("seed", "subseed", "strength", "field"),
    [
        ("bad", "", "", "Seed"),
        ("1.2", "", "", "Seed"),
        ("-2", "", "", "Seed"),
        ("4294967296", "", "", "Seed"),
        ("10", "bad", "", "Subseed"),
        ("10", "", "bad", "Subseed Strength"),
        ("10", "", "NaN", "Subseed Strength"),
        ("10", "", "1.1", "Subseed Strength"),
    ],
)
def test_invalid_numeric_override_visibly_refuses_add(seed, subseed, strength, field):
    app = make_app(SeedCard(seed, subseed, strength))
    app._find_pack_by_id = Mock(side_effect=AssertionError("Pack I/O before validation"))
    app.on_pipeline_add_packs_to_job(["hero"])
    assert f"{field} must be" in app.app_state.status_text
    assert app.app_state.status_text.startswith("Could not add PromptPacks.")
    assert app.app_state.job_draft.packs == []
    assert app.app_state.preview_jobs == []
    assert app.current_operation_label is None
    app._find_pack_by_id.assert_not_called()


def test_failed_merge_refuses_the_add_without_appending_partial_entries(tmp_path):
    pack = tmp_path / "hero.txt"
    pack.write_text("a knight", encoding="utf-8")
    manager = Mock()
    manager.load_pack_config.side_effect = [SAVED, {"txt2img": "invalid stage block"}]
    app = make_app(SeedCard("535291198"), manager=manager)
    app.packs = [
        PromptPackInfo(name="hero", path=pack),
        PromptPackInfo(name="bad", path=pack),
    ]

    app.on_pipeline_add_packs_to_job(["hero", "bad"])

    assert app.app_state.job_draft.packs == []
    assert "Could not merge settings for 'bad'" in app.app_state.status_text
    assert app.current_operation_label is None


def test_pack_worker_only_reads_captured_settings(tmp_path):
    pack = tmp_path / "hero.txt"
    pack.write_text("a knight", encoding="utf-8")
    card = SeedCard("535291198")
    app = make_app(card)
    app.threaded = True
    app.packs = [PromptPackInfo(name="hero", path=pack)]
    app._config_manager = SimpleNamespace(load_pack_config=Mock(return_value=SAVED))
    workers = []
    callbacks = []
    app._ui_thread_id = get_ident()
    app._spawn_tracked_thread = lambda *, target, **_: workers.append(target)
    app.main_window = SimpleNamespace(run_in_main_thread=callbacks.append)

    def gui_reader(value):
        def read():
            assert get_ident() == card.owner
            return value

        return read

    run_config = {"pipeline": {"output_dir": "at-click"}}
    policy = {
        "positive_enabled": True,
        "positive_text": "at-click",
        "negative_enabled": False,
        "negative_text": "",
    }
    app._run_config_with_lora = gui_reader(run_config)
    app.get_current_global_prompt_policy = gui_reader(policy.copy())

    def load_in_worker(_pack_id):
        assert get_ident() != card.owner
        return SAVED

    app._config_manager.load_pack_config.side_effect = load_in_worker
    app._append_log.side_effect = lambda _: gui_reader(None)()

    app.on_pipeline_add_packs_to_job(["hero"])
    card.seed_var.value = "12"
    app.override_pack_config_enabled = False
    run_config["pipeline"]["output_dir"] = "later"
    app.get_current_global_prompt_policy = gui_reader({**policy, "positive_text": "later"})

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(workers.pop()).result(timeout=5)
    assert app.app_state.job_draft.packs == []
    callbacks.pop()()

    [entry] = app.app_state.job_draft.packs
    assert entry.config_snapshot["txt2img"] == {
        "seed": 535291198,
        "subseed": -1,
        "subseed_strength": 0.0,
    }
    assert entry.config_snapshot["global_positive_prompt"] == "at-click"
    assert entry.config_snapshot["pipeline"]["output_dir"] == "at-click"


def test_preview_policy_worker_reads_last_gui_projection():
    app = make_app(SeedCard("0"))
    app._ui_thread_id = get_ident()
    positive = SeedCard("at-click").seed_var
    app.main_window = SimpleNamespace(
        sidebar_panel_v2=SimpleNamespace(
            get_global_positive_config=lambda: {"enabled": True, "text": positive.get()},
            get_global_negative_config=lambda: {"enabled": True, "text": ""},
        )
    )
    assert app.get_current_global_prompt_policy()["positive_text"] == "at-click"

    positive.value = "updated"
    with ThreadPoolExecutor(max_workers=1) as pool:
        get_policy = app.get_current_global_prompt_policy
        assert pool.submit(get_policy).result(timeout=5)["positive_text"] == "at-click"
        assert get_policy()["positive_text"] == "updated"
        assert pool.submit(get_policy).result(timeout=5)["positive_text"] == "updated"
