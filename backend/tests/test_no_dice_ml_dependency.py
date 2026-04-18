"""Guard: `dice_ml` must not be imported anywhere in ml_engine.

The `_dice_counterfactuals` call path was never actually wired up — in
production the orchestrator always passes `transform_fn=predictor._transform`,
which sends `generate()` straight to the binary-search fallback. `dice_ml`
was never added to requirements.txt, so even the one unguarded call path
(no transform_fn) raised ImportError and fell through to fallback.

This test locks in the D5 removal of the dead DiCE code by asserting no
source file under `apps/ml_engine` references `dice_ml`.
"""

import ast
from pathlib import Path


_BANNED_NAMES = {"_dice_counterfactuals", "_build_dice_dataset", "_parse_dice_result"}


def _has_dice_code(path: Path) -> bool:
    """True if *path* has a dice_ml import, dice_ml.X attribute access, or
    a def/call of the banned DiCE helper methods.

    String mentions in docstrings or assertion messages don't count — only
    executable references that would fire at import/call time.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "dice_ml" or alias.name.startswith("dice_ml.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == "dice_ml" or (node.module or "").startswith("dice_ml."):
                return True
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "dice_ml":
                return True
        elif isinstance(node, ast.FunctionDef):
            if node.name in _BANNED_NAMES:
                return True
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _BANNED_NAMES:
                return True
            if isinstance(func, ast.Name) and func.id in _BANNED_NAMES:
                return True
    return False


def test_no_dice_ml_references_in_ml_engine():
    ml_engine = Path(__file__).resolve().parents[1] / "apps" / "ml_engine"
    offenders = [str(py.relative_to(ml_engine.parent.parent)) for py in ml_engine.rglob("*.py") if _has_dice_code(py)]

    assert not offenders, (
        "Dead DiCE code still present. The `_dice_counterfactuals` callpath "
        "was never wired up (dice_ml is not in requirements) and production "
        "always takes the binary-search fallback. Offenders: " + ", ".join(offenders)
    )
