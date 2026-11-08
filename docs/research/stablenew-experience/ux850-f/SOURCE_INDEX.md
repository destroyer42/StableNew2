# Exact accepted source and artifact index

F base is `75842f7ba04429ac918ccf742d6c7ff001c577b6`; authoritative remote `https://github.com/destroyer42/StableNew2.git`. Read-only GitHub fetch_commit(main) independently returned that exact E merge during discovery after shell network resolution failed. No remote writes. Recheck live refs before coordinator publication/integration; a local tracking ref alone is not current remote proof.

## Accepted A–E artifact identities

| Package | Accepted head | Integration | F applicability check |
|---|---|---|---|
| A | `5e081494fac33d96b47fde836a42a9a344c17ce0` | `f51aa870824a0804202c438531f4f1c9e0bc231c` | 11 accepted files; original artifacts unchanged except README addendum link, verified at accepted addendum integration |
| B | `6c909dc144c786e9a7361928318b49916e273ddb` | `f39d748fc2508a69a59e194ac9dcd8f690fed976` | 8 accepted files; every accepted artifact blob matches F base |
| C | `53125db88e194d5ec7d0deb991d1ef04863bc93c` | `d05d4a2d769d7076c902b3b3a63d626fea192112` | 19 accepted files; every accepted artifact blob matches F base |
| D | `48319e90d99f1706abbbb7144f13502a1cebe4d0` | `8f76ee6036baec0eaa298bdde9949c197541132b` | 10 accepted files; every accepted artifact blob matches F base |
| E | `28967e3f2795900ce0c40d1cab12f7e431dc798a` | `75842f7ba04429ac918ccf742d6c7ff001c577b6` | 10 accepted files; every accepted artifact blob matches F base |

Additionally A's late addendum at integration `9360d2432c4b0077b153a4595795ece66241238e` exactly matches the current base blob. A README differs from its original accepted head only by the added addendum index link, also verified against that integration; original A findings/classifications are unchanged. D authored from d05d4a2d; its actual PR base was that addendum integration, and D's accepted artifacts reconcile it. E's merge tree equals accepted E head; D/E exact accepted artifact blobs remain intact. External `accepted_artifacts.json` records all 59 verified artifact rows, not just README identities. Historical hosted-green/skip dispositions are coordinator-supplied accepted evidence, not rerun or independently authenticated physical evidence in F.

Production `src` tree is `802afeedf0328f705c2fa97c0fda5eb758286dcf`, tests tree `ac04888177b8f785cb6b559cdddfb9f2f209b10f`, qualification-tools tree `93a0b094a8734683a9ec294e9e1d8d9378ad8731`. Git comparison of `src`, `tests`, `config`, `presets`, `pyproject.toml` and `tools/qualification` against A application cut `3399f8032182b65bd904f8f27818d927909cd6a3` is empty. A's original evidence cut is `8e1ee82b5fd8cc18437274e86e9af4f59938a799`; reuse is within its partial Comprehensive/six-dimension limits. No new runtime correctness/quality/installation result follows from identity equality.

## Focused new production trace

At the base, Prompt Load button line 300 and double-click line 336 both bind `_on_load_selected_pack` (1787). New (1220, dirty branch 1225) uses discard confirmation; Load parses candidate identity then calls `workspace_state.load_pack` (1803) without dirty confirmation. `PromptWorkspaceState.load_pack` (38) parses before assignment and resets dirty afterward. Source/test AST and line records are preserved outside Git. F concludes only the inspected deliberate Load path has this omission; shutdown/TXT import/all other switching paths are not fully audited. The state basic-flow test proves save/load dirty-reset, not cancellation behavior.

## Verified future implementation and test entrypoints

The 56 files below exist and are pinned by Git blob. Tests are **entrypoints / inspected contracts, NOT RUN in F**. Whole-module references do not mean every function was audited. Detailed accepted production callchains remain in A/D/E source indices; F does not repeat unchanged exploration. Full Git-byte SHA-256 values also appear in the external source manifest; checkout newline transformations do not establish drift.

