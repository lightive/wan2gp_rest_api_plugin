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
