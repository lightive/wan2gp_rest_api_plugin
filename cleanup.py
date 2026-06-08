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
    def load_or_create(cls, config_path: Path, wan2gp_root: Path) -> CleanupConfig:
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


class Ledger:
    """Append-only JSON-lines record of files the plugin generated."""

    def __init__(self, ledger_path: Path) -> None:
        self._path = Path(ledger_path)
        self._lock = threading.Lock()

    def record(self, paths: list[str]) -> None:
        lines = [
            json.dumps({"path": p, "ts": datetime.now(timezone.utc).isoformat()})
            for p in paths
            if isinstance(p, str) and p
        ]
        if not lines:
            return
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")

    def prune(self, retention_days: int, allowed_roots: list[Path]) -> tuple[int, int]:
        with self._lock:
            if not self._path.exists():
                return (0, 0)
            entries = self._read_entries()  # deduped, latest ts wins
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            survivors: list[dict] = []
            deleted = 0
            freed = 0
            for entry in entries:
                ts = _parse_ts(entry.get("ts"))
                path_str = entry.get("path")
                if ts is None or not isinstance(path_str, str):
                    continue  # unusable entry -> drop
                if ts >= cutoff:
                    survivors.append(entry)
                    continue
                # --- expired: guarded deletion ---
                target = _resolve(path_str)
                if target is None:
                    continue  # bad path -> drop
                if not _within_roots(target, allowed_roots):
                    survivors.append(entry)  # outside allowed root -> never delete
                    continue
                # _resolve() already followed symlinks, so the containment
                # check above is the real guard; only the dir check remains.
                if target.is_dir():
                    survivors.append(entry)  # never delete a directory as a file
                    continue
                try:
                    size = target.stat().st_size
                except FileNotFoundError:
                    continue  # already gone -> drop entry
                except OSError:
                    survivors.append(entry)  # can't stat -> keep record
                    continue
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    survivors.append(entry)  # deletion failed -> keep record
                    continue
                deleted += 1
                freed += size
            self._atomic_rewrite(survivors)
            return (deleted, freed)

    def _read_entries(self) -> list[dict]:
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return []
        latest: dict[str, dict] = {}
        order: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # skip malformed line
            if not isinstance(obj, dict) or not isinstance(obj.get("path"), str):
                continue
            key = _path_key(obj["path"])
            if key not in latest:
                order.append(key)
            else:
                old = _parse_ts(latest[key].get("ts"))
                new = _parse_ts(obj.get("ts"))
                if old is not None and new is not None and new < old:
                    continue  # keep the newer record
            latest[key] = obj
        return [latest[k] for k in order]

    def _atomic_rewrite(self, entries: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry) + "\n")
        os.replace(tmp, self._path)


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _resolve(path_str: str) -> Path | None:
    if not isinstance(path_str, str) or not path_str:
        return None
    try:
        return Path(path_str).resolve()
    except (OSError, ValueError):
        return None


def _within_roots(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            if path.is_relative_to(root):
                return True
        except (OSError, ValueError):
            continue
    return False


def clean_uploads(upload_base: Path) -> int:
    """Remove every child of the uploads dir; return count removed.

    Per-child handling never recurses through a symlink/junction/reparse point,
    so deletion cannot escape the upload base.
    """
    upload_base = Path(upload_base)
    if not upload_base.exists():
        return 0
    base = upload_base.resolve()
    removed = 0
    for child in list(upload_base.iterdir()):
        try:
            real_parent = Path(os.path.realpath(child)).parent
            if child.is_symlink() or real_parent != base:
                if not _unlink_or_rmdir(child):  # link/junction -> drop entry only
                    continue  # both removal attempts failed -> do not count
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _unlink_or_rmdir(link: Path) -> bool:
    """Remove a symlink/junction entry without touching its target.

    Returns True if the entry was removed, False if both attempts failed.
    """
    try:
        link.unlink()       # file symlink
        return True
    except (IsADirectoryError, PermissionError, OSError):
        try:
            os.rmdir(link)  # directory symlink / Windows junction
            return True
        except OSError:
            return False


def run_startup_cleanup(upload_base: Path, ledger: Ledger, config: CleanupConfig) -> None:
    """Best-effort one-time cleanup. Never raises -- must not block startup."""
    temp_removed = 0
    out_deleted = 0
    out_freed = 0
    if config.clean_uploads:
        try:
            temp_removed = clean_uploads(upload_base)
        except Exception as exc:
            print(f"[Wan2GP REST] upload cleanup failed: {exc}")
    if config.clean_outputs:
        try:
            out_deleted, out_freed = ledger.prune(config.retention_days, config.allowed_roots)
        except Exception as exc:
            print(f"[Wan2GP REST] output cleanup failed: {exc}")
    mb = out_freed / (1024 * 1024)
    print(f"[Wan2GP REST] cleanup: temp {temp_removed} items, "
          f"outputs {out_deleted} files ({mb:.1f} MB freed)")
