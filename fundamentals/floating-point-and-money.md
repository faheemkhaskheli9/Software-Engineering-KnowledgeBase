---
title: Floating point, decimals and money
category: fundamentals
tags: [floating-point, ieee-754, decimal, money, currency, rounding, bankers-rounding, minor-units, integer-overflow, precision]
use_cases:
  - "prices or invoice totals are off by a cent after adding or multiplying amounts"
  - "store and compute money amounts in a database and API without rounding errors"
  - "split a payment or discount across several line items so the parts add up to the total"
  - "compare floating-point results in tests without flaky equality failures"
  - "large integer ids lose precision when sent to a JavaScript client as JSON numbers"
status: draft
last_verified: 2026-10-24
sources:
  - https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html
  - https://docs.python.org/3/tutorial/floatingpoint.html
  - https://docs.python.org/3/library/decimal.html
  - https://www.iso.org/iso-4217-currency-codes.html
  - https://martinfowler.com/eaaCatalog/money.html
  - https://www.rfc-editor.org/rfc/rfc8259#section-6
  - https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Number/MAX_SAFE_INTEGER
---

# Floating point, decimals and money

## Summary
Binary floating point (IEEE 754 `float`/`double`) stores numbers as a binary
fraction times a power of two, so most decimal fractions such as 0.1 cannot be
represented exactly and every operation rounds. That is fine for measurements
and science, and wrong for money, where totals must match to the cent and
rounding must follow a stated rule. Represent money as an integer count of the
currency's minor unit (or an exact decimal type) together with its currency
code, round only at defined points with a named rounding mode, and allocate
remainders explicitly so parts always sum to the whole.

## Key concepts
- **IEEE 754 double**: 1 sign bit, 11 exponent bits, 52 stored fraction bits
  (53 bits of precision), about 15-17 significant decimal digits. Integers are
  exact only up to 2^53; JavaScript's `Number.MAX_SAFE_INTEGER` is 2^53 - 1.
- **Representation error**: `0.1 + 0.2 != 0.3` because none of the three is
  exactly representable; the printed value is the shortest decimal that
  round-trips, not the stored value.
- **Absolute vs relative tolerance**: compare floats with `math.isclose`
  (relative tolerance, plus an absolute tolerance near zero), never `==`.
- **Special values**: `NaN` is not equal to itself, `inf` absorbs arithmetic,
  and signed zero exists; all of them break naive sorting and hashing.
- **Exact decimal types**: Python `decimal.Decimal`, Java `BigDecimal`, SQL
  `NUMERIC(p, s)`/`DECIMAL(p, s)` store base-10 digits exactly, at a CPU cost.
- **Minor units**: ISO 4217 defines each currency's number of decimal places
  (USD 2, JPY 0, KWD 3). Storing integer minor units (cents) makes addition
  exact and fast.
- **Rounding modes**: half-up (school rounding), half-even (banker's rounding,
  ties go to the even digit, unbiased over many values; Python's `round()` and
  the default `decimal` context use it), down/truncate, ceiling, floor. The
  rule is a business or legal decision; write it down.
- **Money pattern** (Fowler): a value object of amount + currency whose
  operations refuse to mix currencies and do allocation correctly.
- **Allocation**: dividing an amount into parts (instalments, tax per line,
  revenue share) leaves a remainder of minor units that must be assigned
  deliberately, e.g. largest-remainder.
- **Integer overflow**: fixed-width integers (32-bit `int` in Java, C, many
  SQL `INTEGER` columns) wrap or error; size counters and money columns for
  the largest value they will ever hold.

## When to use / scenarios
- Anything that is money, points, quotas or inventory counts: integer minor
  units or exact decimals, never binary floats.
- Interest, tax and FX calculations: exact decimals with a fixed number of
  intermediate digits, rounded once at the step the rules specify.
- Measurements, statistics, ML, graphics, physics: binary floats are correct
  and much faster; use tolerances and numerically stable algorithms
  (`math.fsum` for sums of many terms).
- APIs to JavaScript clients: send 64-bit ids and exact amounts as strings (or
  integer minor units below 2^53), because JSON numbers are usually parsed
  into doubles (RFC 8259 section 6 warns about this interoperability limit).
- When NOT to use decimals: hot numeric loops and vectorised analytics; there
  binary floats with error analysis are the right tool.

## How it works / example
Floats drift, decimals and integer cents do not, and allocation keeps totals
exact:

