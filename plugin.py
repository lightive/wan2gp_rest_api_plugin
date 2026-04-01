"""Wan2GP REST API Plugin.

Starts a FastAPI-based REST API server through the Wan2GP plugin system.
External HTTP clients can request image/video generation via the API.
"""

from shared.utils.plugins import WAN2GPPlugin


class RestApiPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Wan2GP REST API"
        self.version = "1.0.1"
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
        from .job_store import JobStore
        from .rest_server import configure, start_server
        from .uploads import UploadManager

        # 1. Create job store & upload manager
        store = JobStore()
        upload_manager = UploadManager()

        # 2. Create callback adapter (with upload cleanup support)
        callback_adapter = JobCallbackAdapter(store, upload_manager)

        # 3. Initialize Wan2GP session
        plugin_dir = Path(__file__).resolve().parent
        wan2gp_root = plugin_dir.parent.parent
        session = wan2gp_init(
            root=wan2gp_root,
            callbacks=callback_adapter,
        )

        # 4. Inject dependencies into the REST server
        configure(store, session, callback_adapter, upload_manager)

        # 5. Start server
        self._server_thread = start_server(host="0.0.0.0", port=7989)
        print("[Wan2GP REST] Plugin initialized. REST API is ready.")
