"""Analytics engine. Everything returned here is computed from the uploaded DataFrame.

Charts are returned as plain Plotly trace/layout dicts (JSON-safe lists, no numpy arrays)
so any Plotly.js version can render them. Nothing here executes user-supplied code:
the frontend only picks columns / aggregations from fixed, validated whitelists.
"""
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from scipy import stats as sps

from services.dataset_store import sample

AGGS = {"count", "sum", "mean", "median", "min", "max", "nunique"}
NUMERIC_ONLY_AGGS = {"sum", "mean", "median", "min", "max"}
CHART_TYPES = {"bar", "line", "scatter", "pie", "donut", "histogram", "box", "heatmap"}
GRAINS = {"day", "week", "month", "quarter", "year"}
PERIOD = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
SUM_HINT = re.compile(r"sale|revenue|amount|quantity|qty|total|profit|cost|spend|units|orders|count|salary|price", re.I)
ID_NAME = re.compile(r"(^|[_\s\-])(id|uuid|guid|index|idx|no|num|number|code)$", re.I)
MAX_CATS = 30
POINTS_CAP = 5000


class AnalyticsError(ValueError):
    """User-facing validation problem (mapped to HTTP 400)."""


# --------------------------------------------------------------------------- helpers
def jv(v: Any) -> Any:
    """Convert any numpy / pandas scalar into a JSON-safe Python value (NaN -> None)."""
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (int, str)):
        return v
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)


def jl(seq) -> list:
    return [jv(v) for v in seq]


def rnd(v, n=4):
    v = jv(v)
    return round(v, n) if isinstance(v, float) else v


# --------------------------------------------------------------------------- column typing
def column_kinds(df: pd.DataFrame) -> Dict[str, str]:
    """numeric | categorical | datetime | boolean | text | identifier | constant"""
    n = len(df)
    kinds = {}
    for c in df.columns:
        s = df[c]
        nn = s.dropna()
        nu = nn.nunique()
        if nn.empty or nu <= 1:
            kinds[c] = "constant"
        elif pd.api.types.is_bool_dtype(s):
            kinds[c] = "boolean"
        elif pd.api.types.is_datetime64_any_dtype(s):
            kinds[c] = "datetime"
        elif pd.api.types.is_numeric_dtype(s):
            is_int = pd.api.types.is_integer_dtype(s) or bool((nn % 1 == 0).all())
            if is_int and nu == len(nn) and len(nn) >= 20 and (ID_NAME.search(c) or nn.is_monotonic_increasing):
                kinds[c] = "identifier"
            elif ID_NAME.search(c) and is_int and nu / max(len(nn), 1) > 0.9 and len(nn) >= 20:
                kinds[c] = "identifier"
            elif nu == 2 and is_int and set(nn.unique()) <= {0, 1}:
                kinds[c] = "boolean"
            else:
                kinds[c] = "numeric"
        else:
            if nu <= MAX_CATS and nu < 0.9 * len(nn):
                kinds[c] = "categorical"
            elif nu <= 8 and len(nn) <= 10 and nu < len(nn):
                kinds[c] = "categorical"
            else:
                kinds[c] = "text"
    return kinds


def cols_of(kinds, *wanted):
    return [c for c, k in kinds.items() if k in wanted]


def group_cols(kinds):
    """Columns that make sense as a grouping / colour dimension."""
    return cols_of(kinds, "categorical", "boolean")


# --------------------------------------------------------------------------- profile
def profile(df: pd.DataFrame, kinds: Dict[str, str]) -> Dict[str, Any]:
    cols = []
    for c in df.columns:
        s = df[c]
        k = kinds[c]
        info = {"name": c, "kind": k, "dtype": str(s.dtype), "non_null": int(s.notna().sum()),
                "missing": int(s.isna().sum()),
                "missing_pct": rnd(s.isna().mean() * 100, 2) if len(s) else 0,
                "unique": int(s.nunique(dropna=True))}
        nn = s.dropna()
        if k == "numeric" and not nn.empty:
            info.update(min=rnd(nn.min()), max=rnd(nn.max()), mean=rnd(nn.mean()),
                        median=rnd(nn.median()), std=rnd(nn.std()) if len(nn) > 1 else None)
        elif k == "datetime" and not nn.empty:
            info.update(min=jv(nn.min()), max=jv(nn.max()))
        elif k in ("categorical", "boolean"):
            vc = nn.astype(str).value_counts().head(MAX_CATS)
            info["categories"] = [{"value": v, "count": int(n)} for v, n in vc.items()]
        elif k == "text" and not nn.empty:
            info["sample"] = jl(nn.astype(str).head(3))
        cols.append(info)
    return {"columns": cols}


