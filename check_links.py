"""Check that every URL in topic `sources` frontmatter resolves.

Usage:  python check_links.py [topic.md ...]   (default: every topic)
Prints each non-2xx URL under its file. 403 and 429 are warnings (sites that
block bots, e.g. oreilly.com, dl.acm.org); any other HTTP error or a network
failure is an error and makes the exit code 1. Stdlib only. Network-bound, so
CI runs it on a schedule and on demand, not on every push.
"""
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from build_index import ROOT, frontmatter
from check_code import topics

TIMEOUT = 20
WARN = {403, 429}
HEADERS = {  # some sites answer 406 without browser-like Accept headers
    "User-Agent": "Mozilla/5.0 (link checker; +https://github.com/faheemkhaskheli9/Software-Engineering-KnowledgeBase)",
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def status(url):
    """HTTP status after redirects, or the exception text if the request failed."""
    for method in ("HEAD", "GET"):  # some servers reject HEAD with 403/405
        try:
            with urllib.request.urlopen(urllib.request.Request(url, method=method, headers=HEADERS),
                                        timeout=TIMEOUT) as r:
                return r.status
        except urllib.error.HTTPError as e:
            code = e.code
        except Exception as e:  # DNS, TLS, timeout, connection reset
            code = f"{type(e).__name__}: {e}"
    return code


if __name__ == "__main__":
    by_file = {}
    for path in topics(sys.argv[1:]):
        meta = frontmatter(path.read_text(encoding="utf-8")) or {}
        urls = [u.rstrip(".,;)\"'") for s in meta.get("sources", []) for u in re.findall(r"https?://\S+", s)]
        by_file[path.relative_to(ROOT).as_posix()] = urls
    unique = sorted({u for urls in by_file.values() for u in urls})
    with ThreadPoolExecutor(16) as pool:
        result = dict(zip(unique, pool.map(status, unique)))
    errors = warnings = 0
    for rel, urls in by_file.items():
        bad = [(u, result[u]) for u in urls if not (isinstance(result[u], int) and result[u] < 300)]
        if bad:
            print(rel)
        for url, code in bad:
            warn = code in WARN
            warnings += warn
            errors += not warn
            print(f"  {'WARN' if warn else 'FAIL'} {code} {url}")
    print(f"{len(unique)} unique URLs: {errors} failed, {warnings} warnings")
    sys.exit(1 if errors else 0)
