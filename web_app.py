"""Loopback-only web workbench; launch with project Python or web.bat."""

from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import secrets
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from config import (
    APP_TITLE,
    AUTHOR_HANDLE,
    HISTORY_DIR,
    KEYWORDS,
    WEB_DEFAULT_LIMIT,
    WEB_DIR,
    WEB_HOST,
    WEB_PORT,
    utc_today_str,
)
from web_history import artifact, daily_history, run_history, snapshot
from web_jobs import JobConflict, JobManager

logger = logging.getLogger(__name__)


class WorkbenchServer(ThreadingHTTPServer):
    """A local server with explicit storage roots for isolated integration testing."""

    daemon_threads = True

    def __init__(
        self,
        port: int = WEB_PORT,
        manager: JobManager | None = None,
        history_root: Path | None = None,
        web_root: Path = WEB_DIR,
    ) -> None:
        self.manager = manager if manager is not None else JobManager()
        self.history_root = history_root
        self.web_root = web_root
        self.token = secrets.token_urlsafe(32)
        super().__init__((WEB_HOST, port), WorkbenchHandler)
        actual_port = self.server_address[1]
        self.allowed_hosts = {f"{WEB_HOST}:{actual_port}", f"localhost:{actual_port}"}
        self.allowed_origins = {f"http://{host}" for host in self.allowed_hosts}


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer

    def log_message(self, format: str, *args: Any) -> None:
        # Request URLs may contain user keywords. Keep them out of server access logs.
        return

    def _reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, value: Any, status: int = 200) -> None:
        self._reply(
            status,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _local_request(self) -> bool:
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in self.server.allowed_hosts or (
            origin is not None and origin not in self.server.allowed_origins
        ):
            self._json({"error": "仅允许从本机工作台访问。"}, 403)
            return False
        return True

    def do_GET(self) -> None:
        if not self._local_request():
            return
        try:
            self._get()
        except FileNotFoundError as exc:
            self._json({"error": str(exc) or "文件不存在。"}, 404)
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            logger.exception("Workbench read failed")
            self._json({"error": "读取失败，请检查本地数据文件及服务控制台。"}, 500)

    def _get(self) -> None:
        parts = urlsplit(self.path)
        path = unquote(parts.path)
        query = parse_qs(parts.query)
        if path in ("/", "/app.js", "/styles.css"):
            name = "index.html" if path == "/" else path[1:]
            content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._reply(
                200, (self.server.web_root / name).read_bytes(), content_type + "; charset=utf-8"
            )
        elif path == "/favicon.ico":
            self._reply(204, b"", "image/x-icon")
        elif path == "/api/config":
            self._json(
                {
                    "title": APP_TITLE,
                    "author": AUTHOR_HANDLE,
                    "today": utc_today_str(),
                    "token": self.server.token,
                    "suggestions": KEYWORDS,
                    "default_limit": WEB_DEFAULT_LIMIT,
                }
            )
        elif path == "/api/active":
            self._json({"job": self.server.manager.active()})
        elif path in ("/api/history", "/api/runs"):
            filters = {key: query.get(key, [""])[0].strip() for key in ("keyword", "start", "end")}
            try:
                page = int(query.get("page", ["1"])[0])
            except ValueError:
                raise ValueError("页码必须为正整数。") from None
            if path == "/api/history":
                self._json(
                    daily_history(
                        filters["keyword"],
                        filters["start"],
                        filters["end"],
                        page,
                        root=(
                            HISTORY_DIR
                            if self.server.history_root is None
                            else self.server.history_root
                        ),
                    )
                )
            else:
                self._json(run_history(self.server.manager, **filters, page=page))
        elif path.startswith("/api/jobs/"):
            job = self.server.manager.detail(path.removeprefix("/api/jobs/"))
            if job.get("output_id"):
                job["files"] = snapshot(job["output_id"], self.server.manager.output_root)["files"]
            self._json(job)
        elif path.startswith("/api/snapshots/"):
            self._json(
                snapshot(path.removeprefix("/api/snapshots/"), self.server.manager.output_root)
            )
        elif path.startswith("/files/"):
            segments = path.split("/")
            if len(segments) != 4:
                raise FileNotFoundError("结果文件路径无效。")
            file = artifact(segments[2], segments[3], self.server.manager.output_root)
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._reply(200, file.read_bytes(), content_type)
        else:
            self._json({"error": "页面不存在。"}, 404)

    def do_POST(self) -> None:
        # Consume bounded request bodies before rejecting auth/origin. Closing an
        # unread POST can reset the socket on Windows and discard the error body.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("请求大小无效。")
            raw = self.rfile.read(length)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        if not self._local_request():
            return
        if not secrets.compare_digest(self.headers.get("X-AI-Index-Token", ""), self.server.token):
            self._json({"error": "页面会话已失效，请刷新网页后重试。"}, 403)
            return
        if self.path != "/api/jobs":
            self._json({"error": "接口不存在。"}, 404)
            return
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请使用 JSON 提交抓取参数。")
            value = json.loads(raw)
            self._json(self.server.manager.start(value), HTTPStatus.ACCEPTED)
        except JobConflict as exc:
            self._json({"error": str(exc)}, 409)
        except (ValueError, TypeError, UnicodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception:
            logger.exception("Could not create web job")
            self._json({"error": "无法创建任务，请检查服务控制台。"}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="启动本机搜索与历史工作台。")
    parser.add_argument("--port", type=int, default=WEB_PORT, help="本地端口，默认 8765。")
    parser.add_argument("--open", action="store_true", help="自动打开浏览器。")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间。")
    logging.basicConfig(level=logging.INFO)
    try:
        server = WorkbenchServer(args.port)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"工作台启动失败：{exc}\n")
    url = f"http://{WEB_HOST}:{server.server_address[1]}"
    print(f"工作台已启动：{url}\n保持此窗口打开。按 Ctrl+C 关闭服务。", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
