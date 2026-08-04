(() => {
  "use strict";

  const palette = [
    ["send_text", "💬", "Текст", "Обычное сюжетное сообщение"],
    ["send_photo", "🖼", "Фото", "Путь к фото внутри репозитория"],
    ["send_video", "🎬", "Видео", "Путь к видео внутри репозитория"],
    ["send_audio", "🎙", "Аудио", "Голосовое или аудиофайл"],
    ["send_document", "📎", "Документ", "Файл или флешка-подсказка"],
    ["memory_reconstruction", "🧠", "Воспоминание", "Проиграть сохранённую переписку"],
    ["ask_input", "⌨️", "Ожидание ответа", "Проверить текст, число или дату"],
    ["buttons", "🔘", "Кнопки", "Inline-кнопки и переходы"],
    ["delay", "⏳", "Пауза", "Задержка между сообщениями"],
    ["goto", "↪", "Переход", "Перейти к другому этапу"],
  ];

  const actionMeta = Object.fromEntries(palette.map(([type, icon, title]) => [type, { icon, title }]));
  const $ = (selector) => document.querySelector(selector);
  const stepsEl = $("#steps");
  const formEl = $("#inspector-form");
  const statusEl = $("#status");
  const draftKey = "botik-sonya-roadmap-v1";

  let roadmap = loadInitial();
  let selected = { kind: "meta" };
  let dragged = null;

  function sampleRoadmap() {
    return {
      meta: {
        version: 1,
        title: "Квест для Сони",
        entry_step_id: "intro",
        intro_step_id: "intro",
      },
      steps: [
        {
          id: "intro",
          title: "Неожиданное интро",
          notes: "Этот этап бот отправит через пять минут после /start_quest.",
          actions: [
            {
              type: "send_text",
              text: "<b>Соединение восстановлено.</b>\n\nПохоже, у меня осталось для тебя одно незавершённое дело.",
              parse_mode: "HTML",
              disable_notification: false,
            },
            { type: "delay", seconds: 1.2 },
            {
              type: "ask_input",
              prompt: "Для начала введи число, которое ты найдёшь в первой подсказке.",
              parse_mode: "HTML",
              validator: {
                type: "integer_equal",
                values: [],
                pattern: "",
                number: 23,
                minimum: null,
                maximum: null,
                date: "",
                case_sensitive: false,
                trim: true,
                replace_yo: true,
                remove_punctuation: true,
              },
              wrong_answers: ["Нет, это не то число.", "Посмотри на подсказку внимательнее."],
              success_text: "Совпадение найдено.",
              next_step: "memory-1",
            },
          ],
        },
        {
          id: "memory-1",
          title: "Первое восстановление",
          notes: "ID должен совпадать с /memory_new first_chat.",
          actions: [
            {
              type: "memory_reconstruction",
              memory_id: "first_chat",
              number: 1,
              total: 1,
              date_text: "Дата будет указана позже",
              title: "ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ",
              intro: "Найден сохранившийся фрагмент переписки.",
              outro: "Некоторые сообщения помнят больше, чем кажется.",
              message_delay_seconds: 0.65,
            },
            {
              type: "buttons",
              text: "Продолжим?",
              parse_mode: "HTML",
              columns: 1,
              buttons: [
                { text: "Продолжить", id: "continue_1", style: "success", next_step: "finish", answer_text: "" },
              ],
            },
          ],
        },
        {
          id: "finish",
          title: "Тестовый финал",
          notes: "Позже здесь будет следующий кусок квеста.",
          actions: [
            { type: "send_text", text: "Тестовый ROADMAP завершён.", parse_mode: "HTML", disable_notification: false },
          ],
        },
      ],
    };
  }

  function loadInitial() {
    const saved = localStorage.getItem(draftKey);
    if (saved) {
      try { return JSON.parse(saved); } catch (_) { /* ignored */ }
    }
    return sampleRoadmap();
  }

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function uid(prefix) {
    return `${prefix}-${Math.random().toString(36).slice(2, 7)}`;
  }
  function getStep(id) { return roadmap.steps.find((step) => step.id === id); }
  function selectedStep() {
    if (selected.kind === "step" || selected.kind === "action") return getStep(selected.stepId);
    return null;
  }

  function defaultValidator() {
    return {
      type: "text_exact", values: ["ответ"], pattern: "", number: null,
      minimum: null, maximum: null, date: "", case_sensitive: false,
      trim: true, replace_yo: true, remove_punctuation: true,
    };
  }

  function defaultAction(type) {
    const commonMedia = { type, path: `media/${type.replace("send_", "")}/file`, caption: "", parse_mode: "HTML", disable_notification: false };
    switch (type) {
      case "send_text": return { type, text: "Новое сообщение", parse_mode: "HTML", disable_notification: false };
      case "send_photo": case "send_video": case "send_audio": case "send_document": return commonMedia;
      case "delay": return { type, seconds: 1 };
      case "goto": return { type, step_id: roadmap.steps[0]?.id || "" };
      case "memory_reconstruction": return {
        type, memory_id: "memory_id", number: 1, total: 1,
        date_text: "Дата воспоминания", title: "ВОССТАНОВЛЕНИЕ ВОСПОМИНАНИЯ",
        intro: "", outro: "", message_delay_seconds: 0.65,
      };
      case "ask_input": return {
        type, prompt: "Введи ответ", parse_mode: "HTML", validator: defaultValidator(),
        wrong_answers: ["Ответ пока не совпал."], success_text: "", next_step: null,
      };
      case "buttons": return {
        type, text: "Выбери вариант", parse_mode: "HTML", columns: 1,
        buttons: [{ text: "Продолжить", id: uid("button"), style: "primary", next_step: null, answer_text: "" }],
      };
      default: throw new Error(`Unknown action ${type}`);
    }
  }

  function renderPalette() {
    const list = $("#palette-list");
    list.innerHTML = "";
    palette.forEach(([type, icon, title, description]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "palette-item";
      button.innerHTML = `<span class="palette-item__icon">${icon}</span><span><strong>${title}</strong><small>${description}</small></span>`;
      button.addEventListener("click", () => addAction(type));
      list.append(button);
    });
  }

  function render() {
    $("#project-title").textContent = roadmap.meta.title || "Квест";
    stepsEl.innerHTML = "";
    $("#empty-state").hidden = roadmap.steps.length > 0;
    roadmap.steps.forEach((step, stepIndex) => stepsEl.append(renderStep(step, stepIndex)));
    renderInspector();
  }

  function renderStep(step, stepIndex) {
    const article = document.createElement("article");
    article.className = `step ${selected.stepId === step.id && selected.kind === "step" ? "selected" : ""}`;
    article.draggable = true;
    article.dataset.stepId = step.id;
    article.addEventListener("dragstart", (event) => {
      dragged = { kind: "step", index: stepIndex };
      article.classList.add("dragging");
      event.dataTransfer.effectAllowed = "move";
    });
    article.addEventListener("dragend", () => { dragged = null; article.classList.remove("dragging"); });
    article.addEventListener("dragover", (event) => event.preventDefault());
    article.addEventListener("drop", (event) => {
      event.preventDefault();
      if (!dragged || dragged.kind !== "step" || dragged.index === stepIndex) return;
      const [moved] = roadmap.steps.splice(dragged.index, 1);
      roadmap.steps.splice(stepIndex, 0, moved);
      render();
    });

    const head = document.createElement("div");
    head.className = "step__head";
    head.innerHTML = `
      <span class="drag">⠿</span>
      <span><strong>${escapeHtml(step.title || "Без названия")}</strong><small>${escapeHtml(step.id)} · ${step.actions.length} блоков</small></span>
      <span class="action__tools">
        <button type="button" class="icon-button duplicate" title="Дублировать">⧉</button>
        <button type="button" class="icon-button delete" title="Удалить">✕</button>
      </span>`;
    head.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      selected = { kind: "step", stepId: step.id };
      render();
    });
    head.querySelector(".duplicate").addEventListener("click", () => duplicateStep(stepIndex));
    head.querySelector(".delete").addEventListener("click", () => deleteStep(stepIndex));
    article.append(head);

    const actions = document.createElement("div");
    actions.className = "step__actions";
    actions.dataset.stepId = step.id;
    actions.addEventListener("dragover", (event) => event.preventDefault());
    actions.addEventListener("drop", (event) => {
      event.preventDefault();
      if (!dragged || dragged.kind !== "action") return;
      moveAction(dragged.stepId, dragged.index, step.id, step.actions.length);
    });
    if (!step.actions.length) actions.innerHTML = `<div class="empty-actions">Добавь блок слева</div>`;
    step.actions.forEach((action, actionIndex) => actions.append(renderAction(step, action, actionIndex)));
    article.append(actions);
    return article;
  }

  function renderAction(step, action, actionIndex) {
    const meta = actionMeta[action.type] || { icon: "?", title: action.type };
    const row = document.createElement("div");
    const isSelected = selected.kind === "action" && selected.stepId === step.id && selected.actionIndex === actionIndex;
    row.className = `action ${isSelected ? "selected" : ""}`;
    row.draggable = true;
    row.innerHTML = `
      <span class="drag">⠿</span>
      <span class="action__icon">${meta.icon}</span>
      <span class="action__content"><strong>${meta.title}</strong><small>${escapeHtml(actionSummary(action))}</small></span>
      <span class="action__tools">
        <button type="button" class="icon-button duplicate" title="Дублировать">⧉</button>
        <button type="button" class="icon-button delete" title="Удалить">✕</button>
      </span>`;
    row.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      selected = { kind: "action", stepId: step.id, actionIndex };
      render();
    });
    row.querySelector(".duplicate").addEventListener("click", () => {
      step.actions.splice(actionIndex + 1, 0, clone(action));
      selected = { kind: "action", stepId: step.id, actionIndex: actionIndex + 1 };
      render();
    });
    row.querySelector(".delete").addEventListener("click", () => {
      step.actions.splice(actionIndex, 1);
      selected = { kind: "step", stepId: step.id };
      render();
    });
    row.addEventListener("dragstart", (event) => {
      dragged = { kind: "action", stepId: step.id, index: actionIndex };
      row.classList.add("dragging");
      event.stopPropagation();
    });
    row.addEventListener("dragend", () => { dragged = null; row.classList.remove("dragging"); });
    row.addEventListener("dragover", (event) => event.preventDefault());
    row.addEventListener("drop", (event) => {
      event.preventDefault(); event.stopPropagation();
      if (!dragged || dragged.kind !== "action") return;
      moveAction(dragged.stepId, dragged.index, step.id, actionIndex);
    });
    return row;
  }

  function actionSummary(action) {
    if (action.type === "send_text") return action.text.replace(/<[^>]*>/g, " ").slice(0, 90);
    if (action.type.startsWith("send_")) return action.path;
    if (action.type === "delay") return `${action.seconds} сек.`;
    if (action.type === "memory_reconstruction") return `${action.memory_id} · ${action.number}/${action.total}`;
    if (action.type === "ask_input") return `${action.validator.type} → ${action.next_step || "продолжить"}`;
    if (action.type === "buttons") return `${action.buttons.length} кнопок`;
    if (action.type === "goto") return `→ ${action.step_id}`;
    return "";
  }

  function addAction(type) {
    let step = selectedStep();
    if (!step) step = roadmap.steps.at(-1);
    if (!step) {
      addStep();
      step = roadmap.steps[0];
    }
    step.actions.push(defaultAction(type));
    selected = { kind: "action", stepId: step.id, actionIndex: step.actions.length - 1 };
    render();
  }

  function addStep() {
    const id = uid("step");
    roadmap.steps.push({ id, title: "Новый этап", notes: "", actions: [] });
    if (!roadmap.meta.entry_step_id) roadmap.meta.entry_step_id = id;
    selected = { kind: "step", stepId: id };
    render();
  }

  function duplicateStep(index) {
    const duplicate = clone(roadmap.steps[index]);
    duplicate.id = uid(duplicate.id);
    duplicate.title += " — копия";
    roadmap.steps.splice(index + 1, 0, duplicate);
    selected = { kind: "step", stepId: duplicate.id };
    render();
  }

  function deleteStep(index) {
    const step = roadmap.steps[index];
    if (!confirm(`Удалить этап «${step.title}»?`)) return;
    roadmap.steps.splice(index, 1);
    if (roadmap.meta.entry_step_id === step.id) roadmap.meta.entry_step_id = roadmap.steps[0]?.id || "";
    if (roadmap.meta.intro_step_id === step.id) roadmap.meta.intro_step_id = null;
    selected = { kind: "meta" };
    render();
  }

  function moveAction(fromStepId, fromIndex, toStepId, toIndex) {
    const from = getStep(fromStepId);
    const to = getStep(toStepId);
    if (!from || !to) return;
    const [action] = from.actions.splice(fromIndex, 1);
    if (from === to && fromIndex < toIndex) toIndex -= 1;
    to.actions.splice(toIndex, 0, action);
    selected = { kind: "action", stepId: to.id, actionIndex: toIndex };
    render();
  }

  function renderInspector() {
    formEl.innerHTML = "";
    if (selected.kind === "meta") return renderMetaInspector();
    const step = getStep(selected.stepId);
    if (!step) return placeholder();
    if (selected.kind === "step") return renderStepInspector(step);
    const action = step.actions[selected.actionIndex];
    if (!action) return placeholder();
    renderActionInspector(step, action, selected.actionIndex);
  }

  function renderMetaInspector() {
    heading("Настройки проекта", "Экспортируются в meta.");
    field("Название", roadmap.meta.title, (v) => roadmap.meta.title = v);
    numberField("Версия формата", roadmap.meta.version, (v) => roadmap.meta.version = v, 1);
    selectField("Начальный этап", roadmap.meta.entry_step_id, stepOptions(false), (v) => roadmap.meta.entry_step_id = v);
    selectField("Интро после таймера", roadmap.meta.intro_step_id || "", stepOptions(true), (v) => roadmap.meta.intro_step_id = v || null,
      "Именно этот этап запускается после /start_quest.");
  }

  function renderStepInspector(step) {
    heading("Этап", step.id);
    field("ID этапа", step.id, (value) => renameStep(step.id, value), "Латиница, цифры, дефис и подчёркивание.");
    field("Название", step.title, (v) => step.title = v);
    textareaField("Заметки для себя", step.notes || "", (v) => step.notes = v);
    const tools = div("inspector__actions");
    tools.append(button("Добавить текст", "primary", () => addAction("send_text")));
    tools.append(button("Удалить этап", "danger", () => deleteStep(roadmap.steps.indexOf(step))));
    formEl.append(tools);
  }

  function renderActionInspector(step, action, actionIndex) {
    const meta = actionMeta[action.type];
    heading(`${meta?.icon || ""} ${meta?.title || action.type}`, `Этап: ${step.id}`);

    if (action.type === "send_text") {
      textareaField("Текст", action.text, (v) => action.text = v, "Поддерживается HTML или MarkdownV2.");
      parseModeField(action);
      checkboxField("Отправить без звука", action.disable_notification, (v) => action.disable_notification = v);
    } else if (action.type.startsWith("send_")) {
      field("Путь к файлу", action.path, (v) => action.path = v, "Например: media/photos/clue-01.jpg");
      textareaField("Подпись", action.caption || "", (v) => action.caption = v);
      parseModeField(action);
      checkboxField("Отправить без звука", action.disable_notification, (v) => action.disable_notification = v);
    } else if (action.type === "delay") {
      numberField("Пауза, секунд", action.seconds, (v) => action.seconds = v, 0, 3600, 0.1);
    } else if (action.type === "goto") {
      selectField("Перейти к этапу", action.step_id, stepOptions(false), (v) => action.step_id = v);
    } else if (action.type === "memory_reconstruction") {
      field("ID воспоминания", action.memory_id, (v) => action.memory_id = v, "Совпадает с /memory_new <id>.");
      const grid = div("inline-fields");
      grid.append(numberFieldNode("Номер", action.number, (v) => action.number = v, 1));
      grid.append(numberFieldNode("Всего", action.total, (v) => action.total = v, 1));
      formEl.append(grid);
      field("Дата/период", action.date_text, (v) => action.date_text = v);
      field("Заголовок", action.title, (v) => action.title = v);
      textareaField("Вступление", action.intro || "", (v) => action.intro = v);
      textareaField("Фраза после переписки", action.outro || "", (v) => action.outro = v);
      numberField("Пауза между сообщениями", action.message_delay_seconds, (v) => action.message_delay_seconds = v, 0, 10, .05);
    } else if (action.type === "ask_input") {
      textareaField("Сообщение с вопросом", action.prompt || "", (v) => action.prompt = v);
      parseModeField(action);
      selectField("Тип проверки", action.validator.type, [
        ["any", "Любой непустой ввод"], ["text_exact", "Точное слово/фраза"],
        ["text_contains", "Содержит слово/фразу"], ["regex", "Регулярное выражение"],
        ["integer_equal", "Число равно"], ["integer_range", "Число в диапазоне"],
        ["date_equal", "Дата равна"],
      ], (v) => { action.validator.type = v; renderInspector(); });
      renderValidator(action.validator);
      textareaField("Подсказки при ошибках", (action.wrong_answers || []).join("\n"),
        (v) => action.wrong_answers = v.split("\n").map(x => x.trim()).filter(Boolean), "Каждая строка — следующая подсказка.");
      textareaField("Сообщение при успехе", action.success_text || "", (v) => action.success_text = v);
      selectField("После успеха", action.next_step || "", [["", "Продолжить текущий этап"], ...stepOptions(false)],
        (v) => action.next_step = v || null);
    } else if (action.type === "buttons") {
      textareaField("Текст над кнопками", action.text, (v) => action.text = v);
      parseModeField(action);
      numberField("Кнопок в строке", action.columns, (v) => action.columns = v, 1, 4, 1);
      heading("Кнопки", "ID кнопок должны быть уникальны во всём проекте.", true);
      action.buttons.forEach((item, index) => renderButtonEditor(action, item, index));
      formEl.append(button("＋ Добавить кнопку", "primary", () => {
        action.buttons.push({ text: "Новая кнопка", id: uid("button"), style: "default", next_step: null, answer_text: "" });
        renderInspector();
      }));
    }

    const tools = div("inspector__actions");
    tools.append(button("Дублировать", "ghost", () => {
      step.actions.splice(actionIndex + 1, 0, clone(action));
      selected.actionIndex += 1;
      render();
    }));
    tools.append(button("Удалить блок", "danger", () => {
      step.actions.splice(actionIndex, 1);
      selected = { kind: "step", stepId: step.id };
      render();
    }));
    formEl.append(tools);
  }

  function renderValidator(v) {
    if (v.type === "text_exact" || v.type === "text_contains") {
      textareaField("Допустимые варианты", (v.values || []).join("\n"), (value) => v.values = value.split("\n").map(x => x.trim()).filter(Boolean));
    } else if (v.type === "regex") {
      field("Regex", v.pattern || "", (value) => v.pattern = value, "Используется полное совпадение строки.");
    } else if (v.type === "integer_equal") {
      numberField("Правильное число", v.number ?? 0, (value) => v.number = value);
    } else if (v.type === "integer_range") {
      const grid = div("inline-fields");
      grid.append(numberFieldNode("Минимум", v.minimum ?? 0, (value) => v.minimum = value));
      grid.append(numberFieldNode("Максимум", v.maximum ?? 10, (value) => v.maximum = value));
      formEl.append(grid);
    } else if (v.type === "date_equal") {
      field("Дата YYYY-MM-DD", v.date || "", (value) => v.date = value);
    }
    if (["text_exact", "text_contains", "regex"].includes(v.type)) {
      checkboxField("Учитывать регистр", v.case_sensitive, (value) => v.case_sensitive = value);
      checkboxField("Заменять ё на е", v.replace_yo, (value) => v.replace_yo = value);
      checkboxField("Игнорировать пунктуацию", v.remove_punctuation, (value) => v.remove_punctuation = value);
    }
  }

  function renderButtonEditor(action, item, index) {
    const box = div("button-editor");
    box.innerHTML = `<div class="button-editor__head"><strong>Кнопка ${index + 1}</strong></div>`;
    box.querySelector(".button-editor__head").append(button("Удалить", "danger", () => {
      action.buttons.splice(index, 1); renderInspector();
    }));
    box.append(fieldNode("Текст", item.text, (v) => item.text = v));
    box.append(fieldNode("ID", item.id, (v) => item.id = v));
    box.append(selectFieldNode("Цвет", item.style || "default", [
      ["default", "Нейтральный"], ["primary", "Синий · primary"],
      ["success", "Зелёный · success"], ["danger", "Красный · danger"],
    ], (v) => item.style = v));
    box.append(selectFieldNode("Переход", item.next_step || "", [["", "Продолжить текущий этап"], ...stepOptions(false)],
      (v) => item.next_step = v || null));
    box.append(textareaFieldNode("Сообщение после нажатия", item.answer_text || "", (v) => item.answer_text = v));
    formEl.append(box);
  }

  function renameStep(oldId, newId) {
    newId = newId.trim();
    if (!newId || oldId === newId) return;
    if (roadmap.steps.some(step => step.id === newId)) return showStatus(`ID ${newId} уже занят.`, false);
    const step = getStep(oldId);
    step.id = newId;
    roadmap.steps.forEach(s => s.actions.forEach(action => {
      if (action.type === "goto" && action.step_id === oldId) action.step_id = newId;
      if (action.type === "ask_input" && action.next_step === oldId) action.next_step = newId;
      if (action.type === "buttons") action.buttons.forEach(button => {
        if (button.next_step === oldId) button.next_step = newId;
      });
    }));
    if (roadmap.meta.entry_step_id === oldId) roadmap.meta.entry_step_id = newId;
    if (roadmap.meta.intro_step_id === oldId) roadmap.meta.intro_step_id = newId;
    selected.stepId = newId;
    render();
  }

  function validateRoadmap() {
    const errors = [];
    const ids = roadmap.steps.map(step => step.id);
    const known = new Set(ids);
    if (!roadmap.meta.title.trim()) errors.push("Не задано название проекта.");
    if (!roadmap.steps.length) errors.push("Нет этапов.");
    if (ids.some(id => !/^[a-zA-Z0-9_-]+$/.test(id))) errors.push("ID этапов: только латиница, цифры, _ и -.");
    if (known.size !== ids.length) errors.push("ID этапов не уникальны.");
    if (!known.has(roadmap.meta.entry_step_id)) errors.push("Начальный этап не существует.");
    if (roadmap.meta.intro_step_id && !known.has(roadmap.meta.intro_step_id)) errors.push("Интро-этап не существует.");
    const buttonIds = [];
    roadmap.steps.forEach(step => {
      step.actions.forEach((action, index) => {
        const prefix = `${step.id}, блок ${index + 1}`;
        if (action.type.startsWith("send_") && action.type !== "send_text" && !action.path) errors.push(`${prefix}: пустой путь к файлу.`);
        if (action.type === "goto" && !known.has(action.step_id)) errors.push(`${prefix}: переход ведёт в неизвестный этап.`);
        if (action.type === "ask_input") {
          if (action.next_step && !known.has(action.next_step)) errors.push(`${prefix}: неизвестный переход после ответа.`);
          if (["text_exact", "text_contains"].includes(action.validator.type) && !action.validator.values.length) errors.push(`${prefix}: нет допустимых ответов.`);
          if (action.validator.type === "regex" && !action.validator.pattern) errors.push(`${prefix}: пустой regex.`);
        }
        if (action.type === "buttons") action.buttons.forEach(button => {
          buttonIds.push(button.id);
          if (!button.id || button.id.length > 50) errors.push(`${prefix}: ID кнопки пустой или слишком длинный.`);
          if (button.next_step && !known.has(button.next_step)) errors.push(`${prefix}: кнопка ведёт в неизвестный этап.`);
        });
      });
    });
    if (new Set(buttonIds).size !== buttonIds.length) errors.push("ID inline-кнопок должны быть уникальны.");
    showStatus(errors.length ? errors.join("\n") : `Проверка пройдена: ${roadmap.steps.length} этапов.`, !errors.length);
    return !errors.length;
  }

  function exportRoadmap() {
    if (!validateRoadmap()) return;
    const blob = new Blob([JSON.stringify(roadmap, null, 2) + "\n"], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "quest.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function importRoadmap(file) {
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const value = JSON.parse(reader.result);
        if (!value.meta || !Array.isArray(value.steps)) throw new Error("Нет meta или steps");
        roadmap = value;
        selected = { kind: "meta" };
        render();
        validateRoadmap();
      } catch (error) {
        showStatus(`Не удалось импортировать JSON: ${error.message}`, false);
      }
    };
    reader.readAsText(file, "utf-8");
  }

  function saveDraft() {
    localStorage.setItem(draftKey, JSON.stringify(roadmap));
    showStatus("Черновик сохранён в localStorage этого браузера.", true);
  }

  function showStatus(text, ok) {
    statusEl.hidden = false;
    statusEl.className = `status ${ok ? "ok" : "error"}`;
    statusEl.textContent = text;
    statusEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function heading(title, note = "", small = false) {
    const wrap = document.createElement("div");
    wrap.className = "panel__head";
    wrap.innerHTML = `<${small ? "h3" : "h2"}>${escapeHtml(title)}</${small ? "h3" : "h2"}><p>${escapeHtml(note)}</p>`;
    formEl.append(wrap);
  }
  function placeholder() { formEl.innerHTML = `<div class="inspector-placeholder">Выбери этап или действие.</div>`; }
  function div(className) { const node = document.createElement("div"); node.className = className; return node; }
  function button(text, className, onClick) {
    const node = document.createElement("button");
    node.type = "button"; node.className = `button ${className}`; node.textContent = text; node.addEventListener("click", onClick); return node;
  }
  function field(label, value, setter, note = "") { formEl.append(fieldNode(label, value, setter, note)); }
  function fieldNode(label, value, setter, note = "") {
    const wrap = document.createElement("label"); wrap.className = "field";
    wrap.innerHTML = `<span>${escapeHtml(label)}</span><input><small>${escapeHtml(note)}</small>`;
    const input = wrap.querySelector("input"); input.value = value ?? "";
    input.addEventListener("input", () => setter(input.value)); input.addEventListener("change", render);
    return wrap;
  }
  function textareaField(label, value, setter, note = "") { formEl.append(textareaFieldNode(label, value, setter, note)); }
  function textareaFieldNode(label, value, setter, note = "") {
    const wrap = document.createElement("label"); wrap.className = "field";
    wrap.innerHTML = `<span>${escapeHtml(label)}</span><textarea></textarea><small>${escapeHtml(note)}</small>`;
    const input = wrap.querySelector("textarea"); input.value = value ?? "";
    input.addEventListener("input", () => setter(input.value)); input.addEventListener("change", render);
    return wrap;
  }
  function numberField(label, value, setter, min, max, step = 1) { formEl.append(numberFieldNode(label, value, setter, min, max, step)); }
  function numberFieldNode(label, value, setter, min, max, step = 1) {
    const node = fieldNode(label, value, () => {}); const input = node.querySelector("input"); input.type = "number";
    if (min !== undefined) input.min = min; if (max !== undefined) input.max = max; input.step = step;
    input.addEventListener("input", () => setter(Number(input.value))); return node;
  }
  function selectField(label, value, options, setter, note = "") { formEl.append(selectFieldNode(label, value, options, setter, note)); }
  function selectFieldNode(label, value, options, setter, note = "") {
    const wrap = document.createElement("label"); wrap.className = "field";
    const select = document.createElement("select");
    options.forEach(([optionValue, optionLabel]) => {
      const option = document.createElement("option"); option.value = optionValue; option.textContent = optionLabel; option.selected = optionValue === value; select.append(option);
    });
    select.addEventListener("change", () => { setter(select.value); render(); });
    wrap.innerHTML = `<span>${escapeHtml(label)}</span>`; wrap.append(select);
    const small = document.createElement("small"); small.textContent = note; wrap.append(small); return wrap;
  }
  function checkboxField(label, value, setter) {
    const wrap = document.createElement("label"); wrap.className = "checkbox";
    const input = document.createElement("input"); input.type = "checkbox"; input.checked = Boolean(value);
    input.addEventListener("change", () => setter(input.checked)); wrap.append(input, document.createTextNode(label)); formEl.append(wrap);
  }
  function parseModeField(action) {
    selectField("Разметка", action.parse_mode || "HTML", [["HTML", "HTML"], ["MarkdownV2", "MarkdownV2"], ["none", "Без парсинга"]], (v) => action.parse_mode = v);
  }
  function stepOptions(includeEmpty) {
    const options = roadmap.steps.map(step => [step.id, `${step.title} · ${step.id}`]);
    return includeEmpty ? [["", "Не задан"], ...options] : options;
  }
  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
  }

  $("#add-step").addEventListener("click", addStep);
  $("#edit-meta").addEventListener("click", () => { selected = { kind: "meta" }; render(); });
  $("#validate").addEventListener("click", validateRoadmap);
  $("#export").addEventListener("click", exportRoadmap);
  $("#save-draft").addEventListener("click", saveDraft);
  $("#new-project").addEventListener("click", () => {
    if (!confirm("Создать новый проект? Несохранённые изменения исчезнут.")) return;
    roadmap = sampleRoadmap(); selected = { kind: "meta" }; render();
  });
  $("#import-file").addEventListener("change", (event) => {
    if (event.target.files[0]) importRoadmap(event.target.files[0]);
    event.target.value = "";
  });
  window.addEventListener("beforeunload", () => localStorage.setItem(draftKey, JSON.stringify(roadmap)));

  renderPalette();
  render();
})();
