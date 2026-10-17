"""Write-path, delete, backlink, git and image-route tests for webapp/server.py, run against a temp copy of the repo.

Stdlib unittest; `python3 manage.py test webapp` picks it up, so does
`python3 -m unittest webapp.test_server`. Never touches the real topic files.
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerCase(unittest.TestCase):
    """Starts server.py on a temp copy of the repo; subclasses hold the tests."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        # server.py serves the parent of its own folder, so a copied webapp/ serves the temp repo.
        shutil.copytree(HERE, os.path.join(cls.tmp, "webapp"), ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(cls.tmp, "concepts"))
        cls.topic = os.path.join(cls.tmp, "concepts", "a.md")
        with open(cls.topic, "w", encoding="utf-8", newline="\n") as f:
            f.write("old\n")
        # A tiny valid PNG, a text file posing as one, an image outside the repo and a symlink to it.
        cls.png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                                "1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082")
        os.makedirs(os.path.join(cls.tmp, "docs", "img"))
        with open(os.path.join(cls.tmp, "docs", "img", "dot.png"), "wb") as f:
            f.write(cls.png)
        with open(os.path.join(cls.tmp, "docs", "img", "fake.png"), "wb") as f:
            f.write(b"<script>alert(1)</script>")
        with open(os.path.join(cls.tmp, "docs", "img", "pic.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        os.makedirs(os.path.join(cls.tmp, ".hidden"))
        with open(os.path.join(cls.tmp, ".hidden", "h.png"), "wb") as f:
            f.write(cls.png)
        cls.outside = tempfile.mkdtemp()
        with open(os.path.join(cls.outside, "secret.png"), "wb") as f:
            f.write(cls.png)
        cls.symlinks = hasattr(os, "symlink")
        try:
            os.symlink(os.path.join(cls.outside, "secret.png"), os.path.join(cls.tmp, "docs", "img", "out.png"))
            os.symlink(os.path.join(cls.tmp, ".hidden", "h.png"), os.path.join(cls.tmp, "docs", "img", "hid.png"))
            os.symlink(cls.topic, os.path.join(cls.tmp, "docs", "img", "topic.png"))
        except (OSError, NotImplementedError):
            cls.symlinks = False
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, os.path.join(cls.tmp, "webapp", "server.py"),
                                     "--port", str(cls.port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.1).close()
                break
            except OSError:
                time.sleep(0.1)
        cls.token = cls.request("GET", "/api/config")[1]["token"]

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(10)
        shutil.rmtree(cls.tmp, ignore_errors=True)
        shutil.rmtree(cls.outside, ignore_errors=True)

    @classmethod
    def request(cls, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        hdrs = {"Host": "localhost:%d" % cls.port, "Content-Type": "application/json", **(headers or {})}
        conn.request(method, path, json.dumps(body).encode() if body is not None else None, hdrs)
        r = conn.getresponse()
        data = json.loads(r.read() or b"null")
        conn.close()
        return r.status, data

    @classmethod
    def raw(cls, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port, timeout=10)
        conn.request("GET", path, headers={"Host": "localhost:%d" % cls.port, **(headers or {})})
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r, data

    def put(self, body, **headers):
        return self.request("PUT", "/api/file", body, {"X-KB-Token": self.token, **headers})

    def version(self):
        return self.request("GET", "/api/file?path=concepts/a.md")[1]["version"]

    def read(self):
        with open(self.topic, encoding="utf-8") as f:
            return f.read()


class ServerWriteTests(ServerCase):
    def test_no_token_rejected(self):
        status, _ = self.request("PUT", "/api/file", {"path": "concepts/a.md", "content": "x",
                                                      "version": self.version()})
        self.assertEqual(status, 403)
        self.assertEqual(self.read(), "old\n")

    def test_foreign_origin_rejected(self):
        status, _ = self.put({"path": "concepts/a.md", "content": "x", "version": self.version()},
                             Origin="http://evil.example")
        self.assertEqual(status, 403)
        self.assertEqual(self.read(), "old\n")

    def test_parent_path_rejected(self):
        status, _ = self.put({"path": "../escape.md", "content": "x", "version": "0"})
        self.assertEqual(status, 404)
        status, _ = self.request("POST", "/api/new", {"path": "concepts/../../escape.md", "content": "x"},
                                 {"X-KB-Token": self.token})
        self.assertEqual(status, 400)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "escape.md")))

    def test_stale_version_rejected(self):
        status, _ = self.put({"path": "concepts/a.md", "content": "x", "version": "1"})
        self.assertEqual(status, 409)
        self.assertEqual(self.read(), "old\n")

    def test_valid_save_writes_file(self):
        status, data = self.put({"path": "concepts/a.md", "content": "new\r\nline\n", "version": self.version()})
        self.assertEqual(status, 200)
        self.assertEqual(data["version"], self.version())
        with open(self.topic, "rb") as f:
            self.assertEqual(f.read(), b"new\nline\n")
        # Restore so test order does not matter.
        self.put({"path": "concepts/a.md", "content": "old\n", "version": self.version()})



