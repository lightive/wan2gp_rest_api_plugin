import importlib
import json
import sys
import types
from pathlib import Path


def _install_shared_stub():
    if "shared" in sys.modules:
        return
    shared = types.ModuleType("shared")
    utils = types.ModuleType("shared.utils")
    plugins = types.ModuleType("shared.utils.plugins")

    class WAN2GPPlugin:
        def __init__(self):
            pass

    plugins.WAN2GPPlugin = WAN2GPPlugin
    api = types.ModuleType("shared.api")
    api.init = lambda *a, **k: None
    sys.modules.update({
        "shared": shared, "shared.utils": utils,
        "shared.utils.plugins": plugins, "shared.api": api,
    })


_install_shared_stub()
_PKG_DIR = Path(__file__).resolve().parents[1]
_PKG_PARENT = str(_PKG_DIR.parent)
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)
_PKG = _PKG_DIR.name

callbacks = importlib.import_module(f"{_PKG}.callbacks")
cleanup = importlib.import_module(f"{_PKG}.cleanup")
JobCallbackAdapter = callbacks.JobCallbackAdapter
Ledger = cleanup.Ledger


def _make_adapter_with_ledger(tmp_path: Path):
    """Build a JobCallbackAdapter with a real Ledger but stub store/uploads."""
    lg = Ledger(tmp_path / "_state" / "generated_ledger.jsonl")

    class StubStore:
        def __init__(self):
            self.completed = None
            self.failed = None

        def mark_completed(self, jid, files):
            self.completed = (jid, files)

        def mark_failed(self, jid, errs, generated_files=None):
            self.failed = (jid, errs)

        def mark_cancelled(self, jid):
            pass

    class StubUploads:
        def cleanup_job(self, jid):
            pass

    adapter = JobCallbackAdapter(StubStore(), StubUploads(), lg)
    return adapter, lg


class _Result:
    def __init__(self, success, files, errors=None):
        self.success = success
        self.generated_files = files
        self.errors = errors or []


def test_ledger_records_on_success(tmp_path: Path):
    adapter, _lg = _make_adapter_with_ledger(tmp_path)
    adapter.set_active_job("job1")
    adapter.on_complete(_Result(True, ["/out/x.png"]))
    lines = (tmp_path / "_state" / "generated_ledger.jsonl").read_text().splitlines()
    assert json.loads(lines[0])["path"] == "/out/x.png"


def test_ledger_not_recorded_on_failure(tmp_path: Path):
    adapter, _lg = _make_adapter_with_ledger(tmp_path)
    adapter.set_active_job("job2")

    class _Err:
        stage = "inference"
        message = "boom"
        task_index = None
        task_id = None

    adapter.on_complete(_Result(False, ["/out/partial.png"], errors=[_Err()]))
    assert not (tmp_path / "_state" / "generated_ledger.jsonl").exists()


def test_adapter_with_none_ledger_records_nothing(tmp_path: Path):
    class StubStore:
        def __init__(self):
            self.completed = None

        def mark_completed(self, jid, files):
            self.completed = (jid, files)

        def mark_failed(self, jid, errs, generated_files=None):
            pass

        def mark_cancelled(self, jid):
            pass

    class StubUploads:
        def cleanup_job(self, jid):
            pass

    store = StubStore()
    adapter = JobCallbackAdapter(store, StubUploads(), None)
    adapter.set_active_job("job3")
    adapter.on_complete(_Result(True, ["/out/x.png"]))  # must not raise

    assert store.completed == ("job3", ["/out/x.png"])  # store still updated
    assert not (tmp_path / "_state" / "generated_ledger.jsonl").exists()
