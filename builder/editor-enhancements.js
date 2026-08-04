(() => {
  "use strict";

  const form = document.querySelector("#inspector-form");
  if (!form) return;

  let projectRootHandle = null;
  let enhanceScheduled = false;

  const htmlFormats = [
    ["bold", "B", "Жирный", "<b>", "</b>", "текст"],
    ["italic", "I", "Курсив", "<i>", "</i>", "текст"],
    ["underline", "U", "Подчёркнутый", "<u>", "</u>", "текст"],
    ["strike", "S", "Зачёркнутый", "<s>", "</s>", "текст"],
    ["spoiler", "◧", "Спойлер", "<tg-spoiler>", "</tg-spoiler>", "скрытый текст"],
    ["code", "</>", "Код", "<code>", "</code>", "код"],
    ["pre", "¶", "Блок кода", "<pre>", "</pre>", "код"],
  ];

  const markdownFormats = [
    ["bold", "B", "Жирный", "*", "*", "текст"],
    ["italic", "I", "Курсив", "_", "_", "текст"],
    ["underline", "U", "Подчёркнутый", "__", "__", "текст"],
    ["strike", "S", "Зачёркнутый", "~", "~", "текст"],
    ["spoiler", "◧", "Спойлер", "||", "||", "скрытый текст"],
    ["code", "</>", "Код", "`", "`", "код"],
    ["pre", "¶", "Блок кода", "```\n", "\n```", "код"],
  ];

  function fieldByLabel(label) {
    return [...form.querySelectorAll("label.field")].find((field) =>
      field.querySelector(":scope > span")?.textContent?.trim() === label
    ) || null;
  }

  function inspectorTitle() {
    return form.querySelector(".panel__head h2")?.textContent?.trim() || "";
  }

  function scheduleEnhance() {
    if (enhanceScheduled) return;
    enhanceScheduled = true;
    requestAnimationFrame(() => {
      enhanceScheduled = false;
      enhanceInspector();
    });
  }

  function enhanceInspector() {
    enhanceRichTextEditor();
    enhanceMediaPathPicker();
    addMemoryHelp();
    addVersionHelp();
  }

  function enhanceRichTextEditor() {
    const parseField = fieldByLabel("Разметка");
    const parseSelect = parseField?.querySelector("select");
    if (!parseField || !parseSelect) return;

    let textField = parseField.previousElementSibling;
    while (textField && !(textField.matches?.("label.field") && textField.querySelector("textarea"))) {
      textField = textField.previousElementSibling;
    }
    const textarea = textField?.querySelector("textarea");
    if (!textarea || textField.dataset.richTextEnhanced === "true") return;

    textField.dataset.richTextEnhanced = "true";
    const mode = parseSelect.value;
    const toolbar = document.createElement("div");
    toolbar.className = "format-toolbar";
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", `Форматирование ${mode}`);

    if (mode === "none") {
      toolbar.innerHTML = '<span class="format-toolbar__empty">Форматирование отключено: текст будет отправлен без парсинга.</span>';
    } else {
      const formats = mode === "MarkdownV2" ? markdownFormats : htmlFormats;
      formats.forEach(([kind, caption, title, prefix, suffix, placeholder]) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `format-button format-button--${kind}`;
        button.textContent = caption;
        button.title = title;
        button.addEventListener("mousedown", (event) => event.preventDefault());
        button.addEventListener("click", () => wrapSelection(textarea, prefix, suffix, placeholder));
        toolbar.append(button);
      });

      const linkButton = document.createElement("button");
      linkButton.type = "button";
      linkButton.className = "format-button format-button--link";
      linkButton.textContent = "🔗";
      linkButton.title = "Ссылка";
      linkButton.addEventListener("mousedown", (event) => event.preventDefault());
      linkButton.addEventListener("click", () => insertLink(textarea, mode));
      toolbar.append(linkButton);

      if (mode === "MarkdownV2") {
        const escapeButton = document.createElement("button");
        escapeButton.type = "button";
        escapeButton.className = "format-button format-button--escape";
        escapeButton.textContent = "\\";
        escapeButton.title = "Экранировать спецсимволы MarkdownV2";
        escapeButton.addEventListener("mousedown", (event) => event.preventDefault());
        escapeButton.addEventListener("click", () => escapeMarkdownSelection(textarea));
        toolbar.append(escapeButton);
      }
    }

    const textareaNode = textField.querySelector("textarea");
    textField.insertBefore(toolbar, textareaNode);
    textField.append(buildCheatSheet(mode));
  }

  function wrapSelection(textarea, prefix, suffix, placeholder) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    const selected = textarea.value.slice(start, end) || placeholder;
    textarea.setRangeText(`${prefix}${selected}${suffix}`, start, end, "end");
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function insertLink(textarea, mode) {
    const url = window.prompt("Вставь адрес ссылки, например https://example.com");
    if (!url) return;
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    const selected = textarea.value.slice(start, end) || "текст ссылки";
    const replacement = mode === "MarkdownV2"
      ? `[${selected}](${url.replaceAll(")", "\\)")})`
      : `<a href="${escapeHtmlAttribute(url)}">${selected}</a>`;
    textarea.setRangeText(replacement, start, end, "end");
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function escapeMarkdownSelection(textarea) {
    const start = textarea.selectionStart ?? 0;
    const end = textarea.selectionEnd ?? textarea.value.length;
    const selected = textarea.value.slice(start, end);
    if (!selected) return;
    const escaped = selected.replace(/([_\*\[\]()~`>#+\-=|{}.!\\])/g, "\\$1");
    textarea.setRangeText(escaped, start, end, "select");
    textarea.focus();
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function buildCheatSheet(mode) {
    const details = document.createElement("details");
    details.className = "format-cheatsheet";
    if (mode === "none") {
      details.innerHTML = "<summary>Что значит «Без парсинга»</summary><p>Telegram покажет все символы буквально. Теги и Markdown-команды работать не будут.</p>";
      return details;
    }
    if (mode === "MarkdownV2") {
      details.innerHTML = `
        <summary>Шпаргалка MarkdownV2</summary>
        <div class="format-cheatsheet__grid">
          <code>*жирный*</code><span><b>жирный</b></span>
          <code>_курсив_</code><span><i>курсив</i></span>
          <code>__подчёркнутый__</code><span><u>подчёркнутый</u></span>
          <code>~зачёркнутый~</code><span><s>зачёркнутый</s></span>
          <code>||спойлер||</code><span>скрытый текст</span>
          <code>[ссылка](https://...)</code><span>ссылка</span>
          <code>\\. \\- \\( \\)</code><span>спецсимволы надо экранировать</span>
        </div>
        <p>Кнопка <b>\\</b> экранирует спецсимволы в выделенном тексте.</p>`;
      return details;
    }
    details.innerHTML = `
      <summary>Шпаргалка HTML</summary>
      <div class="format-cheatsheet__grid">
        <code>&lt;b&gt;жирный&lt;/b&gt;</code><span><b>жирный</b></span>
        <code>&lt;i&gt;курсив&lt;/i&gt;</code><span><i>курсив</i></span>
        <code>&lt;u&gt;подчёркнутый&lt;/u&gt;</code><span><u>подчёркнутый</u></span>
        <code>&lt;s&gt;зачёркнутый&lt;/s&gt;</code><span><s>зачёркнутый</s></span>
        <code>&lt;tg-spoiler&gt;текст&lt;/tg-spoiler&gt;</code><span>спойлер</span>
        <code>&lt;a href="https://..."&gt;ссылка&lt;/a&gt;</code><span>ссылка</span>
        <code>&lt;code&gt;код&lt;/code&gt;</code><span>код</span>
      </div>`;
    return details;
  }

  function enhanceMediaPathPicker() {
    const pathField = fieldByLabel("Путь к файлу");
    const input = pathField?.querySelector("input");
    if (!pathField || !input || pathField.dataset.filePickerEnhanced === "true") return;
    pathField.dataset.filePickerEnhanced = "true";

    const row = document.createElement("div");
    row.className = "project-file-picker";
    input.before(row);
    row.append(input);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "button ghost project-file-picker__button";
    button.textContent = "📁 Выбрать файл";
    button.addEventListener("click", () => chooseProjectFile(input, pathField));
    row.append(button);
  }

  async function chooseProjectFile(input, pathField) {
    clearInlineNotice(pathField);
    if (!("showDirectoryPicker" in window) || !("showOpenFilePicker" in window)) {
      showInlineNotice(pathField, "Этот браузер не даёт безопасно проверить путь. Открой конструктор в Chromium / Яндекс Браузере.", false);
      return;
    }

    try {
      if (!projectRootHandle) {
        projectRootHandle = await window.showDirectoryPicker({ id: "botik-sonya-root", mode: "read" });
        await verifyProjectRoot(projectRootHandle);
      }

      const pickerOptions = {
        id: "botik-sonya-media",
        multiple: false,
        startIn: projectRootHandle,
        types: mediaPickerTypes(inspectorTitle()),
      };
      let handles;
      try {
        handles = await window.showOpenFilePicker(pickerOptions);
      } catch (error) {
        if (error instanceof TypeError) {
          delete pickerOptions.startIn;
          handles = await window.showOpenFilePicker(pickerOptions);
        } else {
          throw error;
        }
      }

      const fileHandle = handles[0];
      const relativeParts = await projectRootHandle.resolve(fileHandle);
      if (!relativeParts) {
        throw new Error("Выбранный файл находится вне выбранной папки botik_sonya.");
      }

      const relativePath = relativeParts.join("/");
      input.value = relativePath;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (error) {
      if (error?.name === "AbortError") return;
      if (String(error?.message || "").includes("не похожа на корень проекта")) {
        projectRootHandle = null;
      }
      showInlineNotice(pathField, error?.message || "Не удалось выбрать файл.", false);
    }
  }

  async function verifyProjectRoot(handle) {
    const requiredDirectories = ["app", "builder", "roadmap"];
    try {
      for (const name of requiredDirectories) await handle.getDirectoryHandle(name);
      await handle.getFileHandle("requirements.txt");
    } catch {
      throw new Error("Выбранная папка не похожа на корень проекта botik_sonya. Выбери /Users/aartemida/Documents/botik_sonya.");
    }
  }

  function mediaPickerTypes(title) {
    if (title.includes("Фото")) return [{ description: "Изображения", accept: { "image/*": [".jpg", ".jpeg", ".png", ".webp", ".gif"] } }];
    if (title.includes("Видео")) return [{ description: "Видео", accept: { "video/*": [".mp4", ".mov", ".m4v", ".webm"] } }];
    if (title.includes("Аудио")) return [{ description: "Аудио", accept: { "audio/*": [".mp3", ".m4a", ".ogg", ".wav", ".flac"] } }];
    return [{ description: "Документы", accept: { "application/octet-stream": [".pdf", ".zip", ".txt", ".docx", ".xlsx", ".pptx"] } }];
  }

  function addMemoryHelp() {
    if (!inspectorTitle().includes("Воспоминание") || form.querySelector("#memory-number-help")) return;
    const numberField = fieldByLabel("Номер");
    const totalField = fieldByLabel("Всего");
    const grid = numberField?.parentElement;
    if (!numberField || !totalField || !grid?.classList.contains("inline-fields")) return;

    const help = document.createElement("div");
    help.id = "memory-number-help";
    help.className = "inspector-help";
    help.innerHTML = `
      <strong>Что такое «Номер» и «Всего»</strong>
      <p><b>Номер</b> — позиция этого воспоминания в серии, <b>Всего</b> — общее количество воспоминаний. Например, 1 и 5.</p>
      <p>Это только подпись в сообщении и на порядок квеста не влияет. Бот автоматически выведет заголовок как <code>ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ 1/5</code>. Само <code>1/5</code> в поле «Заголовок» писать не нужно.</p>`;
    grid.after(help);
  }

  function addVersionHelp() {
    if (inspectorTitle() !== "Настройки проекта" || form.querySelector("#format-version-help")) return;
    const versionField = fieldByLabel("Версия формата");
    if (!versionField) return;
    const help = document.createElement("div");
    help.id = "format-version-help";
    help.className = "inspector-help";
    help.innerHTML = `
      <strong>Версия формата</strong>
      <p>Это служебная версия структуры файла <code>quest.json</code>, а не версия самого квеста. Сейчас движок использует формат <b>1</b>, поэтому оставляй значение <b>1</b>.</p>`;
    versionField.after(help);
  }

  function showInlineNotice(field, text, ok) {
    clearInlineNotice(field);
    const notice = document.createElement("div");
    notice.className = `inline-notice ${ok ? "ok" : "error"}`;
    notice.textContent = text;
    field.append(notice);
  }

  function clearInlineNotice(field) {
    field.querySelector(".inline-notice")?.remove();
  }

  function escapeHtmlAttribute(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll('"', "&quot;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }

  const observer = new MutationObserver(scheduleEnhance);
  observer.observe(form, { childList: true, subtree: true });
  scheduleEnhance();
})();
