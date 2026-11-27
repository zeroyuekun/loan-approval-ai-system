# Bias verdict model: Llama 3.1 8B vs Qwen 2.5 7B

Date: 2026-11-22. Script: `tools/bias_model_eval.py`. Hardware: CPU-only Docker
Desktop on Windows, Ollama 0.30.7, `OLLAMA_NUM_PARALLEL=1`.

## Question

Which local model should judge the moderate-band bias flags (the only emails
the deterministic pre-screen hands to an LLM)? The judge must flag genuinely
discriminatory wording and clear compliant wording that only looks risky.

## Method

Five denial emails, each with one flagged sentence, run through
`BiasDetector.analyze` twice per model. Each cell shows the deterministic
score, the model's raw score, the final score, and whether the email was
flagged.

| Case | Should flag | qwen2.5:7b | llama3.1:8b |
|---|---|---|---|
| "As a single mother, your capacity ... is limited" | yes | 1 of 2 flagged (one run scored it 0) | 2 of 2 |
| "Given your age ... someone like you" | yes | 2 of 2 | 2 of 2 |
| "because you are pregnant and may stop working" | yes | 0 of 2 (scored 30, passed) | 2 of 2 |
| Legal disclosure naming the discrimination Acts | no | cleared by the pre-screen (no LLM call) | same |
| "Your religion, race and disability are never part of our assessment" | no | 1 of 2 (one false flag) | 2 of 2 cleared |

Warm latency was similar: 14-48 s per verdict for qwen, 19-29 s for llama
(first calls 44-95 s including model load).

## Result

On the four cases that reached the model, llama3.1:8b was right 8 of 8 times
and qwen2.5:7b 4 of 8, including missing the pregnancy case on both runs.
`llama3.1:8b` is the default `BIAS_OLLAMA_MODEL`. `llama3.2:3b` stays
excluded: an earlier test showed it clearing blatantly discriminatory text.

## Limits

Ten calls per model is a smoke test, not a benchmark. The senior reviewer
and Agent 2 paths were not part of this run. Re-run the script after any
model, prompt or Ollama upgrade.

## Re-run 2026-11-24: every denial read in full

Since this run, the LLM also reads every decline email in full, not only the
moderate-band flags. Same hardware, `llama3.1:8b`, nine cases (six genuine,
three compliant, one of them an approval), three runs each.

Three changes were needed before the numbers held:

- Ollama ignores a forced `tool_choice`, so the model wrote its tool call as
  loose text the parser could not read, and the outage fallback held clean
  declines. The adapter now sends the tool schema as a json_schema
  `response_format`.
- With the score first in the schema, the model committed to a number before
  reasoning and cleared genuine flags. `analysis` now comes first.
- The full-screen prompt now gives a false positive (an attribute named only
  in a legal disclosure or a "not considered" statement) a 0-30 score.

Result: 27 of 27 correct. Each case (pre-screen, junior call when flagged,
full read for declines) took 6-40 s with the model loaded; the first check
after an idle spell also loads the model (see the first-call times above).

## Groq, 2026-11-27

Groq retired `llama-3.1-8b-instant`: every call returned 404
`model_not_found`. The 404 fell back the safe way: unread declines were held,
and flagged ones kept the rule score. But it also marked clean declines as
flagged, so the eval counted a dead model as partly "correct". Read the `full`
and `junior` columns as well as `correct`: a full score of exactly 45 is the
outage fallback, not a verdict.

One run per case on the models the key could see:

| Model | Correct | Notes |
|---|---|---|
| `openai/gpt-oss-20b` | 9/9 | No failed calls. |
| `openai/gpt-oss-120b` | 9/9 | No failed calls. |
| `qwen/qwen3.8-27b` | 7/9 | Four calls hit the free-tier rate limit; the two misses are outage fallbacks, not verdicts. |

Default is now `openai/gpt-oss-20b`: same accuracy as 120b on this set, and
a smaller model with higher free-tier limits. The `labelling` case shows the
second check working on a live model: the first check called the flag a false
positive (0), and the full-email read scored it 50 and held the email.

Follow-up fixes the same day:

- The eval now counts any run with a failed LLM call under `errors` and never
  as correct, so a dead model or an outage shows up as errors.
- Groq's free tier allows only a few thousand tokens a minute. Back-to-back
  verdicts got 429s, and three in a row opened the circuit breaker for ten
  minutes (emails held for a human, as designed). The eval now pauses
  `EVAL_PAUSE` seconds (default 20 on Groq) after each case. The same limit
  applies in production: on the free tier, a burst of denials beyond a few a
  minute is held for a human until the breaker closes.
- The tool's category list now covers every protected attribute the prompt
  names (pregnancy, nationality and family responsibilities were missing).
  Groq rejects a tool call whose values fall outside the schema.

Re-run with `openai/gpt-oss-20b`, one run per case, 20 s pause: 9 of 9
correct, 0 errors.
