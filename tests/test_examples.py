import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))

import pytest  # noqa: E402

from export_github_repos import csv_safe  # noqa: E402


@pytest.mark.parametrize("value", ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tx", "\rx"])
def test_csv_safe_neutralises_formula_prefixes(value):
    assert csv_safe(value).startswith("'")


@pytest.mark.parametrize("value", ["normal", "", 5, None, "a=b"])
def test_csv_safe_leaves_ordinary_values_alone(value):
    assert csv_safe(value) == value
