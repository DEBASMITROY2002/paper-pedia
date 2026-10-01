import hashlib
from functools import lru_cache
from jinja2 import pass_context
from fastapi.templating import Jinja2Templates
from .config import TEMPLATE_DIR, STATIC_DIR
@lru_cache(maxsize=64)
def _version(name, modified, size):
    return hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:12]
@pass_context
def asset_url(context, name):
    name = name.lstrip('/')
    stat = (STATIC_DIR / name).stat()
    version = _version(name, stat.st_mtime_ns, stat.st_size)
    return str(context['request'].url_for('static', path='/' + name)) + '?v=' + version
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals['asset_url'] = asset_url
