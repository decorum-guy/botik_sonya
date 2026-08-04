(() => {
  "use strict";

  const DRAFT_KEY = "botik-sonya-roadmap-v1";
  const DEFAULTS = {
    delivery_mode: "instant",
    typing_speed_seconds: 0.12,
    stream_segments: [],
  };
  const settingsByAction = new Map();
  const dirtyActions = new Set();

  function readDraft() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function actionKey(stepId, actionIndex) {
    return `${stepId}::${actionIndex}`;
  }

  function normalizeSettings(action) {
    return {
      delivery_mode: ["instant", "characters", "words"].includes(action?.delivery_mode)
        ? action.delivery_mode
        : DEFAULTS.delivery_mode,
      typing_speed_seconds: Number.isFinite(Number(action?.typing_speed_seconds))
        ? Number(action.typing_speed_seconds)
        : DEFAULTS.typing_speed_seconds,
      stream_segments: Array.isArray(action?.stream_segments)
        ? action.stream_segments.map((segment) => ({
            text: String(segment?.text || ""),
            pause_after_seconds: Number(segment?.pause_after_seconds || 0),
          }))
        : [],
    };
  }

  function rememberRoadmap(roadmap) {
    for (const step of roadmap?.steps || []) {
      (step.actions || []).forEach((action, index) => {
        if (action.type !== "send_text") return;
        const key = actionKey(step.id, index);
        if (!dirtyActions.has(key)) settingsByAction.set(key, normalizeSettings(action));
      });
    }
  }

  function selectedContext() {
    const action = document.querySelector(".action.selected");
    if (!action) return null;
    const step = action.closest(".step");
    const actions = [...step.querySelectorAll(":scope > .step__actions > .action")];
    return {
      stepId: step?.dataset.stepId || "",
      actionIndex: actions.indexOf(action),
    };
  }

  function selectedTextAction() {
    const context = selectedContext();
    if (!context || context.actionIndex < 0) return null;
    const roadmap = readDraft();
    const step = roadmap?.steps?.find((item) => item.id === context.stepId);
    const action = step?.actions?.[context.actionIndex];
    return { context, action };
  }

  function field(label, control, note) {
    const wrapper = document.createElement("label");
    wrapper.className = "field streaming-text-field";
    const title = document.createElement("span");
    title.textContent = label;
    const small = document.createElement("small");
    small.textContent = note || "";
    wrapper.append(title, control, small);
    return wrapper;
  }

  function modeSelect(value) {
    const select = document.createElement("select");
    [
      ["instant", "Сразу, обычным сообщением"],
      ["characters", "Потоково по символам"],
      ["words", "Потоково по словам"],
    ].forEach(([optionValue, label]) => {
      const option = document.createElement("option");
      option.value = optionValue;
      option.textContent = label;
      select.append(option);
    });
    select.value = value;
    return select;
  }

  function segmentsToText(segments) {
    return (segments || []).map((segment) => (
      `${String(segment.text || "")} || ${Number(segment.pause_after_seconds || 0)}`
    )).join("\n");
  }

  function textToSegments(value) {
    return String(value || "")
      .split("\n")
      .map((line) => {
        const separator = line.lastIndexOf("||");
        if (separator < 0) return { text: line, pause_after_seconds: 0 };
        const text = line.slice(0, separator).trimEnd();
        const parsed = Number(line.slice(separator + 2).trim().replace(",", "."));
        return {
          text,
          pause_after_seconds: Number.isFinite(parsed) ? Math.max(0, Math.min(60, parsed)) : 0,
        };
      })
      .filter((segment) => segment.text || segment.pause_after_seconds);
  }

  function patchDraft() {
    const roadmap = readDraft();
    if (!roadmap) return;

    for (const step of roadmap.steps || []) {
      (step.actions || []).forEach((action, index) => {
        if (action.type !== "send_text") return;
        const key = actionKey(step.id, index);
        const settings = settingsByAction.get(key);
        if (!settings || !dirtyActions.has(key)) return;
        action.delivery_mode = settings.delivery_mode;
        action.typing_speed_seconds = settings.typing_speed_seconds;
        action.stream_segments = settings.stream_segments;
      });
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify(roadmap));
  }

  function enhanceInspector() {
    rememberRoadmap(readDraft());
    const form = document.querySelector("#inspector-form");
    if (!form || form.querySelector(".streaming-text-controls")) return;

    const textField = [...form.querySelectorAll(":scope > label.field")].find((item) => (
      item.querySelector(":scope > span")?.textContent?.trim() === "Текст"
    ));
    if (!textField) return;

    const selected = selectedTextAction();
    if (!selected) return;
    const { context, action } = selected;
    if (action && action.type !== "send_text") return;

    const key = actionKey(context.stepId, context.actionIndex);
    const settings = settingsByAction.get(key) || normalizeSettings(action);
    settingsByAction.set(key, settings);

    const controls = document.createElement("div");
    controls.className = "streaming-text-controls";

    const heading = document.createElement("div");
    heading.className = "panel__head";
    heading.innerHTML = `
      <h3>Потоковая печать</h3>
      <p>Telegram показывает временный draft, затем бот закрепляет финальное поле «Текст».</p>
    `;

    const mode = modeSelect(settings.delivery_mode);
    const speed = document.createElement("input");
    speed.type = "number";
    speed.min = "0.03";
    speed.max = "5";
    speed.step = "0.01";
    speed.value = String(settings.typing_speed_seconds);

    const segments = document.createElement("textarea");
    segments.rows = 5;
    segments.placeholder = "Практически || 2.5\n… я больше не уверен. || 0";
    segments.value = segmentsToText(settings.stream_segments);

    const speedField = field(
      "Скорость одного символа/слова, сек.",
      speed,
      "Рекомендуется 0.08–0.18 для символов и 0.25–0.6 для слов.",
    );
    const segmentsField = field(
      "Сегменты и паузы",
      segments,
      "Каждая строка: текст || пауза после него в секундах. Пустое поле печатает обычный «Текст» целиком.",
    );

    function updateVisibility() {
      const enabled = mode.value !== "instant";
      speedField.hidden = !enabled;
      segmentsField.hidden = !enabled;
    }

    function markDirty() {
      settings.delivery_mode = mode.value;
      settings.typing_speed_seconds = Math.max(
        0.03,
        Math.min(5, Number(speed.value.replace(",", ".")) || DEFAULTS.typing_speed_seconds),
      );
      settings.stream_segments = textToSegments(segments.value);
      settingsByAction.set(key, settings);
      dirtyActions.add(key);
    }

    mode.addEventListener("change", () => {
      markDirty();
      updateVisibility();
    });
    speed.addEventListener("input", markDirty);
    segments.addEventListener("input", markDirty);

    controls.append(
      heading,
      field(
        "Режим отправки",
        mode,
        "Потоковые режимы используют Telegram sendMessageDraft.",
      ),
      speedField,
      segmentsField,
    );

    const silentField = [...form.querySelectorAll(":scope > label.field")].find((item) => (
      item.querySelector(":scope > span")?.textContent?.trim() === "Отправить без звука"
    ));
    form.insertBefore(controls, silentField || form.querySelector(".inspector__actions"));
    updateVisibility();
  }

  window.addEventListener("load", () => {
    rememberRoadmap(readDraft());
    enhanceInspector();

    const inspector = document.querySelector("#inspector-form");
    if (inspector) {
      new MutationObserver(enhanceInspector).observe(inspector, {
        childList: true,
        subtree: true,
      });
    }

    const importInput = document.querySelector("#import-file");
    importInput?.addEventListener("change", async () => {
      const file = importInput.files?.[0];
      if (!file) return;
      try {
        rememberRoadmap(JSON.parse(await file.text()));
        setTimeout(enhanceInspector, 50);
      } catch {
        // The main importer will show the validation error.
      }
    });

    document.querySelector("#save-draft")?.addEventListener("click", patchDraft);
    window.addEventListener("beforeunload", patchDraft);
  });
})();
