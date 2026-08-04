(() => {
  "use strict";

  const STEP_ID_LABEL = "ID этапа";

  function isStepIdInput(target) {
    if (!(target instanceof HTMLInputElement)) return false;
    const field = target.closest("label.field");
    const label = field?.querySelector(":scope > span")?.textContent?.trim();
    return label === STEP_ID_LABEL;
  }

  // app.js normally renames the step and rebuilds the whole inspector on every
  // input event. While the user is typing, keep the value only in the current
  // input element so the DOM node — and therefore focus/caret — stays intact.
  document.addEventListener("input", (event) => {
    if (event.isTrusted && isStepIdInput(event.target)) {
      event.stopImmediatePropagation();
    }
  }, true);

  // Commit the finished ID through app.js's existing setter when the field is
  // left. The synthetic event is allowed through, so references to the renamed
  // step are still updated by the original renameStep implementation.
  document.addEventListener("change", (event) => {
    const input = event.target;
    if (!isStepIdInput(input)) return;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, true);

  // Enter behaves like finishing the edit instead of submitting the form.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || !isStepIdInput(event.target)) return;
    event.preventDefault();
    event.target.blur();
  }, true);
})();
