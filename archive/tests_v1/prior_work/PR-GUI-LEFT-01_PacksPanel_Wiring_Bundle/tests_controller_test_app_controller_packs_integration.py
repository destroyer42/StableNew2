import pytest

# from src.controller.app_controller import AppController  # to be wired
# from src.utils.prompt_packs import PackService


class FakeView:
    def __init__(self) -> None:
        self.packs = []
        self.presets = []
        self.active_pack = None
        self.active_preset = None

    def set_packs(self, packs):
        self.packs = packs

    def set_presets(self, presets):
        self.presets = presets

    def set_active_pack(self, name):
        self.active_pack = name

    def set_active_preset(self, name):
        self.active_preset = name


class FakePackService:
    def __init__(self) -> None:
        self.list_packs_called = 0

    def list_packs(self):
        self.list_packs_called += 1
        # Return a minimal structure the controller expects
        return []


class TestAppControllerPacksIntegration:
    def test_controller_fetches_packs_on_init(self):
        # This test should construct AppController with a FakeView and FakePackService
        # and assert that view.set_packs(...) is called with the expected data.
        pytest.skip("AppController packs integration test not implemented yet")