# --------------------------------------------------------------------------- filters
def apply_filters(df: pd.DataFrame, filters: Optional[List[dict]], kinds: Dict[str, str]) -> pd.DataFrame:
    if not filters:
        return df
    mask = pd.Series(True, index=df.index)
    for f in filters:
        col, op = f.get("column"), f.get("op")
        if col not in df.columns:
            raise AnalyticsError(f"Filter column '{col}' does not exist.")
        k = kinds.get(col)
        s = df[col]
        if op == "range":
            if k != "numeric":
                raise AnalyticsError(f"Range filter needs a numeric column; '{col}' is {k}.")
            lo, hi = f.get("min"), f.get("max")
            if lo is not None:
                mask &= s >= lo
            if hi is not None:
                mask &= s <= hi
        elif op == "in":
            vals = f.get("values") or []
            if not vals:
                continue
            mask &= s.astype(str).isin([str(v) for v in vals])
        elif op == "date_range":
            if k != "datetime":
                raise AnalyticsError(f"Date filter needs a date column; '{col}' is {k}.")
            try:
                if f.get("start"):
                    mask &= s >= pd.to_datetime(f["start"])
                if f.get("end"):
                    mask &= s < pd.to_datetime(f["end"]) + pd.Timedelta(days=1)
            except Exception:
                raise AnalyticsError("Invalid date in date filter.")
        else:
            raise AnalyticsError(f"Unknown filter operation '{op}'.")
    return df[mask]


# --------------------------------------------------------------------------- KPIs / quality
def kpis(df: pd.DataFrame, kinds: Dict[str, str], total_rows: Optional[int] = None) -> Dict[str, Any]:
    try:
        dups = int(df.duplicated().sum())
    except TypeError:
        dups = int(df.astype(str).duplicated().sum())
    cells = df.shape[0] * df.shape[1]
    missing = int(df.isna().sum().sum())
    return {
        "rows": int(len(df)), "total_rows": int(total_rows if total_rows is not None else len(df)),
        "columns": int(df.shape[1]), "missing_values": missing,
        "missing_pct": rnd(missing / cells * 100, 2) if cells else 0,
        "duplicate_rows": dups,
        "numeric_columns": len(cols_of(kinds, "numeric")),
        "categorical_columns": len(cols_of(kinds, "categorical", "boolean", "text")),
        "datetime_columns": len(cols_of(kinds, "datetime")),
        "memory_bytes": int(df.memory_usage(deep=True).sum()),
    }


# --------------------------------------------------------------------------- figure helpers
def fig(data, title, xt=None, yt=None, **layout):
    lay = {"title": {"text": title}, "showlegend": len(data) > 1 or layout.pop("legend", False)}
    layout.pop("legend", None)
    if xt:
        lay["xaxis"] = {"title": {"text": xt}}
    if yt:
        lay["yaxis"] = {"title": {"text": yt}}
    lay.update(layout)
    return {"data": data, "layout": lay}


def _agg_series(g, y: Optional[str], agg: str):
    """Apply agg to a groupby object -> Series."""
    if y is None or agg == "count":
        return g.size() if y is None else g[y].count()
    if agg == "nunique":
        return g[y].nunique()
    return getattr(g[y], agg)()


def _bin_numeric(s: pd.Series, bins=10) -> pd.Series:
    cut = pd.cut(s, bins=bins, duplicates="drop")
    return cut.apply(lambda iv: f"{iv.left:.4g} – {iv.right:.4g}" if pd.notna(iv) else None)


def _label(agg, y):
    if y is None or agg == "count":
        return "Count" if y is None else f"Count of {y}"
    return f"{agg.capitalize()} of {y}"


def _auto_grain(s: pd.Series) -> str:
    span = (s.max() - s.min()).days if s.notna().any() else 0
    return "day" if span <= 62 else "week" if span <= 180 else "month" if span <= 1500 else "year"


def _to_period(s: pd.Series, grain: str) -> pd.Series:
    if grain == "day":
        return s.dt.floor("D")
    return s.dt.to_period(PERIOD[grain]).dt.to_timestamp()


def _check(df, col, kinds, label, allowed=None, required=False):
    if not col:
        if required:
            raise AnalyticsError(f"{label} is required for this chart.")
        return None
    if col not in df.columns:
        raise AnalyticsError(f"Column '{col}' does not exist in this dataset.")
    if allowed and kinds.get(col) not in allowed:
        raise AnalyticsError(f"{label} '{col}' must be {' / '.join(allowed)} (it is {kinds.get(col)}).")
    return col