```python
import math
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP

# 1. Binary floats cannot hold 0.1 exactly.
assert 0.1 + 0.2 != 0.3
assert math.isclose(0.1 + 0.2, 0.3, rel_tol=1e-9)
total = 0.0
for _ in range(10):
    total += 0.1                         # naive running sum: error accumulates
assert total != 1.0
assert math.fsum([0.1] * 10) == 1.0    # correctly rounded summation fixes this case
assert float(2**53) + 1 == float(2**53)  # integers above 2**53 lose precision

# 2. Exact decimals, constructed from strings (Decimal(0.1) copies the float error).
assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
assert Decimal(0.1) != Decimal("0.1")

CENT = Decimal("0.01")
assert Decimal("2.675").quantize(CENT, rounding=ROUND_HALF_UP) == Decimal("2.68")
assert Decimal("2.665").quantize(CENT, rounding=ROUND_HALF_EVEN) == Decimal("2.66")
assert round(2.675, 2) == 2.67   # float 2.675 is really 2.67499999...

# 3. Money as integer minor units plus currency, with exact allocation.
MINOR_UNITS = {"USD": 2, "EUR": 2, "JPY": 0, "KWD": 3}  # from ISO 4217

class Money:
    __slots__ = ("minor", "currency")

    def __init__(self, minor: int, currency: str):
        if not isinstance(minor, int):
            raise TypeError("amount must be integer minor units")
        self.minor, self.currency = minor, currency

    @classmethod
    def parse(cls, text: str, currency: str) -> "Money":
        places = MINOR_UNITS[currency]
        d = Decimal(text)
        if d != d.quantize(Decimal(1).scaleb(-places)):
            raise ValueError(f"{text} has more than {places} decimals for {currency}")
        return cls(int(d.scaleb(places)), currency)

    def __add__(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValueError("cannot add different currencies")
        return Money(self.minor + other.minor, self.currency)

    def __eq__(self, other):
        return (self.minor, self.currency) == (other.minor, other.currency)

    def allocate(self, ratios: list[int]) -> list["Money"]:
        """Split by ratios; leftover minor units go to the largest remainders."""
        total = sum(ratios)
        shares = [self.minor * r // total for r in ratios]
        remainders = [self.minor * r % total for r in ratios]
        leftover = self.minor - sum(shares)
        order = sorted(range(len(ratios)), key=lambda i: -remainders[i])
        for i in order[:leftover]:
            shares[i] += 1
        return [Money(s, self.currency) for s in shares]

    def __str__(self):
        places = MINOR_UNITS[self.currency]
        return f"{Decimal(self.minor).scaleb(-places)} {self.currency}"

price = Money.parse("19.99", "USD")
assert price.minor == 1999
assert str(price + Money.parse("0.01", "USD")) == "20.00 USD"

parts = Money.parse("100.00", "USD").allocate([1, 1, 1])
assert [p.minor for p in parts] == [3334, 3333, 3333]     # sums to 10000 exactly
assert sum(p.minor for p in parts) == 10000
assert [p.minor for p in Money.parse("5", "JPY").allocate([70, 30])] == [4, 1]

try:
    Money.parse("1.234", "USD")
except ValueError:
    pass
else:
    raise AssertionError("sub-cent USD amount accepted")
print("ok", [str(p) for p in parts])
```

Storage and transport rules of thumb:

| Layer | Do | Avoid |
|---|---|---|
| Database | `BIGINT` minor units + `CHAR(3)` currency, or `NUMERIC(p, s)` | `FLOAT`/`REAL`/`DOUBLE` columns |
| API / JSON | `{"amount": "19.99", "currency": "USD"}` or integer minor units | bare JSON number amounts with decimals |
| Code | Money value object, explicit rounding mode | `float` arithmetic, rounding inside every step |
| Display | locale formatting at the edge ([[internationalization-and-localization]]) | formatting inside business logic |

## Trade-offs
- **Integer minor units vs decimal type**: integers are fast, compact and
  exact for add/subtract, but need care for multiplication (tax rates, FX) and
  for currencies whose minor unit changes; decimals handle fractional rates
  directly but are slower and need a configured precision and context.
- **Round per line vs round the total**: rounding each line's tax and summing
  can differ from rounding the summed tax by a few minor units; jurisdictions
  and invoices specify one. Pick the rule, then make the code match it.
- **Half-even vs half-up**: half-even removes systematic upward bias over many
  values; half-up matches what users and many regulations expect on one value.
- **Floats with tolerance vs exact arithmetic**: tolerances are cheap and fine
  for measurements; they are never acceptable for balances that must
  reconcile.

## Gotchas
- `Decimal(0.1)` builds from the already-wrong float; build decimals from
  strings or integers.
- `round(2.675, 2)` gives 2.67 because the float is slightly below 2.675;
  this is representation error, not a rounding bug.
- Parsing JSON amounts as floats in a JavaScript, Python or Go client silently
  reintroduces float error, and 64-bit ids above 2^53 come back changed.
- Sums of rounded values do not equal the rounded sum; allocation, not
  division, keeps instalments and splits adding up.
- Hard-coding two decimals breaks JPY (0) and KWD/BHD (3); look up the minor
  unit per currency.
- Mixing currencies in one sum is a silent bug unless the type refuses it.
- A naive `total += x` loop accumulates error; Python 3.12+ `sum()` uses
  compensated summation for floats, so the same data can give different
  results in a loop, in `sum()` on older Pythons, and in other languages.
- `NaN` in a list makes `sorted()` and `max()` give order-dependent results;
  validate inputs.
- 32-bit counters and money columns overflow sooner than expected; a cents
  value in a signed 32-bit column tops out at about 21 million currency units.

## Related
- [[design-payment-system]] - ledgers and double-entry bookkeeping built on exact amounts.
- [[core-data-structures]] - why floats make poor hash and sort keys.
- [[internationalization-and-localization]] - formatting amounts and currencies per locale.
- [[data-modeling-and-schema-design]] - choosing column types for amounts and counters.
- [[strings-and-text-encoding]] - the other everyday representation trap at the byte level.
- [[property-based-and-fuzz-testing]] - checking invariants like "allocations sum to the total".

## References
- David Goldberg, "What Every Computer Scientist Should Know About Floating-Point Arithmetic", ACM Computing Surveys 23(1), 1991 (Oracle reprint linked in sources).
- IEEE Std 754-2019, *IEEE Standard for Floating-Point Arithmetic*.
- Python documentation: "Floating-Point Arithmetic: Issues and Limitations" and the `decimal` module.
- ISO 4217 currency codes and minor units (iso.org).
- Martin Fowler, *Patterns of Enterprise Application Architecture* (2002), "Money" pattern.
- RFC 8259, *The JavaScript Object Notation (JSON) Data Interchange Format*, section 6 "Numbers".
- MDN Web Docs, `Number.MAX_SAFE_INTEGER`.
