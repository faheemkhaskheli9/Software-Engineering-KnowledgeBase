"""Regenerate INDEX.md and llms.txt from the frontmatter of every topic file.

Run after adding or editing a topic:  python build_index.py
Stdlib only; parses the simple frontmatter shape used in _template.md.
Fails on invalid frontmatter (missing keys, category not the folder, unknown
status, undated last_verified, empty sources/use_cases), two topics with the
same file name (a [[link]] names only the file), a missing template
section, a thin section (under MIN_WORDS words, or a ## Related with no
[[links]]), a broken [[link]] (topics and glossary.md), or a relative
Markdown link in any .md file whose target file or #anchor does not exist;
warns on orphan topics and on topics whose last_verified is older than STALE_DAYS;
prints info lines for topics only one other topic links to and for the
number of topics no glossary.md term links to.
"""
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
GLOSSARY = "glossary.md"  # not a topic, but its [[links]] are checked
SKIP = {"README.md", "AGENTS.md", "CLAUDE.md", "INDEX.md", "ROADMAP.md", "_template.md", GLOSSARY}
SKIP_DIRS = ("webapp/", "docs/")  # tooling and its docs, not topics (their relative links are still checked)
STALE_DAYS = {"reliability": 90, "security": 90}  # cite versions and limits that move fast
DEFAULT_STALE_DAYS = 180
STATUSES = ("draft", "stable", "needs-review")
SECTIONS = ("Summary", "Key concepts", "When to use / scenarios", "How it works / example",
            "Trade-offs", "Gotchas", "Related", "References")  # as in _template.md
MIN_WORDS = 15  # per section; words, not lines, since a Summary is often one long line


def strip_code(text):
    return re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))


def links(text):
    """[[wiki-links]] in prose; code is stripped so `[[1, 2]]` lists don't count."""
    return [l.strip() for l in re.findall(r"\[\[([^\]|#]+)", strip_code(text))]


def anchors(text):
    """GitHub-style heading anchors: lowercase, punctuation dropped, spaces to '-', -1 on repeats."""
    seen, out = Counter(), set()
    # Drop fenced code (its '# comment' lines are not headings) but keep inline code:
    # GitHub slugs "## Use `foo()`" as "use-foo", so the code text is part of the anchor.
    prose = re.sub(r"```.*?```", "", text.replace("\r\n", "\n"), flags=re.S)
    for h in re.findall(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", prose, re.M):
        slug = re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-")
        out.add(f"{slug}-{seen[slug]}" if seen[slug] else slug)
        seen[slug] += 1
    return out


def md_link_errors(path, text):
    """Relative Markdown links in prose ([x](../a.md#b), [x](#b)) whose file or anchor is missing."""
    errs = []
    for target in re.findall(r"\]\(<?([^)\s>]+)", strip_code(text)):
        if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I):  # http:, mailto:, ...
            continue
        file, _, anchor = target.partition("#")
        file = file.split("?")[0]
        dest = path.parent / file
        if file and not dest.exists():
            errs.append(f"{target} (no such file)")
        elif anchor and (not file or dest.suffix == ".md") and anchor not in anchors(
                dest.read_text(encoding="utf-8") if file else text):
            errs.append(f"{target} (no such anchor)")
    return errs


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---", text.replace("\r\n", "\n"), re.S)
    if not m:
        return None
    meta, key = {}, None
    for line in m.group(1).splitlines():
        if line.startswith("  - ") and key:
            meta.setdefault(key, []).append(line[4:].strip().strip('"'))
        elif ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if val and val[0] in "\"'" and val[0] in val[1:]:  # quoted: '#' inside is text, not a comment
                meta[key] = val[1:val.index(val[0], 1)]
                continue
            val = re.sub(r"(^|\s)#.*", "", val).strip()  # YAML comment: '#' after whitespace, so "C#" stays
            if val.startswith("["):
                meta[key] = [v.strip() for v in val.strip("[]").split(",") if v.strip()]
            elif val:
                meta[key] = val
    return meta


def cell(text):
    """Text safe inside a Markdown table cell: a literal '|' would start a new column."""
    return text.replace("|", "\\|")


def summary_line(text):
    """First sentence of the ## Summary section, for llms.txt."""
    m = re.search(r"^## Summary\n+(.+?)(?:\n\n|\n#|\Z)", text.replace("\r\n", "\n"), re.S | re.M)
    if not m:
        return ""
    return re.split(r"(?<=[.!?])\s", " ".join(m.group(1).split()), maxsplit=1)[0]


def problems(rel, text):
    """Frontmatter and template-section errors for one topic file; [] if it is valid."""
    meta = frontmatter(text)
    if not meta:
        return ["no frontmatter"]
    errs = [f"missing {k}" for k in ("title", "category", "status", "last_verified") if k not in meta]
    folder = rel.split("/")[0]
    if "category" in meta and meta["category"] != folder:
        errs.append(f"category {meta['category']!r} does not match folder {folder!r}")
    if "status" in meta and meta["status"] not in STATUSES:
        errs.append(f"status {meta['status']!r} not one of {', '.join(STATUSES)}")
    if "last_verified" in meta:
        try:
            date.fromisoformat(meta["last_verified"])
        except ValueError:
            errs.append(f"last_verified {meta['last_verified']!r} is not a YYYY-MM-DD date")
    errs += [f"{k} is empty" for k in ("sources", "use_cases") if not meta.get(k)]
    prose = re.sub(r"```.*?```", "", text.replace("\r\n", "\n"), flags=re.S)
    errs += [f"missing section ## {s}" for s in SECTIONS
             if not re.search(rf"^## {re.escape(s)}[ \t]*$", prose, re.M)]
    # Section bodies, code kept as content but with its '#' lines unable to start a heading.
    body = re.sub(r"```.*?```", lambda m: m.group().replace("\n#", "\n "), text.replace("\r\n", "\n"), flags=re.S)
    parts = re.split(r"^## (.+?)[ \t]*$", body, flags=re.M)
    sections = dict(zip(parts[1::2], parts[2::2]))
    errs += [f"thin section ## {s} (under {MIN_WORDS} words)" for s in SECTIONS
             if s in sections and len(sections[s].split()) < MIN_WORDS]
    if "Related" in sections and not links(sections["Related"]):
        errs.append("## Related has no [[links]]")
    return errs


