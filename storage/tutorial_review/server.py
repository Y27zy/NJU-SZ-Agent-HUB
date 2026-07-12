from __future__ import annotations

import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class RangeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        relative = self.path.split("?", 1)[0].lstrip("/") or "index.html"
        target = (ROOT / relative).resolve()
        if ROOT not in target.parents or not target.is_file():
            self.send_error(404)
            return

        size = target.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            status = 206
            first, _, last = range_header[6:].partition("-")
            start = int(first or 0)
            end = min(int(last) if last else size - 1, size - 1)

        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()

        with target.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8766), RangeHandler).serve_forever()
