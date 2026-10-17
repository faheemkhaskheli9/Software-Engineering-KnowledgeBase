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


def source_urls(sources):
    """URLs in `sources` entries, minus trailing punctuation from the surrounding prose.

    A trailing ')' is dropped only when unbalanced, so a URL such as
    https://en.wikipedia.org/wiki/Fallacies_(computing) keeps its own parenthesis.
    """
    out = []
    for entry in sources:
        for url in re.findall(r"https?://\S+", entry):
            while url and (url[-1] in ".,;\"'" or (url[-1] == ")" and url.count(")") > url.count("("))):
                url = url[:-1]
            out.append(url)
    return out


if __name__ == "__main__":
    by_file = {}
    for path in topics(sys.argv[1:]):
        meta = frontmatter(path.read_text(encoding="utf-8")) or {}
        by_file[path.relative_to(ROOT).as_posix()] = source_urls(meta.get("sources", []))
    unique = sorted({u for urls in by_file.values() for u in urls})
    with ThreadPoolExecutor(16) as pool:
        result = dict(zip(unique, pool.map(status, unique)))
    for rel, urls in by_file.items():
        bad = [(u, result[u]) for u in urls if not (isinstance(result[u], int) and result[u] < 300)]
        if bad:
            print(rel)
        for url, code in bad:
            print(f"  {'WARN' if code in WARN else 'FAIL'} {code} {url}")
    # Counted per unique URL, like the total: a URL cited by five topics is one failure, not five.
    failed = [u for u in unique if not (isinstance(result[u], int) and result[u] < 300)]
    warnings = sum(result[u] in WARN for u in failed)
    errors = len(failed) - warnings
    print(f"{len(unique)} unique URLs: {errors} failed, {warnings} warnings")
    sys.exit(1 if errors else 0)
