"""The local server: the page, the rows, and the two writes it accepts."""

import http.client
import http.server
import json
import threading
import unittest

from helpers import DataCase

from apptracker import server
from apptracker.checklist import checklist_done


class Server(DataCase):
    def setUp(self):
        super().setUp()
        self.write_apps([dict(id="hartwell-dc-ny", firm="hartwell", office="DC;NY", program="2028 2L Summer Associate",
                              opens="2026-11-01", deadline="2027-01-29", letter_required="y",
                              materials="Cover letter, resume and law school transcript.")])
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = srv.server_address[1]
        server.Handler.port = self.port
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        self.local = {"Host": "localhost:%d" % self.port}
        self.today = self.s.today().isoformat()

    def call(self, method, path, headers, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        return r.status, r.read()

    def post(self, path, body):
        return self.call("POST", path, dict(self.local, **{"Content-Type": "application/json", "X-Tracker": "1"}),
                         json.dumps(body))

    def test_the_server_answers_only_local_pages(self):
        self.assertEqual(self.call("GET", "/api/rows", {"Host": "evil.example:%d" % self.port})[0], 403)
        self.assertEqual(self.call("GET", "/api/rows", dict(self.local, Origin="https://evil.example"))[0], 403)
        code, body = self.call("GET", "/", self.local)
        self.assertEqual(code, 200)
        self.assertTrue(body.startswith(b"<!doctype html>") and b"<title>" in body)
        tick = json.dumps({"id": "hartwell-dc-ny", "applied": self.today})
        self.assertEqual(self.call("POST", "/api/applied", dict(self.local, **{"Content-Type": "text/plain"}), tick)[0], 403)
        self.assertEqual(self.call("POST", "/api/applied", dict(self.local, **{"Content-Type": "application/json"}), tick)[0], 403)
        code, body = self.post("/api/applied", {"id": "hartwell-dc-ny", "applied": self.today})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["result"], "applied " + self.today)
        self.assertEqual(self.apps()["hartwell-dc-ny"]["applied"], self.today)

    def test_rows_come_with_what_the_page_draws(self):
        code, body = self.call("GET", "/api/rows", self.local)
        j = json.loads(body)
        self.assertEqual((code, j["today"], [r["id"] for r in j["rows"]]), (200, self.today, ["hartwell-dc-ny"]))
        self.assertEqual(j["rows"][0]["firm_name"], "Hartwell & Pike LLP")
        self.assertEqual((j["offices"], j["tracks"][1]["key"]), (["DC", "NY"], "1L-2027"))

    def test_the_server_takes_checklist_ticks(self):
        self.assertEqual(self.post("/api/check", {"id": "hartwell-dc-ny", "item": "resume", "done": self.today})[0], 200)
        self.assertEqual(checklist_done(self.apps()["hartwell-dc-ny"]), {"resume": self.today})
        self.assertEqual(self.post("/api/check", {"id": "hartwell-dc-ny", "item": "nope", "done": self.today})[0], 400)
        self.assertEqual(self.post("/api/check", {"id": "nobody", "item": "resume", "done": self.today})[0], 404)
        self.assertEqual(self.post("/api/check", [])[0], 400)       # not an object: a clean 400, not a dropped connection
        self.assertEqual(self.post("/api/nothing", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
