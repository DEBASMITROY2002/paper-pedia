import logging, time, uuid
from starlette.datastructures import QueryParams
from paper_pedia.logging_config import request_id
logger = logging.getLogger(__name__)
class RequestLoggingMiddleware:
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        identifier = uuid.uuid4().hex[:12]
        token = request_id.set(identifier)
        started, status, failed = time.perf_counter(), 500, False
        method, path = scope["method"], scope["path"]
        query = QueryParams(scope.get("query_string", b""))
        selection = {key: query[key][:200] for key in ("venue", "year", "group", "refresh", "mode", "scheme") if key in query}
        logger.info("Request started method=%s path=%r selection=%r", method, path, selection)
        async def logged_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [(b"x-request-id", identifier.encode())]
            await send(message)
        try:
            await self.app(scope, receive, logged_send)
        except Exception:
            failed = True
            logger.exception("Unhandled request error method=%s path=%r", method, path)
            raise
        finally:
            level = logging.ERROR if failed or status >= 500 else logging.WARNING if status >= 400 else logging.INFO
            logger.log(level, "Request finished method=%s path=%r status=%d duration_ms=%.1f", method, path, 500 if failed else status, (time.perf_counter() - started) * 1000)
            request_id.reset(token)
