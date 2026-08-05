(() => {
  "use strict";

  const form = document.querySelector("#inspector-form");
  if (!form) return;

  function updateMemoryPacingField() {
    const labels = [...form.querySelectorAll("label.field")];
    const field = labels.find((label) => {
      const title = label.querySelector(":scope > span")?.textContent?.trim();
      return title === "Пауза между сообщениями";
    });
    if (!field || field.dataset.randomMemoryPacing === "1") return;

    const title = field.querySelector(":scope > span");
    const input = field.querySelector("input");
    const hint = field.querySelector("small");
    if (!title || !input) return;

    field.dataset.randomMemoryPacing = "1";
    title.textContent = "Темп переписки";
    input.type = "text";
    input.value = "случайно от 1 до 3,5 секунды";
    input.disabled = true;
    if (hint) {
      hint.textContent = "Новая пауза выбирается отдельно перед каждым следующим сообщением.";
    }
  }

  const observer = new MutationObserver(updateMemoryPacingField);
  observer.observe(form, { childList: true, subtree: true });
  updateMemoryPacingField();
})();
