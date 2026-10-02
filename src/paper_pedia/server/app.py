import asyncio, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from paper_pedia.logging_config import configure_logging
from .request_logging import RequestLoggingMiddleware
from fastapi.staticfiles import StaticFiles
from .apis.venues import router as venues_router
from .pages.home import router as pages_router
from .pages.search import router as search_router
from .config import STATIC_DIR, DATA_DIR
from .jobs import router as jobs_router, manager
configure_logging()
logger = logging.getLogger(__name__)
@asynccontextmanager
async def lifespan(app):
    logger.info("Server started data_dir=%s", DATA_DIR)
    try: yield
    finally:
        await asyncio.to_thread(manager.shutdown)
        logger.info("Server stopped")
app = FastAPI(title="Paper Pedia", version="0.2.0", lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(venues_router, prefix="/api")
from .apis.annotations import router as annotations_router
app.include_router(annotations_router)
app.include_router(jobs_router)
app.include_router(pages_router)
app.include_router(search_router)
@app.get("/health", include_in_schema=False)
def health(): return {"status": "ok"}
