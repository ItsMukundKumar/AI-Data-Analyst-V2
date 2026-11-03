"""Analytics endpoints: profile, KPIs, recommendations, custom charts, insights, explorer, cleaning."""
import io
import json
from typing import List, Literal, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services import analytics as A
from services import dataset_store as store

router = APIRouter(prefix="/analytics", tags=["Analytics"])


class Filter(BaseModel):
    column: str
    op: Literal["range", "in", "date_range"]
    min: Optional[float] = None
    max: Optional[float] = None
    values: Optional[List[str]] = None
    start: Optional[str] = None
    end: Optional[str] = None


class FilterBody(BaseModel):
    filters: List[Filter] = Field(default_factory=list, max_length=20)


class ChartConfig(BaseModel):
    chart_type: Literal["bar", "line", "scatter", "pie", "donut", "histogram", "box", "heatmap"]
    x: Optional[str] = None
    y: Optional[str] = None
    agg: Literal["count", "sum", "mean", "median", "min", "max", "nunique"] = "count"
    color: Optional[str] = None
    value: Optional[str] = None
    bins: Optional[int] = Field(20, ge=2, le=200)   # null means "use default"
    top_n: Optional[int] = Field(15, ge=1, le=100)
    time_grain: Optional[Literal["day", "week", "month", "quarter", "year"]] = None


class ChartBody(FilterBody):
    config: ChartConfig


class ExplorerBody(FilterBody):
    page: int = Field(1, ge=1)
    page_size: int = Field(25, ge=5, le=200)
    sort_by: Optional[str] = None
    sort_dir: Literal["asc", "desc"] = "asc"
    search: Optional[str] = Field(None, max_length=100)


class CleanBody(FilterBody):
    drop_duplicates: bool = False
    drop_missing_rows: bool = False
    fill_numeric: Optional[Literal["mean", "median", "zero"]] = None
    fill_categorical_mode: bool = False


def _load(dataset_id: str):
    try:
        df = store.get_dataframe(dataset_id)
    except store.DatasetNotFound as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Unable to read dataset: {e}")
    kinds = store.memo(dataset_id, "kinds", lambda: A.column_kinds(df))
    return df, kinds


def _filtered(dataset_id: str, body: FilterBody):
    df, kinds = _load(dataset_id)
    flt = [f.model_dump(exclude_none=True) for f in body.filters]
    try:
        return A.apply_filters(df, flt, kinds), kinds, len(df), flt
    except A.AnalyticsError as e:
        raise HTTPException(400, str(e))


def _memo_filtered(dataset_id, name, flt, extra, builder):
    key = f"{name}:{json.dumps(flt, sort_keys=True)}:{extra}"
    entry_count = store.memo(dataset_id, "_count", lambda: {"n": 0})
    if entry_count["n"] > 60:  # keep cache bounded
        store._cache[dataset_id]["memo"].clear()
        entry_count["n"] = 0
    entry_count["n"] += 1
    return store.memo(dataset_id, key, builder)


@router.get("/datasets")
def recent_datasets():
    return {"success": True, "datasets": store.list_datasets()}


@router.get("/{dataset_id}/profile")
def get_profile(dataset_id: str):
    df, kinds = _load(dataset_id)
    p = store.memo(dataset_id, "profile", lambda: A.profile(df, kinds))
    return {"success": True, "dataset_id": dataset_id, "rows": len(df), **p}


@router.post("/{dataset_id}/stats")
def get_stats(dataset_id: str, body: FilterBody = FilterBody()):
    d, kinds, total, flt = _filtered(dataset_id, body)
    return {"success": True, "kpis": A.kpis(d, kinds, total)}


@router.post("/{dataset_id}/recommendations")
def get_recommendations(dataset_id: str, body: FilterBody = FilterBody()):
    d, kinds, total, flt = _filtered(dataset_id, body)
    if d.empty:
        return {"success": True, "charts": [], "message": "No rows match the current filters."}
    charts = _memo_filtered(dataset_id, "rec", flt, "", lambda: A.recommend(d, kinds))
    return {"success": True, "charts": charts, "rows_used": len(d)}


