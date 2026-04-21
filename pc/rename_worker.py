"""Elevated helper — does the registry rename and writes the result as JSON.

Launched from main app via ShellExecute with 'runas' verb. The main Micky
app itself does NOT need to restart.

Usage: python rename_worker.py <output_json_path>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure our module path is importable when launched from a different CWD
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    out_path = Path(sys.argv[1])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from virtual_mic import rename_cable_to_micky
        ok, msg, log = rename_cable_to_micky()
        payload = {"ok": bool(ok), "msg": msg, "log": log or []}
    except Exception as e:
        payload = {"ok": False, "msg": f"Hata: {e}", "log": []}
    try:
        out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