# --------------------------------------------------------------------------- chart builder
def build_chart(df: pd.DataFrame, kinds: Dict[str, str], cfg: Dict[str, Any]) -> Dict[str, Any]:
    ct = cfg.get("chart_type")
    if ct not in CHART_TYPES:
        raise AnalyticsError(f"Unsupported chart type '{ct}'.")
    agg = cfg.get("agg") or "count"
    if agg not in AGGS:
        raise AnalyticsError(f"Unsupported aggregation '{agg}'.")
    x, y, color, value = cfg.get("x"), cfg.get("y"), cfg.get("color"), cfg.get("value")
    for lab, col in (("X-axis", x), ("Y-axis", y), ("Colour column", color), ("Value column", value)):
        _check(df, col, kinds, lab)
    if y and agg in NUMERIC_ONLY_AGGS and kinds.get(y) != "numeric":
        raise AnalyticsError(f"'{agg}' needs a numeric Y column; '{y}' is {kinds.get(y)}. Use count or unique count.")
    if color and kinds.get(color) not in ("categorical", "boolean", "numeric") :
        raise AnalyticsError(f"Colour column '{color}' should be categorical (it is {kinds.get(color)}).")
    bins = int(cfg.get("bins") or 20)
    top_n = int(cfg.get("top_n") or 15)
    if not 2 <= bins <= 200 or not 1 <= top_n <= 100:
        raise AnalyticsError("bins must be 2-200 and top_n 1-100.")
    grain = cfg.get("time_grain")
    if grain and grain not in GRAINS:
        raise AnalyticsError(f"Unsupported time grain '{grain}'.")

    notes: List[str] = []
    if df.empty:
        return {"empty": True, "message": "No rows match the current filters.", "notes": [], "rows_used": 0}

    fn = {"bar": _bar, "line": _line, "scatter": _scatter, "pie": _pie, "donut": _pie,
          "histogram": _hist, "box": _box, "heatmap": _heat}[ct]
    f = fn(df, kinds, dict(cfg, agg=agg, x=x, y=y, color=color, value=value, bins=bins,
                           top_n=top_n, grain=grain, chart_type=ct), notes)
    if f is None:
        return {"empty": True, "message": "Not enough valid data to draw this chart.", "notes": notes, "rows_used": 0}
    return {"empty": False, "figure": f, "notes": notes, "rows_used": int(len(df)),
            "config": {"chart_type": ct, "x": x, "y": y, "agg": agg, "color": color, "value": value,
                       "bins": bins, "top_n": top_n, "time_grain": grain}}


def _color_groups(df, color, limit=10):
    vc = df[color].astype(str).value_counts()
    keep = list(vc.index[:limit])
    return keep, len(vc) > limit


def _bar(df, kinds, c, notes):
    x, y, agg, color = c["x"], c["y"], c["agg"], c["color"]
    if not x:
        raise AnalyticsError("X-axis is required for a bar chart.")
    d = df.copy()
    xk = kinds[x]
    if xk == "datetime":
        d[x] = _to_period(d[x], c["grain"] or _auto_grain(d[x])).dt.strftime("%Y-%m-%d")
    elif xk == "numeric" and d[x].nunique() > MAX_CATS:
        d[x] = _bin_numeric(d[x], 10)
        notes.append(f"'{x}' was grouped into 10 ranges.")
    d = d[d[x].notna()]
    d[x] = d[x].astype(str)
    if y is None:
        agg = "count"
    gcols = [x] + ([color] if color else [])
    if color:
        keep, more = _color_groups(d, color)
        d = d[d[color].astype(str).isin(keep)]
        d[color] = d[color].astype(str)
        if more:
            notes.append(f"Showing the 10 most common '{color}' groups.")
    res = _agg_series(d.groupby(gcols), y, agg)
    if res.empty:
        return None
    tot = res.groupby(level=0).sum() if color else res
    order = tot.sort_values(ascending=False).index
    ordered_x = xk in ("datetime",) or "–" in " ".join(map(str, order[:3]))
    if ordered_x:
        cats = sorted(tot.index, key=lambda v: str(v))
    else:
        cats = list(order)
    if len(cats) > c["top_n"] and not ordered_x:
        notes.append(f"Showing the top {c['top_n']} of {len(cats)} '{x}' values.")
        cats = cats[:c["top_n"]]
    lab = _label(agg, y)
    if color:
        data = [{"type": "bar", "name": g, "x": cats,
                 "y": jl([res.get((cat, g), np.nan) for cat in cats])} for g in sorted(d[color].unique())]
    else:
        data = [{"type": "bar", "x": cats, "y": jl([res[cat] for cat in cats]), "name": lab}]
    return fig(data, f"{lab} by {x}", x, lab, barmode="group")