| File | Git blob at F base |
|---|---|
| [src/controller/app_controller_services/run_submission_service.py](../../../../src/controller/app_controller_services/run_submission_service.py) | `a09132d932317269264969b89bdf3102baa4bdb6` |
| [src/controller/generation_profile_controller.py](../../../../src/controller/generation_profile_controller.py) | `9e5622d374f3ab32e2cdc98da0892285569f1ad1` |
| [src/controller/movie_clips_submission_service.py](../../../../src/controller/movie_clips_submission_service.py) | `6e0f03b99840580b520c1168d0946fffe77ef31b` |
| [src/generation_profiles/application.py](../../../../src/generation_profiles/application.py) | `e35ddcde75321363ceeaaf293caa1eef60818e27` |
| [src/gui/controllers/history_compare_service.py](../../../../src/gui/controllers/history_compare_service.py) | `070ff5044cad89ae90282d46d9119c32c1d3ad6b` |
| [src/gui/controllers/history_iterate_service.py](../../../../src/gui/controllers/history_iterate_service.py) | `34b689e5bb5a6f5afe55c63bec55c3e92ec1f4c6` |
| [src/gui/controllers/learning_controller.py](../../../../src/gui/controllers/learning_controller.py) | `217354054d4b23b5d090cd5073094e438a2c7b2e` |
| [src/gui/controllers/model_evidence_next_test.py](../../../../src/gui/controllers/model_evidence_next_test.py) | `5ba90d9681626b217488baf08010d56d87a51287` |
| [src/gui/generation_profile_strip.py](../../../../src/gui/generation_profile_strip.py) | `f78e2004cef8b909547bc04bfa9dd9880ee1e536` |
| [src/gui/job_history_panel_v2.py](../../../../src/gui/job_history_panel_v2.py) | `fcb382397c0538817f62e8e98ecae85158672880` |
| [src/gui/main_window_v2.py](../../../../src/gui/main_window_v2.py) | `d8dd843cdf22f2e90909434a122c794a74fc49df` |
| [src/gui/prompt_workspace_state.py](../../../../src/gui/prompt_workspace_state.py) | `6f5e5c049a5000a169591d0c7de7f6901f3d1e82` |
| [src/gui/ui_tokens.py](../../../../src/gui/ui_tokens.py) | `36f14a4bbdb00fcfa4d5db12abe64fc1afc49150` |
| [src/gui/views/movie_clips_tab_frame_v2.py](../../../../src/gui/views/movie_clips_tab_frame_v2.py) | `cdbad38d6f22d00fc60019111e4042238b4c57ae` |
| [src/gui/views/next_test_dialog.py](../../../../src/gui/views/next_test_dialog.py) | `2f1f014ad143ecc79beca305b18e121dfac03006` |
| [src/gui/views/pipeline_tab_frame_v2.py](../../../../src/gui/views/pipeline_tab_frame_v2.py) | `d25ef0b3a021c64eebec4cfa7bc115191cec6b0e` |
| [src/gui/views/prompt_tab_frame_v2.py](../../../../src/gui/views/prompt_tab_frame_v2.py) | `8ca536e0535db4e5daa475c26f389e277c0d8a05` |
| [src/gui/views/storyboard_panel_actions.py](../../../../src/gui/views/storyboard_panel_actions.py) | `18ad475300032a36d82a19ff36733a472786eb78` |
| [src/gui/views/video_workflow_sequence_panel_v2.py](../../../../src/gui/views/video_workflow_sequence_panel_v2.py) | `c4171b2f42279550d9bd21db332cc21b991b6122` |
| [src/gui/widgets/media_inspector.py](../../../../src/gui/widgets/media_inspector.py) | `6adaac4305b1118cb20507360a960fd17b108521` |
| [src/gui/widgets/scrollable_frame_v2.py](../../../../src/gui/widgets/scrollable_frame_v2.py) | `5fac7e00c313bafb8b77b299c3a806b6d217bf0c` |
| [src/gui_v2/generation_profile_projection.py](../../../../src/gui_v2/generation_profile_projection.py) | `ccbd1295f8b9819280fd8c5f81cdb13ceab030ae` |
| [src/gui_v2/history_iterate_model.py](../../../../src/gui_v2/history_iterate_model.py) | `dfcd4853fb894fac9e19ca549dc9dec67230ab96` |
| [src/learning/evidence_intelligence.py](../../../../src/learning/evidence_intelligence.py) | `85da737d040003ba6a488d1169f16c0beaa54259` |
| [src/learning/library_status.py](../../../../src/learning/library_status.py) | `5c3ce93bc1d5d96fae819ffd2fa5f403c14838a7` |
| [src/learning/profile_publication.py](../../../../src/learning/profile_publication.py) | `14297086b270e8f4ed199a3cf661b6c1d9e4d914` |
| [src/video/sequence_resume.py](../../../../src/video/sequence_resume.py) | `09aa6762a285e83f04e8ab49a91227efe150bc6b` |
| [src/video/storyboard_readiness.py](../../../../src/video/storyboard_readiness.py) | `88982aeedd1218b7131b0774deaae1156735064c` |
| [src/video/storyboard_store.py](../../../../src/video/storyboard_store.py) | `854fed84368d040d1ae58606f95ddf3e6ef1047e` |
| [tests/controller/test_generation_profile_controller_630.py](../../../../tests/controller/test_generation_profile_controller_630.py) | `7fbe52c67b68850f77e778afed846eb879dc4755` |
| [tests/controller/test_movie_clips_submission_332.py](../../../../tests/controller/test_movie_clips_submission_332.py) | `b78ea9da999f57c794286862c09cf4f2f3f1f404` |
| [tests/gui_v2/test_generation_profile_projection_630.py](../../../../tests/gui_v2/test_generation_profile_projection_630.py) | `306ff85d9b7c97c7b2c3575d19f3efc40ec7ab56` |
| [tests/gui_v2/test_history_compare_610b.py](../../../../tests/gui_v2/test_history_compare_610b.py) | `b66b462b4e54f3871f66335fb1e4d8842ed22652` |
| [tests/gui_v2/test_history_iterate_gui_610a.py](../../../../tests/gui_v2/test_history_iterate_gui_610a.py) | `024960964bd02618f30b30ab94647ead6c325df5` |
| [tests/gui_v2/test_history_iterate_model_610a.py](../../../../tests/gui_v2/test_history_iterate_model_610a.py) | `294de582c7f5a602270fc9a504819ab3da5d2e7b` |
| [tests/gui_v2/test_history_iterate_service_610a.py](../../../../tests/gui_v2/test_history_iterate_service_610a.py) | `57876827cb020ed526c88e02bfea4fec977081a0` |
| [tests/gui_v2/test_learning_profile_publication_660.py](../../../../tests/gui_v2/test_learning_profile_publication_660.py) | `3ea8f51c92336e5735b85cf540d9c014ebc16aaa` |
| [tests/gui_v2/test_learning_tab_state_persistence.py](../../../../tests/gui_v2/test_learning_tab_state_persistence.py) | `090b8742745a7e85e90b1a936838d1937f6b8532` |
| [tests/gui_v2/test_media_inspector_620.py](../../../../tests/gui_v2/test_media_inspector_620.py) | `8948cc2573093a20a721ba3258dc5966a2b545c7` |
| [tests/gui_v2/test_movie_clips_tab_v2.py](../../../../tests/gui_v2/test_movie_clips_tab_v2.py) | `ee24c348611747a1fec161e059cae63632e872cf` |
| [tests/gui_v2/test_next_test_surface_830.py](../../../../tests/gui_v2/test_next_test_surface_830.py) | `8c4af6c7859eed97a4b0bbb5466ef8b0d29d9137` |
| [tests/gui_v2/test_pipeline_tab_layout_v2.py](../../../../tests/gui_v2/test_pipeline_tab_layout_v2.py) | `2885bce9d5c6402ce16b9df927ce8ca7162e33f0` |
| [tests/gui_v2/test_pointer_focus_no_scroll_831.py](../../../../tests/gui_v2/test_pointer_focus_no_scroll_831.py) | `cf4a608b37443645b39abc87cf75419e14509f2f` |
| [tests/gui_v2/test_prompt_authoring_540.py](../../../../tests/gui_v2/test_prompt_authoring_540.py) | `f6c41ea4ebe1eb2626e3d6f1078dae73310130be` |
| [tests/gui_v2/test_prompt_view_contracts.py](../../../../tests/gui_v2/test_prompt_view_contracts.py) | `e939c8adeeb27ea0490dc0694639886bebac1b34` |
| [tests/gui_v2/test_prompt_workspace_state_negative.py](../../../../tests/gui_v2/test_prompt_workspace_state_negative.py) | `bad0bb450c8b0fd35af0e271e2e274bf83b821e7` |
| [tests/gui_v2/test_scrollable_focus_reveal_400.py](../../../../tests/gui_v2/test_scrollable_focus_reveal_400.py) | `07638d9102bb68caeab4d1dac88a812b9a69a020` |
| [tests/gui_v2/test_stage_card_layout_resilience_v2.py](../../../../tests/gui_v2/test_stage_card_layout_resilience_v2.py) | `687253d755f2269f52f19159a93d6fd91f8331f3` |
| [tests/gui_v2/test_storyboard350_ui.py](../../../../tests/gui_v2/test_storyboard350_ui.py) | `beaa146e9c2ab4141edbc069db15bfddcc9fa0bc` |
| [tests/gui_v2/test_task_navigation_contract_410.py](../../../../tests/gui_v2/test_task_navigation_contract_410.py) | `2cc8c01d69d748950d13e564b2b2e411acf3d15b` |
| [tests/gui_v2/test_workspace_layout_resilience_v2.py](../../../../tests/gui_v2/test_workspace_layout_resilience_v2.py) | `f694d160ae49a12d6ec0f04e3cf242da1ac118bb` |
| [tests/integration/test_qualification_batch_810.py](../../../../tests/integration/test_qualification_batch_810.py) | `3d76d174919773b0a894df2066bc2c236fe1ffda` |
| [tests/learning_v2/test_profile_publication_660.py](../../../../tests/learning_v2/test_profile_publication_660.py) | `3a591ffbdd7944f2b94279361efe3b834b9e202a` |
| [tests/state/test_prompt_workspace_state.py](../../../../tests/state/test_prompt_workspace_state.py) | `60d51066d5886ad150f453173d97781dd57c64a6` |
| [tests/video/test_pr_vid_seq_330_checkpoint.py](../../../../tests/video/test_pr_vid_seq_330_checkpoint.py) | `31ec0cb97aec160f0b520f0466c3a7b2c85cefe1` |
| [tests/video/test_storyboard_drafts.py](../../../../tests/video/test_storyboard_drafts.py) | `109e2a945c08083d2c03458a07c5912fe535e27f` |

