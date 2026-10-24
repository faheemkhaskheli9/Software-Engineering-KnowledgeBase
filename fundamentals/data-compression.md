---
title: Data compression for engineers
category: fundamentals
tags: [compression, gzip, deflate, zlib, zstd, zstandard, brotli, lz4, snappy, compression-dictionary, decompression-bomb, breach, content-encoding]
use_cases:
  - "pick a compression algorithm and level for API responses, logs, backups or Kafka messages"
  - "shrink many small JSON messages that barely compress on their own"
  - "decompress user-uploaded or network data without a zip bomb exhausting memory"
  - "decide whether to compress before encrypting and what the BREACH attack means for responses with secrets"
  - "cut storage and egress cost for large text or columnar data"
status: draft
last_verified: 2026-10-24
sources:
  - https://www.rfc-editor.org/rfc/rfc1951
  - https://www.rfc-editor.org/rfc/rfc1952
  - https://www.rfc-editor.org/rfc/rfc7932
  - https://www.rfc-editor.org/rfc/rfc8878
  - https://www.rfc-editor.org/rfc/rfc7457
  - https://docs.python.org/3/library/zlib.html
  - https://peps.python.org/pep-0784/
  - https://kafka.apache.org/documentation/#producerconfigs_compression.type
---

# Data compression for engineers

## Summary
Lossless compression replaces repeated patterns and predictable bytes with
shorter codes, trading CPU time for fewer bytes stored or sent. Engineers meet
it in HTTP responses, log and backup files, message brokers, columnar
warehouses and databases. The practical questions are which codec and level
fits the data and the latency budget, how to compress small messages, how to
decompress untrusted input safely, and when compression leaks secrets.

## Key concepts
- **Redundancy is what compresses**: text, JSON, logs and repeated keys shrink
  a lot; random data, encrypted data and already-compressed media (JPEG, MP4,
  ZIP) do not, and get slightly larger from framing overhead.
- **LZ77 + entropy coding**: most general-purpose codecs replace repeats with
  back-references (distance, length) into a sliding window, then entropy-code
  the result. DEFLATE (RFC 1951) uses LZ77 with Huffman codes and a window of
  up to 32 KiB.
- **Codec families**:
  - *DEFLATE* in three wrappers: raw, zlib (RFC 1950) and gzip (RFC 1952,
    adds a header and CRC-32). Universal; moderate ratio and speed.
  - *Brotli* (RFC 7932): LZ77, Huffman coding and context modelling plus a
    built-in static dictionary of common web text; a strong ratio for web
    assets, with slow high levels best used at build time.
  - *Zstandard* (RFC 8878): a wide range of levels from very fast to high
    ratio, fast decompression at every level, and trained dictionaries. RFC
    8878 also registers the `zstd` HTTP content coding.
  - *LZ4, Snappy*: very fast, lower ratio; used where CPU per byte matters more
    than size (database pages, RPC, hot caches).
  - *bzip2, xz/LZMA*: high ratio, slow; archives and distribution packages.
- **Level**: higher levels search harder for matches. Compression time grows
  much faster than ratio improves; decompression speed barely changes for
  DEFLATE and Zstandard.
- **Dictionary compression**: small messages (a few hundred bytes) have little
  internal repetition. A shared dictionary of typical content, known to both
  sides, gives the compressor something to reference. zlib accepts a preset
  dictionary (`zdict`); Zstandard can train one from samples.
- **Streaming vs whole-buffer**: streaming APIs compress and decompress
  incrementally with bounded memory; required for large files and HTTP bodies.
- **Decompression bomb**: a small input that expands to gigabytes. Defend by
  capping output size, not input size.
- **Compression side channels**: when attacker-controlled input and a secret
  are compressed together, the output length reveals how much of the guess
  matched the secret. RFC 7457 summarises CRIME (TLS and SPDY-level
  compression) and BREACH (HTTP response body compression).
- **Compress then encrypt**: encrypted output looks random and does not
  compress, so compression must happen before encryption, which is exactly
  where the side channel above lives.

## When to use / scenarios
- Text-like HTTP responses (HTML, JSON, CSS, JS): enable gzip or Brotli at the
  server or CDN; precompress static assets at a high level at build time (see
  [[web-performance]]).
- Logs, exports and backups: Zstandard or gzip; pick by whether the bottleneck
  is CPU at write time or storage and transfer.
