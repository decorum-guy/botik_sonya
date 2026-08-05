(() => {
  "use strict";

  const DRAFT_KEY = "botik-sonya-roadmap-v1";
  const COLLAPSED_KEY = "botik-sonya-collapsed-steps-v1";
  const V2_PREFIX = "album:v2:";
  const V1_PREFIX = "album:v1";
  const MIN_ITEMS = 2;
  const MAX_ITEMS = 6;
  const ACTION_TYPES = new Map([
    ["Текст", "send_text"],
    ["Фото", "send_photo"],
    ["Видео", "send_video"],
    ["Медиагруппа", "send_media_group"],
    ["Аудио", "send_audio"],
    ["Документ", "send_document"],
    ["Воспоминание", "memory_reconstruction"],
    ["Ожидание ответа", "ask_input"],
    ["Кнопки", "buttons"],
    ["Пауза", "delay"],
    ["Переход", "goto"],
  ]);

  let enhanceScheduled = false;
  let paletteDrag = null;
  let projectRootHandle = null;
  let stickyFrame = 0;
  const collapsedSteps = loadCollapsedSteps();

  function loadCollapsedSteps() {
    try {
      const value = JSON.parse(localStorage.getItem(COLLAPSED_KEY) || "[]");
      return new Set(Array.isArray(value) ? value : []);
    } catch (_) {
      return new Set();
    }
  }

  function saveCollapsedSteps() {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsedSteps]));
  }

  function scheduleEnhance() {
    if (enhanceScheduled) return;
    enhanceScheduled = true;
    requestAnimationFrame(() => {
      enhanceScheduled = false;
      ensureMediaGroupButton();
      enhancePaletteDrag();
      enhanceMediaGroupCards();
      enhanceMediaGroupInspector();
      enhanceStepCollapse();
      scheduleStickyOffset();
    });
  }

  function parseMediaGroup(value) {
    const text = String(value || "").replaceAll("\r\n", "\n").trim();
    if (text.startsWith(V2_PREFIX)) {
      try {
        return normalizeItems(JSON.parse(decodeURIComponent(text.slice(V2_PREFIX.length))));
      } catch (_) {
        return null;
      }
    }

    if (text === V1_PREFIX || text.startsWith(`${V1_PREFIX}\n`)) {
      const items = text.split("\n").slice(1).filter(Boolean).map((line) => {
        const separator = line.indexOf("\t");
        if (separator < 0) return null;
        return {
          kind: line.slice(0, separator).trim(),
          path: line.slice(separator + 1).trim(),
        };
      }).filter(Boolean);
      return normalizeItems(items);
    }

    if (text.startsWith(V1_PREFIX)) {
      const compacted = text.slice(V1_PREFIX.length).trim();
      const pattern = /(photo|video)\s+(media\/.+?)(?=(?:photo|video)\s+media\/|$)/gi;
      const items = [...compacted.matchAll(pattern)].map((match) => ({
        kind: match[1].toLowerCase(),
        path: match[2].trim(),
      }));
      return normalizeItems(items);
    }
    return null;
  }

  function normalizeItems(value) {
    if (!Array.isArray(value)) return null;
    const items = value.map((item) => ({
      kind: item?.kind === "video" ? "video" : "photo",
      path: String(item?.path || "").trim(),
    }));
    return items.length ? items : null;
  }

  function encodeMediaGroup(items) {
    return `${V2_PREFIX}${encodeURIComponent(JSON.stringify(items.map((item) => ({
      kind: item.kind === "video" ? "video" : "photo",
      path: String(item.path || "").trim(),
    }))))}`;
  }

  function mediaGroupSummary(items) {
    const photos = items.filter((item) => item.kind === "photo").length;
    const videos = items.length - photos;
    const parts = [`${items.length} элементов`];
    if (photos) parts.push(`${photos} фото`);
    if (videos) parts.push(`${videos} видео`);
    return parts.join(" · ");
  }

  function fieldByLabel(label) {
    return [...document.querySelectorAll("#inspector-form label.field")].find((field) =>
      field.querySelector(":scope > span")?.textContent?.trim() === label
    ) || null;
  }

  function ensureMediaGroupButton() {
    const list = document.querySelector("#palette-list");
    if (!list) return null;
    let button = list.querySelector('[data-action-type="send-media-group"]');
    if (button) return button;

    button = document.createElement("button");
    button.type = "button";
    button.className = "palette-item";
    button.dataset.actionType = "send-media-group";
    button.innerHTML = `
      <span class="palette-item__icon">🗂</span>
      <span><strong>Медиагруппа</strong><small>От 2 до 6 фото или видео одним альбомом</small></span>`;
    const video = [...list.querySelectorAll(".palette-item")].find((item) =>
      item.querySelector("strong")?.textContent?.trim() === "Видео"
    );
    if (video) video.after(button);
    else list.append(button);
    return button;
  }

  function createMediaGroupAction() {
    const photoButton = [...document.querySelectorAll("#palette-list .palette-item")].find((item) =>
      item.querySelector("strong")?.textContent?.trim() === "Фото"
    );
    if (!photoButton) return;

    photoButton.click();
    const pathField = fieldByLabel("Путь к файлу");
    const input = pathField?.querySelector("input");
    if (!input) return;

    input.value = encodeMediaGroup([
      { kind: "photo", path: "media/photos/photo-1.jpg" },
      { kind: "photo", path: "media/photos/photo-2.jpg" },
    ]);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    scheduleEnhance();
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest?.('[data-action-type="send-media-group"]');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    createMediaGroupAction();
  }, true);

  function enhanceMediaGroupCards() {
    document.querySelectorAll(".action").forEach((row) => {
      const summary = row.querySelector(".action__content small");
      if (!summary) return;
      const raw = summary.dataset.rawAlbumPath || summary.textContent;
      const items = parseMediaGroup(raw);
      if (!items) return;

      const canonical = encodeMediaGroup(items);
      row.dataset.mediaGroup = "true";
      summary.dataset.rawAlbumPath = canonical;
      const title = row.querySelector(".action__content strong");
      const icon = row.querySelector(".action__icon");
      if (title) title.textContent = "Медиагруппа";
      if (icon) icon.textContent = "🗂";
      summary.textContent = mediaGroupSummary(items);
    });
  }

  function enhanceMediaGroupInspector() {
    const pathField = fieldByLabel("Путь к файлу");
    const canonicalInput = pathField?.querySelector("input");
    const items = parseMediaGroup(canonicalInput?.value || "");
    if (!pathField || !canonicalInput || !items) return;

    const canonical = encodeMediaGroup(items);
    if (canonicalInput.value !== canonical) {
      canonicalInput.value = canonical;
      canonicalInput.dispatchEvent(new Event("input", { bubbles: true }));
    }
    if (pathField.dataset.mediaGroupV2Enhanced === "true") return;

    pathField.dataset.mediaGroupV2Enhanced = "true";
    pathField.classList.add("album-field", "album-field-v2");
    const originalPicker = canonicalInput.closest(".project-file-picker") || canonicalInput;
    originalPicker.hidden = true;
    const note = pathField.querySelector(":scope > small");
    if (note) note.hidden = true;

    const editor = document.createElement("div");
    editor.className = "album-editor album-editor-v2";
    const list = document.createElement("div");
    list.className = "album-editor__list";
    const footer = document.createElement("div");
    footer.className = "album-editor__footer";
    editor.append(list, footer);
    pathField.append(editor);

    function sync({ rebuild = false } = {}) {
      const value = encodeMediaGroup(items);
      canonicalInput.value = value;
      canonicalInput.dispatchEvent(new Event("input", { bubbles: true }));
      const selected = document.querySelector(".action.selected");
      const summary = selected?.querySelector(".action__content small");
      if (selected && summary) {
        selected.dataset.mediaGroup = "true";
        summary.dataset.rawAlbumPath = value;
        summary.textContent = mediaGroupSummary(items);
        const title = selected.querySelector(".action__content strong");
        const icon = selected.querySelector(".action__icon");
        if (title) title.textContent = "Медиагруппа";
        if (icon) icon.textContent = "🗂";
      }
      if (rebuild) renderItems();
    }

    function renderItems() {
      list.innerHTML = "";
      items.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "album-item album-item-v2";

        const select = document.createElement("select");
        select.innerHTML = '<option value="photo">Фото</option><option value="video">Видео</option>';
        select.value = item.kind;
        select.addEventListener("change", () => {
          item.kind = select.value;
          sync({ rebuild: true });
        });

        const pathWrap = document.createElement("div");
        pathWrap.className = "album-item__path";
        const input = document.createElement("input");
        input.value = item.path;
        input.placeholder = item.kind === "video" ? "media/videos/video.mp4" : "media/photos/photo.jpg";
        input.addEventListener("input", () => {
          item.path = input.value;
          sync();
        });
        const browse = document.createElement("button");
        browse.type = "button";
        browse.className = "icon-button album-browse";
        browse.textContent = "📁";
        browse.title = "Выбрать файл из проекта";
        browse.addEventListener("click", async () => {
          const chosen = await chooseProjectMedia(item.kind);
          if (!chosen) return;
          item.path = chosen;
          input.value = chosen;
          sync();
        });
        pathWrap.append(input, browse);

        const controls = document.createElement("div");
        controls.className = "album-item__tools";
        const up = smallTool("↑", "Поднять внутри альбома", index === 0);
        const down = smallTool("↓", "Опустить внутри альбома", index === items.length - 1);
        const remove = smallTool("✕", "Удалить из альбома", items.length <= MIN_ITEMS);
        up.addEventListener("click", () => {
          [items[index - 1], items[index]] = [items[index], items[index - 1]];
          sync({ rebuild: true });
        });
        down.addEventListener("click", () => {
          [items[index], items[index + 1]] = [items[index + 1], items[index]];
          sync({ rebuild: true });
        });
        remove.addEventListener("click", () => {
          items.splice(index, 1);
          sync({ rebuild: true });
        });
        controls.append(up, down, remove);
        row.append(select, pathWrap, controls);
        list.append(row);
      });

      footer.innerHTML = "";
      const addPhoto = footerButton("＋ Фото", () => {
        items.push({ kind: "photo", path: "media/photos/photo.jpg" });
        sync({ rebuild: true });
      });
      const addVideo = footerButton("＋ Видео", () => {
        items.push({ kind: "video", path: "media/videos/video.mp4" });
        sync({ rebuild: true });
      });
      addPhoto.disabled = addVideo.disabled = items.length >= MAX_ITEMS;
      const count = document.createElement("span");
      count.textContent = `${items.length}/${MAX_ITEMS}`;
      footer.append(addPhoto, addVideo, count);
    }

    renderItems();
  }

  function smallTool(text, title, disabled) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button";
    button.textContent = text;
    button.title = title;
    button.disabled = disabled;
    return button;
  }

  function footerButton(text, handler) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button ghost";
    button.textContent = text;
    button.addEventListener("click", handler);
    return button;
  }

  async function chooseProjectMedia(kind) {
    if (!("showDirectoryPicker" in window) || !("showOpenFilePicker" in window)) {
      window.alert("Выбор файлов поддерживается в Chromium / Яндекс Браузере.");
      return null;
    }
    try {
      if (!projectRootHandle) {
        projectRootHandle = await window.showDirectoryPicker({ id: "botik-sonya-root-v2", mode: "read" });
        await verifyProjectRoot(projectRootHandle);
      }
      const types = kind === "video"
        ? [{ description: "Видео", accept: { "video/*": [".mp4", ".mov", ".m4v", ".webm"] } }]
        : [{ description: "Изображения", accept: { "image/*": [".jpg", ".jpeg", ".png", ".webp", ".heic", ".HEIC"] } }];
      let handles;
      try {
        handles = await window.showOpenFilePicker({
          id: `botik-sonya-album-${kind}`,
          multiple: false,
          startIn: projectRootHandle,
          types,
        });
      } catch (error) {
        if (!(error instanceof TypeError)) throw error;
        handles = await window.showOpenFilePicker({
          id: `botik-sonya-album-${kind}`,
          multiple: false,
          types,
        });
      }
      const parts = await projectRootHandle.resolve(handles[0]);
      if (!parts) throw new Error("Файл находится вне выбранной папки проекта.");
      return parts.join("/");
    } catch (error) {
      if (error?.name === "AbortError") return null;
      window.alert(error?.message || "Не удалось выбрать файл.");
      return null;
    }
  }

  async function verifyProjectRoot(handle) {
    for (const name of ["app", "builder", "roadmap"]) await handle.getDirectoryHandle(name);
    await handle.getFileHandle("requirements.txt");
  }

  function enhancePaletteDrag() {
    document.querySelectorAll("#palette-list .palette-item").forEach((item) => {
      const title = item.querySelector("strong")?.textContent?.trim() || "";
      const type = item.dataset.actionType || ACTION_TYPES.get(title);
      if (!type || item.dataset.paletteDragEnhanced === "true") return;
      item.dataset.paletteDragEnhanced = "true";
      item.dataset.actionType = type;
      item.draggable = true;
      item.title = `${item.title ? `${item.title} · ` : ""}Перетащи в нужное место этапа`;
      item.addEventListener("dragstart", (event) => {
        paletteDrag = { button: item, type };
        item.classList.add("palette-dragging");
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData("text/plain", type);
      });
      item.addEventListener("dragend", () => {
        item.classList.remove("palette-dragging");
        paletteDrag = null;
        clearPaletteDropIndicators();
      });
    });
  }

  function actionRows(container) {
    return [...(container?.children || [])].filter((node) => node.classList?.contains("action"));
  }

  function dropContainer(target) {
    return target.closest?.(".step__actions") || target.closest?.(".step")?.querySelector(".step__actions") || null;
  }

  function insertionIndex(container, clientY) {
    const rows = actionRows(container);
    const index = rows.findIndex((row) => {
      const rect = row.getBoundingClientRect();
      return clientY < rect.top + rect.height / 2;
    });
    return index < 0 ? rows.length : index;
  }

  function showPaletteDropIndicator(container, index) {
    clearPaletteDropIndicators();
    const rows = actionRows(container);
    if (index >= rows.length) container.classList.add("palette-drop-at-end");
    else rows[index].classList.add("palette-drop-before");
  }

  function clearPaletteDropIndicators() {
    document.querySelectorAll(".palette-drop-before").forEach((node) => node.classList.remove("palette-drop-before"));
    document.querySelectorAll(".palette-drop-at-end").forEach((node) => node.classList.remove("palette-drop-at-end"));
  }

  document.addEventListener("dragover", (event) => {
    if (!paletteDrag) return;
    const container = dropContainer(event.target);
    if (!container) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    showPaletteDropIndicator(container, insertionIndex(container, event.clientY));
  }, true);

  document.addEventListener("drop", (event) => {
    if (!paletteDrag) return;
    const container = dropContainer(event.target);
    if (!container) return;
    event.preventDefault();
    event.stopImmediatePropagation();

    const stepId = container.closest(".step")?.dataset.stepId;
    const desiredIndex = insertionIndex(container, event.clientY);
    const sourceButton = paletteDrag.button;
    paletteDrag = null;
    sourceButton.classList.remove("palette-dragging");
    clearPaletteDropIndicators();
    if (!stepId) return;

    collapsedSteps.delete(stepId);
    saveCollapsedSteps();
    const currentStep = [...document.querySelectorAll(".step")].find((step) => step.dataset.stepId === stepId);
    currentStep?.querySelector(".step__head")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    sourceButton.click();

    requestAnimationFrame(() => moveNewActionToIndex(stepId, desiredIndex));
  }, true);

  function moveNewActionToIndex(stepId, desiredIndex) {
    const step = [...document.querySelectorAll(".step")].find((node) => node.dataset.stepId === stepId);
    if (!step) return;
    const rows = actionRows(step.querySelector(".step__actions"));
    const newRow = step.querySelector(".action.selected") || rows.at(-1);
    if (!newRow || desiredIndex >= rows.length - 1) return;
    const target = rows[desiredIndex];
    if (!target || target === newRow) return;

    let transfer;
    try { transfer = new DataTransfer(); } catch (_) { transfer = { effectAllowed: "move" }; }
    const rect = target.getBoundingClientRect();
    newRow.dispatchEvent(makeDragEvent("dragstart", transfer, rect.top + 1));
    target.dispatchEvent(makeDragEvent("drop", transfer, rect.top + 1));
    newRow.dispatchEvent(makeDragEvent("dragend", transfer, rect.top + 1));
  }

  function makeDragEvent(type, transfer, clientY) {
    try {
      return new DragEvent(type, {
        bubbles: true,
        cancelable: true,
        dataTransfer: transfer,
        clientY,
      });
    } catch (_) {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(event, "dataTransfer", { value: transfer });
      Object.defineProperty(event, "clientY", { value: clientY });
      return event;
    }
  }

  function enhanceStepCollapse() {
    document.querySelectorAll(".step").forEach((step) => {
      const stepId = step.dataset.stepId;
      if (!stepId) return;
      const tools = step.querySelector(".step__head .action__tools");
      const duplicate = tools?.querySelector(".duplicate");
      if (!tools || !duplicate) return;

      let toggle = tools.querySelector(".collapse-step");
      if (!toggle) {
        toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = "icon-button collapse-step";
        toggle.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (collapsedSteps.has(stepId)) collapsedSteps.delete(stepId);
          else collapsedSteps.add(stepId);
          saveCollapsedSteps();
          applyCollapsedState(step, toggle, stepId);
        });
        duplicate.before(toggle);
      }
      applyCollapsedState(step, toggle, stepId);
    });
  }

  function applyCollapsedState(step, toggle, stepId) {
    const collapsed = collapsedSteps.has(stepId);
    step.classList.toggle("collapsed", collapsed);
    toggle.textContent = collapsed ? "▸" : "▾";
    toggle.title = collapsed ? "Развернуть этап" : "Свернуть этап";
    toggle.setAttribute("aria-expanded", String(!collapsed));
  }

  function scheduleStickyOffset() {
    if (stickyFrame) return;
    stickyFrame = requestAnimationFrame(() => {
      stickyFrame = 0;
      const runner = document.querySelector(".test-runner");
      const topbar = document.querySelector(".topbar");
      const anchor = runner || topbar;
      const bottom = anchor?.getBoundingClientRect().bottom || 64;
      document.documentElement.style.setProperty("--builder-side-top", `${Math.max(14, Math.ceil(bottom + 14))}px`);
    });
  }

  function migrateStoredDraft() {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return false;
    try {
      const draft = JSON.parse(raw);
      let changed = false;
      for (const step of draft.steps || []) {
        for (const action of step.actions || []) {
          if (action.type !== "send_photo") continue;
          const items = parseMediaGroup(action.path);
          if (!items) continue;
          const encoded = encodeMediaGroup(items);
          if (action.path !== encoded) {
            action.path = encoded;
            changed = true;
          }
        }
      }
      if (!changed) return false;
      const migrated = JSON.stringify(draft);
      localStorage.setItem(DRAFT_KEY, migrated);
      window.addEventListener("beforeunload", () => localStorage.setItem(DRAFT_KEY, migrated));
      location.reload();
      return true;
    } catch (_) {
      return false;
    }
  }

  if (migrateStoredDraft()) return;

  const observer = new MutationObserver(scheduleEnhance);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener("resize", scheduleStickyOffset);
  window.addEventListener("scroll", scheduleStickyOffset, { passive: true });
  scheduleEnhance();
})();
