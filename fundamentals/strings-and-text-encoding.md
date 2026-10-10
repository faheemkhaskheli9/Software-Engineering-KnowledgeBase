---
title: Strings and text encoding
category: fundamentals
tags: [unicode, utf-8, utf-16, encoding, normalization, grapheme, mojibake, bytes-vs-str, collation]
use_cases:
  - "fix mojibake like 'cafÃ©' appearing in a CSV import or API response"
  - "truncate a user name to a length limit without breaking emoji or accents"
  - "compare or deduplicate names that look identical but are different strings"
  - "decide what encoding to use for files, databases and HTTP APIs"
  - "count characters the way a user would for a tweet-style length limit"
status: draft
last_verified: 2026-10-10
sources:
  - "The Unicode Standard - https://www.unicode.org/versions/latest/"
  - "RFC 3629, UTF-8, a transformation format of ISO 10646 - https://www.rfc-editor.org/rfc/rfc3629"
  - "UAX 15, Unicode Normalization Forms - https://www.unicode.org/reports/tr15/"
  - "UAX 29, Unicode Text Segmentation - https://www.unicode.org/reports/tr29/"
  - "Python Unicode HOWTO - https://docs.python.org/3/howto/unicode.html"
  - "The Absolute Minimum Every Software Developer Must Know About Unicode, Joel Spolsky, 2003"
---

# Strings and text encoding

## Summary
Text is a sequence of Unicode code points; bytes are what files, sockets and databases store. An encoding (UTF-8, UTF-16, Latin-1) maps one to the other, and nearly every text bug is a mismatch between the encoding used to write and the one assumed to read. Decode at the input boundary, work with text inside, encode at the output boundary, and use UTF-8 everywhere you have a choice.

## Key concepts
- **Code point:** a number assigned to an abstract character (`U+00E9` is e with acute). Unicode code points range up to `U+10FFFF`.
- **Encoding:** a mapping from code points to bytes.
  - *UTF-8:* 1 to 4 bytes per code point, ASCII-compatible, no byte-order issues. The default for the web and most modern systems.
  - *UTF-16:* 2 or 4 bytes (surrogate pairs above `U+FFFF`). Used internally by Java, JavaScript, .NET and Windows APIs.
  - *UTF-32:* fixed 4 bytes; simple indexing, wasteful.
  - *Latin-1 / Windows-1252:* single-byte legacy encodings; every byte decodes to something, so wrong decoding fails silently.
