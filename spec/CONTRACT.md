# The Toli contract — what all seven SDKs must say identically

Toli is a **judge**, not a writer. You give it a *state* and *typed questions*;
it returns one decision per question, with a probability distribution and a
**calibrated confidence**. It does not generate prose, never makes an
irreversible decision, and says so when it does not know.

This document is the SOURCE OF TRUTH. An SDK that departs from it is wrong, even
if it compiles. The cases under `conformance/` are the executable proof: every
SDK replays them, and they must all reach the same verdict.

---

## 1. The three questions

A question always carries `instructions`: what is being asked, in English (the
model is trained on English first — measure before writing them in another
language).

| Form | What you ask | What comes back |
|---|---|---|
| **Choice** | one option out of a **closed** set | `choice`, per-option `probabilities`, `confidence` |
| **Score** | a degree on **ordered, described** levels | `score` (float), `legend`, `confidence` |
| **Noul** | is this statement true | `noul` = probability of yes — **no `confidence`** |

**Choice** requires at least two options and **always an escape hatch**
(`other`, `none`, `unknown`…). Without one, the model is forced to pick between
boxes that do not describe the case, and the confidence it returns stops meaning
anything. An SDK REJECTS a `Choice` with fewer than two options.

**Score** requires levels ordered from weakest to strongest, each one described.

---

## 2. The three-route rule

This is the heart of the SDK, and the reason it exists: without it, every
project copies its thresholds slightly wrong.

```
confidence >= act      → ACT       the code may act on its own
confidence >= confirm  → CONFIRM   propose it; a human approves in one click
otherwise              → ESCALATE  Toli does not know: human queue, or an LLM
```

**A Noul carries no confidence**: 0.5 is the admission of ignorance, while 0.02
and 0.98 are both frank answers. So we measure the distance from doubt:

```
certainty = |noul - 0.5| * 2        # 0.5 → 0.0 ;  0.0 or 1.0 → 1.0
```

and apply the same three-route rule to `certainty`. An SDK that compares `noul`
straight against `act` is wrong: it would rank "I don't know" (0.5) as more
certain than a frank "no" (0.02).

### What an SDK NEVER exposes

Any method that applies the decision: no `autoRoute()`, no `classifyAndSave()`.
The SDK returns a route; the caller acts. A library that decides on the caller's
behalf removes the human guardrail without anyone having chosen to.

---

## 3. Thresholds are dated, or they do not exist

A threshold holds for **one model, one set of questions, one corpus**. Changing
it without re-measuring is flying blind. So an SDK requires:

```
Thresholds {
  act: float        # default 0.85
  confirm: float    # default 0.60
  measured_on: str  # "896 do-alo tickets, French"  — on WHAT
  measured_at: str  # "2026-09-18"                  — WHEN
}
```

`measured_on` and `measured_at` are **mandatory** as soon as you depart from the
defaults. The defaults themselves carry the words "not measured on your data".

Constraint: `0 < confirm <= act <= 1`. Otherwise, an error at construction time.

### Advisory thresholds — where acting alone is not an option

Some domains cannot have an ACT route at all. Clinical orientation and
screening — sickle-cell disease, haemophilia, rare diseases — are the clearest
case: a mis-routed support ticket is re-routed the next morning; a person sent
down the wrong care pathway is not.

Every SDK therefore ships a second constructor:

```
Thresholds.advisory(confirm, measured_on, measured_at)
```

Under it, `route()` **cannot return ACT**, whatever confidence the model
reports. The most a reading earns is CONFIRM — a proposal a qualified human
accepts or rejects. The guarantee is structural, not a matter of choosing a high
threshold: a threshold can be edited in passing, a missing branch cannot.

`advisory` travels in the log, so a reading can be shown afterwards to have been
advisory-only.

---

## 4. The call

```
ask(state, questions, model?) -> Reading
```

- `state`: text, or a structure (map) serialised as JSON. ≤ 32k tokens.
- `questions`: a map `name -> Question`. **All evaluated in a single call** —
  that is 12× cheaper and 10× faster than one question per call.
- `model`: a **pinned** version. A moving alias would silently invalidate your
  thresholds the day the provider ships an update.

```
Reading {
  model: str                    # the version that ACTUALLY answered
  answers: {name -> Answer}
  usage: {input_tokens, output_tokens}
}
```

`model` is returned exactly as the server reported it, never echoed back from
the request: that is what lets you notice you were not served by the version you
asked for.

### What you do not send it

Names, phone numbers, personal identifiers. An SDK cannot enforce this, but each
SDK's documentation says it and its examples show it.

---

## 5. Errors — the same names everywhere

| Error | When | Retry? |
|---|---|---|
| `ToliConfigError` | missing key, inconsistent thresholds, one-option `Choice` | no — this is a caller bug |
| `ToliAuthError` | 401 / 403 | no |
| `ToliRateLimitError` | 429 | yes, after `retry_after` |
| `ToliUnavailableError` | 5xx, 529, dropped connection | yes |
| `ToliTimeoutError` | deadline exceeded | yes |
| `ToliProtocolError` | response without `answers`, unreadable JSON | no |

Each one carries `status` (when HTTP), `request_id` (the `x-request-id` header)
and a body excerpt capped at **300 characters** — enough to diagnose, too little
to spill a whole state into a log file.

### Retries

Five attempts, exponential backoff from 1 s (1, 2, 4, 8, 16), on **429, 529, 5xx
and dropped connections**. A connection timeout is transient and retries like a
429: across 897 real readings, three were lost for want of that rule.

A `retry_after` returned by the server always wins over the local backoff.

---

## 6. Transports

```
Gateway (default)  POST https://toli.essabu.com/v1/ask   Authorization: Bearer <Essabu key>
Direct (dev only)  POST {base}/v1/systemone              Authorization: Bearer <provider key>
```

`https://toli.essabu.com` is the default base, hard-coded in every SDK: a correct
integration has no URL to configure. (`toli.cd` follows later; the day it serves,
it becomes an alternative base, not a second contract.)

The gateway is the **only public path**: it holds the provider key, carries
quotas, billing and the audit log, and lets the engine change without touching a
single SDK. The direct transport exists to develop against before the gateway is
deployed; it is labelled as such, and the provider's name appears nowhere in the
public API.

Deadlines: 15 s to connect, 60 s overall.

---

## 7. What gets logged

Enough to replay a decision six months later: `model`, the question name, the
returned value, the confidence, the **whole** probability distribution, the
route taken and the thresholds that produced it. Not the state.

---

## 8. Version

The contract is versioned (`CONTRACT_VERSION` below) and every SDK exposes that
value. Two SDKs on different contract versions may diverge — and that becomes
visible instead of subtle.

```
CONTRACT_VERSION = 1
```
