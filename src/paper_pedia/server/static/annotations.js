(() => {
  const cards = [...document.querySelectorAll('[data-paper-annotation]')];
  if (!cards.length) return;
  const byID = new Map();
  cards.forEach(card => { const id = card.dataset.paperAnnotation; if (!byID.has(id)) byID.set(id, []); byID.get(id).push(card); });
  function state(card, annotation, comments = true) {
    const mark = card.querySelector('[data-mark]');
    mark.setAttribute('aria-pressed', String(annotation.marked)); mark.textContent = annotation.marked ? '★ Marked' : '☆ Mark paper';
    card.dataset.marked = String(annotation.marked);
    card.querySelector('summary').textContent = annotation.comment ? 'Comment · Saved' : 'Add comment';
    if (comments) { const input = card.querySelector('textarea'); input.value = annotation.comment; input.dataset.saved = annotation.comment; }
  }
  function controls(card, disabled) { card.querySelectorAll('[data-mark],textarea,[data-save-comment]').forEach(node => node.disabled = disabled); }
  async function request(path, method, body) {
    const response = await fetch(path, {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body), cache:'no-store', signal:AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error('Annotations unavailable. Retry without leaving this page.');
    return response.json();
  }
  async function load(ids) {
    for (let offset=0; offset<ids.length; offset+=500) {
      const batch = ids.slice(offset, offset+500);
      try {
        const saved = await request('/api/annotations/lookup', 'POST', {paper_ids:batch});
        batch.forEach(id => byID.get(id).forEach(card => { state(card, Object.hasOwn(saved,id) ? saved[id] : {marked:false,comment:''}); controls(card,false); card.querySelector('[data-annotation-status]').textContent=''; card.querySelector('[data-retry]').hidden=true; }));
      } catch {
        batch.forEach(id => byID.get(id).forEach(card => { card.querySelector('[data-annotation-status]').textContent='Could not load your marks and comments.'; card.querySelector('[data-retry]').hidden=false; }));
      }
    }
  }
  async function save(card, patch) {
    const id=card.dataset.paperAnnotation, status=card.querySelector('[data-annotation-status]');
    controls(card,true); status.textContent='Saving…';
    try {
      const saved=await request('/api/annotations','PATCH',{paper_id:id,...patch});
      byID.get(id).forEach(other => {
        const input=other.querySelector('textarea');
        state(other,saved,other===card && 'comment' in patch || input.value===input.dataset.saved);
      });
      status.textContent='Saved';
    } catch { status.textContent='Could not save. Your draft is still here; please try again.'; }
    finally { controls(card,false); }
  }
  cards.forEach(card => {
    card.querySelector('[data-mark]').onclick=()=>save(card,{marked:card.dataset.marked!=='true'});
    card.querySelector('[data-save-comment]').onclick=()=>save(card,{comment:card.querySelector('textarea').value});
    card.querySelector('textarea').addEventListener('input',event=> { card.querySelector('[data-annotation-status]').textContent=event.target.value===event.target.dataset.saved ? '' : 'Unsaved comment'; });
    card.querySelector('[data-retry]').onclick=()=>load([card.dataset.paperAnnotation]);
  });
  window.addEventListener('beforeunload',event=> { if(cards.some(card=> { const input=card.querySelector('textarea'); return input.value!==input.dataset.saved; })) { event.preventDefault(); event.returnValue=''; } });
  window.addEventListener('pageshow', event => { if (event.persisted) { const ids=[...byID.keys()].filter(id => byID.get(id).every(card => { const input=card.querySelector('textarea'); return input.value===input.dataset.saved; })); ids.forEach(id=>byID.get(id).forEach(card=>controls(card,true))); load(ids); } });
  load([...byID.keys()]);
})();
