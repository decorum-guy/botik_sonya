(() => {
  "use strict";

  const steps = document.querySelector("#steps");
  const inspectorForm = document.querySelector("#inspector-form");
  const inspectorPanel = document.querySelector(".inspector");
  const palettePanel = document.querySelector(".palette");

  if (!steps || !inspectorForm) return;

  const ARM_TIME_MS = 2000;
  const RESTORE_DELAYS_MS = [0, 40, 120, 300];
  let snapshot = null;
  let armedUntil = 0;
  let restoreToken = 0;
  let restoring = false;
  let releaseHeightTimer = null;
  let previousBodyMinHeight = "";
  let previousHtmlMinHeight = "";
  let heightHeld = false;

  // The editor replaces large DOM sections. Disable browser scroll anchoring for
  // those sections so Chromium does not choose a new anchor near the page top.
  [document.documentElement, document.body, steps, inspectorForm].forEach((node) => {
    node.style.overflowAnchor = "none";
  });

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
      previousHtmlMinHeight = document.documentElement.style.minHeight;
      heightHeld = true;
    }

    const height = Math.max(
      document.documentElement.scrollHeight,
      document.body.scrollHeight,
      window.innerHeight,
    );
    const heldHeight = `${height}px`;
    document.body.style.minHeight = heldHeight;
    document.documentElement.style.minHeight = heldHeight;

    clearTimeout(releaseHeightTimer);
    releaseHeightTimer = setTimeout(releaseDocumentHeight, ARM_TIME_MS + 500);
  }

  function releaseDocumentHeight() {
    if (!heightHeld) return;
    clearTimeout(releaseHeightTimer);
    releaseHeightTimer = null;
    document.body.style.minHeight = previousBodyMinHeight;
    document.documentElement.style.minHeight = previousHtmlMinHeight;
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
    window.scrollTo(state.left, state.top);

    if (state.preserveInspector && inspectorPanel) {
      inspectorPanel.scrollTop = state.inspectorTop;
    }
    if (palettePanel) palettePanel.scrollTop = state.paletteTop;
  }

  function scheduleRestore(state = snapshot) {
    if (!state || performance.now() > armedUntil) return;

    const saved = { ...state };
    const token = ++restoreToken;
    restoring = true;

    queueMicrotask(() => {
      if (token !== restoreToken) return;
      restorePosition(saved);

      requestAnimationFrame(() => {
        if (token !== restoreToken) return;
        restorePosition(saved);

        requestAnimationFrame(() => {
          if (token !== restoreToken) return;
          restorePosition(saved);
        });
      });
    });

    RESTORE_DELAYS_MS.forEach((delay, index) => {
      setTimeout(() => {
        if (token !== restoreToken) return;
        restorePosition(saved);
        if (index === RESTORE_DELAYS_MS.length - 1) {
          restoring = false;
          releaseDocumentHeight();
        }
      }, delay);
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

  function isStepIdInput(target) {
    if (!(target instanceof HTMLInputElement)) return false;
    const field = target.closest("label.field");
    return field?.querySelector(":scope > span")?.textContent?.trim() === "ID этапа";
  }

  function isRedundantInspectorChange(target) {
    if (!(target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement)) {
      return false;
    }
    if (!target.closest("#inspector-form")) return false;
    if (target instanceof HTMLInputElement) {
      if (["checkbox", "radio", "file", "button", "submit"].includes(target.type)) {
        return false;
      }
    }
    return !isStepIdInput(target);
  }

  const observer = new MutationObserver((mutations) => {
    if (restoring || !mutations.some(mutationRebuildsEditor)) return;
    scheduleRestore();
  });

  observer.observe(steps, { childList: true, subtree: true });
  observer.observe(inspectorForm, { childList: true, subtree: true });

  // app.js already writes text and number values on every `input` event. Its
  // additional `change -> render()` handler only rebuilds the entire editor when
  // the field loses focus. Stop that redundant handler before it reaches the
  // field. The current value is already stored in the roadmap model.
  document.addEventListener("change", (event) => {
    if (!event.isTrusted || !isRedundantInspectorChange(event.target)) return;
    captureBeforeInteraction(event);
    event.stopImmediatePropagation();
    scheduleRestore();
  }, true);

  ["pointerdown", "keydown", "input", "click"].forEach((eventName) => {
    document.addEventListener(eventName, captureBeforeInteraction, true);
  });

  // Do not fight a deliberate manual scroll.
  ["wheel", "touchmove"].forEach((eventName) => {
    document.addEventListener(eventName, () => {
      restoreToken += 1;
      restoring = false;
      releaseDocumentHeight();
    }, { capture: true, passive: true });
  });
})();
