"""One-time safe file cleanup performed at plugin startup.

Two responsibilities:
  * wipe leftover temp uploads under ``<plugin_dir>/_uploads/`` (safe because
    cleanup runs before the HTTP server starts -- no jobs are in flight);
  * delete the plugin's *own* generated outputs older than a retention window,
    tracked via a persistent JSON-lines ledger so the user's manual Wan2GP UI
    generations are never touched.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_RETENTION_DAYS = 30


@dataclass
class CleanupConfig:
    clean_uploads: bool = True
    clean_outputs: bool = True
    retention_days: int = _DEFAULT_RETENTION_DAYS
    allowed_roots: list[Path] = field(default_factory=list)

    @classmethod
    def load_or_create(cls, config_path: Path, wan2gp_root: Path) -> "CleanupConfig":
        default_root = (Path(wan2gp_root) / "outputs").resolve()
        raw: dict = {}
        if config_path.exists():
            try:
                parsed = json.loads(config_path.read_text(encoding="utf-8"))
                raw = parsed if isinstance(parsed, dict) else {}
            except (ValueError, OSError) as exc:
                print(f"[Wan2GP REST] cleanup_config.json unreadable ({exc}); using defaults")
        else:
            _write_default_config(config_path)

        roots = [default_root]
        for r in raw.get("output_roots", []) or []:
            try:
                roots.append(Path(r).resolve())
            except (TypeError, ValueError):
                continue

        return cls(
            clean_uploads=_as_bool(raw.get("clean_uploads", True), True),
            clean_outputs=_as_bool(raw.get("clean_outputs", True), True),
            retention_days=_valid_days(raw.get("output_retention_days", _DEFAULT_RETENTION_DAYS)),
            allowed_roots=roots,
        )


def _write_default_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    default = {
        "_comment": "Wan2GP REST startup cleanup. Edit values, restart to apply.",
        "clean_uploads": True,
        "clean_outputs": True,
        "output_retention_days": _DEFAULT_RETENTION_DAYS,
        "output_roots": [],
    }
    config_path.write_text(json.dumps(default, indent=2), encoding="utf-8")


def _as_bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _valid_days(value) -> int:
    # bool is a subclass of int -- reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        if value != _DEFAULT_RETENTION_DAYS:
            print(f"[Wan2GP REST] invalid output_retention_days={value!r}; using {_DEFAULT_RETENTION_DAYS}")
        return _DEFAULT_RETENTION_DAYS
    return value
