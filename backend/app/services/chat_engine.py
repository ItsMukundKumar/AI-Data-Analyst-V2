"""Chat engine: question -> intent + columns -> pandas computation -> text + chart configs.

No numbers are ever produced by a language model. A question is mapped to a fixed set of
analyses (the same validated `build_chart` used by the dashboard). If the question can't be
mapped, the engine says so and lists what it can do instead of guessing.
"""
import re
from typing import Any, Dict, List

import pandas as pd

from services import analytics as A


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def mentioned_columns(question: str, df: pd.DataFrame) -> List[str]:
    q = question.lower()
    qn = _norm(q)
    qtokens = {_stem(t) for t in re.findall(r"[a-z0-9]+", q)}
    hits = []
    for c in df.columns:
        cn = _norm(c)
        if not cn:
            continue
        ctoks = [_stem(t) for t in re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", c).lower())]
        pos = q.find(c.lower())
        if pos >= 0:
            hits.append((pos, -len(cn), c))
        elif len(cn) >= 3 and cn in qn:
            hits.append((qn.find(cn), -len(cn), c))
        elif ctoks and all(t in qtokens for t in ctoks):
            hits.append((min(q.find(t) for t in ctoks if t in q) if any(t in q for t in ctoks) else 999, -len(cn), c))
    hits.sort()
    seen, out = set(), []
    for _, _, c in hits:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _agg_word(q: str, default: str) -> str:
    for words, agg in ((("average", "mean", "avg"), "mean"), (("median",), "median"), (("total", "sum", "combined"), "sum"),
                       (("maximum", "max"), "max"), (("minimum", "min"), "min")):
        if any(re.search(rf"\b{w}\b", q) for w in words):
            return agg
    return default


def _chart(df, kinds, cfg, title=None):
    res = A.build_chart(df, kinds, cfg)
    if res.get("empty"):
        return None
    return {"title": title or res["figure"]["layout"]["title"]["text"], "figure": res["figure"],
            "config": res["config"], "notes": res["notes"]}


def _table(df: pd.DataFrame, cols=None, limit=10):
    d = df[cols] if cols else df
    return {"columns": list(d.columns), "rows": [[A.jv(v) for v in r] for r in d.head(limit).values.tolist()]}


def answer(df: pd.DataFrame, kinds: Dict[str, str], question: str) -> Dict[str, Any]:
    q = question.strip().lower()
    if not q:
        raise A.AnalyticsError("Please type a question.")
    cols = mentioned_columns(q, df)
    nums = [c for c in cols if kinds[c] == "numeric"]
    cats = [c for c in cols if kinds[c] in ("categorical", "boolean")]
    dts = [c for c in cols if kinds[c] == "datetime"]
    n = len(df)
    res: Dict[str, Any] = {"answer": "", "charts": [], "table": None, "columns_used": cols}
    has = lambda *w: any(re.search(w_, q) for w_ in w)

    # ---- outliers
    if has(r"outlier", r"unusual", r"anomal", r"abnormal", r"extreme"):
        o = A.outliers(df, kinds)["columns"]
        if nums:
            o = [r for r in o if r["column"] in nums] or o
        if not o:
            res["answer"] = "I checked every numeric column with the 1.5×IQR rule and found no unusual values."
            return res
        lines = [f"• {r['column']}: {r['count']} outlier(s) ({r['pct']}%), outside {r['lower_bound']} – {r['upper_bound']}" for r in o[:6]]
        res["answer"] = "Using the 1.5×IQR rule, I found unusual values in:\n" + "\n".join(lines)
        top = o[0]
        res["table"] = {"title": f"Rows with unusual {top['column']}", "columns": list(top["examples"][0].keys()),
                        "rows": [list(e.values()) for e in top["examples"]]}
        ch = _chart(df, kinds, {"chart_type": "box", "y": top["column"]}, f"Outliers in {top['column']}")
        if ch:
            res["charts"].append(ch)
        return res

    # ---- correlation
    if has(r"correlat", r"relationship", r"related", r"associat"):
        pairs = A.correlated_pairs(df, kinds)
        if nums and len(nums) >= 2:
            pairs = [p for p in pairs if p[0] in nums and p[1] in nums] or pairs
        if not pairs:
            res["answer"] = "I need at least two numeric columns with variation to compute correlations; this dataset doesn't have them."
            return res
        top = pairs[:3]
        res["answer"] = "Strongest Pearson correlations:\n" + "\n".join(f"• {a} ↔ {b}: r = {r:.3f}" for a, b, r in top)
        if n < 10:
            res["answer"] += f"\n(Only {n} rows, so treat these as indicative.)"
        nn = A.cols_of(kinds, "numeric")
        if len(nn) >= 3:
            ch = _chart(df, kinds, {"chart_type": "heatmap"}, "Correlation heatmap")
            if ch:
                res["charts"].append(ch)
        a, b, _ = top[0]
        ch = _chart(df, kinds, {"chart_type": "scatter", "x": a, "y": b}, f"{b} vs {a}")
        if ch:
            res["charts"].append(ch)
        return res

    # ---- data quality
    if has(r"missing", r"null", r"blank", r"duplicate", r"data quality", r"quality"):
        k = A.kpis(df, kinds)
        miss = df.isna().sum()
        miss = miss[miss > 0].sort_values(ascending=False)
        txt = f"{k['missing_values']:,} missing cells ({k['missing_pct']}%) and {k['duplicate_rows']:,} duplicate row(s) across {n:,} rows."
        if len(miss):
            txt += "\nColumns with missing values: " + ", ".join(f"{c} ({int(v)})" for c, v in miss.items())
            res["charts"].append({"title": "Missing values by column", "config": None, "notes": [], "figure": A.fig(
                [{"type": "bar", "x": A.jl(miss.index), "y": A.jl(miss.values)}], "Missing values by column", "Column", "Missing cells")})
        res["answer"] = txt
        return res

    # ---- trend / time
    if has(r"trend", r"over time", r"monthly", r"yearly", r"daily", r"weekly", r"quarterly", r"by month", r"by year", r"per month", r"per year", r"timeline"):
        all_dts = A.cols_of(kinds, "datetime")
        dcol = (dts or all_dts or [None])[0]
        if not dcol:
            res["answer"] = "This dataset has no date/time column, so I can't compute a time trend. Date-like text columns are detected automatically; none were found."
            return res
        grain = next((g for w, g in (("daily", "day"), ("weekly", "week"), ("monthly", "month"), ("month", "month"), ("quarter", "quarter"),
                                     ("yearly", "year"), ("year", "year"), ("day", "day")) if w in q), None)
        measure = nums[0] if nums else None
        agg = _agg_word(q, "sum" if measure and A.SUM_HINT.search(measure) else "mean") if measure else "count"
        cfg = {"chart_type": "line", "x": dcol, "y": measure, "agg": agg, "time_grain": grain}
        ch = _chart(df, kinds, cfg)
        if not ch:
            res["answer"] = "There isn't enough dated data to draw a trend."
            return res
        s = ch["figure"]["data"][0]
        ys = [v for v in s["y"] if v is not None]
        what = f"{agg} of {measure}" if measure else "number of records"
        txt = f"Here is the {what} over {dcol}" + (f" ({grain})" if grain else "") + f" across {len(ys)} period(s)."
        if len(ys) >= 2:
            hi, lo = max(range(len(s["y"])), key=lambda i: s["y"][i] or -1e300), min(range(len(s["y"])), key=lambda i: s["y"][i] if s["y"][i] is not None else 1e300)
            txt += f"\nHighest: {s['y'][hi]:,.2f} at {s['x'][hi][:10]}. Lowest: {s['y'][lo]:,.2f} at {s['x'][lo][:10]}."
        if not measure:
            txt += "\nNo numeric column was named, so I counted rows."
        res["answer"], res["charts"] = txt, [ch]
        return res

    # ---- distribution
    if has(r"distribution", r"histogram", r"spread", r"how are .* distributed", r"range of"):
        target = (nums or [])[:1] or A.cols_of(kinds, "numeric")[:1]
        if cats and not nums:
            c = cats[0]
            ch = _chart(df, kinds, {"chart_type": "bar", "x": c}, f"Frequency of {c}")
            vc = df[c].value_counts()
            res["answer"] = f"{c} has {len(vc)} distinct values. Most common: " + ", ".join(f"{k} ({v})" for k, v in vc.head(3).items()) + "."
            res["charts"] = [ch] if ch else []
            return res
        if not target:
            res["answer"] = "There is no numeric column to show a distribution for."
            return res
        c = target[0]
        s = df[c].dropna()
        ch = _chart(df, kinds, {"chart_type": "histogram", "x": c, "bins": 15}, f"Distribution of {c}")
        res["answer"] = (f"{c}: n = {len(s):,}, mean {s.mean():,.2f}, median {s.median():,.2f}, std {s.std():,.2f}, "
                         f"min {s.min():,.2f}, max {s.max():,.2f}." + ("" if nums else f"\nNo column was named, so I used the first numeric column ({c})."))
        res["charts"] = [ch] if ch else []
        return res

    # ---- ranking: highest / lowest / top by category
    if has(r"highest", r"lowest", r"top\b", r"best", r"worst", r"most", r"least", r"largest", r"smallest", r"maximum", r"minimum", r" by ", r" per ", r"compare", r"breakdown"):
        group = (cats or [None])[0]
        if group is None:
            cand = [c for c in A.group_cols(kinds) if c not in nums]
            group = cand[0] if len(cand) == 1 else (cand[0] if cand else None)
            if group is None:
                res["answer"] = "I couldn't find a category column to group by. Try naming one, e.g. 'average salary by department'."
                return res
            guessed = True
        else:
            guessed = False
        measure = nums[0] if nums else None
        agg = _agg_word(q, "sum" if measure and A.SUM_HINT.search(measure) else "mean") if measure else "count"
        cfg = {"chart_type": "bar", "x": group, "y": measure, "agg": agg, "top_n": 15}
        ch = _chart(df, kinds, cfg)
        if not ch:
            res["answer"] = "Not enough data for that comparison."
            return res
        d = df.dropna(subset=[group]).groupby(group)
        ser = (d.size() if not measure else getattr(d[measure], agg if agg != "count" else "count")()).dropna().sort_values(ascending=False)
        lab = A._label(agg, measure)
        want_low = has(r"lowest", r"worst", r"least", r"smallest", r"minimum")
        pick = ser.index[-1] if want_low else ser.index[0]
        val = ser.iloc[-1] if want_low else ser.iloc[0]
        txt = f"{'Lowest' if want_low else 'Highest'} {lab.lower()} by {group}: {pick} ({val:,.2f})."
        txt += "\n" + "\n".join(f"• {k}: {v:,.2f}" for k, v in ser.head(5).items())
        if not measure:
            txt += "\nNo numeric column was named, so I counted rows per category."
        if guessed:
            txt += f"\nI grouped by '{group}' because no category column was named."
        res["answer"], res["charts"] = txt, [ch]
        res["table"] = {"title": lab + " by " + group, "columns": [group, lab], "rows": [[A.jv(k), A.rnd(v, 2)] for k, v in ser.head(10).items()]}
        return res

    # ---- insights
    if has(r"insight", r"key finding", r"interesting", r"tell me about"):
        ins = A.insights(df, kinds)
        res["answer"] = "\n".join(f"• {i['title']}: {i['text']}" for i in ins)
        return res

    # ---- overview
    if has(r"overview", r"summar", r"describe", r"about (this|the) (data|dataset)", r"what('s| is) in"):
        k = A.kpis(df, kinds)
        res["answer"] = (f"The dataset has {k['rows']:,} rows and {k['columns']} columns: {k['numeric_columns']} numeric, "
                         f"{k['categorical_columns']} categorical/text, {k['datetime_columns']} date. "
                         f"{k['missing_values']:,} missing cells and {k['duplicate_rows']:,} duplicate rows.\nColumns: " +
                         ", ".join(f"{c} ({kinds[c]})" for c in df.columns))
        return res

    # ---- visualisation suggestions
    if has(r"visuali[sz]", r"chart", r"plot", r"graph"):
        recs = A.recommend(df, kinds)[:6]
        res["answer"] = "Suggested visualizations for this data:\n" + "\n".join(f"• {r['title']} - {r['why']}" for r in recs)
        res["charts"] = [{"title": r["title"], "figure": r["figure"], "config": r["config"], "notes": r["notes"]} for r in recs[:2]]
        return res

    # ---- single column fallback
    if len(cols) == 1:
        c = cols[0]
        if kinds[c] == "numeric":
            return answer(df, kinds, f"distribution of {c}")
        if kinds[c] in ("categorical", "boolean"):
            return answer(df, kinds, f"distribution of {c}")

    res["answer"] = ("I couldn't map that question to an analysis I can compute reliably, so I won't guess. I can: show trends over time, "
                     "rank categories (highest/lowest), show distributions, find correlations, flag outliers, and report missing values/duplicates. "
                     "Try mentioning column names, e.g. 'average " + (A.cols_of(kinds, "numeric") or ["value"])[0] + " by " +
                     (A.group_cols(kinds) or ["category"])[0] + "'.")
    return res
