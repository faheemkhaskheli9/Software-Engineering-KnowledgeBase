#!/usr/bin/env python3
"""Local web app to browse, search and edit this knowledge base.

Run:  python3 webapp/server.py [--port N] [--open]
Stdlib only. Binds to 127.0.0.1; writes need a per-run token. Edits go straight
to the files in this repo (review and commit them with git as usual).
"""
import argparse, json, os, re, secrets, shutil, subprocess, sys, tempfile, threading, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.join(HERE, ".."))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
EXTS = tuple(CFG["extensions"])
SKIP_DIRS = set(CFG["skip_dirs"])
READONLY = tuple(CFG.get("readonly", []))
ACTIONS = CFG.get("actions", {})
MAX_BYTES = 2 * 1024 * 1024
# Read-only image types shown inline by the Markdown view. No SVG: it can carry script.
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
          ".webp": "image/webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_DIFF_BYTES = 256 * 1024
GIT = shutil.which("git")
TOKEN = secrets.token_urlsafe(24)
LOCK = threading.Lock()
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8")}


def is_readonly(rel):
    return any(rel == p.rstrip("/") or rel.startswith(p if p.endswith("/") else p + "/") for p in READONLY)


def resolve(rel, must_exist=True, exts=EXTS):
    """Map a repo-relative POSIX path to an absolute one, or None if not allowed."""
    if not rel or "\x00" in rel or rel.startswith("/") or "\\" in rel:
        return None
    parts = rel.split("/")
    if any(p in ("", ".", "..") or p.startswith(".") or p in SKIP_DIRS for p in parts):
        return None
    if not rel.lower().endswith(exts):
        return None
    full = os.path.realpath(os.path.join(ROOT, *parts))
    if os.path.commonpath([ROOT, full]) != ROOT or not full.lower().endswith(exts):
        return None
    # A symlink must not lead into a hidden or skipped folder either.
    if any(p.startswith(".") or p in SKIP_DIRS for p in os.path.relpath(full, ROOT).split(os.sep)):
        return None
    if must_exist and not os.path.isfile(full):
        return None
    return full


def walk():
    out = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = sorted(d for d in dns if d not in SKIP_DIRS and not d.startswith("."))
        for fn in sorted(fns):
            if fn.startswith(".") or not fn.lower().endswith(EXTS):
                continue
            full = os.path.join(dp, fn)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            out.append({"path": rel, "size": os.path.getsize(full), "readonly": is_readonly(rel)})
    return out


def read_text(full):
    with open(full, "rb") as f:
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("file too large to edit here")
    return data.decode("utf-8")


def image_type(data):
    """Content-Type from the file's magic bytes, or None if it is not an allowed image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_image(full):
    """Bytes and Content-Type of an allowlisted image; ValueError if too large or not that type."""
    with open(full, "rb") as f:
        data = f.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    ctype = image_type(data)
    if ctype != IMAGES[os.path.splitext(full)[1].lower()]:
        raise ValueError("not a valid image of its type")
    return data, ctype


def search(q, limit=200):
    q = q.lower()
    hits = []
    for f in walk():
        full = resolve(f["path"])
        try:
            text = read_text(full)
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        if q in f["path"].lower():
            hits.append({"path": f["path"], "line": 0, "text": "(filename)"})
        for n, line in enumerate(text.splitlines(), 1):
            if q in line.lower():
                hits.append({"path": f["path"], "line": n, "text": line.strip()[:200]})
                if len(hits) >= limit:
                    return hits
    return hits


WIKI = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MDLINK = re.compile(r"\]\(([^)\s#]+)(?:#[^)\s]*)?(?:\s+\"[^)]*\")?\)")


def wiki_target(name, paths):
    """Same rule as the browser: full path without .md first, then file name alone."""
    n = name.strip().lower()
    n = n[:-3] if n.endswith(".md") else n
    key = lambda p: p.lower()[:-3] if p.lower().endswith(".md") else p.lower()
    for p in paths:
        if key(p) == n:
            return p
    for p in paths:
        if key(p).rsplit("/", 1)[-1] == n:
            return p
    return None


def link_target(base, href):
    """Repo-relative path a relative Markdown link in file `base` points at."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I) or href.startswith("//"):
        return None
    folder = base.rsplit("/", 1)[0] if "/" in base else ""
    parts = (href[1:] if href.startswith("/") else folder + "/" + href).split("/")
    out = []
    for p in parts:
        if p == "..":
            if out:
                out.pop()
        elif p and p != ".":
            out.append(p)
    return "/".join(out)


