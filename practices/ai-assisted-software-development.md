---
title: AI-assisted software development (Claude, ChatGPT, Copilot, coding agents)
category: practices
tags: [ai-assisted-development, llm, coding-agents, claude-code, chatgpt, codex, copilot, cursor, gemini, productivity, agents-md]
use_cases:
  - "introduce AI coding assistants like Claude, ChatGPT or Copilot to a team without lowering quality"
  - "decide which development tasks to give an AI model and which to keep human"
  - "set up a repo so coding agents follow our conventions and run our checks"
  - "review and test AI-generated code safely before merging"
  - "measure whether AI tools actually make our team faster"
  - "write a team policy for using LLMs on proprietary code and secrets"
status: draft
last_verified: 2026-10-24
sources:
  - https://www.anthropic.com/engineering/claude-code-best-practices
  - https://code.claude.com/docs/en/overview
  - https://developers.openai.com/codex
  - https://docs.github.com/en/copilot
  - https://agents.md/
  - https://dora.dev/research/2025/dora-report/
  - https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
  - https://arxiv.org/abs/2302.06590
  - https://arxiv.org/abs/2406.10279
  - https://genai.owasp.org/llm-top-10/
---

# AI-assisted software development (Claude, ChatGPT, Copilot, coding agents)

## Summary
Large language models (Anthropic Claude, OpenAI ChatGPT/Codex, Google Gemini,
GitHub Copilot, Cursor and others) can draft code, tests, docs, reviews and
migrations, and coding agents can edit a repository and run its commands on
their own. They improve delivery only when wrapped in the same engineering
discipline as human work: small scoped tasks, explicit context, automated
verification (tests, types, lint, CI) and human review of what ships. This
topic covers the process side; model choice and agent internals live in the AI KB.

## Key concepts
- **Interaction modes, from least to most autonomy:**
  1. *Chat* (ChatGPT, Claude.ai, Gemini): explain, design, draft snippets; you copy code in.
  2. *Inline completion* (Copilot, Cursor Tab): next lines as you type.
  3. *IDE/CLI agent* (Claude Code, Codex CLI, Cursor Agent, Copilot agent mode):
     reads files, edits many of them, runs tests and shell commands in a loop.
  4. *Background/cloud agent* (Claude Code on the web, Codex cloud, Copilot coding
     agent): takes an issue, works in a sandbox, opens a pull request.
  More autonomy means larger diffs per prompt, so verification matters more.
