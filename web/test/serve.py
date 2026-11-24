"""시험용 정적 서버: web/dist 를 cross-origin isolation 헤더와 함께 연다 (GitHub Pages 에서는 coi-serviceworker 가 대신함).

    python web/test/serve.py [포트]
/test/ 아래는 web/test 폴더 (시험 페이지).
"""
import functools
import http.server
import os
import sys

WEB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class H(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = path.split("?", 1)[0]
        if p.startswith("/test/"):
            return os.path.join(WEB, "test", p[len("/test/"):])
        if p.startswith("/local-models/") and os.environ.get("MODEL_DIR"):  # 시험: Hugging Face 대신 로컬 모델
            return os.path.join(os.environ["MODEL_DIR"], p[len("/local-models/"):])
        return super().translate_path(path)

    def end_headers(self):
        if not os.environ.get("NO_COI"):  # NO_COI=1: GitHub Pages 처럼 헤더 없이 (coi-serviceworker 시험)
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    h = functools.partial(H, directory=os.path.join(WEB, "dist"))
    http.server.ThreadingHTTPServer(("127.0.0.1", port), h).serve_forever()