- **Bytes vs str:** Python 3 separates `bytes` and `str`; `.encode()` and `.decode()` cross the boundary. Most languages have the same split, sometimes less strictly.
- **Grapheme cluster:** what a user perceives as one character. `e` + combining acute, a flag (two regional indicators) and a family emoji (several code points joined by ZWJ) are each one grapheme but several code points.
- **Normalization (UAX #15):** the same text can have different code point sequences (precomposed `é` vs `e` + `U+0301`). NFC composes, NFD decomposes; NFKC/NFKD also fold compatibility variants (full-width letters, ligatures).
- **Case folding:** `casefold()` is the correct basis for case-insensitive comparison; `lower()` is not enough for all scripts.
- **Collation:** sorting order is locale-dependent; code point order is not alphabetical for most languages.
- **BOM:** an optional byte-order mark at file start (`EF BB BF` in UTF-8). Some tools emit it, many parsers choke on it.
- **Mojibake:** garbled text from decoding bytes with the wrong encoding, e.g. UTF-8 bytes read as Windows-1252.
- **Length is ambiguous:** bytes, UTF-16 code units, code points and graphemes give different counts for the same string.

## When to use / scenarios
- Reading files, HTTP bodies, subprocess output or DB rows: always specify the encoding explicitly (`open(path, encoding="utf-8")`).
- Storing user text: UTF-8 in the database, with a charset that covers 4-byte characters (in MySQL, `utf8mb4`, not legacy `utf8`).
- Usernames, identifiers and dedup keys: normalize (NFC or NFKC) and case-fold before comparing or indexing; consider confusable-character checks for security-sensitive identifiers.
- Length limits shown to users: count graphemes; length limits enforced by storage: count bytes in the target encoding.
- Truncating: cut on grapheme boundaries, never in the middle of a multi-byte sequence.
- NOT needed: guessing encodings for data you control. Detection libraries are a last resort for unknown legacy input.

## How it works / example

UTF-8 byte layout:

```
U+0000..U+007F    0xxxxxxx                              1 byte (ASCII)
U+0080..U+07FF    110xxxxx 10xxxxxx                     2 bytes
U+0800..U+FFFF    1110xxxx 10xxxxxx 10xxxxxx            3 bytes
U+10000..U+10FFFF 11110xxx 10xxxxxx 10xxxxxx 10xxxxxx   4 bytes
```

Lengths, mojibake, normalization and case folding with the stdlib:

```python
import unicodedata

s = "café \U0001F600"                       # 'café 😀'
print(len(s))                                    # 6 code points
print(len(s.encode("utf-8")))                    # 10 bytes in UTF-8
print(len(s.encode("utf-16-le")) // 2)           # 7 UTF-16 code units (emoji is a surrogate pair)

# Mojibake: UTF-8 bytes decoded as Windows-1252
garbled = "café".encode("utf-8").decode("cp1252")
print(garbled)                                   # cafÃ©
print(garbled.encode("cp1252").decode("utf-8"))  # repaired: café

# Normalization: visually identical, different code points
a, b = "é", "é"
print(a == b)                                                    # False
print(unicodedata.normalize("NFC", a) == unicodedata.normalize("NFC", b))  # True

# Case-insensitive comparison
print("Straße".lower() == "STRASSE".lower())         # False
print("Straße".casefold() == "STRASSE".casefold())   # True
```

Safe byte-limited truncation (never splits a code point). Grapheme-aware truncation needs a UAX #29 segmenter such as the third-party `regex` module's `\X`:

```python
def truncate_utf8(text: str, max_bytes: int) -> str:
    data = text.encode("utf-8")[:max_bytes]
    return data.decode("utf-8", errors="ignore")   # drops a trailing partial sequence

print(truncate_utf8("naïve 😀 text", 9))           # 'naïve ' - the emoji did not fit
assert len(truncate_utf8("😀😀", 5).encode()) <= 5
```

## Trade-offs
- **UTF-8 vs UTF-16:** UTF-8 is compact for ASCII-heavy text and has no byte-order ambiguity; UTF-16 matches platform APIs (JS, Java, Windows) and can be smaller for some East Asian text. Convert at the boundary.
- **NFC vs NFKC:** NFC preserves meaning and is the usual storage form; NFKC folds look-alikes (useful for identifiers and search) but loses distinctions like superscripts.
- **Strict vs lenient decoding:** `errors="strict"` surfaces bad data early; `errors="replace"` keeps pipelines running but hides corruption. Pick strict for data you own.
- **Storing normalized vs original:** normalizing on write simplifies comparison; keeping the original preserves what the user typed. Many systems store both: original for display, normalized key for lookup.

## Gotchas
- Platform default encodings differ (Windows has historically used a locale code page, not UTF-8); never rely on the default in `open()` or `subprocess`.
- JavaScript `"😀".length` is 2 (UTF-16 code units); Python `len` is 1 (code points); a user sees 1 grapheme; a flag emoji is 2 code points. Agree which count a limit means.
- Slicing a string by index can split a grapheme (strip an accent or half a flag).
- `.lower()`/`.upper()` are locale-insensitive in Python; Turkish dotted and dotless i need locale-aware handling.
- A UTF-8 BOM at the start of a CSV or JSON file can break header matching or parsers.
- MySQL's legacy `utf8` charset stores at most 3 bytes per character and rejects or truncates emoji; use `utf8mb4`.
- Mixing `str` and `bytes` in Python raises `TypeError`; in Python 2 or in C, the same mistake silently corrupts data.
- Homoglyph attacks: Cyrillic `а` looks like Latin `a`; normalize and restrict identifier scripts where spoofing matters ([[owasp-top-10]]).
- URL, HTML and SQL escaping are separate from character encoding; treating them as the same causes injection bugs.

## Related
- [[core-data-structures]] - strings as arrays of code units and their cost model
- [[networking-fundamentals]] - charsets in HTTP headers and protocols
- [[rest-api-design]] - declaring `charset=utf-8` in content types
- [[data-modeling-and-schema-design]] - column charsets, collations and normalized lookup keys
- [[owasp-top-10]] - injection and spoofing via encoding tricks

## References
- The Unicode Standard; UAX #15 (normalization); UAX #29 (grapheme clusters)
- RFC 3629 (UTF-8)
- Python docs: Unicode HOWTO, `unicodedata`, codecs error handlers
- Spolsky, "The Absolute Minimum Every Software Developer Absolutely, Positively Must Know About Unicode and Character Sets" (2003)