- Message brokers: compress per batch at the producer; Kafka supports `gzip`,
  `snappy`, `lz4` and `zstd` via `compression.type`. Batching first gives the
  codec more repetition to work with.
- Analytical data: columnar formats (Parquet, ORC, warehouse engines) compress
  each column separately with encodings such as dictionary and run-length,
  which beats compressing rows (see [[data-warehousing-and-olap]]).
- Many small similar messages (events, cache values, RPC payloads): try a
  shared dictionary before giving up on compression.
- When NOT to compress:
  - Already-compressed media, encrypted blobs and random identifiers.
  - Tiny payloads where headers and CPU cost outweigh savings.
  - Responses that reflect user input alongside secrets (CSRF tokens, session
    data) unless BREACH mitigations are in place.
  - CPU-bound hot paths where bandwidth is cheap and local (same rack).

## How it works / example

```
input bytes -> match finder (LZ77 window / dictionary) -> literals + (distance, length)
            -> entropy coder (Huffman / FSE / context model) -> framed output (+ checksum)
```

Ratios on repetitive vs random data, levels, framing, dictionary compression of
small messages, bounded decompression and a length oracle, with the standard
library (`zlib`, `gzip`, `lzma`):

```python
import gzip
import json
import lzma
import os
import zlib

# 1. Redundancy decides the ratio.
logs = "".join(
    json.dumps({"ts": 1_700_000_000 + i, "level": "INFO", "svc": "checkout",
                "msg": "order placed", "order_id": i, "latency_ms": i % 97}) + "\n"
    for i in range(5_000)
).encode()
random_bytes = os.urandom(len(logs))
assert len(zlib.compress(logs, 6)) < len(logs) / 5
assert len(zlib.compress(random_bytes, 6)) >= len(random_bytes)   # framing overhead, no gain

# 2. Higher levels and stronger codecs: smaller output, more CPU.
sizes = {
    "zlib-1": len(zlib.compress(logs, 1)),
    "zlib-9": len(zlib.compress(logs, 9)),
    "xz-6": len(lzma.compress(logs, preset=6)),
}
assert sizes["zlib-9"] <= sizes["zlib-1"] and sizes["xz-6"] < sizes["zlib-1"], sizes

# 3. Same DEFLATE stream, different wrappers: wbits 15 = zlib, -15 = raw, 31 = gzip, 47 = auto.
gz = gzip.compress(logs)
assert zlib.decompress(gz, wbits=31) == logs
assert zlib.decompress(zlib.compress(logs), wbits=47) == zlib.decompress(gz, wbits=47) == logs

# 4. Small messages: a preset dictionary of typical content helps a lot.
def event(i: int) -> bytes:
    return json.dumps({"type": "page_view", "user_id": f"u{i:06d}", "path": "/products/list",
                       "referrer": "https://www.example.com/", "device": "mobile"}).encode()

messages = [event(i) for i in range(1_000)]
zdict = b"".join(event(i) for i in range(900_000, 900_005))   # built from samples, shipped to both sides

def deflate(msg: bytes, zd: bytes | None = None) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15, zdict=zd) if zd else zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(msg) + c.flush()

def inflate(blob: bytes, zd: bytes) -> bytes:
    d = zlib.decompressobj(-15, zdict=zd)
    return d.decompress(blob) + d.flush()

raw = sum(map(len, messages))
plain = sum(len(deflate(m)) for m in messages)
with_dict = sum(len(deflate(m, zdict)) for m in messages)
assert inflate(deflate(messages[0], zdict), zdict) == messages[0]
assert with_dict < plain * 0.6, (raw, plain, with_dict)

# 5. Decompression bomb: cap the OUTPUT, never trust the input size.
bomb = zlib.compress(b"\0" * 50_000_000, 9)      # ~50 MB of zeros in a few tens of KB

def safe_decompress(blob: bytes, max_out: int) -> bytes:
    d = zlib.decompressobj()
    out = d.decompress(blob, max_out)            # stops after max_out bytes
    if d.unconsumed_tail or not d.eof:
        raise ValueError(f"decompressed size exceeds {max_out} bytes")
    return out

assert len(bomb) < 100_000
try:
    safe_decompress(bomb, 1_000_000)
    raise AssertionError("bomb not detected")
except ValueError:
    pass
assert safe_decompress(zlib.compress(b"ok"), 1_000_000) == b"ok"

# 6. Length oracle (the idea behind CRIME/BREACH): secret + reflected guess in one stream.
SECRET = "csrf_token=7f3a9c21e8b4d605"

def response_len(reflected: str) -> int:
    body = f"<p>You searched for {reflected}</p><input value='{SECRET}'>"
    return len(zlib.compress(body.encode(), 9))

right = response_len("csrf_token=7f3a9c21e8b4d605")
wrong = response_len("csrf_token=0b5e2d7a91c4f836")
assert right < wrong, (right, wrong)
print(f"logs {len(logs)} B -> {sizes}; small msgs {raw} -> {plain} plain, {with_dict} with dict; "
      f"oracle right={right} wrong={wrong}")
```