## Distinct-method negative-contract extraction

43 existing test bodies selected for specific failure/stale/unknown/refusal/cancel/publication/summary concerns were parsed with Python AST. Assertion counts describe authored tests, **not executed pass counts**. Full assertion strings are in external `negative_contracts.json`; selection is scoped, not exhaustive control coverage.

| Existing test / pinned line | Inspection |
|---|---|
| [test_conflict_on_a_later_job_rolls_back_earlier_new_jobs_and_spares_existing](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/queue/test_batch_admission_atomicity.py#L143) | 4 explicit assertions inspected |
| [test_injected_sqlite_failure_mid_batch_rolls_back_every_new_row](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/queue/test_batch_admission_atomicity.py#L161) | 5 explicit assertions inspected |
| [test_failed_batch_never_triggers_start_when_idle](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/queue/test_batch_admission_atomicity.py#L259) | 1 explicit assertions inspected |
| [test_startup_failure_after_commit_returns_admitted_ids_and_reports_separately](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/queue/test_batch_admission_atomicity.py#L502) | 8 explicit assertions inspected |
| [test_one_bad_design_refuses_entire_selection_and_preserves_edits](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L156) | 2 explicit assertions inspected |
| [test_partial_or_ambiguous_submission_stops_without_retry](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L197) | 9 explicit assertions inspected |
| [test_explicit_confirmation_and_cancellation_are_admission_boundaries](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L297) | 2 explicit assertions inspected |
| [test_changed_last_compiler_refuses_before_any_submission](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L307) | 1 explicit assertions inspected |
| [test_stale_visible_run_and_save_cannot_duplicate_or_erase_batch_admission](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L323) | 4 explicit assertions inspected |
| [test_stale_terminal_checkpoint_preserves_newer_library_projection_and_review_drafts](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L399) | 3 explicit assertions inspected |
| [test_checkpoint_failure_preserves_writeahead_ids_and_stops](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L452) | 5 explicit assertions inspected |
| [test_mid_batch_cancel_reports_prefix_and_never_submits_next](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L477) | 3 explicit assertions inspected |
| [test_saved_context_is_reused_and_conflicting_prompt_drafts_are_preserved](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/integration/test_qualification_batch_810.py#L488) | 2 explicit assertions inspected |
| [test_invalid_schema_fields_and_values_refuse_without_rewrite](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L82) | 1 explicit assertions inspected |
| [test_malformed_file_and_atomic_failure_leave_previous_bytes](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L93) | 3 explicit assertions inspected |
| [test_stale_revision_and_concurrent_save_never_lose_a_write](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L113) | 2 explicit assertions inspected |
| [test_export_never_overwrites_media_or_an_existing_json](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L134) | 2 explicit assertions inspected |
| [test_random_seed_and_summary_do_not_freeze_or_submit](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L179) | 5 explicit assertions inspected |
| [test_draft_session_dirty_and_path_edit_does_not_reuse_an_old_hash](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L250) | 2 explicit assertions inspected |
| [test_history_uses_canonical_frozen_plan_and_never_mutates_parent](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L267) | 7 explicit assertions inspected |
| [test_duplicate_json_keys_refuse_without_rewriting](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L317) | 1 explicit assertions inspected |
| [test_unrepresentable_or_tampered_frozen_history_refuses](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/video/test_storyboard_drafts.py#L345) | 1 explicit assertions inspected |
| [test_other_sources_refuse](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L135) | 1 explicit assertions inspected |
| [test_missing_execution_proof_refuses](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L161) | 2 explicit assertions inspected |
| [test_contradictory_proof_refuses](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L181) | 1 explicit assertions inspected |
| [test_invalid_or_draft_rating_refuses](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L189) | 1 explicit assertions inspected |
| [test_identity_context_and_value_conflicts](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L211) | 1 explicit assertions inspected |
| [test_rerating_is_effective_latest_and_stales_proposal](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L307) | 3 explicit assertions inspected |
| [test_concurrent_publish_and_immutable_store_boundary](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L368) | 4 explicit assertions inspected |
| [test_failed_atomic_publish_preserves_prior_revision](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L409) | 2 explicit assertions inspected |
| [test_resources_are_qualified_but_never_substituted](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L428) | 4 explicit assertions inspected |
| [test_learning_application_refuses_changed_exact_version_and_missing_bytes](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L514) | 2 explicit assertions inspected |
| [test_duplicate_findings_in_an_older_revision_are_not_republished](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L560) | 1 explicit assertions inspected |
| [test_incompatible_learning_startup_reference_remains_readable_but_not_applied](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/learning_v2/test_profile_publication_660.py#L583) | 2 explicit assertions inspected |
| [test_startup_tab_resolution](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_task_navigation_contract_410.py#L133) | 1 explicit assertions inspected |
| [test_startup_tab_resolution_is_empty_only_when_nothing_is_available](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_task_navigation_contract_410.py#L137) | 2 explicit assertions inspected |
| [test_dialog_details_toggle_stale_state_resize_and_keyboard](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_next_test_surface_830.py#L121) | 6 explicit assertions inspected |
| [test_closing_the_window_cancels_pending_work_and_destroys_the_dialog](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_next_test_surface_830.py#L184) | 2 explicit assertions inspected |
| [test_stale_action_is_refused_and_nothing_is_routed](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_next_test_surface_830.py#L287) | 2 explicit assertions inspected |
| [test_saved_values_are_shown_as_stored_and_never_replaced_by_examples](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_prompt_authoring_540.py#L165) | 5 explicit assertions inspected |
| [test_an_unknown_saved_template_is_kept_visible_and_untouched](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_prompt_authoring_540.py#L245) | 8 explicit assertions inspected |
| [test_insert_trigger_words_edits_only_the_current_slot_and_never_saves](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_prompt_authoring_540.py#L324) | 9 explicit assertions inspected |
| [test_the_style_status_never_scans_for_target_changes](https://github.com/destroyer42/StableNew2/blob/75842f7ba04429ac918ccf742d6c7ff001c577b6/tests/gui_v2/test_prompt_authoring_540.py#L603) | 1 explicit assertions inspected |

## Authorities consulted and retained limits

AGENTS/STATUS, CODEX_MAP/relevant generated CODE_MAP entries, architecture v2.6, coding/testing and living Testing/Runtime/PromptPack/GUI/Learning/Profiles/Video authorities; AI_MODEL_SELECTION, AGENT_OPERATING_MODEL and CODEX_WORK_PACKAGE_TEMPLATE; assessment README/playbook v1.2 and current roadmap for sequence context. These outrank old research and the abridged predecessor register. The complete owner register supplies confirmed wording, not current runtime qualification. No external standards/model-card research was needed to create this local-source delivery program.
