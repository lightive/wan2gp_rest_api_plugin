# Startup File Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-time, safe file-cleanup pass at plugin startup that wipes leftover `_uploads/` temp files and deletes the plugin's own age-expired Wan2GP outputs (tracked via a ledger), never touching the user's manual UI generations.

**Architecture:** A new self-contained `cleanup.py` module holds a `CleanupConfig` (auto-generated JSON, Notepad-editable), a JSON-lines `Ledger` of generated files, an `clean_uploads` purge, and a best-effort `run_startup_cleanup` orchestrator. It runs in `plugin.py` `post_ui_setup` **before** the uvicorn server starts (so no jobs are in flight). `callbacks.py` records generated files to the ledger **only on successful** completion. Output deletion is ledger-scoped and root-contained, so manual UI work and pre-feature outputs are never deleted.

**Tech Stack:** Python 3.10+ (stdlib only: `json`, `os`, `shutil`, `threading`, `dataclasses`, `datetime`, `pathlib`), pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-startup-file-cleanup-design.md`

---

## File Structure

- **Create** `cleanup.py` — config, ledger, upload purge, orchestrator. Stdlib-only so it imports both as a package module (`.cleanup`) and standalone (`cleanup`) for tests.
- **Create** `tests/test_cleanup.py` — unit tests for every behavior.
- **Modify** `callbacks.py` — `JobCallbackAdapter` takes a `ledger`; records on success only.
- **Modify** `plugin.py` — build `Ledger` + `CleanupConfig`, run cleanup before `start_server`.
- **Modify** `.gitignore` — ignore `_state/` and `cleanup_config.json`.
- **Modify** `README.md` — document the cleanup feature and config file.

Tests import modules top-level (e.g. `from cleanup import ...`), matching the existing `tests/test_uploads.py` style (`from uploads import UploadManager`).

---

## Task 1: CleanupConfig (load / auto-create / validate)

**Files:**
- Create: `cleanup.py`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cleanup import CleanupConfig


def test_config_created_with_defaults_when_missing(tmp_path: Path):
    cfg_path = tmp_path / "cleanup_config.json"
    root = tmp_path / "wan2gp"
    cfg = CleanupConfig.load_or_create(cfg_path, root)

    assert cfg_path.exists()  # auto-created
    assert cfg.clean_uploads is True
    assert cfg.clean_outputs is True
    assert cfg.retention_days == 30
    assert (root / "outputs").resolve() in cfg.allowed_roots


def test_config_reads_values(tmp_path: Path):
    cfg_path = tmp_path / "cleanup_config.json"
    cfg_path.write_text(json.dumps({
        "clean_uploads": False,
        "clean_outputs": True,
        "output_retention_days": 7,
        "output_roots": [str(tmp_path / "extra")],
    }))
    cfg = CleanupConfig.load_or_create(cfg_path, tmp_path / "wan2gp")
    assert cfg.clean_uploads is False
    assert cfg.retention_days == 7
    assert (tmp_path / "extra").resolve() in cfg.allowed_roots
    assert (tmp_path / "wan2gp" / "outputs").resolve() in cfg.allowed_roots


def test_config_malformed_json_uses_defaults_and_keeps_file(tmp_path: Path):
    cfg_path = tmp_path / "cleanup_config.json"
    cfg_path.write_text("{ this is not json")
    cfg = CleanupConfig.load_or_create(cfg_path, tmp_path / "wan2gp")
    assert cfg.clean_uploads is True
    assert cfg.retention_days == 30
    assert cfg_path.read_text() == "{ this is not json"  # not overwritten


@pytest.mark.parametrize("bad", [-1, 0, 1.5, "30", None, True, False])
def test_invalid_retention_days_falls_back_to_30(tmp_path: Path, bad):
    cfg_path = tmp_path / "cleanup_config.json"
    cfg_path.write_text(json.dumps({"output_retention_days": bad}))
    cfg = CleanupConfig.load_or_create(cfg_path, tmp_path / "wan2gp")
    assert cfg.retention_days == 30


def test_garbage_toggle_falls_back_to_default(tmp_path: Path):
    cfg_path = tmp_path / "cleanup_config.json"
    cfg_path.write_text(json.dumps({"clean_outputs": "yes"}))
    cfg = CleanupConfig.load_or_create(cfg_path, tmp_path / "wan2gp")
    assert cfg.clean_outputs is True  # non-bool ignored -> default True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'cleanup'`