def _line(df, kinds, c, notes):
    x, y, agg, color = c["x"], c["y"], c["agg"], c["color"]
    if not x:
        raise AnalyticsError("X-axis is required for a line chart.")
    d = df[df[x].notna()].copy()
    xk = kinds[x]
    if y is None:
        agg = "count"
    if xk == "datetime":
        grain = c["grain"] or _auto_grain(d[x])
        d["_x"] = _to_period(d[x], grain)
        notes.append(f"Aggregated by {grain}." + (" The first and last periods may be incomplete, which can make the ends look lower." if grain != "day" else ""))
    elif xk in ("numeric",):
        d["_x"] = d[x]
    else:
        d["_x"] = d[x].astype(str)
    gcols = ["_x"] + ([color] if color else [])
    if color:
        keep, more = _color_groups(d, color, 8)
        d = d[d[color].astype(str).isin(keep)]
        d[color] = d[color].astype(str)
    res = _agg_series(d.groupby(gcols), y, agg).dropna()
    if res.empty:
        return None
    lab = _label(agg, y)

    def xs(idx):
        return [v.isoformat() if isinstance(v, pd.Timestamp) else jv(v) for v in idx]

    if color:
        data = []
        for g, sub in res.groupby(level=1):
            sub = sub.droplevel(1).sort_index()
            data.append({"type": "scatter", "mode": "lines+markers", "name": str(g), "x": xs(sub.index), "y": jl(sub.values)})
    else:
        res = res.sort_index()
        data = [{"type": "scatter", "mode": "lines+markers", "name": lab, "x": xs(res.index), "y": jl(res.values)}]
    return fig(data, f"{lab} over {x}" if xk == "datetime" else f"{lab} by {x}", x, lab)


def _scatter(df, kinds, c, notes):
    x, y, color = c["x"], c["y"], c["color"]
    if not x or not y:
        raise AnalyticsError("Scatter plots need both X and Y numeric columns.")
    for col in (x, y):
        if kinds[col] not in ("numeric",):
            raise AnalyticsError(f"Scatter axis '{col}' must be numeric (it is {kinds[col]}).")
    cols = [x, y] + ([color] if color else [])
    d = df[cols].dropna()
    if d.empty:
        return None
    if len(d) > POINTS_CAP:
        d = d.sample(POINTS_CAP, random_state=42)
        notes.append(f"Showing a random sample of {POINTS_CAP:,} points.")
    data = []
    if color and kinds[color] == "numeric":
        data.append({"type": "scatter", "mode": "markers", "x": jl(d[x]), "y": jl(d[y]), "name": color,
                     "marker": {"color": jl(d[color]), "colorscale": "Viridis", "showscale": True,
                                "colorbar": {"title": {"text": color}}, "size": 8}})
    elif color:
        keep, more = _color_groups(d, color)
        for g in keep:
            sub = d[d[color].astype(str) == g]
            data.append({"type": "scatter", "mode": "markers", "name": g, "x": jl(sub[x]), "y": jl(sub[y]), "marker": {"size": 8}})
    else:
        data.append({"type": "scatter", "mode": "markers", "name": f"{y} vs {x}", "x": jl(d[x]), "y": jl(d[y]), "marker": {"size": 8}})
    if len(d) >= 3 and d[x].nunique() > 1 and d[y].nunique() > 1:
        r = float(np.corrcoef(d[x].astype(float), d[y].astype(float))[0, 1])
        notes.append(f"Pearson r = {r:.3f} (n = {len(d):,}).")
    return fig(data, f"{y} vs {x}", x, y, legend=bool(color))


def _pie(df, kinds, c, notes):
    x, y, agg = c["x"], c["y"], c["agg"]
    if not x:
        raise AnalyticsError("Select a category column for pie / donut charts.")
    d = df[df[x].notna()].copy()
    d[x] = d[x].astype(str)
    if y is None:
        agg = "count"
    if y and agg in ("mean", "median", "min", "max"):
        notes.append("Slices show a non-additive aggregate, so shares are not parts of a whole.")
    res = _agg_series(d.groupby(x), y, agg).dropna()
    res = res[res > 0] if (res >= 0).all() else res.abs()
    res = res.sort_values(ascending=False)
    if res.empty:
        return None
    n = min(c["top_n"], 8)
    if len(res) > n:
        top, rest = res.iloc[:n], res.iloc[n:]
        if agg in ("count", "sum", "nunique"):
            top = pd.concat([top, pd.Series({"Other": rest.sum()})])
            notes.append(f"{len(rest)} smaller categories combined into 'Other'.")
        else:
            notes.append(f"Showing the top {n} of {len(res)} categories.")
        res = top
    lab = _label(agg, y)
    data = [{"type": "pie", "labels": jl(res.index), "values": jl(res.values), "hole": 0.5 if c["chart_type"] == "donut" else 0,
             "textinfo": "label+percent", "sort": False}]
    return fig(data, f"{lab} by {x}", legend=True)


