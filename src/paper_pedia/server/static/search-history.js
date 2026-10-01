(() => {
  const key = 'paper-pedia-search-history-v1';
  let memory = [];
  const clean = value => typeof value === 'string' ? value.trim().replace(/\s+/g, ' ').slice(0, 1000) : '';
  function read() {
    try {
      const value = JSON.parse(localStorage.getItem(key) || '[]');
      if (Array.isArray(value)) memory = [...new Map(value.map(clean).filter(Boolean).map(q => [q.toLowerCase(), q])).values()].slice(0, 50);
    } catch {}
    return memory;
  }
  function write(values) { memory = values; try { localStorage.setItem(key, JSON.stringify(values)); } catch {} }
  document.querySelectorAll('form[data-indexed-search]').forEach((form, number) => {
    const input = form.querySelector('input[name="q"]');
    if (!input) return;
    const field = input.closest('label'); field.classList.add('history-field');
    const box = document.createElement('div'); box.className = 'query-history'; box.hidden = true;
    const heading = document.createElement('div'); heading.className = 'history-heading'; heading.textContent = 'Recent searches';
    const list = document.createElement('div'); list.id = 'query-history-' + number; list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', 'Previous search queries');
    const clear = document.createElement('button'); clear.type = 'button'; clear.className = 'history-clear'; clear.textContent = 'Clear search history';
    box.append(heading, list, clear); field.append(box);
    input.autocomplete = 'off'; input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('aria-controls', list.id); input.setAttribute('aria-expanded', 'false');
    let matches = [], selected = -1;
    function close() { box.hidden = true; selected = -1; input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant'); }
    function choose(value) { input.value = value; input.dispatchEvent(new Event('input', {bubbles:true})); close(); input.focus(); close(); }
    function show() {
      const query = clean(input.value).toLowerCase();
      matches = read().filter(value => value.toLowerCase().includes(query)).slice(0, 8);
      selected = -1; input.removeAttribute('aria-activedescendant'); list.replaceChildren();
      if (!matches.length) { close(); return; }
      matches.forEach((value, index) => {
        const option = document.createElement('div'); option.id = list.id + '-' + index; option.setAttribute('role', 'option'); option.setAttribute('aria-selected', 'false'); option.className = 'history-option'; option.textContent = value;
        option.addEventListener('pointerdown', event => { event.preventDefault(); choose(value); });
        list.append(option);
      });
      box.hidden = false; input.setAttribute('aria-expanded', 'true');
    }
    input.addEventListener('focus', show); input.addEventListener('input', show);
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { close(); return; }
      if (event.key === 'Tab') { close(); return; }
      if (event.key === 'Enter' && !box.hidden && selected >= 0) { event.preventDefault(); choose(matches[selected]); return; }
      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
      event.preventDefault(); if (box.hidden) show(); if (box.hidden) return;
      selected = (selected + (event.key === 'ArrowDown' ? 1 : selected < 0 ? 0 : -1) + matches.length) % matches.length;
      [...list.children].forEach((option, index) => option.setAttribute('aria-selected', String(index === selected)));
      input.setAttribute('aria-activedescendant', list.children[selected].id); list.children[selected].scrollIntoView({block:'nearest'});
    });
    clear.addEventListener('click', event => { event.preventDefault(); write([]); close(); input.focus(); });
    form.addEventListener('submit', event => {
      if (event.defaultPrevented || form.querySelector('[data-search-submit]')?.disabled || !form.checkValidity()) return;
      const query = clean(input.value); if (!query) return;
      write([query, ...read().filter(value => value.toLowerCase() !== query.toLowerCase())].slice(0, 50)); close();
    });
    document.addEventListener('pointerdown', event => { if (!field.contains(event.target)) close(); });
    field.addEventListener('focusout', event => { if (!field.contains(event.relatedTarget)) close(); });
    window.addEventListener('storage', event => { if (event.key === key && document.activeElement === input) show(); });
  });
})();
