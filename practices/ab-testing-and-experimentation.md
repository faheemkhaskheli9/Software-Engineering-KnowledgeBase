---
title: A/B testing and online experimentation
category: practices
tags: [ab-testing, experimentation, controlled-experiment, statistics, sample-ratio-mismatch, srm, statistical-power, peeking, guardrail-metrics, cuped, oec]
use_cases:
  - "find out whether a new checkout flow actually raises conversion before rolling it out to everyone"
  - "work out how many users and how many days an experiment needs to detect a 2 percent lift"
  - "explain why an experiment that looked significant on day 2 lost its effect by day 14"
  - "check that experiment assignment and logging are not broken before trusting a result"
  - "build in-house experiment assignment and analysis on top of feature flags"
status: draft
last_verified: 2026-10-24
sources:
  - "Ron Kohavi, Diane Tang, Ya Xu, Trustworthy Online Controlled Experiments: A Practical Guide to A/B Testing, Cambridge University Press, 2020"
  - https://experimentguide.com/
  - https://www.evanmiller.org/how-not-to-run-an-ab-test.html
  - "Alex Deng, Ya Xu, Ron Kohavi, Toby Walker, Improving the Sensitivity of Online Controlled Experiments by Utilizing Pre-Experiment Data (CUPED), WSDM 2013"
  - "Aleksander Fabijan et al., Diagnosing Sample Ratio Mismatch in Online Controlled Experiments, KDD 2019"
  - https://docs.python.org/3/library/statistics.html#statistics.NormalDist
---

# A/B testing and online experimentation

## Summary
An online controlled experiment (A/B test) randomly splits users between the
current experience (control) and a change (treatment), then compares
pre-declared metrics to estimate the change's causal effect. It is the
standard way to decide whether a product or performance change helps, because
before/after comparisons mix the change with seasonality, marketing and
everything else that shipped that week. The engineering is mostly about
trustworthy assignment, logging and analysis: a broken split or a peeked
p-value produces confident, wrong answers.

## Key concepts
- **Randomization unit**: what gets assigned to a variant (user, device,
  session, tenant, page view). Users are the usual choice so one person sees
  one experience; use a coarser unit (tenant, city, cluster) when users
  interact. Assign deterministically by hashing `experiment id + unit id`.
- **OEC (overall evaluation criterion)**: the one metric, or small weighted set,
  that defines success, chosen before the test. Kohavi et al. recommend metrics
  that predict long-term value (retention, sessions per user), not only
  short-term revenue.
- **Guardrail metrics**: metrics that must not degrade (latency, error rate,
  crash rate, unsubscribe rate) whatever the OEC does. A latency regression is a
  valid reason to stop a "winning" test.
- **Statistical significance and power**: the significance level (alpha,
  usually 0.05) is the false-positive rate you accept; power (usually 80%) is
  the chance of detecting a true effect of the chosen **minimum detectable
  effect (MDE)**. Smaller MDE or noisier metric means more users.
- **Sample size rule of thumb** (from the Kohavi book): with alpha 0.05 and
  80% power, about `16 * variance / delta^2` units per variant, where `delta`
  is the absolute effect you want to detect.
- **A/A test**: both variants get the same experience. It should show
  "significant" differences about 5% of the time at alpha 0.05; more often
  means the pipeline or the statistics are broken.
- **Sample ratio mismatch (SRM)**: the observed split differs from the
  configured split (e.g. 50/50 configured, 50.6/49.4 observed on 100k users).
  A chi-square test flags it. SRM means assignment, redirect, bot filtering or
  logging differs between variants; the result is not trustworthy until the
  cause is found.
