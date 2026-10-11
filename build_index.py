"""Regenerate INDEX.md and llms.txt from the frontmatter of every topic file.

Run after adding or editing a topic:  python build_index.py
Stdlib only; parses the simple frontmatter shape used in _template.md.
Fails on invalid frontmatter (missing keys, category not the folder, unknown
status, undated last_verified, empty sources/use_cases), a missing template
section, a thin section (under MIN_WORDS words, or a ## Related with no
[[links]]), or a broken [[link]] (topics and glossary.md);
warns on orphan topics and on topics whose last_verified is older than STALE_DAYS;
prints an info line for topics only one other topic links to.
"""
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent
GLOSSARY = "glossary.md"  # not a topic, but its [[links]] are checked
SKIP = {"README.md", "AGENTS.md", "CLAUDE.md", "INDEX.md", "ROADMAP.md", "_template.md", GLOSSARY}
STALE_DAYS = {"reliability": 90, "security": 90}  # cite versions and limits that move fast
DEFAULT_STALE_DAYS = 180
STATUSES = ("draft", "stable", "needs-review")
SECTIONS = ("Summary", "Key concepts", "When to use / scenarios", "How it works / example",
            "Trade-offs", "Gotchas", "Related", "References")  # as in _template.md
MIN_WORDS = 15  # per section; words, not lines, since a Summary is often one long line


def links(text):
    """[[wiki-links]] in prose; code is stripped so `[[1, 2]]` lists don't count."""
    prose = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", text, flags=re.S))
    return [l.strip() for l in re.findall(r"\[\[([^\]|#]+)", prose)]


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
            key, val = key.strip(), val.split("#")[0].strip()
            if val.startswith("["):
                meta[key] = [v.strip() for v in val.strip("[]").split(",") if v.strip()]
            elif val:
                meta[key] = val.strip('"')
    return meta


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
        if path.name in SKIP or rel.startswith("."):
            continue
        text = path.read_text(encoding="utf-8")
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
            f"| [{meta['title']}]({rel}) | {cat} "
            f"| {', '.join(meta.get('tags', []))} | {'; '.join(uses[:3])} "
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
    if gloss.exists():
        broken += [f"{GLOSSARY} -> [[{l}]]" for l in links(gloss.read_text(encoding="utf-8"))
                   if l not in out_links]
    inbound = Counter(l for stem, (_, ls) in out_links.items() for l in set(ls) if l != stem)
    orphans = sorted(rel for stem, (rel, _) in out_links.items() if not inbound[stem])
    weak = sorted(rel for stem, (rel, _) in out_links.items() if inbound[stem] == 1)
    return total, bad, broken, orphans, stale, weak


if __name__ == "__main__":
    total, bad, broken, orphans, stale, weak = build()
    print(f"indexed {total} topics")
    if orphans:
        print(f"warning: {len(orphans)} topic(s) no other topic links to: {orphans}")
    if weak:
        print(f"info: {len(weak)} topic(s) only one other topic links to: {weak}")
    if stale:
        print(f"warning: {len(stale)} topic(s) due for re-verification:")
        print("\n".join(f"  {s}" for s in stale))
    if bad or broken:
        raise SystemExit("\n".join(["invalid topics:", *(f"  {b}" for b in bad),
                                    "broken [[links]]:", *(f"  {b}" for b in broken)]))
