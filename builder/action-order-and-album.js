(() => {
  "use strict";

  const V2_PREFIX = "album:v2:";
  const V1_PREFIX = "album:v1";
  const MIN_ITEMS = 2;
  const MAX_ITEMS = 6;
  const paletteTypes = new Map([
    ["Текст", "send_text"],
    ["Фото", "send_photo"],
    ["Видео", "send_video"],
    ["Аудио", "send_audio"],
    ["Документ", "send_document"],
    ["Воспоминание", "memory_reconstruction"],
    ["Ожидание ответа", "ask_input"],
    ["Кнопки", "buttons"],
    ["Пауза", "delay"],
    ["Переход", "goto"],
  ]);

  let redirectingDrop = false;
  let enhanceScheduled = false;
  let paletteDrag = null;

  function scheduleEnhance() {
    if (enhanceScheduled) return;
    enhanceScheduled = true;
    requestAnimationFrame(() => {
      enhanceScheduled = false;
      addAlbumPaletteButton();
      enhancePaletteDrag();
      enhanceActionCards();
      enhanceAlbumInspector();
    });
  }

  function fieldByLabel(label) {
    return [...document.querySelectorAll("#inspector-form label.field")].find((field) =>
      field.querySelector(":scope > span")?.textContent?.trim() === label
    ) || null;
  }

  function addAlbumPaletteButton() {
    const list = document.querySelector("#palette-list");
    if (!list || list.querySelector('[data-builder-action-type="send_media_group"]')) return;

    const button = document.createElement("button");
    button.type = "button";
    button.className = "palette-item";
    button.dataset.builderActionType = "send_media_group";
    button.innerHTML = `
      <span class="palette-item__icon">🗂</span>
      <span><strong>Медиагруппа</strong><small>От 2 до 6 фото или видео одним альбомом</small></span>`;
    button.addEventListener("click", createAlbumAction);

    const videoButton = [...list.querySelectorAll(".palette-item")].find((item) =>
      item.querySelector("strong")?.textContent?.trim() === "Видео"
    );
    if (videoButton) videoButton.after(button);
    else list.append(button);
  }

  function enhancePaletteDrag() {
    document.querySelectorAll("#palette-list .palette-item").forEach((button) => {
      if (!button.dataset.builderActionType) {
        const title = button.querySelector("strong")?.textContent?.trim() || "";
        const type = paletteTypes.get(title);
        if (type) button.dataset.builderActionType = type;
      }
      const type = button.dataset.builderActionType;
      if (!type || button.dataset.paletteDragEnhanced === "true") return;
      button.dataset.paletteDragEnhanced = "true";
      button.draggable = true;
      button.addEventListener("dragstart", (event) => {
        paletteDrag = { type, button };
        button.classList.add("dragging");
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData("text/plain", `roadmap-action:${type}`);
      });
      button.addEventListener("dragend", () => {
        paletteDrag = null;
        button.classList.remove("dragging");
        clearDropIndicators();
      });
    });
  }

  function createAlbumAction() {
    const photoButton = [...document.querySelectorAll("#palette-list .palette-item")].find((item) =>
      item.dataset.builderActionType === "send_photo"
      || item.querySelector("strong")?.textContent?.trim() === "Фото"
    );
    if (!photoButton) return;

    photoButton.click();
    const pathField = fieldByLabel("Путь к файлу");
    const input = pathField?.querySelector("input");
    if (!input) return;

    input.value = encodeAlbum([
      { kind: "photo", path: "media/photos/photo-1.jpg" },
      { kind: "photo", path: "media/photos/photo-2.jpg" },
    ]);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    scheduleEnhance();
  }

  function parseAlbum(value) {
    const raw = String(value || "").replaceAll("\r\n", "\n").trim();
    if (raw.startsWith(V2_PREFIX)) {
      try {
        const decoded = JSON.parse(decodeURIComponent(raw.slice(V2_PREFIX.length)));
        if (!Array.isArray(decoded)) return null;
        return decoded.map(normalizeItem).filter(Boolean);
      } catch (_) {
        return null;
      }
    }
    if (!raw.startsWith(V1_PREFIX)) return null;

    const lines = raw.split("\n").slice(1).filter(Boolean);
    if (lines.length) {
      const items = lines.map((line) => {
        const separator = line.indexOf("\t");
        if (separator < 0) return null;
        return normalizeItem({
          kind: line.slice(0, separator),
          path: line.slice(separator + 1),
        });
      });
      return items.every(Boolean) ? items : null;
    }

    const remainder = raw.slice(V1_PREFIX.length);
    const matches = [...remainder.matchAll(
      /(photo|video)\s+(media\/.+?)(?=(?:photo|video)\s+media\/|$)/gi
    )];
    const items = matches.map((match) => normalizeItem({
      kind: match[1],
      path: match[2],
    })).filter(Boolean);
    return items.length ? items : null;
  }

  function normalizeItem(item) {
    const kind = String(item?.kind || "").trim().toLowerCase();
    const path = String(item?.path || "").trim();
    if (!["photo", "video"].includes(kind) || !path) return null;
    return { kind, path };
  }

  function encodeAlbum(items) {
    const payload = JSON.stringify(items.map((item) => ({
      kind: item.kind === "video" ? "video" : "photo",
      path: String(item.path || "").trim(),
    })));
    return `${V2_PREFIX}${encodeURIComponent(payload)}`;
  }

  function albumSummary(items) {
    const photos = items.filter((item) => item.kind === "photo").length;
    const videos = items.length - photos;
    const parts = [`${items.length} элементов`];
    if (photos) parts.push(`${photos} фото`);
    if (videos) parts.push(`${videos} видео`);
    return parts.join(" · ");
  }

  function enhanceActionCards() {
    document.querySelectorAll(".action").forEach((row) => {
      addMoveButtons(row);
      const summary = row.querySelector(".action__content small");
      const raw = summary?.dataset.rawAlbumPath || summary?.textContent || "";
      const items = parseAlbum(raw);
      if (!items) return;

      summary.dataset.rawAlbumPath = raw;
      row.dataset.mediaGroup = "true";
      const title = row.querySelector(".action__content strong");
      const icon = row.querySelector(".action__icon");
      if (title) title.textContent = "Медиагруппа";
      if (icon) icon.textContent = "🗂";
      summary.textContent = albumSummary(items);
    });
  }

  function addMoveButtons(row) {
    const tools = row.querySelector(":scope > .action__tools");
    const duplicate = tools?.querySelector(".duplicate");
    if (!tools || !duplicate || tools.querySelector(".move-up")) return;

    const rows = actionRows(row.parentElement);
    const index = rows.indexOf(row);
    const up = toolButton("move-up", "↑", "Переместить выше · ⌥↑", index <= 0);
    const down = toolButton("move-down", "↓", "Переместить ниже · ⌥↓", index >= rows.length - 1);
    up.addEventListener("click", () => moveRow(row, -1));
    down.addEventListener("click", () => moveRow(row, 1));
    duplicate.before(up, down);
  }

  function toolButton(className, text, title, disabled) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `icon-button ${className}`;
    button.textContent = text;
    button.title = title;
    button.disabled = disabled;
    return button;
  }

  function actionRows(container) {
    return [...(container?.children || [])].filter((node) => node.classList?.contains("action"));
  }

  function moveRow(row, direction) {
    const container = row.parentElement;
    const rows = actionRows(container);
    const index = rows.indexOf(row);
    if (index < 0) return;

    let target;
    if (direction < 0) {
      if (index === 0) return;
      target = rows[index - 1];
    } else {
      if (index >= rows.length - 1) return;
      target = rows[index + 2] || container;
    }
    dispatchMove(row, target);
  }

  function dragEvent(type, options = {}) {
    let dataTransfer;
    try {
      dataTransfer = new DataTransfer();
    } catch (_) {
      dataTransfer = { effectAllowed: "move" };
    }
    try {
      return new DragEvent(type, {
        bubbles: true,
        cancelable: true,
        dataTransfer,
        ...options,
      });
    } catch (_) {
      const event = new Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(event, "dataTransfer", { value: dataTransfer });
      Object.defineProperty(event, "clientY", { value: options.clientY || 0 });
      return event;
    }
  }

  function dispatchMove(row, target) {
    row.dispatchEvent(dragEvent("dragstart"));
    redirectingDrop = true;
    target.dispatchEvent(dragEvent("drop"));
    redirectingDrop = false;
    row.dispatchEvent(dragEvent("dragend"));
  }

  function insertionTarget(container, clientY) {
    const rows = actionRows(container).filter((row) => !row.classList.contains("dragging"));
    return rows.find((row) => {
      const rect = row.getBoundingClientRect();
      return clientY < rect.top + rect.height / 2;
    }) || container;
  }

  function insertionIndex(container, clientY) {
    const rows = actionRows(container);
    const target = rows.find((row) => {
      const rect = row.getBoundingClientRect();
      return clientY < rect.top + rect.height / 2;
    });
    return target ? rows.indexOf(target) : rows.length;
  }

  function clearDropIndicators() {
    document.querySelectorAll(".action.drop-before").forEach((row) => {
      row.classList.remove("drop-before");
    });
    document.querySelectorAll(".step__actions.drop-at-end").forEach((container) => {
      container.classList.remove("drop-at-end");
    });
  }

  function showDropIndicator(container, clientY) {
    clearDropIndicators();
    const target = insertionTarget(container, clientY);
    if (target === container) container.classList.add("drop-at-end");
    else target.classList.add("drop-before");
  }

  document.addEventListener("dragover", (event) => {
    const container = event.target.closest?.(".step__actions");
    if (!container) return;

    if (paletteDrag) {
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "copy";
      showDropIndicator(container, event.clientY);
      return;
    }

    if (!document.querySelector(".action.dragging")) return;
    event.preventDefault();
    showDropIndicator(container, event.clientY);
  }, true);

  document.addEventListener("drop", (event) => {
    const container = event.target.closest?.(".step__actions");
    if (!container) return;

    if (paletteDrag) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const stepId = container.dataset.stepId;
      const targetIndex = insertionIndex(container, event.clientY);
      const type = paletteDrag.type;
      clearDropIndicators();
      addPaletteActionAt(type, stepId, targetIndex);
      return;
    }

    if (redirectingDrop || !document.querySelector(".action.dragging")) return;
    const target = insertionTarget(container, event.clientY);
    event.preventDefault();
    event.stopImmediatePropagation();
    clearDropIndicators();

    redirectingDrop = true;
    target.dispatchEvent(dragEvent("drop", { clientY: event.clientY }));
    redirectingDrop = false;
  }, true);

  document.addEventListener("dragend", clearDropIndicators, true);

  function addPaletteActionAt(type, stepId, targetIndex) {
    const stepHead = document.querySelector(`.step[data-step-id="${cssEscape(stepId)}"] .step__head`);
    stepHead?.click();

    const button = document.querySelector(
      `#palette-list .palette-item[data-builder-action-type="${cssEscape(type)}"]`
    );
    button?.click();

    const newRow = document.querySelector(".action.selected");
    if (!newRow) return;
    const refreshedContainer = document.querySelector(
      `.step[data-step-id="${cssEscape(stepId)}"] .step__actions`
    );
    if (!refreshedContainer) return;
    const rows = actionRows(refreshedContainer);
    const currentIndex = rows.indexOf(newRow);
    if (targetIndex >= currentIndex) return;
    dispatchMove(newRow, rows[targetIndex]);
  }

  function cssEscape(value) {
    return window.CSS?.escape ? CSS.escape(value) : String(value).replace(/["\\]/g, "\\$&");
  }

  function enhanceAlbumInspector() {
    const pathField = fieldByLabel("Путь к файлу");
    const canonicalInput = pathField?.querySelector("input");
    const items = parseAlbum(canonicalInput?.value || "");
    if (!pathField || !canonicalInput || !items || pathField.dataset.albumEnhanced === "true") return;

    pathField.dataset.albumEnhanced = "true";
    pathField.classList.add("album-field");
    const picker = canonicalInput.closest(".project-file-picker") || canonicalInput;
    picker.hidden = true;
    const note = pathField.querySelector(":scope > small");
    if (note) note.hidden = true;

    const editor = document.createElement("div");
    editor.className = "album-editor";
    const list = document.createElement("div");
    list.className = "album-editor__list";
    const footer = document.createElement("div");
    footer.className = "album-editor__footer";
    editor.append(list, footer);
    pathField.append(editor);

    function updateSelectedCard() {
      const summary = document.querySelector(".action.selected .action__content small");
      if (!summary) return;
      summary.dataset.rawAlbumPath = canonicalInput.value;
      summary.textContent = albumSummary(items);
      const row = summary.closest(".action");
      row.dataset.mediaGroup = "true";
      row.querySelector(".action__content strong").textContent = "Медиагруппа";
      row.querySelector(".action__icon").textContent = "🗂";
    }

    function sync() {
      canonicalInput.value = encodeAlbum(items);
      canonicalInput.dispatchEvent(new Event("input", { bubbles: true }));
      renderItems();
      updateSelectedCard();
    }

    function renderItems() {
      list.innerHTML = "";
      items.forEach((item, index) => {
        const row = document.createElement("div");
        row.className = "album-item";

        const select = document.createElement("select");
        select.innerHTML = '<option value="photo">Фото</option><option value="video">Видео</option>';
        select.value = item.kind;
        select.addEventListener("change", () => {
          item.kind = select.value;
          sync();
        });

        const input = document.createElement("input");
        input.value = item.path;
        input.placeholder = item.kind === "video"
          ? "media/videos/video.mp4"
          : "media/photos/photo.jpg";
        input.className = "album-item__path";
        input.dataset.mediaKind = item.kind;
        input.addEventListener("input", () => {
          item.path = input.value;
          canonicalInput.value = encodeAlbum(items);
          canonicalInput.dispatchEvent(new Event("input", { bubbles: true }));
          updateSelectedCard();
        });

        const controls = document.createElement("div");
        controls.className = "album-item__tools";
        const up = toolButton("album-up", "↑", "Поднять внутри альбома", index === 0);
        const down = toolButton(
          "album-down",
          "↓",
          "Опустить внутри альбома",
          index === items.length - 1
        );
        const remove = toolButton(
          "album-remove",
          "✕",
          "Удалить из альбома",
          items.length <= MIN_ITEMS
        );
        up.addEventListener("click", () => {
          [items[index - 1], items[index]] = [items[index], items[index - 1]];
          sync();
        });
        down.addEventListener("click", () => {
          [items[index], items[index + 1]] = [items[index + 1], items[index]];
          sync();
        });
        remove.addEventListener("click", () => {
          items.splice(index, 1);
          sync();
        });
        controls.append(up, down, remove);
        row.append(select, input, controls);
        list.append(row);
      });

      footer.innerHTML = "";
      const count = document.createElement("span");
      count.textContent = `${items.length}/${MAX_ITEMS}`;
      const addPhoto = document.createElement("button");
      addPhoto.type = "button";
      addPhoto.className = "button ghost";
      addPhoto.textContent = "＋ Фото";
      const addVideo = document.createElement("button");
      addVideo.type = "button";
      addVideo.className = "button ghost";
      addVideo.textContent = "＋ Видео";
      addPhoto.disabled = addVideo.disabled = items.length >= MAX_ITEMS;
      addPhoto.addEventListener("click", () => {
        items.push({ kind: "photo", path: "media/photos/photo.jpg" });
        sync();
      });
      addVideo.addEventListener("click", () => {
        items.push({ kind: "video", path: "media/videos/video.mp4" });
        sync();
      });
      footer.append(addPhoto, addVideo, count);
    }

    // Immediately migrate any legacy one-line or multiline value to v2.
    sync();
  }

  function albumErrors() {
    const errors = [];
    document.querySelectorAll(".action").forEach((row) => {
      const summary = row.querySelector(".action__content small");
      const raw = summary?.dataset.rawAlbumPath || summary?.textContent || "";
      const items = parseAlbum(raw);
      if (!items) return;
      if (items.length < MIN_ITEMS || items.length > MAX_ITEMS) {
        errors.push("Медиагруппа должна содержать от 2 до 6 элементов.");
      }
      items.forEach((item, index) => {
        if (!isSafePath(item.path)) {
          errors.push(`Медиагруппа, элемент ${index + 1}: некорректный путь.`);
        }
      });
    });
    return errors;
  }

  function isSafePath(path) {
    const normalized = String(path || "").replaceAll("\\", "/").trim();
    return Boolean(normalized)
      && !normalized.startsWith("/")
      && !normalized.startsWith("~")
      && !normalized.split("/").includes("..");
  }

  function showAlbumErrors(errors) {
    const status = document.querySelector("#status");
    if (!status) return;
    status.hidden = false;
    status.className = "status error";
    status.textContent = [...new Set(errors)].join("\n");
    status.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#validate, #export")) return;
    const errors = albumErrors();
    if (!errors.length) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    showAlbumErrors(errors);
  }, true);

  window.addEventListener("keydown", (event) => {
    if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;
    const target = event.target;
    if (target?.matches?.("input, textarea, select, [contenteditable='true']")) return;
    const row = document.querySelector(".action.selected");
    if (!row) return;
    const button = row.querySelector(event.key === "ArrowUp" ? ".move-up" : ".move-down");
    if (!button || button.disabled) return;
    event.preventDefault();
    button.click();
  });

  const observer = new MutationObserver(scheduleEnhance);
  observer.observe(document.body, { childList: true, subtree: true });
  scheduleEnhance();
})();