def stale_days(category, verified, today):
    """Days past the category's threshold, or None if fresh/undated."""
    try:
        age = (today - date.fromisoformat(verified)).days
    except (TypeError, ValueError):
        return None
    limit = STALE_DAYS.get(category, DEFAULT_STALE_DAYS)
    return age - limit if age > limit else None


def build(today=None):
    today = today or date.today()
    groups, bad, stale, out_links, llms = {}, [], [], {}, {}
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        if path.name in SKIP or rel.startswith((".", *SKIP_DIRS)):
            continue
        text = path.read_text(encoding="utf-8")
        if path.stem in out_links:  # [[stem]] links resolve by file name alone
            bad.append(f"{rel}: same file name as {out_links[path.stem][0]}, so [[{path.stem}]] is ambiguous")
            continue
        out_links[path.stem] = (rel, links(text))
        errs = problems(rel, text)
        if errs:
            bad += [f"{rel}: {e}" for e in errs]
            continue
        meta = frontmatter(text)
        cat = meta.get("category", rel.split("/")[0])
        verified = meta.get("last_verified", "?")
        uses = meta.get("use_cases", [])
        groups.setdefault(cat, []).append(
            f"| [{cell(meta['title'])}]({rel}) | {cat} "
            f"| {cell(', '.join(meta.get('tags', [])))} | {cell('; '.join(uses[:3]))} "
            f"| {meta.get('status', '?')} | {verified} |"
        )
        llms.setdefault(cat, []).append(f"- [{meta['title']}]({rel}): {summary_line(text)}".rstrip(": "))
        over = stale_days(cat, verified, today)
        if over is not None:
            stale.append(f"{rel} (last_verified {verified}, {over} days past the limit)")

    total = sum(len(r) for r in groups.values())
    out = [
        "# Index",
        "",
        "Generated by `python build_index.py` - do not edit by hand.",
        f"{total} topics. Match your task against Tags / Use when, then read the full file.",
        "Terms: [glossary.md](glossary.md).",
        "",
        " | ".join(f"[{c} ({len(groups[c])})](#{c})" for c in sorted(groups)),
        "",
    ]
    for cat in sorted(groups):
        out += [
            f"## {cat}",
            "",
            f"{len(groups[cat])} topics.",
            "",
            "| Topic | Category | Tags | Use when | Status | Verified |",
            "|---|---|---|---|---|---|",
            *groups[cat],
            "",
        ]
    (ROOT / "INDEX.md").write_text("\n".join(out), encoding="utf-8", newline="\n")

    txt = [
        "# Software Engineering Knowledge Base",
        "",
        "> Reference on software engineering and system design for people and AI coding agents.",
        "> One topic per Markdown file; INDEX.md has tags and use cases, glossary.md defines terms.",
        "",
    ]
    for cat in sorted(llms):
        txt += [f"## {cat}", "", *llms[cat], ""]
    txt += ["## Optional", "", "- [Glossary](glossary.md): terms linked to the topic that explains each", ""]
    (ROOT / "llms.txt").write_text("\n".join(txt), encoding="utf-8", newline="\n")

    broken = [f"{rel} -> [[{l}]]" for rel, ls in out_links.values() for l in ls if l not in out_links]
    gloss = ROOT / GLOSSARY
    glossed = set(links(gloss.read_text(encoding="utf-8"))) if gloss.exists() else set()
    broken += [f"{GLOSSARY} -> [[{l}]]" for l in sorted(glossed) if l not in out_links]
    unglossed = sum(stem not in glossed for stem in out_links)
    for path in sorted(ROOT.rglob("*.md")):  # every Markdown file, generated INDEX.md included
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith("."):
            broken += [f"{rel} -> {e}" for e in md_link_errors(path, path.read_text(encoding="utf-8"))]
    inbound = Counter(l for stem, (_, ls) in out_links.items() for l in set(ls) if l != stem)
    orphans = sorted(rel for stem, (rel, _) in out_links.items() if not inbound[stem])
    weak = sorted(rel for stem, (rel, _) in out_links.items() if inbound[stem] == 1)
    return total, bad, broken, orphans, stale, weak, unglossed


if __name__ == "__main__":
    total, bad, broken, orphans, stale, weak, unglossed = build()
    print(f"indexed {total} topics")
    print(f"info: {unglossed} topic(s) have no {GLOSSARY} term linking to them")
    if orphans:
        print(f"warning: {len(orphans)} topic(s) no other topic links to: {orphans}")
    if weak:
        print(f"info: {len(weak)} topic(s) only one other topic links to: {weak}")
    if stale:
        print(f"warning: {len(stale)} topic(s) due for re-verification:")
        print("\n".join(f"  {s}" for s in stale))
    if bad or broken:
        raise SystemExit("\n".join(["invalid topics:", *(f"  {b}" for b in bad),
                                    "broken links:", *(f"  {b}" for b in broken)]))
