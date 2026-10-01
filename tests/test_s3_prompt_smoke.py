from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "eval"
    / "studies"
    / "s3-redocred"
    / "prompt_smoke.py"
)
SPEC = importlib.util.spec_from_file_location("s3_prompt_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
s3_prompt_smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(s3_prompt_smoke)


@pytest.mark.skipif(
    not os.environ.get("DEEPREFINE_REPO"),
    reason="set DEEPREFINE_REPO to run the research-engine prompt smoke",
)
def test_real_action_prompt_open_closed_contract() -> None:
    result = s3_prompt_smoke.run_prompt_smoke(Path(os.environ["DEEPREFINE_REPO"]))

    assert result["open_contains_sentinel"] is True
    assert result["closed_contains_sentinel"] is False
    assert result["only_difference_is_context"] is True
