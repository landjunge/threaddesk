function typingTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

function helpPanel() {
  return document.getElementById("help");
}

function toggleHelp(force) {
  const el = helpPanel();
  if (!el) return;
  if (typeof force === "boolean") {
    el.hidden = !force;
  } else {
    el.hidden = !el.hidden;
  }
}

function threadButtons() {
  return Array.from(document.querySelectorAll("[data-thread-index]"));
}

function currentIndex() {
  const on = document.querySelector("[data-thread-index].is-current");
  if (!on) return -1;
  return Number(on.getAttribute("data-thread-index")) - 1;
}

function switchByOffset(delta) {
  const buttons = threadButtons();
  if (!buttons.length) return;
  const next = (currentIndex() + delta + buttons.length) % buttons.length;
  buttons[next].click();
}

document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented) return;

  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    const form = event.target instanceof Element ? event.target.closest("form") : null;
    if (form) {
      event.preventDefault();
      form.requestSubmit();
    }
    return;
  }

  if (event.metaKey || event.ctrlKey || event.altKey) return;

  if (event.key === "Escape") {
    toggleHelp(false);
    const title = document.querySelector("[data-new-title]");
    if (title && document.activeElement === title) {
      title.blur();
    }
    return;
  }

  if (event.key === "?" || (event.shiftKey && event.key === "/")) {
    event.preventDefault();
    toggleHelp();
    return;
  }

  if (typingTarget(document.activeElement)) return;

  if (event.key === "n") {
    event.preventDefault();
    document.querySelector("[data-new-thread]")?.click();
    window.setTimeout(() => document.querySelector("[data-new-title]")?.focus(), 30);
    return;
  }

  if (event.key === "j") {
    event.preventDefault();
    switchByOffset(1);
    return;
  }

  if (event.key === "k") {
    event.preventDefault();
    switchByOffset(-1);
    return;
  }

  if (event.key === "s") {
    event.preventDefault();
    document.querySelector("[data-snapshot-label]")?.focus();
    return;
  }

  if (event.key >= "1" && event.key <= "9") {
    event.preventDefault();
    document.querySelector(`[data-thread-index="${event.key}"]`)?.click();
  }
});

document.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;

  if (target.closest("[data-help-open]")) {
    event.preventDefault();
    toggleHelp(true);
    return;
  }
  if (target.closest("[data-help-close]")) {
    event.preventDefault();
    toggleHelp(false);
    return;
  }
  if (target.id === "help") {
    toggleHelp(false);
    return;
  }

  const copy = target.closest("[data-copy]");
  if (!copy) return;
  const sel = copy.getAttribute("data-copy");
  const el = sel ? document.querySelector(sel) : null;
  if (!el || !navigator.clipboard) return;
  const prev = copy.textContent;
  navigator.clipboard.writeText(el.textContent || "").then(() => {
    copy.textContent = "Kopiert";
    window.setTimeout(() => {
      copy.textContent = prev;
    }, 1400);
  });
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  const root = event.detail && event.detail.target;
  if (root && window.Alpine) {
    window.Alpine.initTree(root);
  }
});

document.body.addEventListener("htmx:sendError", () => {
  console.warn("ThreadDesk UI: Anfrage fehlgeschlagen");
});