- **Context is the main lever.** Models know public libraries, not your
  architecture, conventions or business rules. Give them: a project
  instruction file (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`),
  the relevant files, the failing test or error output, and constraints.
- **Verification loop.** The agent must be able to check its own work: a
  test command, type checker, linter, build, or a screenshot for UI. Without a
  check it can run, it will report success on code that does not work.
- **Explore -> plan -> implement -> verify -> commit.** Ask for a plan
  first on non-trivial work, correct the plan, then let it code (Anthropic's
  published Claude Code workflow; the same works with any tool).
- **Human accountability.** The person who merges owns the change. AI output
  is a draft from a fast, confident contributor who has never seen production.
- **Failure modes to expect:** hallucinated APIs and packages, plausible but
  wrong edge-case handling, tests that assert the bug, over-broad diffs,
  deleted or weakened tests to make CI pass, outdated library versions,
  copied insecure patterns, and secrets pasted into prompts.

## When to use / scenarios
Good fits (high leverage, easy to verify):
- Boilerplate and glue: CRUD endpoints, DTOs, serializers, CLI flags, config.
- Writing tests for existing code, and characterization tests before a
  refactor (see [[snapshot-and-golden-testing]]).
- Mechanical refactors and migrations across many files (rename, API upgrade,
  framework version bump) with a test suite as the safety net.
- Explaining unfamiliar code, onboarding Q&A, tracing a request through a codebase.
- Debugging from a stack trace or failing test: hypothesis generation and
  bisecting suspects.
- First-pass code review, PR descriptions, changelogs, docstrings, ADR drafts.
- Prototypes and spikes you intend to throw away.
- Regex, SQL, shell one-liners, data transformation scripts (verify on sample data).

Poor fits or needs extra care:
- Security-critical code (authN/authZ, crypto, payment flows): use AI for
  review and tests, have a domain expert own the design ([[threat-modeling]]).
- Architecture and product decisions: use the model as a sparring partner
  listing options and trade-offs, not as the decider.
- Code with no tests or no runnable environment: add a verification path first.
- Novel algorithms or performance-critical paths: benchmark, do not trust claims.
- Regulated or confidential code where policy forbids sending it to a third party:
  use an approved enterprise plan, a zero-data-retention agreement, or a
  self-hosted model.

## How it works / example

### 1. Prepare the repository
```
repo/
  AGENTS.md                         # read by Codex, Cursor, Copilot and others
  CLAUDE.md                         # read by Claude Code (can just contain "@AGENTS.md")
  .github/copilot-instructions.md   # optional, Copilot-specific
  Makefile / package.json scripts   # one command each: test, lint, typecheck, build
```
A useful instruction file is short and concrete:
```
# Project: payments-api (Python 3.12, FastAPI, Postgres)
## Commands
- Test: make test      Lint: make lint      Types: make typecheck
- Run all three before saying a task is done.
## Conventions
- Layers: api/ -> services/ -> repositories/. No SQL outside repositories/.
- Money is integer cents; never float.
- New endpoints need an integration test in tests/api/.
## Never
- Never edit migrations that are already merged; add a new one.
- Never weaken or delete a test to make it pass; fix the code or ask.
- Never add a dependency without saying why; pin it in requirements.txt.
```

### 2. Prompt like a ticket, not a wish
```
Weak:   "add rate limiting"
Better: "Add per-API-key rate limiting to POST /payments: 100 requests/minute,
         token bucket, Redis-backed, return 429 with Retry-After.
         Follow the middleware pattern in api/middleware/auth.py.
         First write failing tests in tests/api/test_rate_limit.py, show me
         the plan, then implement. Run `make test lint typecheck` before finishing."
```
Ingredients: goal, acceptance criteria, where it fits, an example to copy,
what not to touch, and how to verify.

### 3. Test-first contract for AI-written code
Write (or approve) the tests yourself, then let the model implement until
they pass. The tests encode intent the model cannot guess. The block below
simulates that loop: a human-written spec, a model-proposed implementation,
and a gate that rejects the candidate unless every case passes.

```python
import unittest

# Human-owned specification: written or reviewed before asking the model.
class SlugifySpec(unittest.TestCase):
    impl = None
    def test_basic(self):
        self.assertEqual(self.impl("Hello World"), "hello-world")
    def test_punctuation_and_spaces(self):
        self.assertEqual(self.impl("  AI, for   devs! "), "ai-for-devs")
    def test_empty(self):
        self.assertEqual(self.impl(""), "")
    def test_non_ascii_dropped(self):
        self.assertEqual(self.impl("Café déjà vu"), "caf-d-j-vu")

# Two candidates as a model might return them.
def candidate_v1(s):                       # plausible but wrong on edge cases
    return s.lower().replace(" ", "-")

def candidate_v2(s):
    out, dash = [], False
    for ch in s.lower():
        if ch.isascii() and ch.isalnum():
            out.append(ch); dash = False
        elif out and not dash:
            out.append("-"); dash = True
    return "".join(out).strip("-")

def gate(candidate):
    """Accept AI output only if the human-owned spec passes."""
    SlugifySpec.impl = staticmethod(candidate)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SlugifySpec)
    result = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w")).run(suite)
    return result.wasSuccessful(), len(result.failures) + len(result.errors)

for cand in (candidate_v1, candidate_v2):
    ok, failed = gate(cand)
    print(f"{cand.__name__}: {'ACCEPT' if ok else f'REJECT ({failed} failing)'}")
assert gate(candidate_v2)[0] and not gate(candidate_v1)[0]
```

### 4. Guardrails in CI for AI-heavy repos
Models sometimes invent package names (attackers register them:
"slopsquatting") or quietly delete tests. Cheap checks catch both:

```python
import re

