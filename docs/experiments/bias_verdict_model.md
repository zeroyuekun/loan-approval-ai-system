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
