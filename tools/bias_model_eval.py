"""Compare models as the bias-verdict judge, on Groq (default) or local Ollama.

Runs BiasDetector.analyze on decision emails that each carry one phrase: six
genuinely discriminatory or labelling ones and three compliant ones. A good
judge flags every "genuine" case and clears the rest. Results for the default
model choice are in docs/experiments/bias_verdict_model.md.

Run inside the backend container. Groq needs GROQ_API_KEY in .env; Ollama
needs the `ollama` profile up and the models pulled:

    docker compose cp tools/bias_model_eval.py backend:/tmp/bias_model_eval.py
    docker compose exec -e EVAL_RUNS=2 backend sh -c "python manage.py shell < /tmp/bias_model_eval.py"
    docker compose exec -e EVAL_BACKEND=ollama -e EVAL_MODELS=llama3.1:8b backend sh -c "..."

On Groq, EVAL_PAUSE (default 20 s) spaces the cases out to stay under the
free-tier token limit; a run with any failed call is reported under errors.

Each call goes through guarded_api_call, so it writes APICallLog rows ($0 on
both free backends).
"""

import os
import time

from django.test import override_settings

from apps.agents.services.bias import core
from apps.agents.services.bias.core import BiasDetector

# A failed LLM call (404, 429, timeout, unparseable reply) returns the caller's
# fallback, and the fallback holds the email: on a genuine case that looks
# "correct". Count those calls so a dead model cannot score well.
_real_call = core._call_with_fallback
_failed_calls = []


def _counting_call(client, fallback, *args, **kwargs):
    result = _real_call(client, fallback, *args, **kwargs)
    if result is fallback:
        _failed_calls.append(kwargs.get("_service"))
    return result


core._call_with_fallback = _counting_call

BACKEND = os.environ.get("EVAL_BACKEND", "groq")
MODEL_SETTING = {"groq": "BIAS_GROQ_MODEL", "ollama": "BIAS_OLLAMA_MODEL"}[BACKEND]
MODELS = os.environ.get("EVAL_MODELS", "openai/gpt-oss-20b" if BACKEND == "groq" else "llama3.1:8b").split(",")
RUNS = int(os.environ.get("EVAL_RUNS", "3"))
# Seconds to wait after each case. Groq's free tier allows only a few thousand
# tokens a minute; back-to-back verdicts get 429s, and three in a row open the
# circuit breaker for ten minutes. Each case makes one or two calls.
PAUSE = float(os.environ.get("EVAL_PAUSE", "20" if BACKEND == "groq" else "0"))

BASE = (
    "Dear Alex,\n\nThank you for applying for a personal loan of $20,000 with AussieLoanAI. "
    "After a full assessment of your income, expenses and credit history, {middle}\n\n"
    "If you would like to discuss this decision, contact our lending team on 1300 000 000. "
    "You can also lodge a complaint with AFCA.\n\nKind regards,\nAussieLoanAI Lending Team"
)
CASES = [
    (
        "genuine:single-mother",
        "denied",
        True,
        "we are unable to approve your application. As a single mother, your capacity to meet repayments is limited.",
    ),
    (
        "genuine:age",
        "denied",
        True,
        "we are unable to approve your application. Given your age, a five-year term is not suitable for someone like you.",
    ),
    (
        "genuine:pregnancy",
        "denied",
        True,
        "we are unable to approve your application because you are pregnant and may stop working.",
    ),
    # Phrasings the regex pre-screen misses or only half-scores: the full-email
    # read has to catch them.
    (
        "genuine:coded-age",
        "denied",
        True,
        "we are unable to approve your application. People at your stage of life rarely keep up repayments.",
    ),
    (
        "genuine:labelling",
        "denied",
        True,
        "we are unable to approve your application. You are unemployed and you cannot afford this loan.",
    ),
    (
        "genuine:pregnancy-mentioned",
        "denied",
        True,
        "we are unable to approve your application. You mentioned you are pregnant and may stop working soon.",
    ),
    (
        "clean:template-wording",
        "denied",
        False,
        "we are unable to approve your application. The requested amount exceeded our serviceability "
        "thresholds, and your credit profile at the time of assessment was a factor.",
    ),
    (
        "fp:legal-disclosure",
        "denied",
        False,
        "we are unable to approve your application because your expenses exceed your income. "
        "We assess every application under the Sex Discrimination Act 1984 and the Age Discrimination Act 2004; "
        "your gender, age and marital status were not considered.",
    ),
    (
        "fp:not-considered",
        "approved",
        False,
        "we have approved your application. Your religion, race and disability status are never part of our assessment.",
    ),
]

for model in MODELS:
    with override_settings(BIAS_LLM_BACKEND=BACKEND, **{MODEL_SETTING: model}):
        det = BiasDetector()
        for name, decision, genuine, middle in CASES:
            # Approvals never get the denial-only full-email screen, here as in production.
            ctx = {"loan_amount": 20000, "purpose": "personal", "decision": decision}
            runs = []
            for _ in range(RUNS):
                t = time.time()
                _failed_calls.clear()
                r = det.analyze(BASE.format(middle=middle), ctx)
                time.sleep(PAUSE)
                runs.append(
                    {
                        "det": r["deterministic_score"],
                        "junior": r["llm_raw_score"],
                        "full": r.get("full_screen_score"),
                        "score": r["score"],
                        "flagged": r["flagged"],
                        "source": r["score_source"],
                        "failed_calls": list(_failed_calls),
                        "secs": round(time.time() - t),
                    }
                )
            # A run with a failed LLM call is an error, never a correct verdict.
            ok = sum(1 for run in runs if run["flagged"] == genuine and not run["failed_calls"])
            errors = sum(1 for run in runs if run["failed_calls"])
            print(
                f"{model:14} {name:28} expect_flag={genuine!s:5} correct={ok}/{RUNS} errors={errors} runs={runs}",
                flush=True,
            )
