(() => {
  "use strict";

  const status = document.querySelector("#status");
  const saveDraftButton = document.querySelector("#save-draft");
  const inspector = document.querySelector(".inspector");
  const inspectorHeader = inspector?.querySelector(":scope > .panel__head");
  const steps = document.querySelector("#steps");

  if (!inspector || !inspectorHeader || !steps) return;

  const RESTORE_DELAYS_MS = [0, 40, 120, 260];
  let suppressStatusScrollUntil = 0;
  let suppressTextareaFocusScrollUntil = 0;

  function viewportSnapshot() {
    const scrollingElement = document.scrollingElement || document.documentElement;
    return {
      left: window.scrollX || scrollingElement.scrollLeft || 0,
      top: window.scrollY || scrollingElement.scrollTop || 0,
      inspectorTop: inspector.scrollTop,
    };
  }

  function restoreViewport(snapshot) {
    const scrollingElement = document.scrollingElement || document.documentElement;
    scrollingElement.scrollLeft = snapshot.left;
    scrollingElement.scrollTop = snapshot.top;
    window.scrollTo({ left: snapshot.left, top: snapshot.top, behavior: "auto" });
    inspector.scrollTop = snapshot.inspectorTop;
  }

  function preserveViewport(snapshot = viewportSnapshot()) {
    queueMicrotask(() => restoreViewport(snapshot));
    RESTORE_DELAYS_MS.forEach((delay) => {
      setTimeout(() => restoreViewport(snapshot), delay);
    });
  }

  if (status && saveDraftButton) {
    const nativeScrollIntoView = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView(options) {
      if (this === status && performance.now() < suppressStatusScrollUntil) return;
      return nativeScrollIntoView.call(this, options);
    };

    saveDraftButton.addEventListener("click", () => {
      const snapshot = viewportSnapshot();
      suppressStatusScrollUntil = performance.now() + 1200;
      preserveViewport(snapshot);
    }, true);
  }

  const nativeTextareaFocus = HTMLTextAreaElement.prototype.focus;
  HTMLTextAreaElement.prototype.focus = function focus(options) {
    if (performance.now() < suppressTextareaFocusScrollUntil) {
      const safeOptions = typeof options === "object" && options !== null
        ? { ...options, preventScroll: true }
        : { preventScroll: true };
      return nativeTextareaFocus.call(this, safeOptions);
    }
    return nativeTextareaFocus.call(this, options);
  };

  document.addEventListener("pointerdown", (event) => {
    const button = event.target.closest?.(".format-button");
    if (!button) return;
    const snapshot = viewportSnapshot();
    suppressTextareaFocusScrollUntil = performance.now() + 1000;
    preserveViewport(snapshot);
  }, true);

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.(".format-button");
    if (!button) return;
    suppressTextareaFocusScrollUntil = performance.now() + 1000;
  }, true);

  const style = document.createElement("style");
  style.textContent = `
    .inspector-locate-button {
      width: 100%;
      margin-top: 10px;
      border-color: #4b5f86;
    }
    .inspector-locate-button[hidden] { display: none; }
    .locate-target-flash {
      animation: locate-target-flash 1.15s ease;
    }
    @keyframes locate-target-flash {
      0%, 100% { box-shadow: inherit; }
      25%, 70% { box-shadow: 0 0 0 3px rgba(96, 165, 250, .9), 0 0 28px rgba(59, 130, 246, .5); }
    }
  `;
  document.head.append(style);

  const locateButton = document.createElement("button");
  locateButton.type = "button";
  locateButton.className = "button ghost inspector-locate-button";
  locateButton.hidden = true;
  inspectorHeader.append(locateButton);

  function selectedCanvasTarget() {
    return steps.querySelector(".action.selected") || steps.querySelector(".step.selected");
  }

  function updateLocateButton() {
    const target = selectedCanvasTarget();
    locateButton.hidden = !target;
    if (!target) return;
    locateButton.textContent = target.classList.contains("action")
      ? "◎ Перейти к выбранному блоку"
      : "◎ Перейти к выбранному этапу";
  }

  locateButton.addEventListener("click", () => {
    const target = selectedCanvasTarget();
    if (!target) return;

    target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    target.classList.remove("locate-target-flash");
    void target.offsetWidth;
    target.classList.add("locate-target-flash");
    setTimeout(() => target.classList.remove("locate-target-flash"), 1250);
  });

  const observer = new MutationObserver(updateLocateButton);
  observer.observe(steps, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });

  updateLocateButton();
})();