def _hist(df, kinds, c, notes):
    x, color = c["x"] or c["y"], c["color"]
    if not x:
        raise AnalyticsError("Select a numeric column for the histogram.")
    if kinds[x] != "numeric":
        raise AnalyticsError(f"Histogram column '{x}' must be numeric (it is {kinds[x]}).")
    s = df[x].dropna().astype(float)
    if s.empty:
        return None
    nb = min(c["bins"], max(2, int(s.nunique())))
    edges = np.histogram_bin_edges(s, bins=nb)
    centers = (edges[:-1] + edges[1:]) / 2
    width = float(edges[1] - edges[0]) if len(edges) > 1 else 1.0

    def trace(vals, name):
        counts, _ = np.histogram(vals, bins=edges)
        return {"type": "bar", "name": name, "x": jl(centers), "y": jl(counts), "width": width * 0.95,
                "customdata": [f"{a:.4g} – {b:.4g}" for a, b in zip(edges[:-1], edges[1:])],
                "hovertemplate": "Range %{customdata}<br>Count %{y}<extra>" + name + "</extra>"}

    if color and kinds[color] != "numeric":
        d = df[[x, color]].dropna()
        keep, _more = _color_groups(d, color, 6)
        data = [trace(d[d[color].astype(str) == g][x].astype(float), g) for g in keep]
        lay = {"barmode": "overlay"}
        for t in data:
            t["opacity"] = 0.65
    else:
        data, lay = [trace(s, x)], {}
    skew = float(sps.skew(s)) if len(s) > 2 and s.nunique() > 1 else None
    notes.append(f"n = {len(s):,}, mean = {s.mean():.4g}, median = {s.median():.4g}" + (f", skew = {skew:.2f}." if skew is not None else "."))
    return fig(data, f"Distribution of {x}", x, "Count", **lay)


def _box_stats(vals: pd.Series):
    q1, med, q3 = vals.quantile([.25, .5, .75])
    iqr = q3 - q1
    lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    inside = vals[(vals >= lo_f) & (vals <= hi_f)]
    out = vals[(vals < lo_f) | (vals > hi_f)]
    return dict(q1=q1, med=med, q3=q3, lo=float(inside.min()), hi=float(inside.max()), mean=float(vals.mean()), out=out)


def _box(df, kinds, c, notes):
    y = c["y"] or c["x"]
    grp = c["color"] or (c["x"] if c["x"] and c["x"] != y else None)
    if not y:
        raise AnalyticsError("Select a numeric column for the box plot.")
    if kinds[y] != "numeric":
        raise AnalyticsError(f"Box plot value '{y}' must be numeric (it is {kinds[y]}).")
    d = df[[y] + ([grp] if grp else [])].dropna()
    if d.empty:
        return None
    if grp and kinds[grp] == "numeric":
        d[grp] = _bin_numeric(d[grp], 6)
    names, rows = [], []
    if grp:
        d[grp] = d[grp].astype(str)
        keep = list(d[grp].value_counts().index[:12])
        for g in keep:
            names.append(g)
            rows.append(_box_stats(d[d[grp] == g][y].astype(float)))
        if d[grp].nunique() > 12:
            notes.append("Showing the 12 largest groups.")
    else:
        names, rows = [y], [_box_stats(d[y].astype(float))]
    box = {"type": "box", "name": y, "x": names, "q1": jl([r["q1"] for r in rows]), "median": jl([r["med"] for r in rows]),
           "q3": jl([r["q3"] for r in rows]), "lowerfence": jl([r["lo"] for r in rows]), "upperfence": jl([r["hi"] for r in rows]),
           "mean": jl([r["mean"] for r in rows]), "boxmean": True}
    data = [box]
    ox, oy = [], []
    for nme, r in zip(names, rows):
        for v in r["out"].head(100):
            ox.append(nme)
            oy.append(float(v))
    n_out = sum(len(r["out"]) for r in rows)
    if ox:
        data.append({"type": "scatter", "mode": "markers", "name": "Outliers (IQR)", "x": ox, "y": oy,
                     "marker": {"size": 7, "symbol": "circle-open"}})
    notes.append(f"{n_out:,} outlier(s) beyond 1.5×IQR." if n_out else "No outliers beyond 1.5×IQR.")
    return fig(data, f"{y}" + (f" by {grp}" if grp else ""), grp or "", y, legend=bool(ox))


