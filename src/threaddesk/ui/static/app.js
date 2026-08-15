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

  if (event.key === "m") {
    event.preventDefault();
    document.querySelector("[data-mic]")?.click();
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

function notesMic() {
  return {
    on: false,
    err: "",
    interim: "",
    rec: null,
    toggle() {
      if (this.on) this.stop();
      else this.start();
    },
    start() {
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) {
        this.err = "Dieser Browser hat keine Spracheingabe.";
        return;
      }
      if (!window.isSecureContext) {
        this.err = "Mikrofon braucht einen sicheren Kontext.";
        return;
      }
      this.err = "";
      this.interim = "";
      const rec = new SR();
      rec.lang = "de-DE";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (event) => {
        let finalText = "";
        let live = "";
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const piece = event.results[i][0].transcript;
          if (event.results[i].isFinal) finalText += piece;
          else live += piece;
        }
        this.interim = live.trim();
        if (finalText.trim()) appendSpokenNote(finalText.trim());
      };
      rec.onerror = (event) => {
        if (event.error === "not-allowed") this.err = "Mikrofon nicht erlaubt.";
        else if (event.error === "no-speech") this.err = "";
        else this.err = "Spracheingabe: " + event.error;
        if (event.error !== "no-speech") this.stop();
      };
      rec.onend = () => {
        if (this.on) {
          try {
            rec.start();
          } catch (_err) {
            this.stop();
          }
        }
      };
      this.rec = rec;
      this.on = true;
      rec.start();
    },
    stop() {
      this.on = false;
      this.interim = "";
      const rec = this.rec;
      this.rec = null;
      if (rec) {
        rec.onend = null;
        try {
          rec.stop();
        } catch (_err) {
          /* already stopped */
        }
      }
    },
    destroy() {
      this.stop();
    },
  };
}

function appendSpokenNote(text) {
  const field = document.querySelector("#notes textarea[name='text']");
  if (!field) return;
  const cur = field.value.replace(/\s*$/, "");
  field.value = cur ? cur + "\n" + text : text;
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

window.notesMic = notesMic;

document.addEventListener("alpine:init", () => {
  if (window.Alpine) window.Alpine.data("notesMic", notesMic);
});
