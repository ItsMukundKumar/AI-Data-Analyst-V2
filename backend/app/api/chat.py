"""Chat endpoint: answers are computed from the real dataset (see services/chat_engine.py)."""
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.analytics import Filter, _filtered, FilterBody
from services import analytics as A
from services import chat_engine

router = APIRouter(tags=["AI Chat"])


class ChatBody(BaseModel):
    dataset_id: str
    question: str = Field(..., min_length=1, max_length=1000)
    filters: List[Filter] = Field(default_factory=list, max_length=20)


@router.post("/chat")
def chat(body: ChatBody):
    d, kinds, total, flt = _filtered(body.dataset_id, FilterBody(filters=body.filters))
    if d.empty:
        return {"success": True, "answer": "No rows match the active filters, so there is nothing to analyze.", "charts": [], "table": None, "columns_used": []}
    try:
        res = chat_engine.answer(d, kinds, body.question)
    except A.AnalyticsError as e:
        raise HTTPException(400, str(e))
    return {"success": True, **res}