def _heat(df, kinds, c, notes):
    x, y, value, agg = c["x"], c["y"], c["value"], c["agg"]
    if not x and not y:  # correlation heatmap
        num = [k for k in cols_of(kinds, "numeric") if k in df.columns and df[k].nunique() > 1][:25]
        if len(num) < 2:
            raise AnalyticsError("A correlation heatmap needs at least two numeric columns with variation.")
        corr = df[num].corr(numeric_only=True)
        z = [[jv(v) for v in row] for row in corr.values]
        text = [[("" if v is None else f"{v:.2f}") for v in row] for row in z]
        data = [{"type": "heatmap", "x": num, "y": num, "z": z, "text": text, "texttemplate": "%{text}", "zmin": -1, "zmax": 1,
                 "colorscale": "RdBu", "reversescale": True, "hovertemplate": "%{x} × %{y}<br>r = %{z:.3f}<extra></extra>"}]
        notes.append("Pearson correlation on pairwise-complete rows.")
        return fig(data, "Correlation heatmap")
    if not x or not y:
        raise AnalyticsError("Heatmaps need both X and Y (or neither, for a correlation heatmap).")
    d = df.copy()
    for col in (x, y):
        if kinds[col] == "numeric" and d[col].nunique() > 12:
            d[col] = _bin_numeric(d[col], 10)
        elif kinds[col] == "datetime":
            d[col] = _to_period(d[col], c["grain"] or _auto_grain(d[col])).dt.strftime("%Y-%m")
        d[col] = d[col].astype(str).where(d[col].notna())
    d = d.dropna(subset=[x, y])
    if d.empty:
        return None
    for col in (x, y):
        keep = d[col].value_counts().index[:25]
        d = d[d[col].isin(keep)]
    if value and kinds.get(value) == "numeric" and agg != "count":
        res = getattr(d.groupby([y, x])[value], agg if agg != "nunique" else "nunique")()
        lab = _label(agg, value)
    else:
        res = d.groupby([y, x]).size()
        lab = "Count"
    piv = res.unstack(x)
    xs, ys = sorted(piv.columns, key=str), sorted(piv.index, key=str)
    piv = piv.reindex(index=ys, columns=xs)
    data = [{"type": "heatmap", "x": jl(xs), "y": jl(ys), "z": [[jv(v) for v in row] for row in piv.values], "colorscale": "Blues",
             "colorbar": {"title": {"text": lab}}, "hovertemplate": "%{x} × %{y}<br>" + lab + " = %{z}<extra></extra>"}]
    return fig(data, f"{lab}: {y} × {x}", x, y)


# --------------------------------------------------------------------------- recommendations
def _score_group_numeric(df, kinds):
    """Pick the (categorical, numeric) pair whose group means differ the most (eta-squared)."""
    best = None
    for g in group_cols(kinds):
        if df[g].nunique() < 2 or df[g].nunique() > 12:
            continue
        for n in cols_of(kinds, "numeric"):
            d = df[[g, n]].dropna()
            if len(d) < 4 or d[n].var() in (0, np.nan):
                continue
            total = ((d[n] - d[n].mean()) ** 2).sum()
            if total == 0:
                continue
            between = sum(len(s) * (s.mean() - d[n].mean()) ** 2 for _, s in d.groupby(g)[n])
            eta = between / total
            if best is None or eta > best[0]:
                best = (eta, g, n)
    return best


def correlated_pairs(df, kinds, min_abs=0.0):
    num = [c for c in cols_of(kinds, "numeric") if df[c].nunique() > 1]
    pairs = []
    if len(num) < 2:
        return pairs
    corr = df[num].corr(numeric_only=True)
    for i, a in enumerate(num):
        for b in num[i + 1:]:
            r = corr.loc[a, b]
            if pd.notna(r) and abs(r) >= min_abs:
                pairs.append((a, b, float(r)))
    return sorted(pairs, key=lambda t: -abs(t[2]))


