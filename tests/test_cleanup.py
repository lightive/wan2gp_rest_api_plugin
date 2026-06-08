import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cleanup import CleanupConfig, Ledger, clean_uploads, run_startup_cleanup


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
    remaining = [
        json.loads(x)
        for x in (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines()
        if x.strip()
    ]
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


def test_config_load_does_not_raise_when_unwritable(tmp_path: Path):
    # Put a FILE where the config's parent dir should be, so that
    # mkdir(parents=True) / write_text raise OSError inside _write_default_config.
    blocker = tmp_path / "blocked"
    blocker.write_bytes(b"i am a file, not a dir")
    cfg_path = blocker / "cleanup_config.json"  # parent is a file -> unwritable

    cfg = CleanupConfig.load_or_create(cfg_path, tmp_path / "wan2gp")  # must not raise

    assert cfg.clean_uploads is True
    assert cfg.clean_outputs is True
    assert cfg.retention_days == 30
    assert (tmp_path / "wan2gp" / "outputs").resolve() in cfg.allowed_roots


def test_record_best_effort_when_unwritable(tmp_path: Path):
    # Make the ledger's _state parent a FILE so mkdir(parents=True) raises.
    state_blocker = tmp_path / "_state"
    state_blocker.write_bytes(b"file, not a dir")
    lg = Ledger(state_blocker / "generated_ledger.jsonl")

    lg.record(["/out/a.png"])  # must not raise


def test_read_entries_keeps_valid_over_unparseable_dup(tmp_path: Path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    f = outputs / "reused.png"
    f.write_bytes(b"x" * 42)
    # Same path twice: first a VALID expired ts, then an UNPARSEABLE ts.
    # The valid (expired) record must win, so prune deletes the file.
    lg = _write_ledger(tmp_path, [
        {"path": str(f), "ts": _old_ts(40)},
        {"path": str(f), "ts": "not-a-timestamp"},
    ])
    deleted, freed = lg.prune(30, [outputs.resolve()])
    assert deleted == 1  # valid expired record kept -> file deleted
    assert freed == 42
    assert not f.exists()