def new_dependencies(old_reqs: str, new_reqs: str) -> set[str]:
    name = lambda line: re.split(r"[=<>!~\[; ]", line.strip(), maxsplit=1)[0].lower()
    parse = lambda text: {name(l) for l in text.splitlines() if l.strip() and not l.startswith("#")}
    return parse(new_reqs) - parse(old_reqs)

def removed_tests(diff: str) -> list[str]:
    """Lines deleting a test function or an assertion in a unified diff."""
    return [l for l in diff.splitlines()
            if l.startswith("-") and not l.startswith("---")
            and re.search(r"\bdef test_|\bassert\b|\.assert[A-Z]", l)]

APPROVED = {"fastapi", "pydantic", "sqlalchemy", "httpx", "redis"}
old = "fastapi==0.115.0\npydantic==2.9.0\n"
new = "fastapi==0.115.0\npydantic==2.9.0\nredis==5.0.8\nfastapi-ratelimit-pro==1.0\n"
diff = "--- a/tests/test_pay.py\n+++ b/tests/test_pay.py\n-    assert total == 100\n+    pass\n"

unknown = new_dependencies(old, new) - APPROVED
print("needs human approval:", sorted(unknown))       # ['fastapi-ratelimit-pro']
print("deleted test lines:", removed_tests(diff))     # ['-    assert total == 100']
assert unknown == {"fastapi-ratelimit-pro"} and len(removed_tests(diff)) == 1
```
In real CI, read the base and head versions with `git show origin/main:requirements.txt`
and `git diff origin/main...HEAD`, and fail or require a label for review.
Add secret scanning (see [[secrets-management]]) and the usual lint/type/test gates
([[static-analysis-and-type-checking]], [[ci-cd-pipelines]]).

### 5. Calling a model from your own tooling
For scripted uses (PR summaries, test generation in CI, log triage), call the
provider SDK. Take the model ID from the provider's current models page,
not from memory; IDs are retired on a schedule.

```python fragment
import os, subprocess
import anthropic          # or: from openai import OpenAI

diff = subprocess.check_output(["git", "diff", "origin/main...HEAD"], text=True)[:100_000]
client = anthropic.Anthropic()          # reads ANTHROPIC_API_KEY
msg = client.messages.create(
    model=os.environ["REVIEW_MODEL"],   # current ID from the provider docs
    max_tokens=1500,
    system="You are a senior reviewer. Report only concrete bugs, security issues "
           "and missing tests, each with file:line and a suggested fix. No style nits.",
    messages=[{"role": "user", "content": f"Review this diff:\n\n{diff}"}],
)
print(msg.content[0].text)
```

### 6. Team workflow
```
issue (clear acceptance criteria)
  -> developer + AI: plan, agree approach (ADR if architectural)
  -> AI drafts code + tests on a branch; developer steers, runs checks locally
  -> CI: lint, types, tests, dependency/secret scan, diff-size warning
  -> AI first-pass review (bugs, missing tests) -> human review (design, risk, domain)
  -> merge by a human who understands the change
  -> measure: lead time, change failure rate, rework, review latency
```

## Trade-offs
- **Autonomy vs control.** Agents that run commands unattended finish more
  per prompt but produce bigger diffs and can do damage. Use permission
  modes, sandboxes/containers, and branch protection; give background agents
  their own branch and least-privilege tokens.
- **Speed now vs maintainability later.** Generated code is cheap to write,
  not to own. Duplicated or over-engineered output becomes debt; ask for the
  smallest change that passes, and refactor ([[technical-debt-management]]).
- **Learning vs throughput.** Juniors who accept code they cannot explain stop
  learning. Require authors to explain any AI-written change in review.
- **Hosted frontier models vs self-hosted open models.** Hosted models are
  usually stronger; self-hosted keeps code on your infrastructure. Enterprise
  plans with no training on your data and retention controls are the usual middle ground.
- **One tool for everyone vs freedom of choice.** Standardizing eases policy,
  billing and shared instruction files; `AGENTS.md` keeps most tools aligned either way.
- **Evidence is mixed.** A 2023 controlled experiment found Copilot users
  finished a scoped task about 56% faster (Peng et al.); a 2025 randomized
  study of experienced open-source developers on their own large repos found
  them about 19% slower with AI tools, while they believed they were faster
  (METR). DORA's 2025 report frames AI as an amplifier of existing practices.
  Measure your own team instead of assuming a gain.

## Gotchas
- **"Tests pass" is not "correct."** Models write tests that mirror their own
  bug, or mock the thing under test. Review tests harder than code; try
  [[mutation-testing]] on critical modules.
- **Weakened checks.** Agents may delete a failing test, add `# type: ignore`,
  skip a lint rule, or catch-and-ignore an exception to get green. Forbid it in
  the instruction file and catch it in review/CI.
