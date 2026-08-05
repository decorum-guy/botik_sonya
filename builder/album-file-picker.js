(() => {
  "use strict";

  let projectRootHandle = null;
  let scheduled = false;

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      enhance();
    });
  }

  function enhance() {
    document.querySelectorAll(".album-item__path").forEach((input) => {
      if (input.dataset.albumPickerEnhanced === "true") return;
      input.dataset.albumPickerEnhanced = "true";
      const wrapper = document.createElement("div");
      wrapper.className = "project-file-picker album-file-picker";
      input.before(wrapper);
      wrapper.append(input);

      const button = document.createElement("button");
      button.type = "button";
      button.className = "button ghost project-file-picker__button";
      button.textContent = "📁";
      button.title = "Выбрать файл";
      button.addEventListener("click", () => chooseFile(input, wrapper));
      wrapper.append(button);
    });
  }

  async function chooseFile(input, wrapper) {
    clearNotice(wrapper);
    if (!("showDirectoryPicker" in window) || !("showOpenFilePicker" in window)) {
      showNotice(wrapper, "Выбор файлов поддерживается в Chromium / Яндекс Браузере.");
      return;
    }

    try {
      if (!projectRootHandle) {
        projectRootHandle = await window.showDirectoryPicker({
          id: "botik-sonya-album-root",
          mode: "read",
        });
        await verifyProjectRoot(projectRootHandle);
      }

      const kind = input.dataset.mediaKind === "video" ? "video" : "photo";
      const options = {
        id: `botik-sonya-album-${kind}`,
        multiple: false,
        startIn: projectRootHandle,
        types: pickerTypes(kind),
      };
      let handles;
      try {
        handles = await window.showOpenFilePicker(options);
      } catch (error) {
        if (!(error instanceof TypeError)) throw error;
        delete options.startIn;
        handles = await window.showOpenFilePicker(options);
      }

      const relative = await projectRootHandle.resolve(handles[0]);
      if (!relative) throw new Error("Файл находится вне выбранной папки botik_sonya.");
      input.value = relative.join("/");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } catch (error) {
      if (error?.name === "AbortError") return;
      if (String(error?.message || "").includes("корень проекта")) {
        projectRootHandle = null;
      }
      showNotice(wrapper, error?.message || "Не удалось выбрать файл.");
    }
  }

  async function verifyProjectRoot(handle) {
    try {
      for (const name of ["app", "builder", "roadmap"]) {
        await handle.getDirectoryHandle(name);
      }
      await handle.getFileHandle("requirements.txt");
    } catch {
      throw new Error("Выбранная папка не похожа на корень проекта botik_sonya.");
    }
  }

  function pickerTypes(kind) {
    if (kind === "video") {
      return [{
        description: "Видео",
        accept: { "video/*": [".mp4", ".mov", ".m4v", ".webm"] },
      }];
    }
    return [{
      description: "Изображения",
      accept: {
        "image/*": [".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"],
      },
    }];
  }

  function clearNotice(wrapper) {
    wrapper.parentElement?.querySelector(":scope > .inline-notice")?.remove();
  }

  function showNotice(wrapper, text) {
    clearNotice(wrapper);
    const notice = document.createElement("div");
    notice.className = "inline-notice error";
    notice.textContent = text;
    wrapper.parentElement?.append(notice);
  }

  new MutationObserver(schedule).observe(document.querySelector("#inspector-form"), {
    childList: true,
    subtree: true,
  });
  schedule();
})();
