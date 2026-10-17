#!/usr/bin/env python3
"""Status, checks and web-app sync across the sibling knowledge-base repos.

    python3 kb_maintain.py status              # branch, uncommitted files, commits ahead/behind
    python3 kb_maintain.py check [--full]      # run each repo's checks (--full adds the slow ones)
    python3 kb_maintain.py drift               # shared web-app files that differ between repos
    python3 kb_maintain.py sync-webapp FROM    # copy the shared web-app files from repo FROM to the others

Repos are looked up as folders next to the repo this script lives in (or under --root).
Stdlib only. Exit code 1 when a check fails or the web app has drifted.
"""
import argparse
import filecmp
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(os.path.realpath(os.path.join(HERE, "..", "..", "..")))

# name -> (quick checks, extra slow checks). Each check is (label, argv). "{py}" is this Python.
REPOS = {
    "AI-Knowledge-Base": (
        [("index", ["{py}", "build_index.py", "--strict"]),
         ("index tests", ["{py}", "-m", "unittest", "-q", "test_build_index_freshness"]),
         ("webapp", ["{py}", "webapp/test_server.py"])],
        [("django site", ["{py}", "manage.py", "test", "webapp"]),
         ("topic code", ["{py}", "check_code.py", "--jobs", "4"])]),
    "Software-Engineering-KnowledgeBase": (
        [("index tests", ["{py}", "test_build_index.py"]),
         ("index", ["{py}", "build_index.py"]),
         ("webapp", ["{py}", "webapp/test_server.py"])],
        [("topic code", ["{py}", "check_code.py"])]),
    "Cyber-Security-Knowledge-Base": (
        [("kb lint", ["bash", "scripts/check-kb.sh"]),
         ("scripts parse", ["bash", "-n", "scripts/audit.sh"]),
         ("webapp", ["{py}", "webapp/test_server.py"])],
        []),
    "Brain": (
        [("index", ["{py}", "build_index.py"]),
         ("webapp", ["{py}", "webapp/test_server.py"])],
        [("topic code", ["{py}", "run_code_blocks.py"]),
         ("game models", ["{py}", "game/test_sim.py"]),
         ("brain world", ["node", "game/world/test_brain.mjs", "1"])]),
}
# Files that are identical in every repo's webapp/ (config.json and repo-specific extras are not).
SHARED = ["server.py", "app.js", "app.css", "index.html", "test_server.py", "screenshots.mjs"]
# Generated files that must be committed after a rebuild.
GENERATED = ["INDEX.md", "llms.txt"]


def repos(root):
    found = [(n, os.path.join(root, n)) for n in REPOS if os.path.isdir(os.path.join(root, n, ".git"))]
    if not found:
        sys.exit("no knowledge-base repos under %s (clone them side by side, or pass --root)" % root)
    return found


def git(path, *args):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def status(root):
    for name, path in repos(root):
        branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
        dirty = [line for line in git(path, "status", "--porcelain").splitlines() if line]
        base = next((b for b in ("@{upstream}", "origin/HEAD", "origin/main", "origin/master")
                     if git(path, "rev-parse", "--verify", "--quiet", b)), "")
        counts = git(path, "rev-list", "--left-right", "--count", base + "...HEAD").split()
        sync = "%s behind, %s ahead of %s" % (*counts, base) if len(counts) == 2 else "no remote"
        print("%-36s %-28s %3d uncommitted  %s" % (name, branch, len(dirty), sync))


def check(root, full):
    failed = []
    for name, path in repos(root):
        quick, slow = REPOS[name]
        for label, argv in quick + (slow if full else []):
            argv = [sys.executable if a == "{py}" else a for a in argv]
            if shutil.which(argv[0]) is None and not os.path.isabs(argv[0]):
                print("SKIP %-36s %-14s (%s not installed)" % (name, label, argv[0]))
                continue
            r = subprocess.run(argv, cwd=path, capture_output=True, text=True)
            out = (r.stdout + r.stderr).strip().splitlines()
            warn = [line for line in out if line.lower().startswith("warning")]
            print("%s %-36s %-14s%s" % ("ok  " if r.returncode == 0 else "FAIL", name, label,
                                         "  (%d warning lines)" % len(warn) if warn else ""))
            if r.returncode != 0:
                failed.append((name, label))
                print("\n".join("      " + line for line in out[-15:]))
        stale = [g for g in GENERATED if os.path.exists(os.path.join(path, g))
                 and git(path, "status", "--porcelain", "--", g)]
        if stale:
            print("NOTE %-36s regenerated, commit: %s" % (name, ", ".join(stale)))
    if failed:
        sys.exit("failed: " + ", ".join("%s/%s" % f for f in failed))


def drift(root):
    found = [(n, p) for n, p in repos(root) if os.path.isdir(os.path.join(p, "webapp"))]
    differs = []
    for f in SHARED:
        copies = [(n, os.path.join(p, "webapp", f)) for n, p in found]
        missing = [n for n, p in copies if not os.path.exists(p)]
        present = [(n, p) for n, p in copies if os.path.exists(p)]
        groups = []
        for n, p in present:
            for g in groups:
                if filecmp.cmp(g[0][1], p, shallow=False):
                    g.append((n, p))
                    break
            else:
                groups.append([(n, p)])
        if len(groups) > 1 or missing:
            differs.append(f)
            print("webapp/%s: %d versions%s" % (f, len(groups), ", missing in " + ", ".join(missing) if missing else ""))
            for g in groups:
                print("    " + ", ".join(n for n, _ in g))
    if not differs:
        print("shared web-app files are identical in: " + ", ".join(n for n, _ in found))
    return differs


def sync(root, source):
    found = dict(repos(root))
    if source not in found:
        sys.exit("unknown repo %s (have: %s)" % (source, ", ".join(found)))
    for name, path in found.items():
        if name == source:
            continue
        os.makedirs(os.path.join(path, "webapp"), exist_ok=True)
        for f in SHARED:
            src, dst = os.path.join(found[source], "webapp", f), os.path.join(path, "webapp", f)
            if os.path.exists(src) and not (os.path.exists(dst) and filecmp.cmp(src, dst, shallow=False)):
                shutil.copyfile(src, dst)
                print("updated %s/webapp/%s" % (name, f))
        if not os.path.exists(os.path.join(path, "webapp", "config.json")):
            print("NOTE %s has no webapp/config.json: copy one and set title, port and screenshots" % name)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=DEFAULT_ROOT, help="folder holding the repos (default: %(default)s)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    c = sub.add_parser("check")
    c.add_argument("--full", action="store_true", help="also run the slow checks (topic code, game)")
    sub.add_parser("drift")
    s = sub.add_parser("sync-webapp")
    s.add_argument("source", choices=sorted(REPOS))
    a = ap.parse_args()
    if a.cmd == "status":
        status(a.root)
    elif a.cmd == "check":
        check(a.root, a.full)
    elif a.cmd == "drift":
        sys.exit(1 if drift(a.root) else 0)
    else:
        sync(a.root, a.source)


if __name__ == "__main__":
    main()
