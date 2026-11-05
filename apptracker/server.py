"""The local page: tracker.html plus a small JSON API, on 127.0.0.1 only.

  GET  /              the page
  GET  /api/rows      {today, rows, tracks, offices, tz, eyebrow}
  POST /api/applied   {id, applied: "YYYY-MM-DD" or ""}
  POST /api/check     {id, item, done: "YYYY-MM-DD" or ""}

Writes need the X-Tracker header and a JSON body, and every request must name
localhost in Host (and Origin, if sent): a page from another site, or a
DNS-rebound name, can't reach the ledger.
"""

import http.server
import json
import os

from . import applications as A
from . import view
from .config import PACKAGE, settings

PAGE = os.path.join(PACKAGE, "tracker.html")
# the skeleton a claude.ai artifact page gets, so the page renders the same here
SKELETON = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>:root{color-scheme:light}body{margin:0;font:14px system-ui,sans-serif}'
            'img{max-width:100%}[hidden]{display:none!important}</style></head><body>{page}</body></html>')


def payload(extra=None):
    today = settings().today()
    shown = view.rows(today)
    out = {"today": today.isoformat(), "rows": shown}
    out.update(view.page_info(shown))
    out.update(extra or {})
    return out


class Handler(http.server.BaseHTTPRequestHandler):
    port = 8765

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _local_host(self):
        ok = {"localhost:%d" % self.port, "127.0.0.1:%d" % self.port}
        if self.headers.get("Host", "") not in ok:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {"http://" + h for h in ok}

    def do_GET(self):
        if not self._local_host():
            return self._send(403, '{"error": "local requests only"}')
        path = self.path.split("?")[0]
        if path == "/":
            with open(PAGE, encoding="utf-8") as fh:
                return self._send(200, SKELETON.replace("{page}", fh.read()), "text/html")
        if path == "/api/rows":
            return self._send(200, json.dumps(payload()))
        return self._send(404, '{"error": "not found"}')

    def do_POST(self):
        if not self._local_host() or self.headers.get("X-Tracker") != "1" \
                or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(403, '{"error": "local requests only"}')
        if self.path not in ("/api/applied", "/api/check"):
            return self._send(404, '{"error": "not found"}')
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("the body must be a JSON object")
            if self.path == "/api/check":
                result = A.set_check(str(body.get("id", "")), str(body.get("item", "")), str(body.get("done", "")))
            else:
                result = A.set_applied(str(body.get("id", "")), str(body.get("applied", "")))
        except KeyError as e:
            return self._send(404, json.dumps({"error": "no application %s" % e}))
        except (ValueError, SystemExit, RecursionError, TypeError, AttributeError) as e:
            return self._send(400, json.dumps({"error": str(e) or "bad request"}))
        self._send(200, json.dumps(payload({"result": result})))


def serve(port=None):
    port = int(port or settings().get("port"))
    Handler.port = port
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("tracker on http://localhost:%d (Ctrl-C to stop)" % port, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
