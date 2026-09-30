import os
from pathlib import Path
SERVER_DIR = Path(__file__).resolve().parent
SRC_DIR = SERVER_DIR.parents[1]
DATA_DIR = Path(os.environ.get("PAPER_PEDIA_DATA_DIR", SRC_DIR / "data"))
VENUES_DIR = DATA_DIR / "venues"
INDICES_DIR = DATA_DIR / "indices"
CLIP_INDICES_DIR = DATA_DIR / "clip_indices"
CLIP_MODEL_DIR = DATA_DIR / "models" / "clip"
CATALOG_CACHE = DATA_DIR / "catalog.json"
TEMPLATE_DIR = SERVER_DIR / "templates"
STATIC_DIR = SERVER_DIR / "static"
VENUES_DIR.mkdir(parents=True, exist_ok=True)