- **Hallucinated or stale APIs.** Point the model at the installed version's
  docs or source; pin versions; prefer libraries already in the project.
- **Hallucinated packages** can be registered by attackers. Verify every new
  dependency exists, is maintained and is the intended one.
- **Secrets and personal data in prompts.** Never paste `.env` files, tokens,
  customer data or production dumps. Keep secrets out of files agents read.
- **Prompt injection.** An agent reading an issue, web page, dependency README
  or log can be instructed by that text to exfiltrate data or run commands.
  Treat external content as untrusted, limit network and tool access, and
  require approval for outward actions (OWASP LLM Top 10).
- **Huge diffs.** A 3,000-line AI PR gets rubber-stamped. Keep tasks small
  ([[code-review]]); split by concern.
- **Context drift in long sessions.** Quality drops as a conversation fills
  with stale attempts. Start a fresh session per task; keep durable rules in
  the instruction file, not the chat.
- **Licensing and provenance.** Check your provider's terms and enable
  public-code filters where offered if your policy requires it.
- **Measuring lines of code or "% AI-written"** rewards volume. Track DORA
  metrics, defect rates and review rework instead.

## Related
- [[code-review]] - review standards apply to AI-written diffs; AI as a first-pass reviewer
- [[tdd-and-bdd]] - tests as the specification an AI implementation must satisfy
- [[static-analysis-and-type-checking]] - automated checks that keep generated code honest
- [[ci-cd-pipelines]] - where AI guardrails (dependency, secret, test-deletion checks) run
- [[secrets-management]] - keep credentials out of prompts and agent-readable files
- [[documentation-practices]] - instruction files and docs as context for models
- [[technical-debt-management]] - cheap generated code still has an ownership cost
- [[mutation-testing]] - check whether AI-written tests actually catch bugs
- See also (AI KB): [Coding agents and project instruction files](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/coding-agents.md) - setting up Claude Code, Codex, Cursor and AGENTS.md in depth.
- See also (AI KB): [Prompt engineering](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/prompt-engineering.md) and [Prompt injection](https://github.com/faheemkhaskheli9/AI-Knowledge-Base/blob/main/llm-apps/prompt-injection.md) - writing effective prompts and defending agents from hostile input.

## References
- Anthropic, "Claude Code: Best practices for agentic coding": https://www.anthropic.com/engineering/claude-code-best-practices
- Claude Code documentation: https://code.claude.com/docs/en/overview
- OpenAI Codex documentation: https://developers.openai.com/codex
- GitHub Copilot documentation: https://docs.github.com/en/copilot
- AGENTS.md open format for coding-agent instructions: https://agents.md/
- DORA, "State of AI-assisted Software Development" (2025): https://dora.dev/research/2025/dora-report/
- METR, "Measuring the Impact of Early-2025 AI on Experienced Open-Source Developer Productivity" (2025): https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
- Peng et al., "The Impact of AI on Developer Productivity: Evidence from GitHub Copilot" (2023): https://arxiv.org/abs/2302.06590
- Spracklen et al., "We Have a Package for You! A Comprehensive Analysis of Package Hallucinations by Code Generating LLMs" (2024): https://arxiv.org/abs/2406.10279
- OWASP Top 10 for LLM Applications: https://genai.owasp.org/llm-top-10/
