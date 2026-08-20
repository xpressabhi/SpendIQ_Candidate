"""Golden-set evaluation harness for the SpendIQ agent.

`cases.py` holds the tiered question set with composable checks
(deterministic substring/count/tool/source checks plus optional
LLM-as-judge rubrics). `runner.py` executes cases through the real
agent and grades them; `graders.py` implements the individual checks.
"""

from .cases import CASES
from .runner import run_evals

__all__ = ["CASES", "run_evals"]
