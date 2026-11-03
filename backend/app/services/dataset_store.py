"""Dataset store: resolves dataset_id -> DataFrame with caching.

Uploaded files are saved by api/upload.py as <uuid>.<ext>. This module is the single
place that reads them back, so every analytics endpoint shares one cached copy.
"""
import re
import threading
from collections import OrderedDict
from pathlib import Path

import pandas as pd

from api.upload import UPLOAD_DIR

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EXTS = (".csv", ".xlsx", ".xls")
MAX_CACHED = 8
SAMPLE_ROWS = 20000  # row cap for chart payloads (stats always use the full data)

_lock = threading.Lock()
_cache: "OrderedDict[str, dict]" = OrderedDict()


class DatasetNotFound(Exception):
    pass


def _find_file(dataset_id: str) -> Path:
    # Strict UUID check blocks path traversal such as "../../etc/passwd".
    if not _UUID_RE.match(dataset_id or ""):
        raise DatasetNotFound("Invalid dataset id.")
    for ext in _EXTS:
        p = UPLOAD_DIR / f"{dataset_id}{ext}"
        if p.is_file():
            return p
    raise DatasetNotFound("Dataset not found. It may have been deleted - please upload it again.")


def _read(path: Path) -> pd.DataFrame:
    if path.suffix == ".csv":
        try:
            df = pd.read_csv(path)
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="latin-1")
    else:
        df = pd.read_excel(path)
    df.columns = [str(c).strip() for c in df.columns]
    # Make duplicate column names unique so column selection is unambiguous.
    seen, cols = {}, []
    for c in df.columns:
        if c in seen:
            seen[c] += 1
            cols.append(f"{c}.{seen[c]}")
        else:
            seen[c] = 0
            cols.append(c)
    df.columns = cols
    return _coerce_dates(df)


def _coerce_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Convert text columns that are overwhelmingly parseable dates into datetime."""
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            continue
        if not (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
            continue
        nn = s.dropna()
        if nn.empty:
            continue
        probe = nn.astype(str).head(200)
        # Cheap pre-filter: dates contain a separator and a digit.
        if not probe.str.contains(r"\d").all() or not probe.str.contains(r"[-/.:]|\s").any():
            continue
        parsed = pd.to_datetime(probe, errors="coerce", format="mixed")
        if parsed.notna().mean() >= 0.9:
            full = pd.to_datetime(s, errors="coerce", format="mixed")
            if full.notna().sum() >= 0.9 * len(nn):
                df[c] = full
    return df


def get_dataframe(dataset_id: str) -> pd.DataFrame:
    """Return the cached DataFrame (do not mutate it; copy first)."""
    path = _find_file(dataset_id)
    mtime = path.stat().st_mtime
    with _lock:
        hit = _cache.get(dataset_id)
        if hit and hit["mtime"] == mtime:
            _cache.move_to_end(dataset_id)
            return hit["df"]
    df = _read(path)
    with _lock:
        _cache[dataset_id] = {"df": df, "mtime": mtime, "memo": {}}
        _cache.move_to_end(dataset_id)
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return df


def memo(dataset_id: str, key: str, builder):
    """Cache an expensive analysis result per dataset (invalidated with the file)."""
    get_dataframe(dataset_id)
    with _lock:
        entry = _cache[dataset_id]
        if key in entry["memo"]:
            return entry["memo"][key]
    value = builder()
    with _lock:
        if dataset_id in _cache:
            _cache[dataset_id]["memo"][key] = value
    return value


def sample(df: pd.DataFrame, n: int = SAMPLE_ROWS) -> pd.DataFrame:
    return df if len(df) <= n else df.sample(n=n, random_state=42).sort_index()


def list_datasets() -> list:
    """Recent uploads, newest first (original filenames aren't stored, so id + type + size)."""
    items = []
    for p in UPLOAD_DIR.iterdir():
        if p.suffix.lower() in _EXTS and _UUID_RE.match(p.stem):
            st = p.stat()
            items.append({"dataset_id": p.stem, "file_type": p.suffix.lstrip("."),
                          "file_size": st.st_size, "uploaded_at": st.st_mtime})
    return sorted(items, key=lambda x: x["uploaded_at"], reverse=True)
