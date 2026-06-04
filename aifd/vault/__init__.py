"""aifd vault — data sovereignty operations on AI history.

v0.4 introduced two commands:
- `aifd vault scan` — find PII / secrets across all provider jsonl
- `aifd vault cost`  — estimate token use and USD spend

Module layout:
- prices.py    canonical model price table (per 1M tokens, USD)
- cost.py      token aggregation + cost calculation
- scan.py      detector patterns + Shannon entropy + scan walker

Future (deferred to v0.5+ in TODOS.md):
- export       full backup archive
- sync         multi-machine merge
- redact       selective deletion
- encrypt      local-only encrypted vault
"""