def recommend(df: pd.DataFrame, kinds: Dict[str, str]) -> List[Dict[str, Any]]:
    """Choose a small set of meaningful charts from column types and cardinality."""
    out: List[Dict[str, Any]] = []
    n = len(df)

    def add(section, title, why, cfg):
        res = build_chart(df, kinds, cfg)
        if not res.get("empty"):
            out.append({"id": f"{section}-{len(out)}", "section": section, "title": title, "why": why,
                        "config": res["config"], "figure": res["figure"], "notes": res["notes"]})

    nums = [c for c in cols_of(kinds, "numeric")]
    nums = sorted(nums, key=lambda c: -df[c].nunique())[:6]
    cats = [c for c in cols_of(kinds, "categorical") if df[c].nunique() >= 2]
    bools = cols_of(kinds, "boolean")
    dts = cols_of(kinds, "datetime")

    # Numerical
    for c in nums[:4]:
        add("numerical", f"Distribution of {c}", "Shows the shape, spread and skew of this numeric column.",
            {"chart_type": "histogram", "x": c, "bins": 15})
    best = _score_group_numeric(df, kinds)
    if best and best[0] >= 0.05:
        _, g, nm = best
        add("numerical", f"{nm} by {g}", "This grouping explains the most variation in the numeric column.",
            {"chart_type": "box", "y": nm, "x": g})
    elif nums:
        add("numerical", f"Spread and outliers: {nums[0]}", "Box plot highlights the quartiles and IQR outliers.",
            {"chart_type": "box", "y": nums[0]})

    # Categorical
    donut_done = False
    for c in (cats + bools)[:4]:
        nu = df[c].nunique()
        if nu <= 6 and not donut_done:
            add("categorical", f"Share of {c}", "Few categories - a donut shows each share of the total.",
                {"chart_type": "donut", "x": c}); donut_done = True
        else:
            add("categorical", f"Frequency of {c}", "Ranks categories by number of rows.",
                {"chart_type": "bar", "x": c, "top_n": 15})
    if best and best[0] >= 0.05 and nums:
        _, g, nm = best
        add("categorical", f"Average {nm} by {g}", "Compares the category averages with the largest differences.",
            {"chart_type": "bar", "x": g, "y": nm, "agg": "mean"})

    # Relationships
    if len(nums) >= 3:
        add("relationships", "Correlation heatmap", "Pearson correlation between numeric columns.",
            {"chart_type": "heatmap"})
    pairs = [p for p in correlated_pairs(df, kinds) if abs(p[2]) >= 0.3][:2]
    if not pairs and len(nums) == 2 and n >= 5:
        pairs = correlated_pairs(df, kinds)[:1]
    colour = next((c for c in cats if 2 <= df[c].nunique() <= 6), None)
    for a, b, r in pairs:
        add("relationships", f"{b} vs {a}", f"Correlation r = {r:.2f}.",
            {"chart_type": "scatter", "x": a, "y": b, "color": colour})

    # Time series
    for dcol in dts[:1]:
        add("timeseries", f"Records over {dcol}", "Row counts per period.",
            {"chart_type": "line", "x": dcol})
        for nm in nums[:2]:
            agg = "sum" if SUM_HINT.search(nm) else "mean"
            add("timeseries", f"{agg.capitalize()} of {nm} over {dcol}", "Trend of this measure across time.",
                {"chart_type": "line", "x": dcol, "y": nm, "agg": agg})

    # Data quality
    miss = df.isna().sum()
    miss = miss[miss > 0].sort_values(ascending=False)
    if len(miss):
        out.append({"id": f"quality-{len(out)}", "section": "quality", "title": "Missing values by column",
                    "why": "Columns with blank cells.", "config": None, "notes": [],
                    "figure": fig([{"type": "bar", "x": jl(miss.index), "y": jl(miss.values),
                                    "customdata": jl((miss / n * 100).round(2)),
                                    "hovertemplate": "%{x}<br>%{y} missing (%{customdata}%)<extra></extra>"}],
                                  "Missing values by column", "Column", "Missing cells")})
    try:
        dup = int(df.duplicated().sum())
    except TypeError:
        dup = int(df.astype(str).duplicated().sum())
    if dup:
        out.append({"id": f"quality-{len(out)}", "section": "quality", "title": "Duplicate rows",
                    "why": "Fully identical rows.", "config": None, "notes": [],
                    "figure": fig([{"type": "pie", "labels": ["Unique rows", "Duplicate rows"], "values": [n - dup, dup],
                                    "hole": 0.55, "textinfo": "label+percent"}], "Duplicate analysis", legend=True)})
    kc = pd.Series(kinds).value_counts()
    out.append({"id": f"quality-{len(out)}", "section": "quality", "title": "Column data types",
                "why": "How the columns were interpreted.", "config": None, "notes": [],
                "figure": fig([{"type": "pie", "labels": jl(kc.index), "values": jl(kc.values), "hole": 0.55,
                                "textinfo": "label+value"}], "Column data-type distribution", legend=True)})
    return out


# --------------------------------------------------------------------------- outliers
def outliers(df: pd.DataFrame, kinds: Dict[str, str], limit_rows=10) -> Dict[str, Any]:
    res = []
    for c in cols_of(kinds, "numeric"):
        s = df[c].dropna()
        if len(s) < 4 or s.nunique() < 3:
            continue
        q1, q3 = s.quantile([.25, .75])
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        bad = df[(df[c] < lo) | (df[c] > hi)]
        if len(bad):
            res.append({"column": c, "count": int(len(bad)), "pct": rnd(len(bad) / len(s) * 100, 2),
                        "lower_bound": rnd(lo), "upper_bound": rnd(hi),
                        "examples": [{k: jv(v) for k, v in r.items()} for r in bad.head(limit_rows).to_dict("records")]})
    return {"columns": sorted(res, key=lambda r: -r["count"])}


