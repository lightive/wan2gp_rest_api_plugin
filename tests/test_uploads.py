from pathlib import Path

import pytest

from uploads import UploadManager


def _manager(tmp_path: Path) -> UploadManager:
    return UploadManager(base_dir=tmp_path / "uploads")


@pytest.fixture()
def mgr(tmp_path: Path) -> UploadManager:
    return _manager(tmp_path)


def test_save_file_returns_absolute_path(mgr: UploadManager):
    path = mgr.save_file("grp1", "photo.png", b"\x89PNG...")
    assert Path(path).is_absolute()
    assert Path(path).read_bytes() == b"\x89PNG..."


def test_save_file_does_not_overwrite(mgr: UploadManager):
    p1 = mgr.save_file("grp1", "photo.png", b"data1")
    p2 = mgr.save_file("grp1", "photo.png", b"data2")
    assert p1 != p2
    assert Path(p1).read_bytes() == b"data1"
    assert Path(p2).read_bytes() == b"data2"


def test_cleanup_job_removes_directory(mgr: UploadManager):
    mgr.save_file("grp1", "a.png", b"data")
    mgr.save_file("grp1", "b.png", b"data")
    d = mgr.base_dir / "grp1"
    assert d.exists()
    mgr.cleanup_job("grp1")
    assert not d.exists()


def test_resolve_data_uris_replaces_base64_value(mgr: UploadManager):
    settings = {
        "prompt": "test",
        "image_start": "data:image/png;base64,aGVsbG8=",  # "hello"
    }
    job_id = "job_abc"
    mgr.resolve_data_uris(settings, job_id)
    assert isinstance(settings["image_start"], str)
    path = Path(settings["image_start"])
    assert path.exists()
    assert path.read_bytes() == b"hello"
    assert path.suffix == ".png"


def test_resolve_data_uris_leaves_plain_path(mgr: UploadManager):
    settings = {"image_start": "/tmp/existing.png"}
    mgr.resolve_data_uris(settings, "job_xyz")
    assert settings["image_start"] == "/tmp/existing.png"


def test_resolve_data_uris_handles_invalid_base64(mgr: UploadManager):
    settings = {"image_start": "data:image/png;base64,!!!NOT_B64!!!"}
    with pytest.raises(ValueError, match="Invalid base64"):
        mgr.resolve_data_uris(settings, "job_err")


def test_register_groups_and_cleanup(mgr: UploadManager):
    mgr.save_file("grp1", "a.png", b"data")
    mgr.register_groups_for_job("job1", {"grp1"})
    # job_id directory also gets cleaned (even if it has no files)
    mgr.cleanup_job("job1")
    assert not (mgr.base_dir / "grp1").exists()
