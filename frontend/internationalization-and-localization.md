---
title: Internationalization and localization
category: frontend
tags: [i18n, l10n, locale, cldr, icu, intl, messageformat, plural-rules, time-zones, iana-tz, zoneinfo, rtl, bidi, pseudo-localization, collation]
use_cases:
  - "prepare our web app to be translated into several languages"
  - "show prices, numbers and dates in each user's local format"
  - "store event times so they display correctly across time zones and DST changes"
  - "support right-to-left languages like Arabic and Urdu"
  - "catch hard-coded strings and truncated labels before translation starts"
status: draft
last_verified: 2026-10-11
sources:
  - https://www.w3.org/International/questions/qa-i18n
  - https://cldr.unicode.org/
  - https://cldr.unicode.org/index/cldr-spec/plural-rules
  - https://unicode-org.github.io/icu/userguide/format_parse/messages/
  - https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl
  - https://docs.python.org/3/library/zoneinfo.html
  - https://www.iana.org/time-zones
  - https://www.w3.org/International/questions/qa-html-dir
  - https://www.unicode.org/reports/tr9/
  - https://www.unicode.org/reports/tr10/
  - https://learn.microsoft.com/en-us/globalization/methodology/pseudolocalization
---

# Internationalization and localization

## Summary
Internationalization (i18n) is designing and building software so it can be
adapted to different languages, regions and cultures without code changes;
localization (l10n) is the adaptation itself for one target locale:
translated text, local formats, and cultural fit. Good i18n means Unicode
end to end, every user-visible string externalised as a complete message,
locale-aware formatting from CLDR data (via ICU or the JavaScript `Intl` API),
timestamps stored in UTC and converted with IANA time zones at the edge, and
layouts that survive right-to-left scripts and longer translations. Encoding
details are in [[strings-and-text-encoding]]; this topic covers the layer above.

