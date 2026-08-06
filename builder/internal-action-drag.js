(() => {
  "use strict";

  let internalDrag = null;
  let forwardingDrop = false;

  function actionRows(container) {
    return [...(container?.children || [])].filter((node) =>
      node.classList?.contains("action")
    );
  }

  function dropContainer(target) {
    return target?.closest?.(".step__actions")
      || target?.closest?.(".step")?.querySelector(".step__actions")
      || null;
  }

  function insertionIndex(container, clientY) {
    const rows = actionRows(container);
    const index = rows.findIndex((row) => {
      const rect = row.getBoundingClientRect();
      return clientY < rect.top + rect.height / 2;
    });
    return index < 0 ? rows.length : index;
  }

  function clearDropIndicators() {
    document.querySelectorAll(".action.drop-before").forEach((node) => {
      node.classList.remove("drop-before");
    });
    document.querySelectorAll(".step__actions.drop-at-end").forEach((node) => {
      node.classList.remove("drop-at-end");
    });
  }

  function showDropIndicator(container, index) {
    clearDropIndicators();
    const rows = actionRows(container);
    if (index >= rows.length) {
      container.classList.add("drop-at-end");
      return;
    }
    rows[index].classList.add("drop-before");
  }

  function makeDropEvent(dataTransfer, clientY) {
    try {
      return new DragEvent("drop", {
        bubbles: true,
        cancelable: true,
        dataTransfer,
        clientY,
      });
    } catch (_) {
      const event = new Event("drop", { bubbles: true, cancelable: true });
      Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
      Object.defineProperty(event, "clientY", { value: clientY });
      return event;
    }
  }

  document.addEventListener("dragstart", (event) => {
    const row = event.target?.closest?.(".action");
    if (!row) return;
    internalDrag = { row };
    clearDropIndicators();
  }, true);

  document.addEventListener("dragover", (event) => {
    if (!internalDrag || forwardingDrop) return;
    const container = dropContainer(event.target);
    if (!container) {
      clearDropIndicators();
      return;
    }

    event.preventDefault();
    try { event.dataTransfer.dropEffect = "move"; } catch (_) { /* ignored */ }
    showDropIndicator(container, insertionIndex(container, event.clientY));
  }, true);

  document.addEventListener("drop", (event) => {
    if (!internalDrag || forwardingDrop) return;
    const container = dropContainer(event.target);
    if (!container) {
      clearDropIndicators();
      internalDrag = null;
      return;
    }

    event.preventDefault();
    event.stopImmediatePropagation();

    const rows = actionRows(container);
    const index = insertionIndex(container, event.clientY);
    const destination = index >= rows.length ? container : rows[index];
    clearDropIndicators();

    // app.js owns the roadmap state and its moveAction implementation. Re-dispatch
    // the drop to the exact row/container represented by the visual indicator so
    // the actual insertion position and the highlighted position cannot diverge.
    forwardingDrop = true;
    try {
      destination.dispatchEvent(makeDropEvent(event.dataTransfer, event.clientY));
    } finally {
      forwardingDrop = false;
      internalDrag = null;
      clearDropIndicators();
    }
  }, true);

  document.addEventListener("dragend", () => {
    internalDrag = null;
    clearDropIndicators();
  }, true);

  window.addEventListener("blur", () => {
    internalDrag = null;
    clearDropIndicators();
  });
})();
