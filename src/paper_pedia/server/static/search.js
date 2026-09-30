document.querySelectorAll("form[data-indexed-search]").forEach(form => {
  const button = form.querySelector("[data-search-submit]");
  const message = form.querySelector("[data-search-status]");
  const picker = form.querySelector('[name="selection"]');
  const panel = form.closest(".search-panel");
  const mode = () => form.querySelector('[name="mode"]:checked')?.value || "sparse";
  const current = () => {
    const source = picker ? picker.selectedOptions[0] : form;
    const chosen = picker ? Boolean(picker.value) : Boolean(form.querySelector('[name="venue"]')?.value);
    const states = {sparse: source?.dataset.sparseState || "missing", dense: source?.dataset.denseState || "missing"};
    return {chosen, states, state: states[mode() === "dense" ? "dense" : "sparse"]};
  };
  const update = () => {
    const {chosen, states, state} = current();
    button.disabled = !chosen || state !== "indexed";
    message.textContent = !chosen ? "Choose a collection to search." : state === "indexed" ? "Ready to search." : state === "stale" ? "Index out of date. Reindex to search." : state === "invalid" ? "Index unavailable. Reindex to search." : "Not yet indexed. Index this collection to search.";
    if (!picker) return;
    const controls = panel.querySelector("[data-search-index-controls]");
    if (controls) controls.hidden = !chosen;
    panel.querySelectorAll("[data-build-index]").forEach(build => {
      const scheme = build.dataset.buildIndex;
      const params = new URLSearchParams(picker.value);
      params.set("scheme", scheme);
      params.set("force", states[scheme] === "missing" ? "false" : "true");
      params.set("destination", "search");
      params.set("mode", mode());
      params.set("q", form.querySelector('[name="q"]').value);
      params.set("k", form.querySelector('[name="k"]').value);
      build.action = "/indices/build?" + params.toString();
      build.querySelector("button").textContent = (states[scheme] === "missing" ? "Index " : "Reindex ") + (scheme === "dense" ? "CLIP" : "TF-IDF / Jaccard");
    });
    panel.querySelectorAll("[data-index-label]").forEach(label => {
      const scheme = label.dataset.indexLabel, status = states[scheme];
      label.className = "badge " + (status === "indexed" ? "cached" : "uncached");
      label.textContent = (scheme === "dense" ? "CLIP: " : "TF-IDF / Jaccard: ") + ({indexed: "Indexed", stale: "Needs reindex", invalid: "Index unavailable"}[status] || "Not yet indexed");
    });
  };
  form.addEventListener("change", update);
  form.addEventListener("input", update);
  form.addEventListener("submit", event => {
    update();
    if (button.disabled) event.preventDefault();
  });
  update();
});
