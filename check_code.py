"""Check the Python code in topic files, so "minimal and runnable" is tested.

Usage:  python check_code.py [topic.md ...]   (default: every topic)
Every ```python block must compile. A topic's runnable blocks are then joined
and run as one script in a temp dir, with a timeout. A block whose info string
is ```python fragment is only compiled (use it for snippets that need a server,
network or surrounding code). Topics importing a package that is not installed
are compiled but not run; CI installs requirements-check.txt so most third-party
topics run there. Stdlib only; exits 1 on any failure.
"""
import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from build_index import ROOT, SKIP, SKIP_DIRS

TIMEOUT = 60
BLOCK = re.compile(r"^```python([^\n]*)\n(.*?)^```", re.S | re.M)


def blocks(path):
    """[(is_fragment, code)] for every ```python block in the file."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return [("fragment" in info.split(), code) for info, code in BLOCK.findall(text)]


def imports(code):
    names = set()
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def check(path):
    """Return (status, detail): status is pass, fail or skip."""
    found = blocks(path)
    if not found:
        return "skip", "no python code"
    for i, (_, code) in enumerate(found, 1):
        try:
            compile(code, f"{path.name} block {i}", "exec")
        except SyntaxError as e:
            return "fail", f"block {i} does not compile: {e}"
    code = "\n\n".join(c for frag, c in found if not frag)
    # Python wants `from __future__` imports first, so lift them out of later blocks.
    future = re.findall(r"^from __future__ import .*$", code, re.M)
    if future:
        code = "\n".join(dict.fromkeys(future)) + "\n" + re.sub(r"^from __future__ import .*$", "", code, flags=re.M)
    if not code.strip():
        return "pass", "fragments only"
    extra = {m for m in imports(code) - set(sys.stdlib_module_names) if importlib.util.find_spec(m) is None}
    if extra:
        return "skip", f"compiled; not run, needs {', '.join(sorted(extra))}"
    with tempfile.TemporaryDirectory() as tmp:
        # a real file, not -c: multiprocessing's spawn start method re-imports __main__
        Path(tmp, "topic_code.py").write_text(code, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, "-I", "topic_code.py"], cwd=tmp, capture_output=True,
                               text=True, timeout=TIMEOUT, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        except subprocess.TimeoutExpired:
            return "fail", f"timed out after {TIMEOUT}s"
    if r.returncode:
        return "fail", (r.stderr.strip().splitlines() or [f"exit code {r.returncode}"])[-1]
    return "pass", ""


def topics(args):
    if args:
        return [Path(a).resolve() for a in args]
    return [p for p in sorted(ROOT.rglob("*.md"))
            if p.name not in SKIP and not p.relative_to(ROOT).as_posix().startswith((".", *SKIP_DIRS))]


def shown(path):
    """Repo-relative path for messages; a file outside the repo keeps its full path."""
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


if __name__ == "__main__":
    paths = topics(sys.argv[1:])
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(check, paths))
    counts = {"pass": 0, "fail": 0, "skip": 0}
    for path, (status, detail) in zip(paths, results):
        counts[status] += 1
        if status != "pass" and detail != "no python code":
            print(f"{status.upper()} {shown(path)}: {detail}")
    print(f"{counts['pass']} passed, {counts['fail']} failed, {counts['skip']} skipped")
    sys.exit(1 if counts["fail"] else 0)
