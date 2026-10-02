from typing import Literal
from urllib.parse import parse_qs, urlencode
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from .home import templates
from .. import service
from ..jobs import BackgroundRoute
router = APIRouter(route_class=BackgroundRoute, )
@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, venue: str = "", year: int | None = None, group: str = "",
    selection: str = Query("", max_length=2000), q: str = Query("", max_length=1000), k: int = Query(10, ge=1, le=100), mode: Literal["sparse", "splade", "dense", "subset"] = "sparse", scope: Literal["venue", "global"] = "venue"):
    error, code, results, info, options = "", 200, [], None, []
    sparse_info, splade_info, clip_info = None, None, None
    global_states, global_result = {}, {}
    try:
        catalog = service.get_catalog()
        for card in service.catalog_cards(catalog["venues"]):
            for row in card["rows"]:
                if row["cached"]:
                    options.append({"value": row["query"], "sparse_state": row["index_info"]["state"], "splade_state": row["splade_info"]["state"], "dense_state": row["clip_info"]["state"], "label": f"{card['venue']} {row['year']} · {row['group'] or 'All papers'}"})
        global_states = {method: ('indexed' if next(service.indexed_collections(method), None) else 'missing') for method in ['sparse', 'dense', 'splade']}
        if scope == 'global':
            info = {'indexed': global_states['sparse' if mode=='subset' else mode]=='indexed', 'state': global_states['sparse' if mode=='subset' else mode]}
            if q.strip():
                global_result = service.search_global(q, k, mode)
                results = global_result['papers']
        if selection and scope != 'global':
            values = parse_qs(selection, keep_blank_values=True)
            venue, year, group = values["venue"][0], int(values["year"][0]), values.get("group", [""])[0]
        if scope == "global": pass
        elif venue and year is not None:
            service.validate_selection(venue, year, group)
            selection = service.selection_query(venue, year, group)
            sparse_info = service.collection_index_status(venue, year, group)
            splade_info = service.collection_splade_status(venue, year, group)
            clip_info = service.collection_clip_status(venue, year, group)
            info = clip_info if mode == "dense" else splade_info if mode == "splade" else sparse_info
            if q.strip(): results = service.search_collection(venue, year, group, q, k, mode)
        elif q.strip(): error, code = "Choose a collection to search.", 400
    except service.SelectionError as exc: error, code = str(exc), 404
    except service.IndexUnavailable as exc: error, code = str(exc), 409
    except service.ServiceError as exc: error, code = str(exc), 503
    except (ValueError, KeyError, IndexError): error, code = "Invalid collection selection.", 422
    return templates.TemplateResponse(request=request, name="search.html", status_code=code,
        context={"papers": results, "venue": venue, "year": year, "group": group, "selection": selection,
            "scope": scope, "global_states": global_states, "global_result": global_result, "options": options, "q": q, "k": k, "index_info": info, "error": error,
            "index_query": service.selection_query(venue, year, group) if venue and year is not None else "",
            "searching": True, "mode": mode, "sparse_info": sparse_info, "splade_info": splade_info, "clip_info": clip_info,
            "method_label": {"dense": "Dense (CLIP)", "sparse": "Sparse (TF-IDF)", "splade": "Neural sparse (SPLADE)", "subset": "Subset (Jaccard)"}[mode]})
@router.post("/indices/build", response_class=HTMLResponse)
def build_index(request: Request, venue: str, year: int, group: str = "", force: bool = False,
    scheme: Literal["sparse", "splade", "dense"] = "sparse", destination: Literal["home", "papers", "search"] = "home", q: str = Query("", max_length=1000), k: int = Query(10, ge=1, le=100), mode: Literal["sparse", "splade", "dense", "subset"] = "sparse"):
    try:
        builder = {"dense": service.build_collection_clip, "splade": service.build_collection_splade, "sparse": service.build_collection_index}[scheme]
        builder(venue, year, group, force)
    except (service.SelectionError, service.ServiceError) as exc:
        return templates.TemplateResponse(request=request, name="index_error.html", status_code=404 if isinstance(exc, service.SelectionError) else 409,
            context={"error": str(exc), "query": service.selection_query(venue, year, group)})
    target = "/" if destination == "home" else "/" + destination + "?" + service.selection_query(venue, year, group)
    if destination == "search": target += "&" + urlencode({"q": q, "k": k, "mode": mode})
    return RedirectResponse(target, status_code=303)
