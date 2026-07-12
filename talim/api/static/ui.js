"use strict";

// Shared UI helpers for the operator dashboard pages: toasts instead of
// alert(), <dialog>-based confirm/secret prompts instead of confirm()/prompt().
// Loaded as a plain script before each page's own script; everything lives
// under the TalimUI namespace so it cannot collide with per-page globals.
window.TalimUI = (function () {
  function make(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (k === "class") node.className = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
        else if (v === true) node.setAttribute(k, "");
        else if (v != null && v !== false) node.setAttribute(k, String(v));
      }
    }
    for (const c of [].concat(children || [])) {
      if (c == null) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }

  function toastRegion() {
    let region = document.getElementById("talim-toasts");
    if (!region) {
      region = make("div", { id: "talim-toasts", class: "toast-region", role: "status", "aria-live": "polite" });
      document.body.appendChild(region);
    }
    return region;
  }

  function toast(message, kind) {
    const node = make("div", { class: `toast ${kind || "info"}`, text: message });
    node.addEventListener("click", () => node.remove());
    toastRegion().appendChild(node);
    setTimeout(() => node.remove(), kind === "error" ? 8000 : 4500);
  }

  function openDialog({ cancelValue, render, focus }) {
    return new Promise((resolve) => {
      const dialog = make("dialog", { class: "talim-dialog" });
      let settled = false;
      const finish = (value) => {
        if (!settled) {
          settled = true;
          resolve(value);
        }
        if (dialog.open) {
          try { dialog.close(); } catch (_) { /* already closing */ }
        }
        dialog.remove();
      };
      // Esc fires cancel; cleanup must not depend on the close event, which
      // some embedded browsers never dispatch for programmatic close().
      dialog.addEventListener("cancel", () => finish(cancelValue));
      dialog.addEventListener("close", () => finish(cancelValue));
      render(dialog, finish);
      document.body.appendChild(dialog);
      dialog.showModal();
      if (focus) focus();
    });
  }

  function confirmAction(message, opts = {}) {
    if (typeof HTMLDialogElement === "undefined") return Promise.resolve(window.confirm(message));
    let confirmBtn;
    return openDialog({
      cancelValue: false,
      render(dialog, finish) {
        confirmBtn = make("button", {
          type: "button",
          class: opts.danger ? "danger" : "ok",
          text: opts.confirmLabel || "Confirm",
          onClick: () => finish(true),
        });
        dialog.appendChild(make("div", { class: "dialog-message", text: message }));
        dialog.appendChild(make("div", { class: "dialog-actions" }, [
          make("button", { type: "button", text: "Cancel", onClick: () => finish(false) }),
          confirmBtn,
        ]));
      },
      focus() { confirmBtn.focus(); },
    });
  }

  function promptSecret(message) {
    const text = message || "Paste the Talim bridge secret once for this browser session.";
    if (typeof HTMLDialogElement === "undefined") return Promise.resolve((window.prompt(text) || "").trim() || null);
    let input;
    return openDialog({
      cancelValue: null,
      render(dialog, finish) {
        input = make("input", {
          type: "password",
          autocomplete: "current-password",
          placeholder: "TALIM_BRIDGE_SECRET",
          "aria-label": "Talim bridge secret",
        });
        const form = make("form", null, [
          make("div", { class: "dialog-message", text }),
          input,
          make("div", { class: "dialog-actions" }, [
            make("button", { type: "button", text: "Cancel", onClick: () => finish(null) }),
            make("button", { type: "submit", class: "ok", text: "Sign in" }),
          ]),
        ]);
        form.addEventListener("submit", (ev) => {
          ev.preventDefault();
          finish(input.value.trim() || null);
        });
        dialog.appendChild(form);
      },
      focus() { input.focus(); },
    });
  }

  return { toast, confirm: confirmAction, promptSecret };
})();