# --------------------------------------------------------------------------- insights
def insights(df: pd.DataFrame, kinds: Dict[str, str]) -> List[Dict[str, str]]:
    out = []
    n = len(df)
    if n == 0:
        return [{"level": "warning", "title": "No rows", "text": "No rows match the current filters."}]
    k = kpis(df, kinds)
    if k["missing_values"]:
        worst = df.isna().sum().sort_values(ascending=False)
        worst = worst[worst > 0]
        out.append({"level": "warning", "title": "Missing values",
                    "text": f"{k['missing_values']:,} cells ({k['missing_pct']}%) are empty. Most affected: " +
                            ", ".join(f"{c} ({int(v)})" for c, v in worst.head(3).items()) + "."})
    else:
        out.append({"level": "good", "title": "Complete data", "text": "No missing values were found."})
    if k["duplicate_rows"]:
        out.append({"level": "warning", "title": "Duplicate rows",
                    "text": f"{k['duplicate_rows']:,} fully duplicated row(s) ({k['duplicate_rows'] / n * 100:.1f}% of rows)."})
    for p in correlated_pairs(df, kinds, 0.5)[:2]:
        a, b, r = p
        d = df[[a, b]].dropna()
        txt = f"{a} and {b} have a {'positive' if r > 0 else 'negative'} correlation (r = {r:.2f}, n = {len(d)})."
        if len(d) >= 8:
            pv = sps.pearsonr(d[a], d[b])[1]
            txt += f" p = {pv:.3g}."
        else:
            txt += " The sample is small, so treat this as indicative only."
        out.append({"level": "info", "title": "Strong relationship", "text": txt})
    best = _score_group_numeric(df, kinds)
    if best and best[0] >= 0.1:
        _, g, nm = best
        m = df.groupby(g)[nm].mean().sort_values(ascending=False)
        out.append({"level": "info", "title": f"{nm} differs by {g}",
                    "text": f"Average {nm} is highest for '{m.index[0]}' ({m.iloc[0]:,.2f}) and lowest for '{m.index[-1]}' ({m.iloc[-1]:,.2f}); "
                            f"{g} explains {best[0] * 100:.0f}% of the variation."})
    for c in cols_of(kinds, "categorical")[:6]:
        vc = df[c].value_counts(normalize=True)
        if len(vc) > 2 and vc.iloc[0] >= 0.5:
            out.append({"level": "info", "title": f"Dominant {c}", "text": f"'{vc.index[0]}' makes up {vc.iloc[0] * 100:.0f}% of rows."})
            break
    for c in cols_of(kinds, "numeric")[:8]:
        s = df[c].dropna()
        if len(s) > 10 and s.nunique() > 3:
            sk = float(sps.skew(s))
            if abs(sk) > 1:
                out.append({"level": "info", "title": f"Skewed {c}", "text": f"{c} is {'right' if sk > 0 else 'left'}-skewed (skew = {sk:.2f}); the median ({s.median():,.2f}) differs from the mean ({s.mean():,.2f})."})
                break
    o = outliers(df, kinds, 0)["columns"]
    if o:
        out.append({"level": "warning", "title": "Unusual values",
                    "text": "IQR outliers: " + ", ".join(f"{r['column']} ({r['count']})" for r in o[:4]) + "."})
    for dcol in cols_of(kinds, "datetime")[:1]:
        nums = cols_of(kinds, "numeric")
        if nums:
            nm = nums[0]
            grain = _auto_grain(df[dcol])
            agg = "sum" if SUM_HINT.search(nm) else "mean"
            ser = getattr(df.assign(_p=_to_period(df[dcol], grain)).dropna(subset=["_p"]).groupby("_p")[nm], agg)()
            # First/last periods are usually partial; compare complete periods for additive measures.
            if len(ser) >= 5 and agg == "sum":
                ser = ser.iloc[1:-1]
            if len(ser) >= 3 and ser.iloc[0]:
                ch = (ser.iloc[-1] - ser.iloc[0]) / abs(ser.iloc[0]) * 100
                out.append({"level": "info", "title": f"Trend in {nm}",
                            "text": f"{agg.capitalize()} of {nm} moved {ch:+.1f}% from the first to the last {grain} "
                                    f"({len(ser)} periods compared{', partial edge periods excluded' if agg == 'sum' else ''})."})
    return out[:10]
