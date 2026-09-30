import asyncio, hashlib, json, logging, re, threading, time, uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar, copy_context
from urllib.parse import parse_qs
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from .templating import templates
from .config import TEMPLATE_DIR
logger = logging.getLogger(__name__)
current_job = ContextVar('background_job', default=None)
class JobManager:
    def __init__(self, workers=3, capacity=16):
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='paper-pedia-job')
        self.lock, self.jobs, self.capacity, self.closed = threading.RLock(), {}, capacity, False
    def snapshot(self, job):
        return {k: v for k, v in job.items() if k not in {'response', 'key'}}
    def submit(self, key, title, fn):
        with self.lock:
            if self.closed: raise HTTPException(503, 'Server is shutting down. Try again after restart.')
            for job in self.jobs.values():
                if job['key'] == key and job['state'] in {'queued', 'running'}: return self.snapshot(job)
            if sum(j['state'] in {'queued', 'running'} for j in self.jobs.values()) >= self.capacity:
                raise HTTPException(429, 'Background queue is full. Please try again after a task finishes.')
            # Bound retained HTML/JSON results and expire completed jobs after one hour.
            done = [j for j in self.jobs.values() if j['state'] in {'completed', 'failed'}]
            for j in done:
                if time.time() - j['updated_at'] > 3600 or len(self.jobs) >= 32: self.jobs.pop(j['id'], None)
            identity = uuid.uuid4().hex
            job = dict(id=identity, key=key, title=title, state='queued', message='Processing in background — queued.', created_at=time.time(), updated_at=time.time(), status_url=f'/api/jobs/{identity}', result_url=f'/api/jobs/{identity}/result')
            self.jobs[identity] = job
            context = copy_context()
            self.executor.submit(context.run, self._run, identity, fn)
            return self.snapshot(job)
    def _run(self, identity, fn):
        token = current_job.set((self, identity))
        try:
            self.update(identity, state='running', message='Processing in background…')
            logger.info('Background job started job=%s', identity)
            response = fn()
            failed = response.status_code >= 400
            count = self.get(identity).get('count')
            if hasattr(response, 'context') and 'papers' in response.context: count = len(response.context['papers'])
            elif response.media_type == 'application/json':
                try: count = json.loads(response.body).get('count', count)
                except (ValueError, AttributeError): pass
            summary = f'Completed — {count} papers processed. Your results are ready.' if count is not None else 'Completed. Your results are ready.'
            self.update(identity, response=response, state='failed' if failed else 'completed', message='Task failed. Open details for the error.' if failed else summary)
            logger.info('Background job finished job=%s status=%s', identity, response.status_code)
        except Exception as exc:
            logger.exception('Background job failed job=%s', identity)
            code = exc.status_code if isinstance(exc, HTTPException) else 422 if isinstance(exc, RequestValidationError) else 500
            detail = exc.detail if isinstance(exc, HTTPException) else jsonable_encoder(exc.errors()) if isinstance(exc, RequestValidationError) else 'Background task failed. Check the server logs and retry.'
            self.update(identity, response=JSONResponse({'detail': detail}, status_code=code), state='failed', message=str(detail))
        finally: current_job.reset(token)
    def update(self, identity, **values):
        with self.lock: self.jobs[identity].update(values, updated_at=time.time())
    def get(self, identity):
        with self.lock:
            if identity not in self.jobs: raise HTTPException(404, 'Job expired or the server restarted. Completed caches are preserved; retry unfinished work.')
            return self.snapshot(self.jobs[identity])
    def result(self, identity):
        with self.lock:
            job = self.get(identity)
            if job['state'] in {'queued', 'running'}: return JSONResponse(job, status_code=202)
            return self.jobs[identity]['response']
    def shutdown(self):
        with self.lock: self.closed = True
        self.executor.shutdown(wait=True)
manager = JobManager()
class ProgressHandler(logging.Handler):
    def emit(self, record):
        active = current_job.get()
        if not active or record.name == __name__: return
        owner, identity = active
        message = record.getMessage()
        count, total = re.search(r'papers=(\d+)', message), re.search(r'total=(\d+)', message)
        if count:
            count = int(count.group(1))
            text = f"Processing papers: {count}" + (f" of {total.group(1)}" if total else '')
            if 'checkpoint saved' in message.lower(): text = f"Saved checkpoint: {count} papers. Still processing…"
            owner.update(identity, count=count, message=text)
        elif 'Downloading SPLADE' in message: owner.update(identity, message='Downloading the SPLADE model for first use…')
        elif 'Loading SPLADE' in message: owner.update(identity, message='Loading the SPLADE model…')
logging.getLogger('paper_pedia').addHandler(ProgressHandler())
class BackgroundRoute(APIRoute):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.responses[202] = {'description': 'Processing in background. Poll status_url and fetch result_url when finished.'}
        self.responses[429] = {'description': 'Background queue is full. Retry after a job finishes.'}
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def dispatch(request: Request):
            from . import service
            path, query = request.url.path, request.query_params
            heavy = path in {'/papers', '/papers/refresh', '/cache/refresh', '/indices/build', '/api/venues/papers', '/api/venues/papers/refresh', '/api/venues/catalog/refresh', '/api/venues/search'}
            heavy |= path in {'/api/venues/index', '/api/venues/splade-index'} and request.method == 'POST'
            heavy |= path == '/search' and bool(query.get('q', '').strip())
            heavy |= path == '/api/venues/catalog' and query.get('refresh', '').lower() in {'true', '1'}
            if not heavy:
                try: service._read_catalog()
                except (OSError, ValueError, KeyError, TypeError): heavy = True
            if not heavy: return await handler(request)
            await request.body()
            title = ('Search' if 'search' in path else 'Index '+('SPLADE' if 'splade' in path or query.get('scheme') == 'splade' else 'TF-IDF') if 'index' in path or 'indices' in path else 'Refresh catalog' if 'catalog' in path or path in {'/', '/cache/refresh'} else 'Render papers')
            selection = parse_qs(query.get('selection', ''))
            fields = [query.get(name) or selection.get(name, [''])[0] for name in ['venue', 'year', 'group']]
            title += ' · ' + ' '.join(filter(None, fields)) if fields[0] else ''
            key = hashlib.sha256((request.method + path + str(sorted(query.multi_items()))).encode()).hexdigest()
            job = manager.submit(key, title, lambda: asyncio.run(handler(request)))
            headers = {'Location': job['status_url'], 'Retry-After': '1', 'Cache-Control': 'no-store'}
            if path.startswith('/api/') or request.headers.get('X-Background-Job') == '1':
                return JSONResponse(job, status_code=202, headers=headers)
            return templates.TemplateResponse(request=request, name='processing.html', context={'job': job}, status_code=202, headers=headers)
        return dispatch
router = APIRouter(prefix='/api/jobs', tags=['background jobs'])
@router.get('')
def list_jobs():
    with manager.lock: return {'jobs': [manager.snapshot(j) for j in manager.jobs.values()]}
@router.get('/{identity}')
def job_status(identity: str): return JSONResponse(manager.get(identity), headers={'Cache-Control': 'no-store'})
@router.get('/{identity}/result')
def job_result(identity: str): return manager.result(identity)
