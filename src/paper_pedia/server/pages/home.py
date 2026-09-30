from urllib.parse import urlparse
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from paper_pedia.storage.csv_store import load_papers_csv
from ..config import TEMPLATE_DIR
from .. import service
router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
def safe_url(value):
    return value if value and urlparse(value).scheme in ("http", "https") else ""
templates.env.filters["safe_url"] = safe_url
def render_home(request, error="", status_code=200):
    try: catalog = service.get_catalog()
    except service.ServiceError as exc:
        catalog, error, status_code = {"venues": {}, "updated_at": None}, str(exc), 503
    cards = service.catalog_cards(catalog["venues"])
    return templates.TemplateResponse(request=request, name="index.html", status_code=status_code,
        context={"cards": cards, "updated_at": catalog["updated_at"], "error": error,
            "year_count": sum(c["years"] for c in cards), "cache_count": sum(r["cached"] for c in cards for r in c["rows"])})
@router.get("/", response_class=HTMLResponse)
def home(request: Request): return render_home(request)
@router.post("/cache/refresh", response_class=HTMLResponse)
def refresh(request: Request):
    try: service.refresh_catalog()
    except service.ServiceError as exc: return render_home(request, str(exc), 502)
    return RedirectResponse("/", status_code=303)
def render_papers(request, venue, year, group, refresh=False):
    error, code, rows, path = "", 200, [], None
    try: rows, path = service.get_papers(venue, year, group, refresh)
    except service.SelectionError as exc: error, code = str(exc), 404
    except service.ServiceError as exc:
        error, code = str(exc), 502
        candidate = service.csv_path(venue, year, group)
        if candidate.exists():
            try:
                rows, path = load_papers_csv(candidate), candidate
                error += " Showing the previous cached papers."
            except (OSError, ValueError, KeyError, TypeError): pass
    return templates.TemplateResponse(request=request, name="papers.html", status_code=code,
        context={"papers": rows, "venue": venue, "year": year, "group": group, "error": error,
            "query": service.selection_query(venue, year, group), "csv_file": path.name if path else None,
            "updated_at": service.cache_status(path)["updated_at"] if path else None,
            "clip_info": service.clip_index.index_status(path, service.CLIP_INDICES_DIR) if path else {"state": "uncached", "indexed": False, "label": "Render first"},
            "index_info": service.search_index.index_status(path, service.INDICES_DIR) if path else {"state": "uncached", "indexed": False, "label": "Render first"}})
@router.get("/papers", response_class=HTMLResponse)
def papers_page(request: Request, venue: str, year: int, group: str = "", refresh: bool = False):
    return render_papers(request, venue, year, group, refresh)
@router.post("/papers/refresh", response_class=HTMLResponse)
def refresh_papers(request: Request, venue: str, year: int, group: str = ""):
    response = render_papers(request, venue, year, group, True)
    if response.status_code != 200: return response
    return RedirectResponse("/papers?" + service.selection_query(venue, year, group), status_code=303)
