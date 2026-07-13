"""Research-only labels that separate return ranking from execution-path risk."""
from __future__ import annotations

import pandas as pd


_RETURN_COLUMN = "net_return_after_cost_10d"
_GRADE_COLUMN = "return_relevance_grade_10d"
_TOP10_COLUMN = "label_return_top10_10d"
_REQUIRED_COLUMNS = ("trade_date", "eligible_for_training", _RETURN_COLUMN)


def add_return_only_labels(rows: pd.DataFrame) -> pd.DataFrame:
    """Derive costed-return labels without changing canonical path-risk labels."""
    missing = sorted(set(_REQUIRED_COLUMNS) - set(rows.columns))
    if missing:
        raise ValueError("return-only label input missing columns: " + ", ".join(missing))

    result = rows.copy()
    result[_GRADE_COLUMN] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result[_TOP10_COLUMN] = pd.Series(False, index=result.index, dtype="boolean")
    returns = pd.to_numeric(result[_RETURN_COLUMN], errors="coerce")
    eligible = result["eligible_for_training"].eq(True) & returns.notna()

    for _trade_date, indexes in result.loc[eligible].groupby("trade_date", sort=False).groups.items():
        current_returns = returns.loc[indexes]
        top_rank = current_returns.rank(ascending=False, method="max", pct=True)
        positive = current_returns.gt(0)
        grades = pd.Series(0, index=indexes, dtype="Int64")
        grades.loc[positive] = 1
        grades.loc[top_rank.le(0.20) & positive] = 2
        grades.loc[top_rank.le(0.10) & positive] = 3
        grades.loc[top_rank.le(0.05) & positive] = 4
        result.loc[indexes, _GRADE_COLUMN] = grades
        result.loc[indexes, _TOP10_COLUMN] = (top_rank.le(0.10) & positive).astype("boolean")

    return result
