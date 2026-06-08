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
