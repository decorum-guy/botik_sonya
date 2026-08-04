(() => {
  "use strict";

  const DRAFT_KEY = "botik-sonya-roadmap-v1";
  const TARGET_KEY = "botik-sonya-test-target";
  let busy = false;

  function createUi() {
    const header = document.querySelector(".topbar");
    if (!header || document.querySelector("#test-runner")) return;

    const panel = document.createElement("section");
    panel.id = "test-runner";
    panel.className = "test-runner";
    panel.innerHTML = `
      <div class="test-runner__intro">
        <strong>▶ Тест в Telegram</strong>
        <span id="test-runner-connection">Проверяю локальный сервер…</span>
      </div>
      <label class="test-runner__target">
        <span>Получатель теста</span>
        <select id="test-runner-target">
          <option value="">Загружаю пользователей…</option>
        </select>
        <button type="button" class="button ghost" id="test-runner-refresh" title="Обновить список">↻</button>
      </label>
      <div class="test-runner__actions">
        <button type="button" class="button success" data-test-scope="full">Весь сценарий</button>
        <button type="button" class="button primary" data-test-scope="step">Выбранный этап</button>
        <button type="button" class="button ghost" data-test-scope="action">Выбранный блок</button>
        <button type="button" class="button memory" id="fill-memory">🧠 Наполнить воспоминание</button>
      </div>
      <div id="test-runner-result" class="test-runner__result" hidden></div>
    `;
    header.after(panel);

    panel.querySelectorAll("[data-test-scope]").forEach((button) => {
      button.addEventListener("click", () => runTest(button.dataset.testScope));
    });
    panel.querySelector("#fill-memory").addEventListener("click", startMemoryFill);
    panel.querySelector("#test-runner-refresh").addEventListener("click", refreshUsers);
    panel.querySelector("#test-runner-target").addEventListener("change", (event) => {
      localStorage.setItem(TARGET_KEY, event.target.value);
    });
  }

  function saveAndReadRoadmap() {
    document.querySelector("#save-draft")?.click();
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) throw new Error("Черновик ROADMAP не найден. Сначала сохрани проект.");
    return JSON.parse(raw);
  }

  function selectedContext(roadmap = null) {
    const actionNode = document.querySelector(".action.selected");
    if (actionNode) {
      const stepNode = actionNode.closest(".step");
      const actions = [...stepNode.querySelectorAll(":scope > .step__actions > .action")];
      const stepId = stepNode?.dataset.stepId || null;
      const actionIndex = actions.indexOf(actionNode);
      const step = roadmap?.steps?.find((item) => item.id === stepId) || null;
      return {
        stepId,
        actionIndex,
        action: step?.actions?.[actionIndex] || null,
      };
    }

    const stepNode = document.querySelector(".step.selected");
    return {
      stepId: stepNode?.dataset.stepId || null,
      actionIndex: null,
      action: null,
    };
  }

  function selectedTarget() {
    const value = document.querySelector("#test-runner-target")?.value || "";
    if (!value) throw new Error("Выбери Telegram-пользователя для теста.");
    return Number(value);
  }

  function setBusy(value) {
    busy = value;
    document.querySelectorAll("#test-runner button, #test-runner select").forEach((control) => {
      control.disabled = value;
    });
  }

  function showResult(text, ok) {
    const result = document.querySelector("#test-runner-result");
    if (!result) return;
    result.hidden = false;
    result.className = `test-runner__result ${ok ? "ok" : "error"}`;
    result.textContent = text;
  }

  async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    return { response, data };
  }

  async function runTest(scope) {
    if (busy) return;
    try {
      const roadmap = saveAndReadRoadmap();
      const context = selectedContext(roadmap);
      const targetChatId = selectedTarget();
      if (scope === "step" && !context.stepId) {
        throw new Error("Сначала выбери этап или любой блок внутри него.");
      }
      if (scope === "action" && (context.actionIndex === null || context.actionIndex < 0)) {
        throw new Error("Сначала выбери конкретный блок.");
      }

      setBusy(true);
      showResult("Отправляю текущую версию выбранному Telegram-пользователю…", true);
      const { response, data } = await requestJson("/api/test-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          roadmap,
          scope,
          step_id: context.stepId,
          action_index: context.actionIndex,
          target_chat_id: targetChatId,
        }),
      });
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      showResult(data.message || "Тестовый запуск выполнен.", true);
    } catch (error) {
      showResult(error.message || String(error), false);
    } finally {
      setBusy(false);
      refreshUsers();
    }
  }

  async function startMemoryFill() {
    if (busy) return;
    try {
      const roadmap = saveAndReadRoadmap();
      const context = selectedContext(roadmap);
      if (!context.action || context.action.type !== "memory_reconstruction") {
        throw new Error("Сначала выбери конкретный блок «Воспоминание».");
      }

      setBusy(true);
      showResult(`Активирую наполнение ${context.action.memory_id} в админском чате…`, true);
      let replace = false;
      while (true) {
        const { response, data } = await requestJson("/api/memory/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            roadmap,
            step_id: context.stepId,
            action_index: context.actionIndex,
            replace,
          }),
        });

        if (response.status === 409 && data.requires_confirmation) {
          const confirmed = window.confirm(
            `Воспоминание «${data.memory_id}» уже содержит ${data.existing_count} сообщений. ` +
            "Удалить их и записать воспоминание заново?"
          );
          if (!confirmed) {
            showResult("Перезапись воспоминания отменена. Старые сообщения сохранены.", true);
            return;
          }
          replace = true;
          continue;
        }
        if (!response.ok || !data.ok) {
          throw new Error(data.error || `HTTP ${response.status}`);
        }
        showResult(data.message || "Бот перешёл в режим наполнения воспоминания.", true);
        return;
      }
    } catch (error) {
      showResult(error.message || String(error), false);
    } finally {
      setBusy(false);
    }
  }

  async function refreshUsers() {
    const label = document.querySelector("#test-runner-connection");
    const select = document.querySelector("#test-runner-target");
    if (!label || !select || busy) return;

    try {
      const { response, data } = await requestJson("/api/users", { cache: "no-store" });
      if (!response.ok || !data.ok) throw new Error(data.error || "Сервер недоступен");

      const previous = select.value || localStorage.getItem(TARGET_KEY) || "";
      select.innerHTML = "";
      if (!data.users.length) {
        const option = new Option("Никто ещё не писал боту", "");
        select.append(option);
        label.textContent = "Напиши боту с нужного аккаунта и обнови список";
        label.className = "waiting";
        return;
      }

      data.users.forEach((user) => {
        const option = new Option(`${user.label} · ${user.chat_id}`, String(user.chat_id));
        select.append(option);
      });
      const available = [...select.options].some((option) => option.value === previous);
      select.value = available ? previous : select.options[0].value;
      localStorage.setItem(TARGET_KEY, select.value);
      label.textContent = `Доступно получателей: ${data.users.length}`;
      label.className = "connected";
    } catch (error) {
      select.innerHTML = '<option value="">Локальный сервер не запущен</option>';
      label.textContent = "Запусти: python -m tools.builder_server";
      label.className = "offline";
    }
  }

  window.addEventListener("load", () => {
    createUi();
    refreshUsers();
    setInterval(refreshUsers, 5000);
  });
})();
