# PR-RES-070: Model Resource Discovery and Refresh Cleanup

## Goal

Make WebUI resource discovery and refresh use one canonical snapshot contract from the resource service through controller normalization, app-state storage, and GUI dropdown hydration.

## Scope

- `src/api/webui_resource_service.py`
- `src/controller/app_controller.py`
- `src/gui/app_state_v2.py`
- `src/gui/dropdown_loader_v2.py`
- targeted API/controller/GUI refresh tests

## Changes

1. Added canonical WebUI resource snapshot keys in `webui_resource_service.py` and shared helpers for empty-map creation and normalization.
2. Extended `refresh_all()` to include `hypernetworks` and `embeddings` in the same canonical snapshot as models, vaes, samplers, schedulers, upscalers, and ADetailer resources.
3. Removed controller/app-state/dropdown duplication around resource-map normalization by reusing the same canonical helper.
4. Expanded refresh logging in `AppController` so resource updates report hypernetwork and embedding counts too.
5. Added regression coverage proving the canonical refresh path now preserves `hypernetworks` and `embeddings` instead of silently dropping them.

## Result

Resource discovery is now consistent across:

- WebUI service refresh
- controller refresh/update dispatch
- app-state resource storage
- pipeline dropdown/state hydration

This PR does not add new GUI widgets for hypernetworks or embeddings. It fixes the contract and propagation layer so those resources are available consistently to current and future UI consumers.

## Verification

- `pytest tests/api/test_webui_resources.py tests/api/test_webui_resources_adetailer_v2.py tests/controller/test_resource_refresh_adetailer_v2.py tests/gui_v2/test_pipeline_dropdown_refresh_v2.py tests/journey/test_phase1_pipeline_journey_v2.py -q`
- `pytest --collect-only -q`
- `python -m compileall src/api/webui_resource_service.py src/controller/app_controller.py src/gui/app_state_v2.py src/gui/dropdown_loader_v2.py tests/api/test_webui_resources_adetailer_v2.py tests/controller/test_resource_refresh_adetailer_v2.py tests/gui_v2/test_pipeline_dropdown_refresh_v2.py`