class ServerDeleteTests(ServerCase):
    def new(self, rel, content="x\n"):
        return self.request("POST", "/api/new", {"path": rel, "content": content}, {"X-KB-Token": self.token})

    def delete(self, body, **headers):
        return self.request("DELETE", "/api/file", body, {"X-KB-Token": self.token, **headers})

    def test_delete_removes_file(self):
        self.assertEqual(self.new("concepts/gone.md")[0], 200)
        v = self.request("GET", "/api/file?path=concepts/gone.md")[1]["version"]
        status, _ = self.delete({"path": "concepts/gone.md", "version": v})
        self.assertEqual(status, 200)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "concepts", "gone.md")))

    def test_delete_needs_token_and_current_version(self):
        self.new("concepts/keep.md")
        v = self.request("GET", "/api/file?path=concepts/keep.md")[1]["version"]
        self.assertEqual(self.request("DELETE", "/api/file", {"path": "concepts/keep.md", "version": v})[0], 403)
        self.assertEqual(self.delete({"path": "concepts/keep.md", "version": "1"})[0], 409)
        self.assertEqual(self.delete({"path": "../x.md", "version": v})[0], 404)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "concepts", "keep.md")))


class ServerLinkAndGitTests(ServerCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for rel, text in (("concepts/b.md", "See [[a]] and [[concepts/a|A]].\n"),
                          ("docs/c.md", "Read [a](../concepts/a.md#part).\nNo link here.\n"),
                          ("docs/d.md", "Only [[b]].\n")):
            cls.request("POST", "/api/new", {"path": rel, "content": text}, {"X-KB-Token": cls.token})

    def test_backlinks_find_wiki_and_relative_links(self):
        status, hits = self.request("GET", "/api/backlinks?path=concepts/a.md")
        self.assertEqual(status, 200)
        self.assertEqual(sorted((h["path"], h["line"]) for h in hits), [("concepts/b.md", 1), ("docs/c.md", 1)])
        self.assertEqual(self.request("GET", "/api/backlinks?path=../a.md")[0], 404)

    def test_changes_and_diff(self):
        git = shutil.which("git")
        if not git:
            self.skipTest("git not installed")
        status, _ = self.request("GET", "/api/changes")
        self.assertEqual(status, 404)  # the temp copy is not a git repository yet
        run = lambda *a: subprocess.run([git, "-C", self.tmp, *a], check=True, capture_output=True)
        run("init", "-q")
        run("-c", "user.name=t", "-c", "user.email=t@t", "add", "concepts/a.md")
        run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        with open(self.topic, "a", encoding="utf-8") as f:
            f.write("added line\n")
        try:
            status, items = self.request("GET", "/api/changes")
            self.assertEqual(status, 200)
            by_path = {i["path"]: i["status"] for i in items}
            self.assertEqual(by_path["concepts/a.md"], "modified")
            self.assertEqual(by_path["docs/c.md"], "untracked")
            d = self.request("GET", "/api/diff?path=concepts/a.md")[1]["diff"]
            self.assertIn("+added line", d)
            self.assertIn("+Read [a]", self.request("GET", "/api/diff?path=docs/c.md")[1]["diff"])
            self.assertEqual(self.request("GET", "/api/diff?path=../x.md")[0], 404)
            self.assertEqual(self.request("GET", "/api/diff?path=.git/config")[0], 404)
        finally:
            with open(self.topic, "w", encoding="utf-8", newline="\n") as f:
                f.write("old\n")
            shutil.rmtree(os.path.join(self.tmp, ".git"), ignore_errors=True)


class ServerImageTests(ServerCase):
    """The read-only /api/image route."""

    def test_image_serves_png(self):
        r, data = self.raw("/api/image?path=docs/img/dot.png")
        self.assertEqual(r.status, 200)
        self.assertEqual(data, self.png)
        self.assertEqual(r.getheader("Content-Type"), "image/png")
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'none'", r.getheader("Content-Security-Policy"))

    def test_image_traversal_rejected(self):
        for p in ("../x.png", "docs/../../x.png", "docs/img/../../../x.png", "/etc/x.png",
                  "docs\\img\\dot.png", ".hidden/h.png", "docs/img/./dot.png", "docs//img/dot.png"):
            r, _ = self.raw("/api/image?path=" + urllib.parse.quote(p))
            self.assertEqual(r.status, 404, p)

    def test_image_non_image_types_rejected(self):
        for p in ("concepts/a.md", "docs/img/pic.svg", "webapp/server.py"):
            r, _ = self.raw("/api/image?path=" + p)
            self.assertEqual(r.status, 404, p)
        # Right extension, wrong content: refused, never sent with an image type.
        r, data = self.raw("/api/image?path=docs/img/fake.png")
        self.assertEqual(r.status, 415)
        self.assertNotIn(b"<script>", data)

    def test_image_outside_repo_rejected(self):
        if not self.symlinks:
            self.skipTest("no symlinks on this platform")
        for p in ("docs/img/out.png", "docs/img/hid.png", "docs/img/topic.png"):
            r, data = self.raw("/api/image?path=" + p)
            self.assertEqual(r.status, 404, p)
            self.assertNotEqual(data, self.png)

    def test_image_foreign_host_rejected(self):
        r, _ = self.raw("/api/image?path=docs/img/dot.png", {"Host": "evil.example"})
        self.assertEqual(r.status, 403)

    def test_image_route_is_read_only(self):
        status, _ = self.request("PUT", "/api/image?path=docs/img/dot.png", {"path": "docs/img/dot.png"},
                                 {"X-KB-Token": self.token})
        self.assertEqual(status, 404)
        with open(os.path.join(self.tmp, "docs", "img", "dot.png"), "rb") as f:
            self.assertEqual(f.read(), self.png)

    def test_image_not_editable_as_text(self):
        status, _ = self.request("GET", "/api/file?path=docs/img/dot.png")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
