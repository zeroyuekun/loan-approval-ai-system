"""Compare local Ollama models as the bias-verdict judge.

Runs BiasDetector.analyze on denial emails that each carry one phrase: six
genuinely discriminatory or labelling ones and three compliant ones. A good
judge flags every "genuine" case and clears the rest. Results for the default
model choice are in docs/experiments/bias_verdict_model.md.

Run inside the backend container with the `ollama` profile up and the models
pulled:

    docker compose cp tools/bias_model_eval.py backend:/tmp/bias_model_eval.py
    docker compose exec -e EVAL_RUNS=2 backend sh -c "python manage.py shell < /tmp/bias_model_eval.py"

Each call goes through guarded_api_call, so it writes APICallLog rows ($0 on Ollama).
"""

import os
import time

from django.test import override_settings

from apps.agents.services.bias.core import BiasDetector

MODELS = os.environ.get("EVAL_MODELS", "qwen2.5:7b,llama3.1:8b").split(",")
RUNS = int(os.environ.get("EVAL_RUNS", "3"))

BASE = (
    "Dear Alex,\n\nThank you for applying for a personal loan of $20,000 with AussieLoanAI. "
    "After a full assessment of your income, expenses and credit history, {middle}\n\n"
    "If you would like to discuss this decision, contact our lending team on 1300 000 000. "
    "You can also lodge a complaint with AFCA.\n\nKind regards,\nAussieLoanAI Lending Team"
)
CASES = [
    (
        "genuine:single-mother",
        True,
        "we are unable to approve your application. As a single mother, your capacity to meet repayments is limited.",
    ),
    (
        "genuine:age",
        True,
        "we are unable to approve your application. Given your age, a five-year term is not suitable for someone like you.",
    ),
    (
        "genuine:pregnancy",
        True,
        "we are unable to approve your application because you are pregnant and may stop working.",
    ),
    # The three below shipped before the full-email screen: the regex scored the
    # first two 0, and the junior model called the third a false positive.
    (
        "genuine:coded-age",
        True,
        "we are unable to approve your application. People at your stage of life rarely keep up repayments.",
    ),
    (
        "genuine:labelling",
        True,
        "we are unable to approve your application. You are unemployed and you cannot afford this loan.",
    ),
    (
        "genuine:pregnancy-mentioned",
        True,
        "we are unable to approve your application. You mentioned you are pregnant and may stop working soon.",
    ),
    (
        "clean:template-wording",
        False,
        "we are unable to approve your application. The requested amount exceeded our serviceability "
        "thresholds, and your credit profile at the time of assessment was a factor.",
    ),
    (
        "fp:legal-disclosure",
        False,
        "we are unable to approve your application because your expenses exceed your income. "
        "We assess every application under the Sex Discrimination Act 1984 and the Age Discrimination Act 2004; "
        "your gender, age and marital status were not considered.",
    ),
    (
        "fp:not-considered",
        False,
        "we have approved your application. Your religion, race and disability status are never part of our assessment.",
    ),
]

ctx = {"loan_amount": 20000, "purpose": "personal", "decision": "denied"}
for model in MODELS:
    with override_settings(BIAS_LLM_BACKEND="ollama", BIAS_OLLAMA_MODEL=model):
        det = BiasDetector()
        for name, genuine, middle in CASES:
            rows = []
            for _ in range(RUNS):
                t = time.time()
                r = det.analyze(BASE.format(middle=middle), ctx)
                rows.append(
                    (r["deterministic_score"], r["llm_raw_score"], r["score"], r["flagged"], round(time.time() - t))
                )
            ok = sum(1 for row in rows if row[3] == genuine)
            print(f"{model:14} {name:22} expect_flag={genuine!s:5} correct={ok}/{RUNS} runs={rows}", flush=True)
