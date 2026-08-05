(() => {
  "use strict";

  let resizeObserver = null;
  let observedTopbar = null;
  let observedRunner = null;
  let scheduled = false;

  function update() {
    scheduled = false;
    const topbar = document.querySelector(".topbar");
    const runner = document.querySelector("#test-runner");
    const topbarHeight = Math.ceil(topbar?.getBoundingClientRect().height || 64);
    const runnerHeight = Math.ceil(runner?.getBoundingClientRect().height || 0);
    const sideTop = topbarHeight + runnerHeight + 14;

    document.documentElement.style.setProperty("--topbar-height", `${topbarHeight}px`);
    document.documentElement.style.setProperty("--builder-side-top", `${sideTop}px`);
  }

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(update);
  }

  function refreshObservers() {
    const topbar = document.querySelector(".topbar");
    const runner = document.querySelector("#test-runner");
    if (topbar === observedTopbar && runner === observedRunner) {
      schedule();
      return;
    }

    resizeObserver?.disconnect();
    resizeObserver = new ResizeObserver(schedule);
    observedTopbar = topbar;
    observedRunner = runner;
    if (topbar) resizeObserver.observe(topbar);
    if (runner) resizeObserver.observe(runner);
    schedule();
  }

  new MutationObserver(refreshObservers).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["hidden", "class"],
  });
  window.addEventListener("resize", schedule, { passive: true });
  window.addEventListener("load", refreshObservers);
  refreshObservers();
})();
