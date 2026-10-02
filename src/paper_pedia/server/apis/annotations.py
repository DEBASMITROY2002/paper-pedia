import logging, sqlite3
from typing import Annotated
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, StrictBool, StringConstraints, model_validator
from paper_pedia.storage import annotations
from ..config import ANNOTATIONS_CACHE
logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/annotations', tags=['paper annotations'])
PaperID = Annotated[str, StringConstraints(min_length=1, max_length=2000, pattern=r'\S')]
class Lookup(BaseModel):
    paper_ids: list[PaperID] = Field(max_length=500)
class Update(BaseModel):
    paper_id: PaperID
    marked: StrictBool | None = None
    comment: str | None = Field(default=None, max_length=20000)
    @model_validator(mode='after')
    def has_update(self):
        if self.marked is None and self.comment is None: raise ValueError('Provide marked or comment.')
        return self
def run(fn, *args, **kwargs):
    try: return JSONResponse(fn(ANNOTATIONS_CACHE, *args, **kwargs), headers={'Cache-Control': 'no-store'})
    except (sqlite3.Error, OSError):
        logger.exception('Paper annotation storage unavailable')
        raise HTTPException(503, 'Annotations could not be saved or loaded. Please retry.')
@router.post('/lookup')
def lookup(payload: Lookup): return run(annotations.lookup, payload.paper_ids)
@router.patch('')
def update(payload: Update): return run(annotations.update, payload.paper_id, payload.marked, payload.comment)
