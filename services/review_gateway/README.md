# StableNew phone review gateway

A small self-hosted service that lets a paired phone triage StableNew outputs (Keep, Delete, Favorite, reason tags)
over Tailscale. It is a cache and outbox, never an authority, and it never imports StableNew's `src/` (RG-100, RG-110).

- Deploy, pair, revoke, back up: [`docs/runbooks/review_gateway.md`](../../docs/runbooks/review_gateway.md)
- Behavior and sync HTTP routes: [`docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md`](../../docs/Subsystems/ReviewGateway/REVIEW_GATEWAY.md)
- Install in the Debian container: `bash services/review_gateway/install.sh` as root
- Tests, from the repository root: `python -m pytest tests/review_gateway_service`

Two listeners in one process: the phone app on `127.0.0.1:8443` (published only by `tailscale serve`) and the sync API
on the container's LAN address `:9443` (TLS with a certificate the PC pins, then `Authorization: Bearer` with the contents
of the 0600 secret file).

## Dependencies

`requirements.txt` is the hash-pinned lock (`pip install --require-hashes`). After changing `requirements.in`:

```bash
uv pip compile requirements.in --universal --python-version 3.11 --generate-hashes -o requirements.txt
```

and update the matching pins in the repository's `requirements-dev.txt` (a test compares them).

## Local trial

Write a settings file with `data_dir`, `media_dir`, `secret_file` and `sync_host = "127.0.0.1"`, then from this folder:

```bash
python -m review_gateway --config trial.toml init-secret
python -m review_gateway --config trial.toml serve
```

Admin commands: `devices`, `revoke <id>`, `status`, `purge`, `check-config`.