def backlinks(rel, limit=200):
    """Markdown files that link to `rel` by [[wiki-link]] or relative link, one hit per line."""
    from urllib.parse import unquote
    paths = [f["path"] for f in walk()]
    hits = []
    for p in paths:
        if p == rel or not p.lower().endswith(".md"):
            continue
        try:
            text = read_text(resolve(p))
        except (ValueError, UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if any(wiki_target(m, paths) == rel for m in WIKI.findall(line)) or \
               any(link_target(p, unquote(h)) == rel for h in MDLINK.findall(line)):
                hits.append({"path": p, "line": n, "text": line.strip()[:200]})
                if len(hits) >= limit:
                    return hits
    return hits


def git(*args, timeout=10):
    """Run a read-only git command in the repo; stdout, or None if git is missing or fails."""
    if not GIT:
        return None
    try:
        r = subprocess.run([GIT, "-C", ROOT, *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode in (0, 1) else None


def changes():
    """Working-tree changes from `git status`: [{path, status, viewable}], or None outside git."""
    out = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if out is None:
        return None
    items, recs, i = [], out.decode("utf-8", "replace").split("\0"), 0
    while i < len(recs):
        r = recs[i]
        i += 1
        if len(r) < 4:
            continue
        code, path = r[:2], r[3:]
        if "R" in code or "C" in code:
            i += 1  # the next record is the old name
        st = "untracked" if code == "??" else "deleted" if "D" in code else "added" if "A" in code \
            else "renamed" if "R" in code else "modified"
        items.append({"path": path, "status": st, "viewable": bool(resolve(path, must_exist=False))})
    return sorted(items, key=lambda x: x["path"])


def diff(rel):
    """Unified diff of one viewable file against HEAD (untracked files diff against nothing)."""
    if not resolve(rel, must_exist=False):
        return None
    tracked = git("ls-files", "--error-unmatch", "--", rel)
    if tracked:
        out = git("diff", "--no-color", "--no-ext-diff", "HEAD", "--", rel)
    else:
        out = git("diff", "--no-color", "--no-ext-diff", "--no-index", "--", os.devnull, rel)
    if out is None:
        return None
    text = out[:MAX_DIFF_BYTES].decode("utf-8", "replace")
    return text + ("\n... (diff cut at %d KB)\n" % (MAX_DIFF_BYTES // 1024) if len(out) > MAX_DIFF_BYTES else "")


class Handler(BaseHTTPRequestHandler):
    server_version = "KBWeb"
    sys_version = ""

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                         "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg):
        self._send(code, {"error": msg})

    def _host_ok(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("localhost", "127.0.0.1", "::1"):
            return False  # blocks DNS rebinding
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return False
        return True

    def _body(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise ValueError("JSON required")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BYTES + 4096:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if not self._host_ok():
            return self._err(403, "forbidden host")
        u = urlparse(self.path)
        if u.path in STATIC:
            name, ctype = STATIC[u.path]
            with open(os.path.join(HERE, name), "rb") as f:
                return self._send(200, f.read(), ctype)
        if u.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        qs = parse_qs(u.query)
        if u.path == "/api/config":
            return self._send(200, {"title": CFG["title"], "token": TOKEN, "actions": list(ACTIONS),
                                    "template": CFG.get("template", ""), "git": bool(GIT and git("rev-parse") is not None)})
        if u.path == "/api/tree":
            return self._send(200, walk())
        if u.path == "/api/search":
            q = (qs.get("q") or [""])[0].strip()
            return self._send(200, search(q) if len(q) >= 2 else [])
        if u.path == "/api/file":
            rel = (qs.get("path") or [""])[0]
            full = resolve(rel)
            if not full:
                return self._err(404, "not found")
            try:
                return self._send(200, {"path": rel, "content": read_text(full), "readonly": is_readonly(rel),
                                        "version": str(os.stat(full).st_mtime_ns)})
            except (ValueError, UnicodeDecodeError) as e:
                return self._err(415, str(e))
        if u.path == "/api/backlinks":
            rel = (qs.get("path") or [""])[0]
            if not resolve(rel):
                return self._err(404, "not found")
            return self._send(200, backlinks(rel))
        if u.path == "/api/changes":
            c = changes()
            return self._send(200, c) if c is not None else self._err(404, "not a git repository")
        if u.path == "/api/diff":
            d = diff((qs.get("path") or [""])[0])
            return self._send(200, {"diff": d}) if d is not None else self._err(404, "not found")
        if u.path == "/api/image":
            # Read-only: images under the repo, same path rules as text files, allowlisted types only.
            rel = (qs.get("path") or [""])[0]
            full = resolve(rel, exts=tuple(IMAGES))
            if not full:
                return self._err(404, "not found")
            try:
                data, ctype = read_image(full)
            except (ValueError, OSError) as e:
                return self._err(415, str(e))
            return self._send(200, data, ctype)
        self._err(404, "not found")

    def _write(self, full, content):
        content = content.replace("\r\n", "\n").replace("\r", "\n")
        if len(content.encode()) > MAX_BYTES:
            raise ValueError("file too large")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(full), prefix=".kbtmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            if os.path.exists(full):
                os.chmod(tmp, os.stat(full).st_mode & 0o777)
            os.replace(tmp, full)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def do_POST(self):
        self._mutate("POST")

    def do_PUT(self):
        self._mutate("PUT")

    def do_DELETE(self):
        self._mutate("DELETE")

    def _mutate(self, method):
        if not self._host_ok():
            return self._err(403, "forbidden host")
        if not secrets.compare_digest(self.headers.get("X-KB-Token") or "", TOKEN):
            return self._err(403, "bad token (reload the page)")
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError) as e:
            return self._err(400, str(e))
        path = urlparse(self.path).path
        rel = body.get("path", "")
        with LOCK:
            try:
                if method == "PUT" and path == "/api/file":
                    full = resolve(rel)
                    if not full:
                        return self._err(404, "not found")
                    if is_readonly(rel):
                        return self._err(403, "read-only file (edit the live source instead)")
                    if str(os.stat(full).st_mtime_ns) != str(body.get("version")):
                        return self._err(409, "file changed on disk since you opened it")
                    self._write(full, body.get("content", ""))
                    return self._send(200, {"version": str(os.stat(full).st_mtime_ns)})
                if method == "DELETE" and path == "/api/file":
                    full = resolve(rel)
                    if not full:
                        return self._err(404, "not found")
                    if is_readonly(rel):
                        return self._err(403, "read-only file")
                    if str(os.stat(full).st_mtime_ns) != str(body.get("version")):
                        return self._err(409, "file changed on disk since you opened it")
                    os.remove(full)
                    return self._send(200, {"path": rel})
                if method == "POST" and path == "/api/new":
                    full = resolve(rel, must_exist=False)
                    if not full:
                        return self._err(400, "invalid path (allowed: %s)" % ", ".join(EXTS))
                    if is_readonly(rel):
                        return self._err(403, "read-only location")
                    if os.path.exists(full):
                        return self._err(409, "already exists")
                    self._write(full, body.get("content", ""))
                    return self._send(200, {"path": rel, "version": str(os.stat(full).st_mtime_ns)})
                if method == "POST" and path == "/api/action":
                    cmd = ACTIONS.get(body.get("name"))
                    if not cmd:
                        return self._err(404, "unknown action")
                    r = subprocess.run([sys.executable if c == "python3" else c for c in cmd], cwd=ROOT,
                                       capture_output=True, text=True, timeout=120)
                    return self._send(200, {"code": r.returncode, "output": (r.stdout + r.stderr)[-4000:]})
            except (ValueError, OSError, subprocess.SubprocessError) as e:
                return self._err(400, str(e))
        self._err(404, "not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=CFG["port"])
    ap.add_argument("--open", action="store_true", help="open the browser")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    url = "http://localhost:%d/" % a.port
    print("%s -> %s  (Ctrl+C to stop)" % (CFG["title"], url))
    if a.open:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
