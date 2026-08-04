(() => {
  "use strict";

  const DRAFT_KEY = "botik-sonya-roadmap-v1";
  let refreshTimer = null;

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function readRoadmap() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function collectVariables(roadmap) {
    const result = [];
    const byId = new Map();
    let invalid = 0;
    for (const step of roadmap?.steps || []) {
      for (const action of step.actions || []) {
        if (action.type !== "memory_reconstruction") continue;
        const id = String(action.memory_id || "").trim();
        if (!id) {
          invalid += 1;
          continue;
        }
        let variable = byId.get(id);
        if (!variable) {
          variable = {
            id,
            label: String(
              action.title ||
              action.date_text ||
              `Воспоминание ${action.number || result.length + 1}`
            ).trim(),
            usages: 0,
          };
          byId.set(id, variable);
          result.push(variable);
        }
        variable.usages += 1;
      }
    }
    return { variables: result, invalid };
  }

  function ensurePanel() {
    let panel = document.querySelector("#memory-variable-panel");
    if (panel) return panel;

    panel = document.createElement("section");
    panel.id = "memory-variable-panel";
    panel.className = "memory-variable-panel";
    const palette = document.querySelector(".palette");
    const legend = palette?.querySelector(".legend");
    if (legend) legend.before(panel);
    else palette?.append(panel);

    const style = document.createElement("style");
    style.textContent = `
      .memory-variable-panel{margin:14px 0;padding:14px;border:1px solid rgba(120,130,155,.3);border-radius:14px;background:rgba(255,255,255,.72)}
      .memory-variable-panel h3{margin:0 0 5px;font-size:14px}
      .memory-variable-panel p{margin:0 0 10px;font-size:12px;line-height:1.45;color:#687083}
      .memory-variable-list{display:grid;gap:7px;margin:0;padding:0;list-style:none}
      .memory-variable-item{padding:8px 9px;border-radius:10px;background:rgba(88,101,242,.07);font-size:12px}
      .memory-variable-item code{display:block;margin-bottom:2px;font-weight:700;word-break:break-all}
      .memory-variable-meta{font-size:11px;color:#687083}
      .memory-variable-error{margin-top:8px;padding:7px;border-radius:9px;background:rgba(220,53,69,.1);color:#a11b2c;font-size:11px}
    `;
    document.head.append(style);
    return panel;
  }

  function render() {
    const panel = ensurePanel();
    const roadmap = readRoadmap();
    if (!roadmap) {
      panel.innerHTML = "<h3>🧠 Переменные воспоминаний</h3><p>Не удалось прочитать текущий черновик.</p>";
      return;
    }

    const { variables, invalid } = collectVariables(roadmap);
    const items = variables.map((variable, index) => `
      <li class="memory-variable-item">
        <code>${index + 1}. ${escapeHtml(variable.id)}</code>
        <span>${escapeHtml(variable.label || variable.id)}</span>
        <div class="memory-variable-meta">Заполняется один раз · проигрываний: ${variable.usages}</div>
      </li>
    `).join("");

    panel.innerHTML = `
      <h3>🧠 Переменные воспоминаний · ${variables.length}</h3>
      <p>Каждый уникальный <code>memory_id</code> — одна переменная. После <code>/admin пароль</code> бот попросит заполнить их по порядку.</p>
      ${items ? `<ol class="memory-variable-list">${items}</ol>` : "<p>Добавь блок «Воспоминание» в нужную точку сюжета.</p>"}
      ${invalid ? `<div class="memory-variable-error">У ${invalid} блок(ов) не заполнен memory_id — бот их не увидит.</div>` : ""}
    `;
  }

  function persistAndRender() {
    const saveButton = document.querySelector("#save-draft");
    if (saveButton) saveButton.click();
    requestAnimationFrame(render);
  }

  function scheduleRefresh(event) {
    if (event?.target?.closest?.("#memory-variable-panel")) return;
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(persistAndRender, 120);
  }

  document.addEventListener("input", scheduleRefresh, true);
  document.addEventListener("change", scheduleRefresh, true);
  document.querySelector("#steps")?.addEventListener("click", scheduleRefresh, true);
  document.querySelector("#add-step")?.addEventListener("click", scheduleRefresh, true);
  window.addEventListener("load", () => setTimeout(persistAndRender, 0));
})();
