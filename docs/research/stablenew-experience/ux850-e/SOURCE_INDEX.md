# Exact source and API index

Evidence cut: **8f76ee6036baec0eaa298bdde9949c197541132b**. Production `src/` tree: **802afeedf0328f705c2fa97c0fda5eb758286dcf**, identical to accepted A code cut `3399f8032182b65bd904f8f27818d927909cd6a3`. Paths below are repository-relative; each pinned link carries the base SHA and verified one-based lines. Git blob IDs permit reuse checks without repeating discovery. A whole-module anchor is navigation, not a claim every branch was audited.

## Production and qualification seams

<a id="e01"></a>
### E01

- [src/image_backends/model_policy.py:140–223](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/image_backends/model_policy.py#L140-L223) — `ModelPolicy`; blob `a1235bb06a0fc55ce3df213860328c0f5a3ad316`.
- [src/image_backends/model_policy.py:365–397](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/image_backends/model_policy.py#L365-L397) — `resolve_model_policy`; blob `a1235bb06a0fc55ce3df213860328c0f5a3ad316`.

<a id="e02"></a>
### E02

- [src/generation_profiles/identity.py:42–67](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/identity.py#L42-L67) — `RegistryShaLookup`; blob `f1c381f9e7954e058c2c2ede18ee676f62124c03`.
- [src/generation_profiles/identity.py:182–219](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/identity.py#L182-L219) — `match_identity`; blob `f1c381f9e7954e058c2c2ede18ee676f62124c03`.

<a id="e03"></a>
### E03

- [src/generation_profiles/application.py:133–267](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/application.py#L133-L267) — `plan_application`; blob `e35ddcde75321363ceeaaf293caa1eef60818e27`.

<a id="e04"></a>
### E04

- [src/generation_profiles/service.py:101–452](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/service.py#L101-L452) — `GenerationProfileService`; blob `dc5598889a56a16fd07c82a139afbf51a81fcef5`.

<a id="e05"></a>
### E05

- [src/generation_profiles/startup.py:76–133](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/startup.py#L76-L133) — `StartupDefaults`; blob `6580e1d2229082edd7182ee14e860516488f4795`.
- [src/generation_profiles/startup.py:43–64](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/startup.py#L43-L64) — `sanitize_stage_settings`; blob `6580e1d2229082edd7182ee14e860516488f4795`.

- [src/controller/generation_profile_controller.py:184–198](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/controller/generation_profile_controller.py#L184-L198) — `on_model_chosen`; blob `9e5622d374f3ab32e2cdc98da0892285569f1ad1`.
- [src/controller/generation_profile_controller.py:205–219](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/controller/generation_profile_controller.py#L205-L219) — `on_profile_selected`; blob `9e5622d374f3ab32e2cdc98da0892285569f1ad1`.

<a id="e06"></a>
### E06

- [src/assets/registry.py:375–392](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/assets/registry.py#L375-L392) — `verified_sha256`; blob `d7f5a0a65080b6970a201c90c1042048ea5964a9`.
- [src/assets/registry.py:418–422](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/assets/registry.py#L418-L422) — `cached_snapshot`; blob `d7f5a0a65080b6970a201c90c1042048ea5964a9`.
- [src/assets/registry.py:575–597](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/assets/registry.py#L575-L597) — `inspect_checkpoint`; blob `d7f5a0a65080b6970a201c90c1042048ea5964a9`.

<a id="e07"></a>
### E07

- [src/prompting/prompt_adaptation.py:613–785](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/prompting/prompt_adaptation.py#L613-L785) — `adapt_structured_prompt`; blob `d3918dff00e1743c9838173a5b4f15e34e791e4c`.
- [src/prompting/prompt_adaptation.py:391–487](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/prompting/prompt_adaptation.py#L391-L487) — `adapt_prompt_for_target`; blob `d3918dff00e1743c9838173a5b4f15e34e791e4c`.

<a id="e08"></a>
### E08

- [src/pipeline/resolution_layer.py:1–684](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/pipeline/resolution_layer.py#L1-L684) — `module / document`; blob `22d6f596ac7140f0be3a1bb9b5f1f42f5e173c41`.

<a id="e09"></a>
### E09

- [src/pipeline/prompt_pack_job_builder.py:213–295](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/pipeline/prompt_pack_job_builder.py#L213-L295) — `build_jobs`; blob `0740ba088c8824ad66c6dcb17753e0184cd8654b`.

<a id="e10"></a>
### E10

- [src/learning/ordinary_snapshot.py:1–82](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/ordinary_snapshot.py#L1-L82) — `module / document`; blob `f6dd388d5de0776fac46f7ca0456b5c4f29c4276`.

<a id="e11"></a>
### E11

- [src/learning/experiment_freeze.py:49–155](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/experiment_freeze.py#L49-L155) — `freeze_prompt_pack_source`; blob `ce03c238a34ba32d45e73c83a96aaff97105763d`.
- [src/learning/experiment_freeze.py:166–208](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/experiment_freeze.py#L166-L208) — `freeze_seed_policy`; blob `ce03c238a34ba32d45e73c83a96aaff97105763d`.
- [src/learning/experiment_freeze.py:237–246](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/experiment_freeze.py#L237-L246) — `seed_vector_matches`; blob `ce03c238a34ba32d45e73c83a96aaff97105763d`.

<a id="e12"></a>
### E12

- [src/learning/execution_controller.py:228–350](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/execution_controller.py#L228-L350) — `reconcile`; blob `e812a32a40fa883d3059ab8a26e8d0d0afb1e688`.
- [src/learning/execution_controller.py:352–433](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/execution_controller.py#L352-L433) — `submit_experiment_jobs`; blob `e812a32a40fa883d3059ab8a26e8d0d0afb1e688`.

<a id="e13"></a>
### E13

- [src/learning/ordinary_njr.py:45–135](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/ordinary_njr.py#L45-L135) — `materialize_njr`; blob `225d5af14737c64533247d16abf7efd53779b6ce`.

<a id="e14"></a>
### E14

- [src/learning/two_axis_grid.py:280–400](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/two_axis_grid.py#L280-L400) — `build_grid_snapshot`; blob `2cced5203d16f32cc560f5ffdb4e17f3808868cd`.
- [src/learning/two_axis_grid.py:628–664](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/two_axis_grid.py#L628-L664) — `rating_classification`; blob `2cced5203d16f32cc560f5ffdb4e17f3808868cd`.

<a id="e15"></a>
### E15

- [src/learning/model_comparison.py:410–514](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/model_comparison.py#L410-L514) — `build_comparison_snapshot`; blob `6a4a4b925317e0e623eb07961269f94515286cfe`.
- [src/learning/model_comparison.py:517–535](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/model_comparison.py#L517-L535) — `verify_arms_admissible`; blob `6a4a4b925317e0e623eb07961269f94515286cfe`.
- [src/learning/model_comparison.py:914–931](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/model_comparison.py#L914-L931) — `rating_classification`; blob `6a4a4b925317e0e623eb07961269f94515286cfe`.

<a id="e16"></a>
### E16

- [src/learning/prompt_model_matrix.py:299–562](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/prompt_model_matrix.py#L299-L562) — `build_matrix_snapshot`; blob `0b17d15e48aead521c85e754d00cd6500893dbc3`.
- [src/learning/prompt_model_matrix.py:797–860](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/prompt_model_matrix.py#L797-L860) — `rating_classification`; blob `0b17d15e48aead521c85e754d00cd6500893dbc3`.
- [src/learning/prompt_model_matrix.py:863–947](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/prompt_model_matrix.py#L863-L947) — `conclusion`; blob `0b17d15e48aead521c85e754d00cd6500893dbc3`.

<a id="e17"></a>
### E17

- [src/learning/setting_evidence.py:90–110](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/setting_evidence.py#L90-L110) — `require_rating_proof`; blob `089377956c16efa87635607f923130934f951ec3`.
- [src/learning/setting_evidence.py:118–124](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/setting_evidence.py#L118-L124) — `screening_supported`; blob `089377956c16efa87635607f923130934f951ec3`.

<a id="e18"></a>
### E18

- [src/learning/qualification_review.py:222–395](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/qualification_review.py#L222-L395) — `project_qualification`; blob `9791b7110e1b5518da6e7b9284d45ee5c06472df`.

<a id="e19"></a>
### E19

- [src/learning/qualification_followup.py:1–144](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/qualification_followup.py#L1-L144) — `module / document`; blob `407a97209f5abf6066d89c63408a2c320066a798`.

<a id="e20"></a>
### E20

- [src/learning/learning_record.py:78–94](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/learning_record.py#L78-L94) — `current_rating_revisions`; blob `a66f8761c1a2a30204600696b567c78a1bb616a0`.
- [src/learning/learning_record.py:60–75](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/learning_record.py#L60-L75) — `rating_revision_key`; blob `a66f8761c1a2a30204600696b567c78a1bb616a0`.
- [src/learning/learning_record.py:23–34](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/learning_record.py#L23-L34) — `evidence_file_lock`; blob `a66f8761c1a2a30204600696b567c78a1bb616a0`.

<a id="e21"></a>
### E21

- [src/learning/preference_evidence.py:93–145](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/preference_evidence.py#L93-L145) — `attribute_ratings`; blob `f3c1194dde19f5878d5ea5fdf0aadce0b7a077b3`.
- [src/learning/preference_evidence.py:152–240](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/preference_evidence.py#L152-L240) — `_summarize`; blob `f3c1194dde19f5878d5ea5fdf0aadce0b7a077b3`.
- [src/learning/preference_evidence.py:243–289](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/preference_evidence.py#L243-L289) — `summarize_preferences`; blob `f3c1194dde19f5878d5ea5fdf0aadce0b7a077b3`.

<a id="e22"></a>
### E22

- [src/learning/profile_publication.py:193–310](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/profile_publication.py#L193-L310) — `_sample`; blob `14297086b270e8f4ed199a3cf661b6c1d9e4d914`.
- [src/learning/profile_publication.py:334–479](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/profile_publication.py#L334-L479) — `evaluate`; blob `14297086b270e8f4ed199a3cf661b6c1d9e4d914`.
- [src/learning/profile_publication.py:481–503](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/profile_publication.py#L481-L503) — `publish`; blob `14297086b270e8f4ed199a3cf661b6c1d9e4d914`.

<a id="e23"></a>
### E23

- [src/learning/recommendation_engine.py:88–100](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/recommendation_engine.py#L88-L100) — `recommendation_confidence`; blob `b72331806d03e795c330244eec42f56f5ae309dd`.
- [src/learning/recommendation_engine.py:680–829](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/recommendation_engine.py#L680-L829) — `_compute_optimal_settings`; blob `b72331806d03e795c330244eec42f56f5ae309dd`.

<a id="e24"></a>
### E24

- [src/generation_profiles/store.py:273–297](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/store.py#L273-L297) — `publish_learning_profile`; blob `f58e61858aff01f6ad886bada2fc3511ef41b89a`.

<a id="e25"></a>
### E25

- [src/learning/evidence_autopilot.py:219–381](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/evidence_autopilot.py#L219-L381) — `plan`; blob `45eebb245141c18efb3dbd523fe3cf16e107b953`.
- [src/learning/evidence_autopilot.py:384–411](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/evidence_autopilot.py#L384-L411) — `validate_current`; blob `45eebb245141c18efb3dbd523fe3cf16e107b953`.

<a id="e26"></a>
### E26

- [src/learning/evidence_proposals.py:47–152](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/evidence_proposals.py#L47-L152) — `evidence_gaps`; blob `c6a160cc3f3ed4e2a2a2c933ee5c5aa471fe5620`.
- [src/learning/evidence_proposals.py:317–333](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/evidence_proposals.py#L317-L333) — `save_proposal`; blob `c6a160cc3f3ed4e2a2a2c933ee5c5aa471fe5620`.

<a id="e27"></a>
### E27

- [src/learning/evidence_intelligence.py:88–168](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/evidence_intelligence.py#L88-L168) — `assess`; blob `85da737d040003ba6a488d1169f16c0beaa54259`.

<a id="e28"></a>
### E28

- [src/learning/ai_evidence_summary.py:75–122](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/ai_evidence_summary.py#L75-L122) — `build_ai_summary`; blob `71653bc1eb78433f329259c7070523d680c5ca99`.
- [src/learning/ai_evidence_summary.py:130–140](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/ai_evidence_summary.py#L130-L140) — `resolve_ai_candidate`; blob `71653bc1eb78433f329259c7070523d680c5ca99`.
- [src/learning/ai_evidence_summary.py:143–166](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/ai_evidence_summary.py#L143-L166) — `validate_ai_summary`; blob `71653bc1eb78433f329259c7070523d680c5ca99`.

- [src/learning/next_actions.py:413–425](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/next_actions.py#L413-L425) — `_sort_key`; blob `7fc4c20e2fb4c37db79b26e86a5fb7ffd90543b7`.
- [src/learning/next_actions.py:428–465](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/next_actions.py#L428-L465) — `build_actions`; blob `7fc4c20e2fb4c37db79b26e86a5fb7ffd90543b7`.

<a id="e29"></a>
### E29

- [src/learning/intelligence_sources.py:1–270](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/intelligence_sources.py#L1-L270) — `module / document`; blob `b354971cb0d719cd671a48a714c28e719f47a0f6`.

<a id="e30"></a>
### E30

- [src/ai_assist/contracts.py:1–211](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/ai_assist/contracts.py#L1-L211) — `module / document`; blob `be389420b49df4e20e31a3847274e0e04c15d2ae`.

- [src/ai_assist/validators.py:104–192](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/ai_assist/validators.py#L104-L192) — `validate_output`; blob `f42de3327b01eef264c04a58440b2c35f754d8e4`.

<a id="e31"></a>
### E31

- [src/ai_assist/service.py:57–66](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/ai_assist/service.py#L57-L66) — `ServicePolicy`; blob `5633535759e4ef69af08143d366a8d40a7789bb6`.
- [src/ai_assist/service.py:309–355](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/ai_assist/service.py#L309-L355) — `_admit`; blob `5633535759e4ef69af08143d366a8d40a7789bb6`.

<a id="e32"></a>
### E32

- [src/controller/app_controller_services/ai_assist_integration.py:33–51](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/controller/app_controller_services/ai_assist_integration.py#L33-L51) — `QueueGenerationActivity`; blob `59785978a50e19e1719fec215e0e1608d0c83da0`.
- [src/controller/app_controller_services/ai_assist_integration.py:54–193](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/controller/app_controller_services/ai_assist_integration.py#L54-L193) — `AiAssistIntegration`; blob `59785978a50e19e1719fec215e0e1608d0c83da0`.

<a id="e33"></a>
### E33

- [src/ai_assist/manifests.py:430–494](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/ai_assist/manifests.py#L430-L494) — `verify_installation`; blob `07abf7dff43c1c20cfd2cf4cb4425e0e1cf8b73f`.

- [src/ai_assist/status.py:39–103](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/ai_assist/status.py#L39-L103) — `read_status`; blob `1f3bf1b6c7e8412e1cef0d6390cc3df7875a51a9`.

<a id="e34"></a>
### E34

- [src/gui/prompt_ai_suggestions.py:79–152](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/gui/prompt_ai_suggestions.py#L79-L152) — `_context`; blob `b9aa3b88cdd7fcb91095ecdd7bbfb730eba29661`.
- [src/gui/prompt_ai_suggestions.py:333–373](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/gui/prompt_ai_suggestions.py#L333-L373) — `accept`; blob `b9aa3b88cdd7fcb91095ecdd7bbfb730eba29661`.

<a id="e35"></a>
### E35

- [config/managed_ai_runtime.json:1–5](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/config/managed_ai_runtime.json#L1-L5) — `module / document`; blob `8d1c5eec4c5092ded3a2ee15731481e964ff8b7f`.

- [config/ai_model_registry.json:1–106](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/config/ai_model_registry.json#L1-L106) — `module / document`; blob `217605cf23057ad0f572fc5f265c2845353d14c8`.

<a id="e36"></a>
### E36

- [src/review/assist/providers.py:1–349](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/review/assist/providers.py#L1-L349) — `module / document`; blob `308c7e0ae49d42397746afa8699fe6bf8cd2dc50`.

<a id="e37"></a>
### E37

- [src/review/assist/session.py:1–317](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/review/assist/session.py#L1-L317) — `module / document`; blob `48aaae9296d0745a46eeb2db46893c799653988b`.

<a id="e38"></a>
### E38

- [src/video/video_eval_metrics.py:34–60](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/video/video_eval_metrics.py#L34-L60) — `ClipMetrics`; blob `6dfa6f529707d36a5cb6fbb7c01b102fa004addd`.
- [src/video/video_eval_metrics.py:153–173](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/video/video_eval_metrics.py#L153-L173) — `measure_clip`; blob `6dfa6f529707d36a5cb6fbb7c01b102fa004addd`.

<a id="e39"></a>
### E39

- [src/learning/video_quality_review.py:413–571](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/video_quality_review.py#L413-L571) — `VideoReviewStore`; blob `695b70d4a135676a105a4ea7d968059f661b195f`.

<a id="e40"></a>
### E40

- [src/learning/dataset_builder.py:1–65](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/dataset_builder.py#L1-L65) — `module / document`; blob `27a3f7c165bc34807eb4dcd301d1e99df753f262`.

<a id="e41"></a>
### E41

- [src/learning/qualification_batch.py:186–293](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/qualification_batch.py#L186-L293) — `prepare`; blob `1c469672b51cd2d441a6f41c8908bdee9dfbafff`.
- [src/learning/qualification_batch.py:295–415](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/qualification_batch.py#L295-L415) — `admit`; blob `1c469672b51cd2d441a6f41c8908bdee9dfbafff`.

<a id="e42"></a>
### E42

- [src/learning/resource_access.py:1–37](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/resource_access.py#L1-L37) — `module / document`; blob `ae010e099f37f0887e3c4fb2b08880fb173dc182`.

- [src/learning/design_estimate.py:1–114](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/design_estimate.py#L1-L114) — `module / document`; blob `7a1ce2121faf4a28b3fe3988b951ef57ea6e5530`.

<a id="e43"></a>
### E43

- [src/gui/controllers/learning_profile_publication.py:140–189](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/gui/controllers/learning_profile_publication.py#L140-L189) — `publish`; blob `9b7c03a4f6e55352e7fb593ea730ebec38f96d3e`.

- [src/gui/controllers/learning_controller.py:2885–2961](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/gui/controllers/learning_controller.py#L2885-L2961) — `apply_recommendations_to_pipeline`; blob `217354054d4b23b5d090cd5073094e438a2c7b2e`.

<a id="e44"></a>
### E44

- [src/generation_profiles/evidence_catalog.py:83–122](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/evidence_catalog.py#L83-L122) — `Claim`; blob `29d75014dfc13e73d8174da9cda5a174bcd77648`.
- [src/generation_profiles/evidence_catalog.py:223–270](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/evidence_catalog.py#L223-L270) — `coverage`; blob `29d75014dfc13e73d8174da9cda5a174bcd77648`.
- [src/generation_profiles/evidence_catalog.py:343–345](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/evidence_catalog.py#L343-L345) — `select_operator_catalog`; blob `29d75014dfc13e73d8174da9cda5a174bcd77648`.

<a id="e45"></a>
### E45

- [src/gui/views/model_evidence_window.py:868–895](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/gui/views/model_evidence_window.py#L868-L895) — `_import`; blob `2b27c9f03c50d2d8b1d77a1b06a6ce6eb1b830a0`.

<a id="e46"></a>
### E46

- [src/generation_profiles/evidence_refresh.py:1–156](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/generation_profiles/evidence_refresh.py#L1-L156) — `module / document`; blob `b438232ac6becf08af5f389279362eada896bc60`.

<a id="e47"></a>
### E47

- [src/learning/output_scanner.py:1–416](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/output_scanner.py#L1-L416) — `module / document`; blob `529964c64ecef21d3d1936737f997e1d65fc610d`.

- [src/learning/discovered_grouping.py:1–214](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/src/learning/discovered_grouping.py#L1-L214) — `module / document`; blob `c1816c2bc3946a211165bf076404cc03fbffe7c7`.

<a id="e48"></a>
### E48

- [tools/qualification/system840/statuses.py:1–102](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tools/qualification/system840/statuses.py#L1-L102) — `module / document`; blob `90711b709be3fa21120e96aa158b001d6c6fe0e0`.

- [tools/qualification/ai111/lfm3_contract.py:1–1089](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tools/qualification/ai111/lfm3_contract.py#L1-L1089) — `module / document`; blob `770914b57a8d38d0d1bd04294caf35b1629b3299`.

## Inspected negative test contracts

T01–T23 were extracted with Python AST to an external manifest and their assertions/counterexamples inspected; **none executed**. These are existing entrypoints for a later implementation package, not fresh passing results. Same-author challenge and limitations: [CHALLENGE.md](CHALLENGE.md).

- T01 [tests/learning_v2/test_learning_intelligence_830.py:231](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_intelligence_830.py#L231-L242) — `test_incompatible_models_and_unmatched_prompts_are_never_pooled`.
- T02 [tests/learning_v2/test_learning_intelligence_830.py:253](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_intelligence_830.py#L253-L259) — `test_competing_experiments_are_reported_as_competing`.
- T03 [tests/learning_v2/test_learning_intelligence_830.py:445](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_intelligence_830.py#L445-L459) — `test_ai_answer_must_be_an_issued_current_executable_candidate`.
- T04 [tests/learning_v2/test_learning_intelligence_830.py:401](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_intelligence_830.py#L401-L425) — `test_ai_summary_is_bounded_opaque_and_leaks_nothing`.
- T05 [tests/learning_v2/test_learning_intelligence_830.py:513](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_intelligence_830.py#L513-L530) — `test_assessment_is_read_only`.
- T06 [tests/learning_v2/test_learning_intelligence_830.py:309](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_intelligence_830.py#L309-L350) — `test_changed_evidence_invalidates_dependent_action_identifiers`.
- T07 [tests/learning_v2/test_profile_publication_660.py:120](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_profile_publication_660.py#L120-L122) — `test_latest_rating_does_not_inflate_counts`.
- T08 [tests/learning_v2/test_profile_publication_660.py:295](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_profile_publication_660.py#L295-L304) — `test_steps_does_not_launder_cfg_or_untested_baseline`.
- T09 [tests/learning_v2/test_profile_publication_660.py:409](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_profile_publication_660.py#L409-L424) — `test_failed_atomic_publish_preserves_prior_revision`.
- T10 [tests/learning_v2/test_profile_publication_660.py:211](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_profile_publication_660.py#L211-L239) — `test_identity_context_and_value_conflicts`.
- T11 [tests/learning_v2/test_qualification_review_820.py:145](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_qualification_review_820.py#L145-L170) — `test_invalid_proof_is_excluded_and_never_supports_inference`.
- T12 [tests/learning_v2/test_qualification_review_820.py:262](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_qualification_review_820.py#L262-L270) — `test_backend_restart_with_same_profile_is_not_controlled`.
- T13 [tests/learning_v2/test_qualification_review_820.py:113](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_qualification_review_820.py#L113-L120) — `test_six_pairs_use_observed_identity_and_pass_only_followup_screen`.
- T14 [tests/integration/test_qualification_batch_810.py:197](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/integration/test_qualification_batch_810.py#L197-L235) — `test_partial_or_ambiguous_submission_stops_without_retry`.
- T15 [tests/integration/test_qualification_batch_810.py:452](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/integration/test_qualification_batch_810.py#L452-L474) — `test_checkpoint_failure_preserves_writeahead_ids_and_stops`.
- T16 [tests/ai_assist/test_production_integration_112.py:140](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/ai_assist/test_production_integration_112.py#L140-L150) — `test_unqualified_candidate_cannot_run_in_production`.
- T17 [tests/ai_assist/test_production_integration_112.py:66](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/ai_assist/test_production_integration_112.py#L66-L73) — `test_unreadable_authority_fails_closed_without_exception_content`.
- T18 [tests/ai_assist/test_contracts_validators.py:219](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/ai_assist/test_contracts_validators.py#L219-L230) — `test_injected_instructions_in_the_authored_text_cannot_widen_what_is_accepted`.
- T19 [tests/ai_assist/test_contracts_validators.py:178](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/ai_assist/test_contracts_validators.py#L178-L186) — `test_closed_list_choices_cannot_name_anything_outside_the_list`.
- T20 [tests/generation_profiles/test_model_evidence_760.py:204](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/generation_profiles/test_model_evidence_760.py#L204-L211) — `test_hypotheses_never_become_executable_defaults`.
- T21 [tests/image_backends/test_prompt_adaptation_140.py:68](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/image_backends/test_prompt_adaptation_140.py#L68-L78) — `test_only_definitive_incompatibility_deletes_and_uncertainty_is_preserved_but_marked_incomplete`.
- T22 [tests/learning_v2/test_learning_evidence_consistency.py:95](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_evidence_consistency.py#L95-L105) — `test_an_unusable_latest_revision_removes_the_sample`.
- T23 [tests/learning_v2/test_learning_evidence_consistency.py:140](https://github.com/destroyer42/StableNew2/blob/8f76ee6036baec0eaa298bdde9949c197541132b/tests/learning_v2/test_learning_evidence_consistency.py#L140-L147) — `test_the_best_rated_value_wins_over_a_more_numerous_poorly_rated_one`.

## Documentary authorities and inherited evidence

- `AGENTS.md`, `STATUS.md`, `docs/CODEX_MAP.md` and relevant generated `docs/CODE_MAP.md` sections; `docs/ARCHITECTURE_v2.6.md` §§2–5, 10; `docs/StableNew_Coding_and_Testing_v2.6.md`; `docs/Subsystems/Testing/TESTING_AND_CI.md` docs-only policy.
- `docs/AI_MODEL_SELECTION.md`, `docs/CODEX_WORK_PACKAGE_TEMPLATE.md`, `docs/AGENT_OPERATING_MODEL.md`, `.github/pull_request_template.md`; `docs/assessments/README.md` and playbook §§12–14: Focused end-to-end controls, distinct-method challenge, six evidence dimensions.
- Living subsystem authorities: `docs/Subsystems/Learning/LEARNING.md` §§3.1–3.16; `docs/Subsystems/Image/MODEL_PROFILES.md` §§9, 17; `docs/Subsystems/PromptPacks/PROMPTPACKS_AND_PROMPTING.md`; `docs/Subsystems/AiAssist/AI_ASSIST.md` §§1–12.
- Existing qualification authority: `docs/runbooks/qual_system_840.md` §§1–3; `docs/runbooks/ai_qualification_etw_capture.md`; `tools/qualification/system840/ledger.v1.json` remains untouched. Historical `docs/Subsystems/AiAssist/PR-AI-115_LFM3_Qualification_Contract.md` is read with later living/source precedence: its old harness-blocker list is not current proof those repairs are absent.
- Accepted [A](../ux850-a/README.md), [A addendum](../ux850-a/ADDENDUM_SOURCE_FINDINGS.md), [B](../ux850-b/README.md), [C](../ux850-c/README.md), [D](../ux850-d/README.md), complete [owner decisions](../ux-850-r1/OWNER_DECISIONS.md). Exact integration identities and reuse limits appear in [EVIDENCE_AND_VALIDATION.md](EVIDENCE_AND_VALIDATION.md).

No external model/backend performance source was needed: E asserts current local contracts and conditional methodology only. Model names, sizes, provenance and runtime floors in existing manifests/contracts are documentary identities, not independently refreshed upstream specifications or local resource evidence. No external benchmark is used to infer quality or qualification.