@router.post("/{dataset_id}/chart")
def custom_chart(dataset_id: str, body: ChartBody):
    d, kinds, total, flt = _filtered(dataset_id, body)
    try:
        res = A.build_chart(d, kinds, body.config.model_dump(exclude_none=True))
    except A.AnalyticsError as e:
        raise HTTPException(400, str(e))
    return {"success": True, **res}


@router.post("/{dataset_id}/insights")
def get_insights(dataset_id: str, body: FilterBody = FilterBody()):
    d, kinds, total, flt = _filtered(dataset_id, body)
    ins = _memo_filtered(dataset_id, "ins", flt, "", lambda: A.insights(d, kinds))
    return {"success": True, "insights": ins, "outliers": A.outliers(d, kinds)["columns"]}


@router.post("/{dataset_id}/explorer")
def explorer(dataset_id: str, body: ExplorerBody):
    d, kinds, total, flt = _filtered(dataset_id, body)
    if body.search:
        s = body.search.lower()
        mask = d.astype(str).apply(lambda col: col.str.lower().str.contains(s, regex=False)).any(axis=1)
        d = d[mask]
    if body.sort_by:
        if body.sort_by not in d.columns:
            raise HTTPException(400, f"Unknown sort column '{body.sort_by}'.")
        d = d.sort_values(body.sort_by, ascending=body.sort_dir == "asc", na_position="last")
    n = len(d)
    start = (body.page - 1) * body.page_size
    page = d.iloc[start:start + body.page_size]
    return {"success": True, "total": n, "page": body.page, "page_size": body.page_size,
            "columns": [{"name": c, "kind": kinds[c]} for c in d.columns],
            "rows": [[A.jv(v) for v in r] for r in page.values.tolist()]}


def _clean(d: pd.DataFrame, kinds, b: CleanBody):
    d = d.copy()
    steps = []
    before = len(d)
    if b.drop_duplicates:
        d = d.drop_duplicates()
        steps.append(f"Removed {before - len(d)} duplicate row(s).")
    if b.fill_numeric:
        filled = 0
        for c in A.cols_of(kinds, "numeric"):
            m = int(d[c].isna().sum())
            if m:
                d[c] = d[c].fillna(0 if b.fill_numeric == "zero" else getattr(d[c], b.fill_numeric)())
                filled += m
        steps.append(f"Filled {filled} numeric missing value(s) with the {b.fill_numeric}.")
    if b.fill_categorical_mode:
        filled = 0
        for c in A.cols_of(kinds, "categorical", "boolean"):
            m = int(d[c].isna().sum())
            if m and not d[c].mode().empty:
                d[c] = d[c].fillna(d[c].mode().iloc[0])
                filled += m
        steps.append(f"Filled {filled} categorical missing value(s) with the most frequent value.")
    if b.drop_missing_rows:
        before = len(d)
        d = d.dropna()
        steps.append(f"Removed {before - len(d)} row(s) that still contained missing values.")
    return d, steps


@router.post("/{dataset_id}/clean/preview")
def clean_preview(dataset_id: str, body: CleanBody):
    d, kinds, total, flt = _filtered(dataset_id, body)
    cleaned, steps = _clean(d, kinds, body)
    return {"success": True, "steps": steps or ["No cleaning options selected."],
            "before": A.kpis(d, kinds), "after": A.kpis(cleaned, kinds)}


@router.post("/{dataset_id}/clean/download")
def clean_download(dataset_id: str, body: CleanBody):
    """Returns a cleaned CSV copy. The uploaded original is never modified."""
    d, kinds, total, flt = _filtered(dataset_id, body)
    cleaned, _ = _clean(d, kinds, body)
    buf = io.StringIO()
    cleaned.to_csv(buf, index=False)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="cleaned_{dataset_id[:8]}.csv"'})
