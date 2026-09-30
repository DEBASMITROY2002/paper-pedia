(() => {
  const panel = document.getElementById('background-jobs'), items = document.getElementById('job-items');
  const announce = document.getElementById('job-announcement');
  let hidden = new Set(), known = new Map(), polling = false;
  try { hidden = new Set(JSON.parse(sessionStorage.getItem('paper-pedia-dismissed-jobs') || '[]')); } catch {}
  const labels = {queued: 'Processing in background — queued', running: 'Processing in background', completed: 'Completed', failed: 'Failed'};
  function render(jobs) {
    if (JSON.stringify(jobs) === JSON.stringify([...known.values()]) && items.children.length) return;
    items.replaceChildren();
    jobs.filter(j => !hidden.has(j.id)).slice().reverse().forEach(job => {
      const section = document.createElement('section'); section.className = 'job-item'; section.dataset.state = job.state;
      const title = document.createElement('strong'); title.textContent = job.title;
      const status = document.createElement('p'); status.className = 'job-state'; status.textContent = labels[job.state];
      const detail = document.createElement('p'); detail.textContent = job.message;
      section.append(title, status, detail);
      if (['completed', 'failed'].includes(job.state)) {
        const actions = document.createElement('div'); actions.className = 'job-actions';
        const link = document.createElement('a'); link.href = job.result_url; link.textContent = job.state === 'completed' ? 'View results' : 'View error'; actions.append(link);
        const refresh = document.createElement('a'); refresh.href = '/'; refresh.textContent = 'Refresh library'; actions.append(refresh);
        const dismiss = document.createElement('button'); dismiss.type = 'button'; dismiss.textContent = 'Dismiss';
        dismiss.onclick = () => { hidden.add(job.id); try { sessionStorage.setItem('paper-pedia-dismissed-jobs', JSON.stringify([...hidden])); } catch {} items.replaceChildren(); render([...known.values()]); };
        actions.append(dismiss); section.append(actions);
      }
      items.append(section);
      if (known.get(job.id)?.state !== job.state) announce.textContent = job.title + ': ' + labels[job.state];
    });
    known = new Map(jobs.map(j => [j.id,j])); panel.hidden = !items.children.length;
  }
  function problem(message) { panel.hidden = false; announce.textContent = message; let p = items.querySelector('.job-notice'); if (!p) { p = document.createElement('p'); p.className = 'job-notice'; items.prepend(p); } p.textContent = message; }
  async function poll() {
    if (polling) return; polling = true;
    try {
      const response = await fetch('/api/jobs', {cache: 'no-store'});
      if (!response.ok) throw new Error('Background status is unavailable. Retrying…');
      const data = await response.json(); render(data.jobs);
    } catch { if ([...known.values()].some(j => ['queued','running'].includes(j.state))) problem('Connection lost. Reconnecting to background tasks…'); }
    finally { polling = false; setTimeout(poll, 1500); }
  }
  async function submit(url, method) {
    problem('Processing in background…');
    try {
      const response = await fetch(url, {method, headers: {'X-Background-Job':'1'}});
      if (response.status === 202) {
        const job = await response.json(); hidden.delete(job.id); const next = new Map(known); next.set(job.id, job); render([...next.values()]);
      } else if (!response.ok) {
        const body = await response.json().catch(() => ({})); problem(typeof body.detail === 'string' ? body.detail : 'Could not start this task. Check the inputs and try again.');
      } else { location.assign(response.url); }
    } catch { problem('Could not confirm the task started. Check the background list before retrying.'); }
  }
  document.addEventListener('submit', event => {
    const form = event.target;
    if (event.defaultPrevented || !(form instanceof HTMLFormElement)) return;
    const url = new URL(form.action, location.href);
    if (url.origin !== location.origin || !['/cache/refresh','/papers/refresh','/indices/build','/search'].includes(url.pathname)) return;
    if (form.querySelector('[data-search-submit]')?.disabled) { event.preventDefault(); return; }
    event.preventDefault();
    if (form.method.toLowerCase() === 'get') for (const [key,value] of new FormData(form)) url.searchParams.set(key, value);
    submit(url, form.method.toUpperCase());
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    const url = new URL(link.href, location.href);
    if (url.origin === location.origin && url.pathname === '/papers') { event.preventDefault(); submit(url, 'GET'); }
  });
  document.getElementById('jobs-minimize').onclick = event => { items.hidden = !items.hidden; event.target.textContent = items.hidden ? 'Expand' : 'Minimize'; event.target.setAttribute('aria-expanded', String(!items.hidden)); };
  poll();
})();
