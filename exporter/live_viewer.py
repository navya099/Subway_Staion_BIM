"""3D 웹 뷰어 실시간 갱신: 앱 안의 작은 로컬 HTTP 서버 (127.0.0.1 만, 외부 접속 없음).

- GET /           뷰어 HTML (web_viewer_template + three.js, LIVE 모드 — 자료는 서버에서 받음)
- GET /version    {"version", "status": idle|building|ok|error, "message"} — 뷰어가 1초마다 물어봄
- GET /data.json  {"version", "data"} (web_viewer.build_web_data 의 자료 dict)
- GET /data.bin   gzip 바이트 열 (뷰어가 DecompressionStream 으로 풂)
update(cfg) 는 설정 사본으로 별도 엔진을 만들어 백그라운드 스레드에서 자료를 만든다 (미리보기 엔진과 3D 문서를 함께 쓰지 않음).
새 자료가 생기면 version 이 올라가고, 뷰어는 카메라·잘라 보기·표시 묶음을 그대로 둔 채 모델만 바꾼다.
"""
import copy
import json
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from exporter.web_viewer import TEMPLATE, THREE_JS, build_web_data, lambda_safe


def live_html() -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    return html.replace("/*__THREE__*/", lambda_safe(THREE_JS.read_text(encoding="utf-8"))) \
        .replace("/*__DATA__*/", "null").replace("/*__BLOB__*/", "").replace("/*__LIVE__*/false", "true")


class LiveViewer:
    """로컬 서버 1개. start() 후 url 로 브라우저를 열고, 모델이 바뀔 때마다 update(cfg) (또는 publish(engine))"""

    def __init__(self, port: int = 0, frames: bool = False):
        self.port, self.frames = port, frames
        self.version = -1
        self.status, self.message = "idle", ""
        self._data, self._blob = None, b""
        self._lock = threading.Lock()
        self._pending = None                     # 만드는 동안 들어온 최신 설정 (끝나면 이어서)
        self._worker = None
        self._busy = False                       # 작업 스레드가 돌고 있음 (잠금 안에서만 바꿈)
        self._server = None
        self._html = None

    # ------------------------------------------------------------ 서버
    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> str:
        if self._server is None:
            viewer = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *a):                # 콘솔에 요청 기록을 남기지 않음
                    pass

                def do_GET(self):
                    path = self.path.split("?", 1)[0]
                    if path in ("/", "/index.html"):
                        if viewer._html is None:
                            viewer._html = live_html()
                        self._send(viewer._html.encode("utf-8"), "text/html; charset=utf-8")
                    elif path == "/version":
                        with viewer._lock:
                            body = {"version": viewer.version, "status": viewer.status, "message": viewer.message}
                        self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                    elif path == "/data.json":
                        with viewer._lock:
                            body = {"version": viewer.version, "data": viewer._data}
                        self._send(json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
                    elif path == "/data.bin":
                        with viewer._lock:
                            blob = viewer._blob
                        self._send(blob, "application/octet-stream")
                    else:
                        self.send_error(404)

                def _send(self, body: bytes, ctype: str):
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)

            self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
            self._server.daemon_threads = True
            self.port = self._server.server_address[1]
            threading.Thread(target=self._server.serve_forever, daemon=True, name="live-viewer").start()
        return self.url

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    # ------------------------------------------------------------ 자료
    def publish(self, engine):
        """engine 으로 자료를 만들어 바로 올림 (호출한 스레드에서)"""
        data, blob = build_web_data(engine, self.frames)
        with self._lock:
            self._data, self._blob = data, blob
            self.version += 1
            self.status, self.message = "ok", ""

    def update(self, cfg, on_done=None):
        """설정 사본으로 백그라운드에서 모델·자료를 만들어 올림. 만드는 중이면 끝난 뒤 최신 설정으로 한 번 더.
        on_done(ok, message) 는 작업 스레드에서 부름 (화면 갱신은 호출한 쪽이 after 로 넘길 것)"""
        cfg = copy.deepcopy(cfg)
        with self._lock:
            if self._busy:
                self._pending = (cfg, on_done)
                return
            self._busy = True
            self.status, self.message = "building", ""
        self._worker = threading.Thread(target=self._run, args=(cfg, on_done), daemon=True, name="live-viewer-build")
        self._worker.start()

    def _run(self, cfg, on_done):
        from engine.cad_engine import StationCADEngine
        while True:
            try:
                self.publish(StationCADEngine(cfg))
                ok, msg = True, ""
            except Exception as e:                       # 입력 오류 등: 이전 모델을 그대로 보여 줌
                traceback.print_exc()
                ok, msg = False, f"{type(e).__name__}: {e}"
                with self._lock:
                    self.status, self.message = "error", msg
            if on_done is not None:
                try:
                    on_done(ok, msg)
                except Exception:
                    traceback.print_exc()
            with self._lock:
                nxt, self._pending = self._pending, None
                if nxt is None:
                    self._busy = False
                    return
                self.status = "building"
            cfg, on_done = nxt

    def wait(self, timeout=None) -> bool:
        """작업이 끝날 때까지 기다림 (테스트용)"""
        w = self._worker
        if w is not None:
            w.join(timeout)
        return w is None or not w.is_alive()


_SHARED = None


def shared() -> LiveViewer:
    """앱 전체에서 하나 (미리보기 창을 닫았다 열어도 같은 주소)"""
    global _SHARED
    if _SHARED is None:
        _SHARED = LiveViewer()
    return _SHARED
