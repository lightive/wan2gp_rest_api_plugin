"""Wan2GP REST API Plugin.

Starts a FastAPI-based REST API server through the Wan2GP plugin system.
External HTTP clients can request image/video generation via the API.
"""

from shared.utils.plugins import WAN2GPPlugin


class RestApiPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Wan2GP REST API"
        self.version = "1.1.0"
        self.author = "lightive"
        self.description = "Exposes Wan2GP generation capabilities via a localhost REST API."
        self._server_thread = None

    def setup_ui(self):
        """UI setup phase. The REST API plugin does not add any UI elements."""
        pass

    def post_ui_setup(self, components: dict):
        """Start the REST API server after UI construction is complete."""
        if self._server_thread is not None:
            return

        from pathlib import Path

        from shared.api import init as wan2gp_init

        from .callbacks import JobCallbackAdapter
        from .cleanup import CleanupConfig, Ledger, run_startup_cleanup
        from .job_store import JobStore
        from .rest_server import configure, start_server
        from .uploads import UploadManager

        plugin_dir = Path(__file__).resolve().parent
        wan2gp_root = plugin_dir.parent.parent

        # 1. Create job store and upload manager
        store = JobStore()
        upload_manager = UploadManager()

        # 2. One-time safe cleanup BEFORE the server starts (no jobs in flight).
        #    The ledger is only maintained when output cleanup is enabled, so a
        #    disabled config never grows the ledger file. Wrapped so cleanup can
        #    never block start_server (defense in depth).
        ledger = None
        try:
            config = CleanupConfig.load_or_create(
                plugin_dir / "cleanup_config.json", wan2gp_root
            )
            ledger = (
                Ledger(plugin_dir / "_state" / "generated_ledger.jsonl")
                if config.clean_outputs
                else None
            )
            run_startup_cleanup(upload_manager.base_dir, ledger, config)
        except Exception as exc:
            print(f"[Wan2GP REST] startup cleanup skipped ({exc})")

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
        self._server_thread = start_server(host="127.0.0.1", port=7989)
        print("[Wan2GP REST] Plugin initialized. REST API is ready.")
