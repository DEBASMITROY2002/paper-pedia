// One timer and at most one request; no polling before activity.
(function(root) {
  function createActivityPoller(run, options = {}) {
    const fast = options.fast || 1500, idle = options.idle || 60000, maximum = options.maximum || 60000;
    const now = options.now || Date.now, later = options.later || setTimeout, cancel = options.cancel || clearTimeout;
    let timer = null, busy = false, stopped = true, lastClick = 0, generation = 0, delay = fast, slow = false;
    function schedule(wait) { if (timer !== null) cancel(timer); timer = later(tick, wait); }
    async function tick() {
      timer = null; if (stopped || busy) return;
      busy = true; const started = generation;
      try { if (await run() && started === generation) slow = true; }
      catch { if (started === generation) slow = true; }
      finally {
        busy = false;
        if (!stopped) {
          if (now() - lastClick >= idle) slow = true;
          delay = slow ? Math.min(maximum, delay * 2) : fast;
          schedule(delay);
        }
      }
    }
    return {
      activity(timestamp = now()) { lastClick = timestamp; generation++; stopped = false; slow = now() - timestamp >= idle; delay = fast; if (!busy) schedule(0); },
      stop() { stopped = true; if (timer !== null) cancel(timer); timer = null; }
    };
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = createActivityPoller;
  else root.createActivityPoller = createActivityPoller;
})(typeof window !== 'undefined' ? window : globalThis);
