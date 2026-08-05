(() => {
  "use strict";

  const PREFIX = "album:v1";

  function parse(value) {
    const lines = String(value || "").replaceAll("\r\n", "\n").trim().split("\n");
    if (lines[0] !== PREFIX) return null;
    return lines.slice(1).filter(Boolean).map((line) => ({
      kind: line.startsWith("video\t") ? "video" : "photo",
    }));
  }

  function summary(items) {
    const photos = items.filter((item) => item.kind === "photo").length;
    const videos = items.length - photos;
    const parts = [`${items.length} элементов`];
    if (photos) parts.push(`${photos} фото`);
    if (videos) parts.push(`${videos} видео`);
    return parts.join(" · ");
  }

  function captureCards() {
    document.querySelectorAll(".action .action__content small").forEach((small) => {
      if (small.textContent.startsWith(`${PREFIX}\n`)) {
        small.dataset.rawAlbumPath = small.textContent;
      }
    });
  }

  document.addEventListener("input", (event) => {
    const input = event.target;
    const field = input.closest?.("label.field");
    if (!field || field.querySelector(":scope > span")?.textContent?.trim() !== "Путь к файлу") return;
    const items = parse(input.value);
    if (!items) return;
    const small = document.querySelector(".action.selected .action__content small");
    if (!small) return;
    small.dataset.rawAlbumPath = input.value;
    small.textContent = summary(items);
  }, true);

  const observer = new MutationObserver(captureCards);
  const steps = document.querySelector("#steps");
  if (steps) observer.observe(steps, { childList: true, subtree: true });
  captureCards();
})();