## Key concepts
- **i18n vs l10n:** W3C defines localization as adapting content to the language, cultural and other requirements of a target market (a locale), and internationalization as the design and development that enables easy localization. The numerals count letters between the first and last ("i18n" has 18).
- **Locale:** identified by a BCP 47 language tag such as `de-AT`, `zh-Hans-CN` or `ur-PK`: language, optional script and region, plus extensions (`-u-nu-thai` for Thai digits). A locale is not a country and not a language alone.
- **CLDR and ICU:** the Unicode Common Locale Data Repository is the shared data for number, date, currency, plural and collation rules; ICU is the reference library that applies it. JavaScript `Intl`, Java, Android, iOS and Python's Babel build on this data.
- **Locale-aware formatting:** decimal and grouping separators, digit systems, currency symbol position, date order, calendar and first day of week all vary. Use `Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.RelativeTimeFormat` and `Intl.ListFormat` (browser) or ICU/Babel (server), never string templates like `f"{m}/{d}/{y}"`.
- **Plural rules:** CLDR defines the categories `zero`, `one`, `two`, `few`, `many`, `other`; `other` is required. English uses `one` and `other`; other languages use more. `Intl.PluralRules` picks the category; messages carry one branch per category the locale uses.
- **Message format:** ICU MessageFormat patterns hold placeholders, `plural` and `select` (e.g. gender) arguments in one string, so translators can reorder words. A message has to be written and translated as a single unit; never concatenate fragments.
- **Time:** store instants in UTC (or with an explicit offset); store the user's IANA zone name (`America/New_York`, `Asia/Karachi`), not a fixed offset, because offsets change with daylight saving time and with law. Convert to local time only for display or for rules defined in local time (opening hours, "9 am every Monday").
- **Right-to-left and bidi:** Arabic, Hebrew, Urdu and Persian run right to left, mixed with left-to-right numbers and names. Set `dir="rtl"` on the `<html>` element (W3C advises not to use CSS for base direction); use `dir="auto"` or `<bdi>` for user-supplied text of unknown direction; use CSS logical properties (`margin-inline-start`) so layouts mirror. The Unicode Bidirectional Algorithm (UAX #9) orders the characters.
- **Collation:** alphabetical order is locale-specific (UTS #10, the Unicode Collation Algorithm); sorting by code point is wrong for most languages. Use `Intl.Collator` or ICU.
- **Pseudo-localization:** an automated fake translation (accented letters, padding for expansion, delimiters) that exposes hard-coded strings, truncation, concatenation and font problems before any real translation exists.

## When to use / scenarios
- Any product that may launch in a second market or language: do the i18n plumbing (externalised strings, `Intl`, UTC storage) from the start; retrofitting means touching every screen.
- Scheduling, booking, reminders, billing cut-offs: UTC instant plus IANA zone, DST-aware conversion, and tests across transitions.
- User-generated content in many scripts: Unicode storage, `dir="auto"`, locale-aware search and sorting.
- Marketing sites with one market: you may skip translation infrastructure, but still store UTC and use `Intl` formatting; both are cheap.
- Not this topic: byte encodings, normalization and grapheme counting ([[strings-and-text-encoding]]); ordering events across machines ([[time-clocks-and-ordering]]).

## How it works / example

Formatting and plurals in the browser with `Intl` (output depends on the
runtime's CLDR version):

```javascript
new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(1234.5);
new Intl.DateTimeFormat("ur-PK", { dateStyle: "long", timeZone: "Asia/Karachi" }).format(new Date());
new Intl.PluralRules("en").select(1);          // "one"
["z", "a", "ä"].sort(new Intl.Collator("de").compare);
```

An ICU message with a plural argument, one complete sentence per branch:

```
{count, plural,
  =0 {You have no new messages.}
  one {You have one new message.}
  other {You have # new messages.}}
```

Store UTC, convert at the edge, and handle DST with the stdlib `zoneinfo`
(IANA database; on Windows it needs the `tzdata` package if the OS has no
IANA data), plus a small pseudo-localizer:

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc

# Same UTC clock time either side of the 2026-03-08 spring-forward
before = datetime(2026, 3, 7, 12, 0, tzinfo=UTC).astimezone(NY)
after = datetime(2026, 3, 9, 12, 0, tzinfo=UTC).astimezone(NY)
assert (before.hour, before.tzname()) == (7, "EST")      # UTC-5
assert (after.hour, after.tzname()) == (8, "EDT")        # UTC-4

# "Same local time tomorrow" is not "+24 hours" across a DST change
meeting = datetime(2026, 3, 7, 9, 0, tzinfo=NY)          # 09:00 EST
next_day_local = meeting + timedelta(days=1)              # wall-clock arithmetic
assert next_day_local.hour == 9 and next_day_local.tzname() == "EDT"
elapsed = next_day_local.astimezone(UTC) - meeting.astimezone(UTC)
assert elapsed == timedelta(hours=23)                     # the day was 23 h long

# Ambiguous local time on 2026-11-01: 01:30 happens twice; fold picks which
first = datetime(2026, 11, 1, 1, 30, tzinfo=NY)
second = first.replace(fold=1)
assert first.utcoffset() == timedelta(hours=-4)
assert second.utcoffset() == timedelta(hours=-5)

# Round trip: storing UTC and converting back loses nothing
stored = after.astimezone(UTC)
assert stored.astimezone(NY) == after and stored.tzinfo is UTC

ACCENTS = str.maketrans("aeiouAEIOUcCnNyY", "àéîöûÀÉÎÖÛçÇñÑýÝ")

def pseudo(message: str, expansion: float = 0.4) -> str:
    """Accent letters, pad for longer translations, wrap in delimiters.
    Text inside {placeholders} is left untouched so formatting still works."""
    out, depth = [], 0
    for ch in message:
        depth += ch == "{"
        out.append(ch if depth else ch.translate(ACCENTS))
        depth -= ch == "}"
    padding = "~" * max(1, round(len(message) * expansion))
    return "[" + "".join(out) + " " + padding + "]"

p = pseudo("Save {count} files")
assert p.startswith("[") and p.endswith("]")        # missing ']' on screen = truncation
assert "{count}" in p                                # placeholder preserved
assert "Sàvé" in p and len(p) > len("Save {count} files") * 1.3
print(p)
```

The 40 % padding follows Microsoft's heuristic for English source text; they
note real translations of short strings can grow far more.

## Trade-offs
- **Client-side vs server-side formatting:** `Intl` in the browser uses the user's environment and no extra data download, but output differs by browser version; server-side ICU/Babel is consistent and testable but must know the user's locale and zone.
- **Bundling all locales vs loading per locale:** one bundle is simple but grows with every language; per-locale chunks keep pages light but add a request and a loading state ([[web-performance]]).
- **Translation keys vs source-text keys:** opaque keys (`checkout.pay_button`) are stable when English copy changes; source-text keys (gettext style) are readable but every copy edit invalidates translations.
- **Machine vs human translation:** machine translation is fast and cheap for coverage; human review is needed for legal, marketing and UI terms where tone and length matter.
- **Storing UTC only vs UTC plus local intent:** UTC is right for instants that already happened; future events defined in local time ("10:00 in Berlin next July") should store local time plus zone, because the zone's rules may change before then.

## Gotchas
- Concatenating fragments (`"You have " + n + " items"`) cannot be translated correctly; word order and plural forms differ.
- `if n == 1 else` plural logic is English-only; use CLDR plural rules.
- Storing a fixed offset (`-05:00`) instead of a zone name breaks at the next DST change.
- Nonexistent local times (02:30 on a spring-forward day) and repeated ones (01:30 on a fall-back day) need an explicit policy; libraries resolve them silently and differently.
- Server-side code using the host's local time zone gives different results per machine; set servers to UTC and pass zones explicitly ([[time-clocks-and-ordering]]).
- Flags are not languages: Spanish is not Spain, and a country can have several official languages. Pick language and region separately.
- Assuming text length: German and Finnish run longer, CJK shorter and taller; fixed-width buttons truncate.
- Mirroring everything in RTL is wrong for some content: numbers, media controls, code and brand logos usually keep their direction.
- Sorting with plain `sorted()` or `ORDER BY` on a binary collation orders by code point, not by any language's alphabet; pick a locale-aware collation in the database ([[data-modeling-and-schema-design]]).
- Turkish dotted and dotless `i` break naive case-insensitive comparisons ([[strings-and-text-encoding]]).
- `zoneinfo` raises `ZoneInfoNotFoundError` on systems with no IANA data unless `tzdata` is installed; declare the dependency.
- Missing `lang` attribute: screen readers pronounce text with the wrong voice ([[accessibility-basics]]).

## Related
- [[strings-and-text-encoding]] - UTF-8, normalization, graphemes and case folding underneath every localized string.
- [[time-clocks-and-ordering]] - wall clocks vs monotonic clocks and ordering across machines.
- [[data-modeling-and-schema-design]] - timestamp column types, collations and per-locale content tables.
- [[rest-api-design]] - `Accept-Language`, ISO 8601 timestamps with offsets in API payloads.
- [[accessibility-basics]] - `lang` and `dir` attributes are accessibility requirements too.
- [[web-performance]] - per-locale bundles and web fonts for many scripts.
- [[floating-point-and-money]] - keep amounts exact with minor units per currency; format them only at the edge.

## References
- W3C Internationalization, Localization vs. Internationalization: https://www.w3.org/International/questions/qa-i18n
- Unicode CLDR: https://cldr.unicode.org/ and Plural rules: https://cldr.unicode.org/index/cldr-spec/plural-rules
- ICU User Guide, Formatting Messages: https://unicode-org.github.io/icu/userguide/format_parse/messages/
- MDN, `Intl`: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl
- Python docs, `zoneinfo` (PEP 615): https://docs.python.org/3/library/zoneinfo.html
- IANA Time Zone Database: https://www.iana.org/time-zones
- W3C Internationalization, Structural markup and right-to-left text in HTML: https://www.w3.org/International/questions/qa-html-dir
- Unicode UAX #9, Bidirectional Algorithm: https://www.unicode.org/reports/tr9/
- Unicode UTS #10, Collation Algorithm: https://www.unicode.org/reports/tr10/
- Microsoft Learn, Pseudolocalization: https://learn.microsoft.com/en-us/globalization/methodology/pseudolocalization
