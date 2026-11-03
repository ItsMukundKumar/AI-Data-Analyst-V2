
import uuid
from io import BytesIO
from pathlib import Path

import pandas as pd
import os
from fastapi import APIRouter, File, HTTPException, UploadFile


# ============================================================
# CONFIGURATION
# ============================================================

router = APIRouter(tags=["Dataset Upload"])

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

DEFAULT_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"

UPLOAD_DIR = Path(
    os.getenv("UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR))
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# UPLOAD ENDPOINT
# ============================================================

@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):

    # --------------------------------------------------------
    # 1. Validate filename and extension
    # --------------------------------------------------------

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Filename is missing."
        )

    extension = Path(file.filename).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only CSV, XLSX and XLS files are supported."
        )

    # --------------------------------------------------------
    # 2. Read file and validate size
    # --------------------------------------------------------

    contents = await file.read(MAX_FILE_SIZE + 1)

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size cannot exceed 50 MB."
        )

    # --------------------------------------------------------
    # 3. Read dataset using Pandas
    # --------------------------------------------------------

    try:
        file_buffer = BytesIO(contents)

        if extension == ".csv":
            df = pd.read_csv(file_buffer)

        elif extension in {".xlsx", ".xls"}:
            df = pd.read_excel(file_buffer)

    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to read dataset: {str(error)}"
        )

    # --------------------------------------------------------
    # 4. Validate dataset
    # --------------------------------------------------------

    if df.empty:
        raise HTTPException(
            status_code=400,
            detail="Dataset contains no data."
        )

    if len(df.columns) == 0:
        raise HTTPException(
            status_code=400,
            detail="Dataset has no columns."
        )

    # --------------------------------------------------------
    # 5. Generate unique dataset ID
    # --------------------------------------------------------

    dataset_id = str(uuid.uuid4())

    # Never use the original filename as the storage path.
    stored_filename = f"{dataset_id}{extension}"

    file_path = UPLOAD_DIR / stored_filename

    # --------------------------------------------------------
    # 6. Save uploaded dataset
    # --------------------------------------------------------

    try:
        file_path.write_bytes(contents)

    except OSError:
        raise HTTPException(
            status_code=500,
            detail="Unable to save uploaded dataset."
        )

    # --------------------------------------------------------
    # 7. Return dataset information
    # --------------------------------------------------------

    return {
        "success": True,
        "dataset_id": dataset_id,
        "filename": file.filename,
        "file_type": extension.lstrip("."),
        "file_size": len(contents),
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_names": df.columns.tolist(),
        "message": "Dataset uploaded successfully."
    }
