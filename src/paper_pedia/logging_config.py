import logging, os, time
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
request_id = ContextVar("request_id", default="-")
class RequestContext(logging.Filter):
    def filter(self, record):
        record.request_id = request_id.get()
        return True
def configure_logging(log_dir=None):
    logger = logging.getLogger("paper_pedia")
    level = os.environ.get("PAPER_PEDIA_LOG_LEVEL", "INFO").upper()
    level = level if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL") else "INFO"
    logger.setLevel(level)
    logger.propagate = False
    if any(getattr(h, "paper_pedia_handler", False) for h in logger.handlers): return
    formatter = logging.Formatter("%(asctime)sZ %(levelname)-8s pid=%(process)d request=%(request_id)s %(name)s | %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime
    def attach(handler):
        handler.paper_pedia_handler = True
        handler.setFormatter(formatter)
        handler.addFilter(RequestContext())
        logger.addHandler(handler)
    attach(logging.StreamHandler())
    directory = Path(log_dir) if log_dir is not None else Path(os.environ.get("PAPER_PEDIA_DATA_DIR", Path(__file__).resolve().parents[1] / "data")) / "logs"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        attach(RotatingFileHandler(directory / "paper-pedia.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"))
    except OSError:
        logger.exception("File logging unavailable directory=%s; console logging remains active", directory)