- **Peeking**: checking the p-value repeatedly and stopping at the first
  significant reading inflates the false-positive rate well above alpha
  (Evan Miller's "How Not To Run an A/B Test"). Fix the sample size in advance,
  or use a method designed for continuous monitoring (sequential tests,
  always-valid p-values).
- **Twyman's law** (as quoted in the Kohavi book): any figure that looks
  interesting or different is usually wrong. Surprising wins get extra checks.
- **Novelty and primacy effects**: users click a new thing because it is new
  (novelty) or resist it because it is unfamiliar (primacy); look at the effect
  over time, not only the total.
- **Variance reduction (CUPED)**: adjust each unit's metric with its
  pre-experiment value of the same metric; this removes variance unrelated to
  the change and lets the same test detect smaller effects.
- **Triggering**: analyse only units that could have seen the change (users
  who reached checkout), which dilutes the effect less than analysing everyone.

## When to use / scenarios
- A product change with a measurable outcome and enough traffic: new
  onboarding, ranking, pricing page, recommendation model.
- Performance work where you want the business impact of latency, not only the
  latency (experiments that add delay on purpose are a classic use).
- Deciding between two implementations when opinions differ and the cost of
  being wrong is real.
- Rolling out a risky backend change with guardrails: run it as an experiment
  so you see error and latency deltas against a concurrent control.
- When NOT to use:
  - Too little traffic to reach the sample size in a few weeks; use qualitative
    research, a staged rollout watched with SLOs, or test a bolder change.
  - Legal, safety or security fixes that must ship to everyone anyway.
  - Strong interference between units (marketplaces, social graphs, shared
    inventory) without cluster or switchback designs; naive per-user splits are
    biased there.
  - One-off migrations where there is nothing to decide; use a canary
    ([[deployment-strategies]]).

## How it works / example

```
define hypothesis, OEC, guardrails, MDE  ->  compute sample size and duration
        |
assign: bucket = hash(experiment_id, user_id) -> variant   (sticky, logged)
        |
exposure event when the user actually reaches the changed code (trigger)
        |
run full weeks; no stopping on early significance
        |
checks first: SRM, A/A-style sanity metrics, logging gaps
        |
analyse OEC and guardrails -> ship / iterate / drop -> write it down
```

Assignment, sample size, an SRM check, a two-proportion z-test and a
simulation of why peeking is dangerous, using only the standard library:

```python
import hashlib
import math
import random
from statistics import NormalDist

Z = NormalDist()

def variant(experiment: str, unit_id: str, split=(("control", 50), ("treatment", 50))) -> str:
    """Deterministic, sticky assignment; independent across experiments."""
    h = int.from_bytes(hashlib.sha256(f"{experiment}:{unit_id}".encode()).digest()[:8], "big") % 100
    edge = 0
    for name, pct in split:
        edge += pct
        if h < edge:
            return name
    raise ValueError("split must sum to 100")

def sample_size_per_arm(p_base: float, rel_mde: float, alpha=0.05, power=0.8) -> int:
    """Units per arm to detect p_base -> p_base*(1+rel_mde) with a two-sided test."""
    p2 = p_base * (1 + rel_mde)
    z = Z.inv_cdf(1 - alpha / 2) + Z.inv_cdf(power)
    var = p_base * (1 - p_base) + p2 * (1 - p2)
    return math.ceil(z * z * var / (p2 - p_base) ** 2)

def srm_p_value(n_control: int, n_treatment: int, expected_ratio=0.5) -> float:
    """Chi-square goodness-of-fit test with 1 degree of freedom."""
    total = n_control + n_treatment
    exp_c, exp_t = total * expected_ratio, total * (1 - expected_ratio)
    chi2 = (n_control - exp_c) ** 2 / exp_c + (n_treatment - exp_t) ** 2 / exp_t
    return math.erfc(math.sqrt(chi2 / 2))

def two_proportion_p_value(conv_a: int, n_a: int, conv_b: int, n_b: int) -> float:
    pa, pb = conv_a / n_a, conv_b / n_b
    pooled = (conv_a + conv_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    return 2 * (1 - Z.cdf(abs(pb - pa) / se))

# 1. Assignment is sticky and close to the configured split.
users = [f"u{i}" for i in range(20_000)]
assert all(variant("checkout-v2", u) == variant("checkout-v2", u) for u in users[:200])
share = sum(variant("checkout-v2", u) == "treatment" for u in users) / len(users)
assert 0.48 < share < 0.52, share

# 2. Sample size: 5% baseline conversion, detect a 10% relative lift (5.0% -> 5.5%).
n = sample_size_per_arm(0.05, 0.10)
rule_of_thumb = 16 * 0.05 * 0.95 / 0.005 ** 2      # Kohavi et al.: 16 * variance / delta^2
assert 30_000 < n < 33_000 and abs(n - rule_of_thumb) / n < 0.05, (n, rule_of_thumb)

# 3. SRM: a 50/50 test that logged 50,000 vs 48,800 users is broken, not lucky.
assert srm_p_value(50_000, 48_800) < 0.001
assert srm_p_value(50_000, 49_900) > 0.05

# 4. Significance test on a fixed-horizon result.
assert two_proportion_p_value(1_550, 31_000, 1_720, 31_000) < 0.05

# 5. Peeking: A/A tests (no real difference) checked after every batch of users.
rng = random.Random(7)
experiments, looks, batch, p = 400, 10, 1_000, 0.05
fixed_hits = peek_hits = 0
for _ in range(experiments):
    ca = cb = na = nb = 0
    stopped_early = False
    for _ in range(looks):
        ca += rng.binomialvariate(batch, p); na += batch
        cb += rng.binomialvariate(batch, p); nb += batch
        if two_proportion_p_value(ca, na, cb, nb) < 0.05:
            stopped_early = True
    peek_hits += stopped_early
    fixed_hits += two_proportion_p_value(ca, na, cb, nb) < 0.05
fixed_fpr, peek_fpr = fixed_hits / experiments, peek_hits / experiments
assert fixed_fpr < 0.10 and peek_fpr > 1.5 * fixed_fpr, (fixed_fpr, peek_fpr)
print(f"n per arm={n}, false positives: fixed horizon {fixed_fpr:.0%}, peeking {peek_fpr:.0%}")
```

The peeking simulation is an A/A test: there is no effect, yet "stop at the
first significant look" declares a winner several times more often than the
5% the analyst thinks they accepted.

Platform pieces a team usually needs, in order: deterministic assignment (often
via the flag system, see [[feature-flags]]); an exposure log written when the
changed code path runs, with the variant; metric pipelines joined on the
randomization unit; automatic SRM and guardrail checks; a results page that
shows confidence intervals, not only p-values; and an experiment log of past
decisions.

## Trade-offs
- **Speed vs sensitivity**: a shorter test or a smaller audience gives earlier
  answers but only for large effects; full weeks and more traffic detect small
  ones and average out weekday patterns.
- **Fixed horizon vs sequential testing**: fixed horizon is simple and exact
  if you do not peek; sequential methods allow early stopping and continuous
  monitoring at the cost of some power and more complex analysis.
- **User vs cluster randomization**: per-user splits are most powerful but
  biased under interference; cluster or switchback designs remove the bias and
  need far more time or clusters.
- **Build vs buy**: assignment is a few lines; trustworthy metric pipelines,
  SRM alerts, variance reduction and a results UI are the expensive part.
  Commercial and open-source platforms exist; the deciding factor is usually
  whether your metrics live in your own warehouse.
- **Many metrics vs few**: more metrics catch side effects but some will be
  "significant" by chance; declare the OEC and guardrails up front and treat
  the rest as exploratory.

## Gotchas
- Assigning with `random()` per request instead of a stable hash: users flip
  between variants and every metric is diluted.
- Hashing only the user id: the same users land in treatment for every
  experiment; include the experiment id (or a per-experiment salt).
- Logging exposure at assignment for users who never reach the changed page
  dilutes the effect; logging it only in the treatment path causes SRM.
- Treatment code that is slower, redirects, or crashes before logging loses
  users from one side: that is SRM, and the "result" reflects who was lost.
- Analysing per page view while randomizing per user understates variance;
  use the delta method or bootstrap for ratio metrics with a different
  analysis unit.
- Bots and internal traffic concentrate in one variant by chance or by
  behaviour; filter them the same way in both arms.
- Running overlapping experiments on the same surface can interact; most
  platforms use layers or mutually exclusive groups for those.
- A significant result with a tiny effect may not be worth the code it adds;
  report effect size with a confidence interval.
- Restarting a test after a bug fix with the same salt keeps users in their old
  buckets with carry-over effects; re-salt.
- Experiment results are decisions about people: privacy rules on what you log
  per user still apply (see [[privacy-and-pii-handling]]).

## Related
- [[feature-flags]] - experiment toggles and deterministic bucketing that assignment builds on.
- [[deployment-strategies]] - canaries compare versions for safety; experiments compare them for impact.
- [[observability-logs-metrics-traces]] - exposure and metric events, and guardrail metrics.
- [[slis-slos-error-budgets]] - latency and error guardrails expressed as SLIs.
- [[data-warehousing-and-olap]] - where experiment metrics are usually computed and joined.
- [[privacy-and-pii-handling]] - limits on what you log per user for analysis.

## References
- Ron Kohavi, Diane Tang, Ya Xu, *Trustworthy Online Controlled Experiments: A Practical Guide to A/B Testing*, Cambridge University Press, 2020 (sample size rule of thumb, SRM, A/A tests, Twyman's law, triggering): https://experimentguide.com/
- Evan Miller, "How Not To Run an A/B Test": https://www.evanmiller.org/how-not-to-run-an-ab-test.html
- Alex Deng, Ya Xu, Ron Kohavi, Toby Walker, "Improving the Sensitivity of Online Controlled Experiments by Utilizing Pre-Experiment Data", WSDM 2013 (CUPED).
- Aleksander Fabijan et al., "Diagnosing Sample Ratio Mismatch in Online Controlled Experiments", KDD 2019.
- Python `statistics.NormalDist`: https://docs.python.org/3/library/statistics.html#statistics.NormalDist