Python 3.14 adds Zstandard to the standard library as `compression.zstd`
(PEP 784), including dictionary training; on older versions use the
`zstandard` package. The same patterns apply: train or ship a dictionary,
stream large data, and cap decompressed size.

## Trade-offs
- **Ratio vs CPU**: the cost that matters is usually compression CPU on the
  writer (per request or per record) against bytes stored for months or sent
  across regions. Fast levels for dynamic data, slow levels for data
  compressed once and read many times.
- **Ubiquity vs efficiency**: gzip is readable everywhere (browsers, CLIs,
  every language); Zstandard and Brotli usually do better but need support at
  every consumer, including old clients and tools on the ops path.
- **Bigger batches vs latency**: compressing larger blocks finds more
  repetition but delays the first byte and increases the data lost or re-read
  on corruption; random access needs independently compressed blocks.
- **Dictionaries vs operational coupling**: a dictionary helps small messages
  but becomes a versioned artifact every producer and consumer must have;
  store its id with each message.
- **Compression vs secrecy**: compressing secrets alongside attacker input
  saves bytes and leaks information; separating them, masking tokens per
  response or disabling compression for those responses costs bytes.

## Gotchas
- Limiting the request body size but not the decompressed size: a 1 MB gzip
  upload can expand to gigabytes. Check every layer that auto-decompresses
  (proxies, frameworks, archive extractors).
- Archive extraction has its own traps beyond size: paths like `../../etc` in
  entry names (zip slip) and huge entry counts; validate paths and counts.
- Compressing encrypted data, JPEGs or already gzipped files twice wastes CPU
  for no gain; check `Content-Type` before compressing.
- Missing `Vary: Accept-Encoding` lets a cache serve a compressed body to a
  client that did not ask for it.
- `Content-Encoding: gzip` with a body that is not gzip (or double-compressed)
  produces garbage that some clients silently accept and others reject.
- Benchmarks on synthetic data mislead; ratio and speed depend heavily on the
  data. Measure on a sample of your own payloads.
- Compressing each Kafka or queue message individually instead of per batch
  loses most of the benefit for small messages.
- Checksums: raw DEFLATE has none; gzip and zlib wrappers detect corruption,
  and Zstandard frames can include a content checksum. Use a wrapped format
  for storage.

## Related
- [[web-performance]] - Content-Encoding negotiation, Brotli/gzip for web assets and precompression.
- [[data-warehousing-and-olap]] - columnar storage and per-column encodings.
- [[time-series-databases]] - delta-of-delta and XOR compression specialised for metrics.
- [[message-queues-and-streams]] - producer-side batch compression in brokers.
- [[cryptography-and-tls]] - compress-then-encrypt ordering and the side channels it creates.
- [[cloud-cost-optimization]] - compression as a lever on storage and egress bills.
- [[choosing-file-and-media-storage]] - decompression bombs and untrusted uploads.

## References
- RFC 1951, DEFLATE Compressed Data Format Specification: https://www.rfc-editor.org/rfc/rfc1951
- RFC 1952, GZIP file format specification: https://www.rfc-editor.org/rfc/rfc1952
- RFC 7932, Brotli Compressed Data Format: https://www.rfc-editor.org/rfc/rfc7932
- RFC 8878, Zstandard Compression and the 'application/zstd' Media Type: https://www.rfc-editor.org/rfc/rfc8878
- RFC 7457, Summarizing Known Attacks on TLS and DTLS (CRIME, BREACH): https://www.rfc-editor.org/rfc/rfc7457
- Python `zlib` module (wbits, zdict, max_length): https://docs.python.org/3/library/zlib.html
- PEP 784, Adding Zstandard to the standard library: https://peps.python.org/pep-0784/
- Apache Kafka producer `compression.type`: https://kafka.apache.org/documentation/#producerconfigs_compression.type
