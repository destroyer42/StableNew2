# Vendored code

Third-party files copied into the repository unchanged. Do not edit, format or lint them: ruff, black, mypy and the
pre-commit hooks skip this directory, `.gitattributes` keeps the bytes as committed, and a test pins each SHA-256.

## qrcodegen.py

QR Code generator library (Python), Project Nayuki, MIT License (the notice is at the top of the file).

| | |
|---|---|
| Source | `https://raw.githubusercontent.com/nayuki/QR-Code-generator/9a217d443937f60cc56c1458c39a211d7f2d3af5/python/qrcodegen.py` |
| Commit | `9a217d443937f60cc56c1458c39a211d7f2d3af5` |
| Git blob | `f480934353d5aebaf4a09fc67fe68aa7cf89a21a` |
| Size | 68,982 bytes |
| SHA-256 | `d09f22750a8d5adfb1643e64c5cd7071b8f02c1d04858f814ca9a7cc6f1f0b23` |
| Retrieved | 2026-11-28 |
| Used by | `src/utils/qr_code.py` (the pairing dialog's QR, PHONE-CORE PP-1) |

Approved by the owner on 2026-11-28 as this one file. Reviewed when added: standard-library imports only, no file,
network, process or `eval` use. To update it, get the same approval, replace the file whole, and change this table and
the test's pin together.
