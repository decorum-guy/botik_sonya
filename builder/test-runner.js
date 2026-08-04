(() => {
  "use strict";

  const DRAFT_KEY = "botik-sonya-roadmap-v1";
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
      <div class="test-runner__actions">
        <button type="button" class="button success" data-test-scope="full">Весь сценарий</button>
        <button type="button" class="button primary" data-test-scope="step">Выбранный этап</button>
        <button type="button" class="button ghost" data-test-scope="action">Выбранный блок</button>
      </div>
      <div id="test-runner-result" class="test-runner__result" hidden></div>
    `;
    header.after(panel);

    panel.querySelectorAll("[data-test-scope]").forEach((button) => {
      button.addEventListener("click", () => runTest(button.dataset.testScope));
    });
  }

  function saveAndReadRoadmap() {
    document.querySelector("#save-draft")?.click();
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) throw new Error("Черновик ROADMAP не найден. Сначала сохрани проект.");
    return JSON.parse(raw);
  }

  function selectedContext() {
    const action = document.querySelector(".action.selected");
    if (action) {
      const step = action.closest(".step");
      const actions = [...step.querySelectorAll(":scope > .step__actions > .action")];
      return {
        stepId: step?.dataset.stepId || null,
        actionIndex: actions.indexOf(action),
      };
    }

    const step = document.querySelector(".step.selected");
    return {
      stepId: step?.dataset.stepId || null,
      actionIndex: null,
    };
  }

  function setBusy(value) {
    busy = value;
    document.querySelectorAll("#test-runner [data-test-scope]").forEach((button) => {
      button.disabled = value;
    });
  }

  function showResult(text, ok) {
    const result = document.querySelector("#test-runner-result");
    if (!result) return;
    result.hidden = false;
    result.className = `test-runner__result ${ok ? "ok" : "error"}`;
    result.textContent = text;
  }

  async function runTest(scope) {
    if (busy) return;
    try {
      const roadmap = saveAndReadRoadmap();
      const context = selectedContext();
      if (scope === "step" && !context.stepId) {
        throw new Error("Сначала выбери этап или любой блок внутри него.");
      }
      if (scope === "action" && (context.actionIndex === null || context.actionIndex < 0)) {
        throw new Error("Сначала выбери конкретный блок.");
      }

      setBusy(true);
      showResult("Отправляю текущую версию в тестовый Telegram-аккаунт…", true);
      const response = await fetch("/api/test-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          roadmap,
          scope,
          step_id: context.stepId,
          action_index: context.actionIndex,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      showResult(data.message || "Тестовый запуск выполнен.", true);
    } catch (error) {
      showResult(error.message || String(error), false);
    } finally {
      setBusy(false);
      refreshConnection();
    }
  }

  async function refreshConnection() {
    const label = document.querySelector("#test-runner-connection");
    if (!label) return;
    try {
      const response = await fetch("/api/test-status", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error();
      if (data.participant_available) {
        label.textContent = "Тестовый аккаунт подключён";
        label.className = "connected";
      } else {
        label.textContent = "Нужен /start со второго Telegram-аккаунта";
        label.className = "waiting";
      }
    } catch {
      label.textContent = "Запусти: python -m tools.builder_server";
      label.className = "offline";
    }
  }

  window.addEventListener("load", () => {
    createUi();
    refreshConnection();
    setInterval(refreshConnection, 5000);
  });
})();
