"""Wan2GP REST API 플러그인.

Wan2GP 플러그인 시스템을 통해 FastAPI 기반 REST API 서버를 기동한다.
외부 클라이언트(worker_luckywiki 등)가 HTTP로 이미지/영상 생성을 요청할 수 있게 한다.
"""

from shared.utils.plugins import WAN2GPPlugin


class RestApiPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Wan2GP REST API"
        self.version = "1.0.0"
        self.description = "Exposes Wan2GP generation capabilities via a localhost REST API."
        self._server_thread = None

    def setup_ui(self):
        """UI 설정 단계. REST API 플러그인은 UI를 추가하지 않는다."""
        pass

    def post_ui_setup(self, components: dict):
        """UI 빌드 완료 후 REST API 서버를 기동한다."""
        from pathlib import Path

        from shared.api import init as wan2gp_init

        from .callbacks import JobCallbackAdapter
        from .job_store import JobStore
        from .rest_server import configure, start_server

        # 1. Job Store 생성
        store = JobStore()

        # 2. 콜백 어댑터 생성
        callback_adapter = JobCallbackAdapter(store)

        # 3. Wan2GP 세션 초기화
        plugin_dir = Path(__file__).resolve().parent
        wan2gp_root = plugin_dir.parent.parent
        session = wan2gp_init(
            root=wan2gp_root,
            callbacks=callback_adapter,
        )

        # 4. REST 서버에 의존성 주입
        configure(store, session, callback_adapter)

        # 5. 서버 기동
        self._server_thread = start_server(host="127.0.0.1", port=8000)
        print("[Wan2GP REST] Plugin initialized. REST API is ready.")
