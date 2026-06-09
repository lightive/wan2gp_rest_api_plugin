"""Wan2GP REST API Plugin.

Starts a FastAPI-based REST API server through the Wan2GP plugin system.
External HTTP clients can request image/video generation via the API.
"""

from shared.utils.plugins import WAN2GPPlugin


class RestApiPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Wan2GP REST API"
        self.version = "1.2.0"
        self.author = "lightive"
        self.description = "Exposes Wan2GP generation capabilities via a localhost REST API."
        self._server_thread = None
        # Resolved at startup: the dir containing wgp.py, and its parent.
        self.wan2gp_root = None
        self.pinokio_wan2gp_root = None

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
        from .cleanup import CleanupConfig, Ledger, find_wan2gp_root, run_startup_cleanup
        from .job_store import JobStore
        from .rest_server import configure, start_server
        from .uploads import UploadManager

        plugin_dir = Path(__file__).resolve().parent
        # Locate the Wan2GP app by finding wgp.py upward from the plugin, so the
        # path is correct on any drive/install depth. Its parent is the Pinokio
        # (wan.git) root. Both are stored for reuse.
        wan2gp_root = find_wan2gp_root(plugin_dir)
        pinokio_wan2gp_root = wan2gp_root.parent
        self.wan2gp_root = wan2gp_root
        self.pinokio_wan2gp_root = pinokio_wan2gp_root
        print(f"[Wan2GP REST] wan2gp_root (wgp.py dir) = {wan2gp_root}")
        print(f"[Wan2GP REST] pinokio_wan2gp_root      = {pinokio_wan2gp_root}")

        # 1. Create job store and upload manager
        store = JobStore()
        upload_manager = UploadManager()

        # 2. One-time safe cleanup BEFORE the server starts (no jobs in flight).
        #    The ledger is only maintained when output cleanup is enabled, so a
        #    disabled config never grows the ledger file. Wrapped so cleanup can
        #    never block start_server (defense in depth).
        config = None
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
            gradio_temp_dir = pinokio_wan2gp_root / "cache" / "GRADIO_TEMP_DIR"
            run_startup_cleanup(upload_manager.base_dir, ledger, config, gradio_temp_dir)
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

        # 6. Start server (host is configurable in cleanup_config.json:
        #    "127.0.0.1" = localhost only (default), "0.0.0.0" = all interfaces.)
        host = config.host if config is not None else "127.0.0.1"
        if host == "0.0.0.0":
            print(
                "[Wan2GP REST] WARNING: host=0.0.0.0 exposes the unauthenticated "
                "API to your LAN. Use 127.0.0.1 unless you intend remote access."
            )
        self._server_thread = start_server(host=host, port=7989)
        print("[Wan2GP REST] Plugin initialized. REST API is ready.")
