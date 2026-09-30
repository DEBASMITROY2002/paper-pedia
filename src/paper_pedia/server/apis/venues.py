from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from .. import service
from ..jobs import BackgroundRoute
router = APIRouter(route_class=BackgroundRoute, prefix="/venues", tags=["venues"])
def run(fn, *args, **kwargs):
    try: return fn(*args, **kwargs)
    except service.SelectionError as exc: raise HTTPException(404, str(exc)) from exc
    except service.IndexUnavailable as exc: raise HTTPException(409, str(exc)) from exc
    except service.ServiceError as exc: raise HTTPException(502, str(exc)) from exc
@router.get("/catalog")
def catalog(refresh: bool = False): return run(service.get_catalog, refresh)
@router.post("/catalog/refresh")
def refresh_catalog(): return run(service.refresh_catalog)
@router.get("/papers")
def papers(venue: str, year: int, group: str = "", refresh: bool = False):
    data, path = run(service.get_papers, venue, year, group, refresh)
    return {"venue": venue, "year": year, "group": group or "All", "count": len(data), "csv": path.name, "papers": data}
@router.post("/papers/refresh")
def refresh_papers(venue: str, year: int, group: str = ""):
    return papers(venue, year, group, True)
@router.get("/csv")
def csv_download(venue: str, year: int, group: str = ""):
    run(service.validate_selection, venue, year, group)
    path = service.csv_path(venue, year, group)
    if not path.exists(): raise HTTPException(404, "Render papers first to create the CSV cache.")
    return FileResponse(path, media_type="text/csv", filename=path.name)

@router.get("/index")
def index_status(venue: str, year: int, group: str = ""):
    return run(service.collection_index_status, venue, year, group)
@router.post("/index")
def index_collection(venue: str, year: int, group: str = "", force: bool = False):
    return run(service.build_collection_index, venue, year, group, force)
@router.get("/search")
def search(venue: str, year: int, group: str = "", q: str = Query(..., min_length=1, max_length=1000), k: int = Query(10, ge=1, le=100), mode: Literal["sparse", "splade", "subset"] = "sparse"):
    if not q.strip(): raise HTTPException(422, "Enter a nonempty search query.")
    results = run(service.search_collection, venue, year, group, q, k, mode)
    return {"venue": venue, "year": year, "group": group or "All", "query": q, "k": k, "mode": mode, "count": len(results), "papers": results}

@router.get("/splade-index")
def splade_status(venue: str, year: int, group: str = ""):
    return run(service.collection_splade_status, venue, year, group)
@router.post("/splade-index")
def splade_collection(venue: str, year: int, group: str = "", force: bool = False):
    return run(service.build_collection_splade, venue, year, group, force)