- [ ] **Step 3: Write minimal implementation**

```python
# cleanup.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup.py -q`
Expected: PASS (all Task 1 tests)

- [ ] **Step 5: Commit**

```bash
git add cleanup.py tests/test_cleanup.py
git commit -m "feat: add CleanupConfig with auto-create and validation"
```

---

## Task 2: Ledger.record (append generated paths)

**Files:**
- Modify: `cleanup.py`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py (append)
from cleanup import Ledger


def _ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "_state" / "generated_ledger.jsonl")


def test_record_appends_one_line_per_path(tmp_path: Path):
    lg = _ledger(tmp_path)
    lg.record(["/out/a.png", "/out/b.png"])
    lines = (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["path"] == "/out/a.png"
    assert "ts" in rec


def test_record_empty_list_is_noop(tmp_path: Path):
    lg = _ledger(tmp_path)
    lg.record([])
    assert not (tmp_path / "_state" / "generated_ledger.jsonl").exists()


def test_record_skips_non_string_and_empty(tmp_path: Path):
    lg = _ledger(tmp_path)
    lg.record(["", None, 5, "/out/ok.png"])  # type: ignore[list-item]
    lines = (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["path"] == "/out/ok.png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup.py -q -k record`
Expected: FAIL — `ImportError: cannot import name 'Ledger'`

- [ ] **Step 3: Write minimal implementation**

```python
# cleanup.py (append)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup.py -q -k record`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cleanup.py tests/test_cleanup.py
git commit -m "feat: add Ledger.record for generated files"
```

---

## Task 3: Ledger.prune — age expiry, missing-file drop, atomic rewrite

**Files:**
- Modify: `cleanup.py`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py (append)
def _write_ledger(tmp_path: Path, entries: list[dict]) -> Ledger:
    p = tmp_path / "_state" / "generated_ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return Ledger(p)


def _old_ts(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_prune_deletes_expired_and_keeps_recent(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    old_file = outputs / "old.png"
    old_file.write_bytes(b"x" * 100)
    new_file = outputs / "new.png"
    new_file.write_bytes(b"y" * 50)

    lg = _write_ledger(tmp_path, [
        {"path": str(old_file), "ts": _old_ts(40)},
        {"path": str(new_file), "ts": _old_ts(1)},
    ])
    deleted, freed = lg.prune(30, [outputs.resolve()])

    assert deleted == 1
    assert freed == 100
    assert not old_file.exists()
    assert new_file.exists()
    # ledger compacted: only the surviving (recent) entry remains
    remaining = [json.loads(x) for x in (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines() if x.strip()]
    assert len(remaining) == 1
    assert remaining[0]["path"] == str(new_file)


def test_prune_drops_entry_for_missing_file(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    lg = _write_ledger(tmp_path, [
        {"path": str(outputs / "gone.png"), "ts": _old_ts(40)},
    ])
    deleted, freed = lg.prune(30, [outputs.resolve()])
    assert deleted == 0
    assert freed == 0
    remaining = [x for x in (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines() if x.strip()]
    assert remaining == []  # gone file -> entry dropped


def test_prune_missing_ledger_returns_zero(tmp_path: Path):
    lg = Ledger(tmp_path / "_state" / "nope.jsonl")
    assert lg.prune(30, [tmp_path]) == (0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup.py -q -k prune`
Expected: FAIL — `AttributeError: 'Ledger' object has no attribute 'prune'`

- [ ] **Step 3: Write minimal implementation**

```python
# cleanup.py -- add these methods to the Ledger class
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
                if target.is_symlink() or target.is_dir():
                    survivors.append(entry)  # never delete a dir/symlink as a file
                    continue
                if not target.exists():
                    continue  # already gone -> drop entry
                try:
                    size = target.stat().st_size
                    target.unlink()
                    deleted += 1
                    freed += size
                except OSError:
                    survivors.append(entry)  # deletion failed -> keep record
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


# cleanup.py -- module-level helpers (add below the Ledger class)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup.py -q -k prune`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cleanup.py tests/test_cleanup.py
git commit -m "feat: add Ledger.prune with age expiry and atomic rewrite"
```

---

## Task 4: Ledger.prune — safety (containment, dir/symlink, dedup, malformed)

**Files:**
- Modify: `tests/test_cleanup.py` (no implementation change — these verify Task 3 safety code)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py (append)
def test_prune_skips_path_outside_allowed_root(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    outsider = tmp_path / "important.png"  # NOT under outputs/
    outsider.write_bytes(b"keep me")
    lg = _write_ledger(tmp_path, [{"path": str(outsider), "ts": _old_ts(99)}])

    deleted, _ = lg.prune(30, [outputs.resolve()])
    assert deleted == 0
    assert outsider.exists()  # never deleted
    remaining = [x for x in (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines() if x.strip()]
    assert len(remaining) == 1  # retained, not dropped


def test_prune_does_not_delete_directory(tmp_path: Path):
    outputs = tmp_path / "outputs"
    a_dir = outputs / "subdir"
    a_dir.mkdir(parents=True)
    lg = _write_ledger(tmp_path, [{"path": str(a_dir), "ts": _old_ts(99)}])
    deleted, _ = lg.prune(30, [outputs.resolve()])
    assert deleted == 0
    assert a_dir.exists()


def test_prune_dedup_latest_wins(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    f = outputs / "reused.png"
    f.write_bytes(b"new content")
    # Older record is expired, newer record for the SAME path is fresh.
    lg = _write_ledger(tmp_path, [
        {"path": str(f), "ts": _old_ts(99)},
        {"path": str(f), "ts": _old_ts(1)},
    ])
    deleted, _ = lg.prune(30, [outputs.resolve()])
    assert deleted == 0  # latest record wins -> not expired -> file survives
    assert f.exists()


def test_prune_skips_malformed_lines(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    good = outputs / "good.png"
    good.write_bytes(b"z" * 10)
    p = tmp_path / "_state" / "generated_ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "not json at all\n"
        + json.dumps({"path": str(good), "ts": _old_ts(40)}) + "\n"
        + "{ broken\n"
    )
    lg = Ledger(p)
    deleted, freed = lg.prune(30, [outputs.resolve()])
    assert deleted == 1
    assert freed == 10
    assert not good.exists()
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `python -m pytest tests/test_cleanup.py -q -k "outside or directory or dedup or malformed"`
Expected: PASS immediately (Task 3 already implements the safety paths). If any FAIL, fix the corresponding branch in `prune`/`_read_entries` before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/test_cleanup.py
git commit -m "test: cover prune safety (containment, dir, dedup, malformed)"
```

---

## Task 5: clean_uploads (purge with symlink/junction escape guard)

**Files:**
- Modify: `cleanup.py`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py (append)
import os

from cleanup import clean_uploads


def test_clean_uploads_removes_children(tmp_path: Path):
    base = tmp_path / "_uploads"
    (base / "grp1").mkdir(parents=True)
    (base / "grp1" / "a.png").write_bytes(b"a")
    (base / "job2").mkdir()
    (base / "stray.bin").write_bytes(b"b")  # stray top-level file

    removed = clean_uploads(base)
    assert removed == 3
    assert list(base.iterdir()) == []  # base itself remains, now empty


def test_clean_uploads_missing_base_returns_zero(tmp_path: Path):
    assert clean_uploads(tmp_path / "does_not_exist") == 0


def test_clean_uploads_does_not_escape_via_symlink(tmp_path: Path):
    base = tmp_path / "_uploads"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    keeper = outside / "keep.txt"
    keeper.write_bytes(b"do not touch")
    try:
        os.symlink(outside, base / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink/junction creation not permitted on this host")

    clean_uploads(base)
    assert not (base / "link").exists()  # link entry removed
    assert keeper.exists()               # target contents untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup.py -q -k clean_uploads`
Expected: FAIL — `ImportError: cannot import name 'clean_uploads'`

- [ ] **Step 3: Write minimal implementation**

```python
# cleanup.py (append, module level)
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
                _unlink_or_rmdir(child)  # link/junction -> drop the entry only
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def _unlink_or_rmdir(link: Path) -> None:
    """Remove a symlink/junction entry without touching its target."""
    try:
        link.unlink()       # file symlink
    except (IsADirectoryError, PermissionError, OSError):
        try:
            os.rmdir(link)  # directory symlink / Windows junction
        except OSError:
            pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup.py -q -k clean_uploads`
Expected: PASS (symlink test may `skip` on hosts without privilege — acceptable)

- [ ] **Step 5: Commit**

```bash
git add cleanup.py tests/test_cleanup.py
git commit -m "feat: add clean_uploads purge with symlink escape guard"
```

---

## Task 6: run_startup_cleanup orchestrator (best-effort, never raises)

**Files:**
- Modify: `cleanup.py`
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py (append)
from cleanup import run_startup_cleanup


def test_orchestrator_runs_both_steps(tmp_path: Path):
    base = tmp_path / "_uploads"
    (base / "grp1").mkdir(parents=True)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    old_file = outputs / "old.png"
    old_file.write_bytes(b"x" * 20)
    lg = _write_ledger(tmp_path, [{"path": str(old_file), "ts": _old_ts(40)}])

    cfg = CleanupConfig(clean_uploads=True, clean_outputs=True,
                        retention_days=30, allowed_roots=[outputs.resolve()])
    run_startup_cleanup(base, lg, cfg)  # must not raise

    assert list(base.iterdir()) == []
    assert not old_file.exists()


def test_orchestrator_respects_toggles(tmp_path: Path):
    base = tmp_path / "_uploads"
    (base / "grp1").mkdir(parents=True)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    old_file = outputs / "old.png"
    old_file.write_bytes(b"x" * 20)
    lg = _write_ledger(tmp_path, [{"path": str(old_file), "ts": _old_ts(40)}])

    cfg = CleanupConfig(clean_uploads=False, clean_outputs=False,
                        retention_days=30, allowed_roots=[outputs.resolve()])
    run_startup_cleanup(base, lg, cfg)

    assert (base / "grp1").exists()  # uploads untouched
    assert old_file.exists()         # outputs untouched


def test_orchestrator_never_raises_on_bad_input(tmp_path: Path):
    cfg = CleanupConfig(clean_uploads=True, clean_outputs=True,
                        retention_days=30, allowed_roots=[tmp_path])
    bad_ledger = Ledger(tmp_path / "_state" / "missing.jsonl")
    # Non-existent upload base + missing ledger must be handled silently.
    run_startup_cleanup(tmp_path / "no_such_uploads", bad_ledger, cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup.py -q -k orchestrator`
Expected: FAIL — `ImportError: cannot import name 'run_startup_cleanup'`

- [ ] **Step 3: Write minimal implementation**

```python
# cleanup.py (append, module level)
def run_startup_cleanup(upload_base: Path, ledger: "Ledger", config: CleanupConfig) -> None:
    """Best-effort one-time cleanup. Never raises -- must not block startup."""
    temp_removed = 0
    out_deleted = 0
    out_freed = 0
    if config.clean_uploads:
        try:
            temp_removed = clean_uploads(upload_base)
        except Exception as exc:  # noqa: BLE001 -- never block startup
            print(f"[Wan2GP REST] upload cleanup failed: {exc}")
    if config.clean_outputs:
        try:
            out_deleted, out_freed = ledger.prune(config.retention_days, config.allowed_roots)
        except Exception as exc:  # noqa: BLE001 -- never block startup
            print(f"[Wan2GP REST] output cleanup failed: {exc}")
    mb = out_freed / (1024 * 1024)
    print(f"[Wan2GP REST] cleanup: temp {temp_removed} items, "
          f"outputs {out_deleted} files ({mb:.1f} MB freed)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup.py -q`
Expected: PASS (entire file)

- [ ] **Step 5: Commit**

```bash
git add cleanup.py tests/test_cleanup.py
git commit -m "feat: add run_startup_cleanup orchestrator"
```

---

## Task 7: Wire ledger into callbacks.py (record on success only)

**Files:**
- Modify: `callbacks.py:29-33` (constructor), `callbacks.py:72-91` (`on_complete`)
- Test: `tests/test_cleanup.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cleanup.py (append)
import sys
import types


def _make_adapter_with_ledger(tmp_path: Path):
    """Build a JobCallbackAdapter with a real Ledger but stub store/uploads."""
    from callbacks import JobCallbackAdapter
    lg = Ledger(tmp_path / "_state" / "generated_ledger.jsonl")

    class StubStore:
        def __init__(self): self.completed = None; self.failed = None
        def mark_completed(self, jid, files): self.completed = (jid, files)
        def mark_failed(self, jid, errs, generated_files=None): self.failed = (jid, errs)
        def mark_cancelled(self, jid): pass

    class StubUploads:
        def cleanup_job(self, jid): pass

    adapter = JobCallbackAdapter(StubStore(), StubUploads(), lg)
    return adapter, lg


class _Result:
    def __init__(self, success, files, errors=None):
        self.success = success
        self.generated_files = files
        self.errors = errors or []


def test_ledger_records_on_success(tmp_path: Path):
    adapter, lg = _make_adapter_with_ledger(tmp_path)
    adapter.set_active_job("job1")
    adapter.on_complete(_Result(True, ["/out/x.png"]))
    lines = (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["path"] == "/out/x.png"


def test_ledger_not_recorded_on_failure(tmp_path: Path):
    adapter, lg = _make_adapter_with_ledger(tmp_path)
    adapter.set_active_job("job2")

    class _Err:
        stage = "inference"
        message = "boom"
        task_index = None
        task_id = None

    adapter.on_complete(_Result(False, ["/out/partial.png"], errors=[_Err()]))
    assert not (tmp_path / "_state" / "generated_ledger.jsonl").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cleanup.py -q -k ledger_record`
Expected: FAIL — `TypeError: __init__() takes ... positional arguments` (constructor has no `ledger` param yet)

- [ ] **Step 3: Modify the implementation**

In `callbacks.py`, change the constructor (currently lines 29-33):

```python
    def __init__(
        self,
        store: JobStore,
        upload_manager: UploadManager | None = None,
        ledger: "Ledger | None" = None,
    ) -> None:
        self._store = store
        self._upload_manager = upload_manager
        self._ledger = ledger
        self._job_lock = threading.Lock()
        self._active_job_id: str | None = None
```

Add the ledger type to the `TYPE_CHECKING` block near the top of `callbacks.py`:

```python
if TYPE_CHECKING:
    from .cleanup import Ledger
    from .job_store import JobStore
    from .uploads import UploadManager
```

In `on_complete`, record on success only. Change the success branch:

```python
        if result.success:
            self._store.mark_completed(job_id, list(result.generated_files))
            if self._ledger is not None:
                self._ledger.record(list(result.generated_files))
        elif any(
            getattr(e, "stage", None) == "cancelled" for e in result.errors
        ):
            self._store.mark_cancelled(job_id)
        else:
            errors = [serialize_wan2gp_error(e) for e in result.errors]
            self._store.mark_failed(
                job_id, errors,
                generated_files=list(result.generated_files),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cleanup.py -q -k ledger_record`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add callbacks.py tests/test_cleanup.py
git commit -m "feat: record generated files to ledger on successful completion"
```

---

## Task 8: Wire cleanup into plugin.py startup + .gitignore

**Files:**
- Modify: `plugin.py:23-57` (`post_ui_setup`)
- Modify: `.gitignore`

- [ ] **Step 1: Update `.gitignore`**

Add under the existing "Upload temp files" entry:

```gitignore
# Upload temp files
_uploads/

# Cleanup state & config
_state/
cleanup_config.json
```

- [ ] **Step 2: Modify `plugin.py` `post_ui_setup`**

Replace the body (current lines 28-57) with:

```python
        from pathlib import Path

        from shared.api import init as wan2gp_init

        from .callbacks import JobCallbackAdapter
        from .cleanup import CleanupConfig, Ledger, run_startup_cleanup
        from .job_store import JobStore
        from .rest_server import configure, start_server
        from .uploads import UploadManager

        plugin_dir = Path(__file__).resolve().parent
        wan2gp_root = plugin_dir.parent.parent

        # 1. Create job store, upload manager, and generated-file ledger
        store = JobStore()
        upload_manager = UploadManager()
        ledger = Ledger(plugin_dir / "_state" / "generated_ledger.jsonl")

        # 2. One-time safe cleanup BEFORE the server starts (no jobs in flight)
        config = CleanupConfig.load_or_create(
            plugin_dir / "cleanup_config.json", wan2gp_root
        )
        run_startup_cleanup(upload_manager.base_dir, ledger, config)

        # 3. Create callback adapter (upload cleanup + ledger recording)
        callback_adapter = JobCallbackAdapter(store, upload_manager, ledger)

        # 4. Initialize Wan2GP session
        session = wan2gp_init(
            root=wan2gp_root,
            callbacks=callback_adapter,
        )

        # 5. Inject dependencies into the REST server
        configure(store, session, callback_adapter, upload_manager)

        # 6. Start server
        self._server_thread = start_server(host="0.0.0.0", port=7989)
        print("[Wan2GP REST] Plugin initialized. REST API is ready.")
```

- [ ] **Step 3: Verify the full suite still passes**

Run: `python -m pytest tests/ -q`
Expected: PASS (all tests; `plugin.py` is import-guarded behind `shared.*` so it is not imported by tests)

- [ ] **Step 4: Lint**

Run: `ruff check cleanup.py callbacks.py plugin.py tests/test_cleanup.py`
Expected: no errors (broad-except lines carry `# noqa: BLE001`)

- [ ] **Step 5: Commit**

```bash
git add plugin.py .gitignore
git commit -m "feat: run startup file cleanup before server start"
```

---

## Task 9: Document the cleanup feature in README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Disk Cleanup" section**

Insert after the "Downloading Generated Files" section and before "Error Handling":

````markdown
## Disk Cleanup

To keep disk usage bounded over long-term use, the plugin runs a one-time safe
cleanup each time it starts (before the API accepts requests):

1. **Temp uploads** — all leftover files under `_uploads/` are removed. These are
   ephemeral: an uploaded file that is not submitted to a job before a restart is
   discarded.
2. **Old generated outputs** — files the plugin itself generated and recorded in
   its ledger (`_state/generated_ledger.jsonl`) that are older than the retention
   window are deleted. Your manual Wan2GP UI generations are **never** touched —
   only files inside the configured output root that the plugin created are
   eligible.

### Configuration — `cleanup_config.json`

On first run the plugin auto-creates `cleanup_config.json` next to it. Edit it in
any text editor (e.g. Notepad) and restart to apply:

```json
{
  "_comment": "Wan2GP REST startup cleanup. Edit values, restart to apply.",
  "clean_uploads": true,
  "clean_outputs": true,
  "output_retention_days": 30,
  "output_roots": []
}
```

| Key | Default | Meaning |
|-----|---------|---------|
| `clean_uploads` | `true` | Wipe leftover `_uploads/` temp files at startup |
| `clean_outputs` | `true` | Delete ledgered generated outputs past the retention window |
| `output_retention_days` | `30` | Age threshold in days. Must be an integer ≥ 1; invalid values fall back to 30 |
| `output_roots` | `[]` | Extra allowed roots for deletion. The default `<wan2gp_root>/outputs` is always included |

To disable output deletion entirely, set `"clean_outputs": false`.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document startup disk cleanup and config"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** L1–L5 (temp upload leaks) → Task 5 + Task 8 (startup purge). L6 (outputs never deleted) → Tasks 3/4 + Task 7 (ledger record) + Task 8 (prune at startup). Config/auto-create/validation → Task 1. Success-only ledger → Task 7. Dedup latest-wins, atomic rewrite, malformed-skip → Tasks 3/4. Root containment + retention validation + symlink guard → Tasks 1/3/4/5. Docs → Task 9. All spec sections mapped.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test shows full assertions.

**Type consistency:** `CleanupConfig(clean_uploads, clean_outputs, retention_days, allowed_roots)`, `Ledger(path)` with `record(list[str])` / `prune(int, list[Path]) -> tuple[int,int]`, `clean_uploads(Path) -> int`, `run_startup_cleanup(upload_base, ledger, config)` — signatures identical across tasks and the `plugin.py` call site.
