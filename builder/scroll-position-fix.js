(() => {
  "use strict";

  const steps = document.querySelector("#steps");
  const inspectorForm = document.querySelector("#inspector-form");
  const inspectorPanel = document.querySelector(".inspector");
  const palettePanel = document.querySelector(".palette");

  if (!steps || !inspectorForm) return;

  const ARM_TIME_MS = 2000;
  let snapshot = null;
  let armedUntil = 0;
  let restoreToken = 0;
  let restoring = false;
  let releaseHeightTimer = null;
  let previousBodyMinHeight = "";
  let heightHeld = false;

  function pagePosition() {
    const scrollingElement = document.scrollingElement || document.documentElement;
    return {
      left: window.scrollX || scrollingElement.scrollLeft || 0,
      top: window.scrollY || scrollingElement.scrollTop || 0,
    };
  }

  function holdDocumentHeight() {
    if (!heightHeld) {
      previousBodyMinHeight = document.body.style.minHeight;
      heightHeld = true;
    }

    const height = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight,
      window.innerHeight,
    );
    document.body.style.minHeight = `${height}px`;

    clearTimeout(releaseHeightTimer);
    releaseHeightTimer = setTimeout(releaseDocumentHeight, ARM_TIME_MS + 250);
  }

  function releaseDocumentHeight() {
    if (!heightHeld) return;
    clearTimeout(releaseHeightTimer);
    releaseHeightTimer = null;
    document.body.style.minHeight = previousBodyMinHeight;
    heightHeld = false;
  }

  function captureBeforeInteraction(event) {
    if (restoring) return;
    const target = event.target;
    if (!(target instanceof Element) || !target.closest(".workspace")) return;

    const position = pagePosition();
    snapshot = {
      left: position.left,
      top: position.top,
      preserveInspector: Boolean(target.closest("#inspector-form")),
      inspectorTop: inspectorPanel?.scrollTop || 0,
      paletteTop: palettePanel?.scrollTop || 0,
    };
    armedUntil = performance.now() + ARM_TIME_MS;
    holdDocumentHeight();
  }

  function restorePosition(state) {
    const scrollingElement = document.scrollingElement || document.documentElement;
    scrollingElement.scrollLeft = state.left;
    scrollingElement.scrollTop = state.top;
    window.scrollTo({ left: state.left, top: state.top, behavior: "auto" });

    if (state.preserveInspector && inspectorPanel) {
      inspectorPanel.scrollTop = state.inspectorTop;
    }
    if (palettePanel) palettePanel.scrollTop = state.paletteTop;
  }

  function scheduleRestore() {
    if (!snapshot || performance.now() > armedUntil) return;

    const state = { ...snapshot };
    const token = ++restoreToken;

    queueMicrotask(() => {
      if (token !== restoreToken) return;
      restoring = true;
      restorePosition(state);

      requestAnimationFrame(() => {
        if (token !== restoreToken) return;
        restorePosition(state);

        requestAnimationFrame(() => {
          if (token !== restoreToken) return;
          restorePosition(state);
          restoring = false;
          releaseDocumentHeight();
        });
      });
    });
  }

  function mutationRebuildsEditor(mutation) {
    if (mutation.type !== "childList") return false;
    const target = mutation.target;
    return target === steps
      || steps.contains(target)
      || target === inspectorForm
      || inspectorForm.contains(target);
  }

  const observer = new MutationObserver((mutations) => {
    if (restoring || !mutations.some(mutationRebuildsEditor)) return;
    scheduleRestore();
  });

  observer.observe(steps, { childList: true, subtree: true });
  observer.observe(inspectorForm, { childList: true, subtree: true });

  ["pointerdown", "keydown", "input", "change", "click"].forEach((eventName) => {
    document.addEventListener(eventName, captureBeforeInteraction, true);
  });
})();
