import gc, logging, sys, threading
from contextlib import contextmanager
from functools import wraps
logger = logging.getLogger(__name__)
_lock, _local = threading.RLock(), threading.local()
def release():
    for name, attr in [('clip_encoder', '_cached_encoder'), ('splade_encoder', '_cached_encoder'), ('jaccard', '_sizes')]:
        module = sys.modules.get('paper_pedia.index.' + name)
        cached = getattr(module, attr, None)
        if hasattr(cached, 'cache_clear'): cached.cache_clear()
    gc.collect()
    torch = sys.modules.get('torch')
    if torch:
        for backend in [getattr(torch, 'mps', None), getattr(torch, 'cuda', None)]:
            try:
                if backend and backend.is_available(): backend.empty_cache()
            except (RuntimeError, AttributeError): pass
    logger.info('Search/index memory released: encoder caches cleared and unused accelerator allocations returned')
@contextmanager
def session():
    # Acquire before collection locks; serialize memory-heavy work across jobs.
    with _lock:
        depth = getattr(_local, 'depth', 0)
        _local.depth = depth + 1
        try: yield
        finally:
            _local.depth = depth
            if depth == 0: release()
def operation(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with session(): return fn(*args, **kwargs)
    return wrapped
