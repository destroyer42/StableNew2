# Visual candidate staging (PR-AI-VL-220, decision D15)

Operator-only. The application never downloads, imports or runs a visual candidate; nothing here touches the AI Assist root
(`%LOCALAPPDATA%\StableNew\ManagedAi`), the text model registry, the selector or Preview. Run Python with the repository
virtual environment. Every command is read-only except `curl` (writes the two files you name) and `import` (writes the
evaluation root you name).

## 1. Staging (download, by hand)

The two files are pinned to one Hugging Face commit; nothing floats. Print the exact anonymous commands:

```bash
python -m tools.qualification.vl220 commands --dest D:/StableNew-Assets/offline-ai/downloads/lfm3-vl-2b
```

Run the two printed `curl` lines yourself (no token, no account; the repository is public and not gated). Together the files
are 1.48 GB (the ceiling is 6 GiB). Keep the staging folder outside any Git working tree. Nothing is executed or loaded.

## 2. Verify

```bash
python -m tools.qualification.vl220 verify-staging --staging D:/StableNew-Assets/offline-ai/downloads/lfm3-vl-2b
```

It hashes both files against the pins, reads each GGUF header as plain bytes (architecture, projector type, quantization,
embedding length against projection dimension) and checks that the runtime build `b11960-cpu` is pinned and carries
`llama-mtmd-cli.exe`. Without your license acknowledgement the verdict is "not admitted" with `license_acknowledgement_missing`;
that is expected until step 3. Exit code 0 means admitted.

## 3. License acknowledgement (your act)

The LFM Open License v1.0 text pinned here has SHA-256 `30adf9d6478191fb87f2424f63ba0728598335aaf99cd2848ef17e8e545fe94b`.
It has the same terms as the text you acknowledged for LFM3-1.7B (AI-QUAL-115, `4d28ca14...`) but different bytes (whitespace),
so that acknowledgement does not name it. Read the text (section 5 limits commercial use by an entity above USD 10,000,000
annual revenue) at the `text_source_url` in `config/ai_visual_candidates.json`, then, if you accept, copy
`license_acknowledgement.TEMPLATE.json` (in the staging folder) to `license_acknowledgement.json`, set `owner_acknowledged` to
`true` and fill `owner_statement` in your words. StableNew never writes this record.

## 4. Import into an evaluation root (held)

```bash
python -m tools.qualification.vl220 import --staging <staging dir> --evaluation-root <new dir outside Git and outside ManagedAi> --acknowledgement <license_acknowledgement.json>
```

It re-verifies everything, copies both files while re-hashing (a cancelled or failed copy leaves nothing), and never
overwrites. It refuses the AI Assist root and any Git working tree. **Do not run it yet:** a visual evaluation cannot run until
you approve the image invocation contract (`docs/Subsystems/AiAssist/PR-AI-VL-220_Image_Invocation_Contract.md`), so an import
has no use today. It is here so the workflow is explicit and reviewable.

## 5. What this does not do

No run, no GPU, no firewall rule, no attestation, no change to `FORBIDDEN_FLAGS` or any registry. Running the evaluation is a
separate owner decision (`PR-AI-VL-220_Visual_Evaluation_Contract.md` section 7).
