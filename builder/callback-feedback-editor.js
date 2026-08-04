(() => {
  "use strict";

  const DRAFT_KEY = "botik-sonya-roadmap-v1";
  const DEFAULT_TEXT = "Принято";
  const MAX_LENGTH = 200;
  const valuesByButtonId = new Map();
  let exportInProgress = false;

  function readDraft() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function walkButtons(roadmap, visitor) {
    for (const step of roadmap?.steps || []) {
      for (const action of step.actions || []) {
        if (action.type !== "buttons") continue;
        for (const button of action.buttons || []) visitor(button);
      }
    }
  }

  function rememberDraftValues() {
    const roadmap = readDraft();
    walkButtons(roadmap, (button) => {
      const id = String(button.id || "");
      if (!id || valuesByButtonId.has(id)) return;
      valuesByButtonId.set(
        id,
        typeof button.callback_text === "string" ? button.callback_text : DEFAULT_TEXT,
      );
    });
  }

  function patchDraft() {
    const roadmap = readDraft();
    if (!roadmap) return null;

    walkButtons(roadmap, (button) => {
      const id = String(button.id || "");
      const stored = valuesByButtonId.get(id);
      const existing = typeof button.callback_text === "string"
        ? button.callback_text
        : DEFAULT_TEXT;
      const value = stored ?? existing;
      button.callback_text = value || DEFAULT_TEXT;
      valuesByButtonId.set(id, button.callback_text);
    });

    localStorage.setItem(DRAFT_KEY, JSON.stringify(roadmap));
    return roadmap;
  }

  function fieldByLabel(container, label) {
    return [...container.querySelectorAll(":scope > label.field")].find((field) => (
      field.querySelector(":scope > span")?.textContent?.trim() === label
    ));
  }

  function makeCallbackField(value) {
    const field = document.createElement("label");
    field.className = "field callback-feedback-field";
    field.innerHTML = `
      <span>Всплывающее уведомление</span>
      <input maxlength="${MAX_LENGTH}">
      <small>Короткое уведомление поверх чата после нажатия. До ${MAX_LENGTH} символов.</small>
    `;
    field.querySelector("input").value = value || DEFAULT_TEXT;
    return field;
  }

  function enhanceButtonEditor(box) {
    if (box.dataset.callbackFeedbackReady === "1") return;

    const idField = fieldByLabel(box, "ID");
    const idInput = idField?.querySelector("input");
    if (!idInput) return;

    const chatField = fieldByLabel(box, "Сообщение после нажатия");
    if (chatField) {
      const label = chatField.querySelector(":scope > span");
      const note = chatField.querySelector(":scope > small");
      if (label) label.textContent = "Сообщение в чат после нажатия";
      if (note) note.textContent = "Обычное новое сообщение от бота. Не путать со всплывающим уведомлением.";
    }

    let currentId = idInput.value;
    if (!valuesByButtonId.has(currentId)) valuesByButtonId.set(currentId, DEFAULT_TEXT);

    const callbackField = makeCallbackField(valuesByButtonId.get(currentId));
    const callbackInput = callbackField.querySelector("input");
    box.append(callbackField);

    idInput.addEventListener("input", () => {
      const nextId = idInput.value;
      if (nextId !== currentId) {
        const currentValue = callbackInput.value || DEFAULT_TEXT;
        valuesByButtonId.set(currentId, currentValue);
        if (!valuesByButtonId.has(nextId)) valuesByButtonId.set(nextId, currentValue);
        currentId = nextId;
        callbackInput.value = valuesByButtonId.get(nextId) || DEFAULT_TEXT;
      }
    });

    callbackInput.addEventListener("input", () => {
      valuesByButtonId.set(currentId, callbackInput.value || DEFAULT_TEXT);
    });

    box.dataset.callbackFeedbackReady = "1";
  }

  function enhanceInspector() {
    rememberDraftValues();
    document.querySelectorAll(".button-editor").forEach(enhanceButtonEditor);
  }

  function saveAndPatch() {
    const save = document.querySelector("#save-draft");
    if (!save) return patchDraft();
    save.click();
    return patchDraft();
  }

  function showExportError(message) {
    const status = document.querySelector("#status");
    if (!status) return;
    status.hidden = false;
    status.className = "status error";
    status.textContent = message;
    status.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function downloadRoadmap(roadmap) {
    const blob = new Blob([JSON.stringify(roadmap, null, 2) + "\n"], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "quest.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function interceptExport(event) {
    if (exportInProgress) return;
    event.preventDefault();
    event.stopImmediatePropagation();

    exportInProgress = true;
    try {
      document.querySelector("#validate")?.click();
      const status = document.querySelector("#status");
      if (!status?.classList.contains("ok")) return;

      const roadmap = saveAndPatch();
      if (!roadmap) {
        showExportError("Не удалось прочитать текущий ROADMAP.");
        return;
      }

      const tooLong = [];
      walkButtons(roadmap, (button) => {
        if (String(button.callback_text || "").length > MAX_LENGTH) {
          tooLong.push(button.id || "без ID");
        }
      });
      if (tooLong.length) {
        showExportError(
          `Всплывающее уведомление длиннее ${MAX_LENGTH} символов: ${tooLong.join(", ")}`,
        );
        return;
      }

      downloadRoadmap(roadmap);
    } finally {
      exportInProgress = false;
    }
  }

  window.addEventListener("load", () => {
    rememberDraftValues();
    enhanceInspector();

    const inspector = document.querySelector("#inspector-form");
    if (inspector) {
      new MutationObserver(enhanceInspector).observe(inspector, {
        childList: true,
        subtree: true,
      });
    }

    document.querySelector("#save-draft")?.addEventListener("click", patchDraft);
    document.querySelector("#export")?.addEventListener("click", interceptExport, true);
    window.addEventListener("beforeunload", patchDraft);
  });
})();
