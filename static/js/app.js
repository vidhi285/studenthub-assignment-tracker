// StudentHub shared UI behaviour: theme toggle, toasts, confirmation dialogs,
// submit loading states, password visibility and the subject colour picker.
(function () {
  "use strict";

  const THEME_KEY = "studenthub-theme";

  function currentTheme() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { /* ignore */ }
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      const icon = btn.querySelector("i");
      if (icon) icon.className = theme === "dark" ? "bi bi-sun" : "bi bi-moon-stars";
      btn.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
      btn.setAttribute("title", btn.getAttribute("aria-label"));
    });
    document.dispatchEvent(new CustomEvent("studenthub:themechange", { detail: { theme: theme } }));
  }

  function initTheme() {
    applyTheme(currentTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    });
  }

  function initToasts() {
    if (!window.bootstrap) return;
    document.querySelectorAll(".toast").forEach(function (el) {
      const delay = el.dataset.category === "danger" || el.dataset.category === "warning" ? 8000 : 5000;
      const toast = bootstrap.Toast.getOrCreateInstance(el, { delay: delay, autohide: true });
      toast.show();
    });
  }

  // Forms (or buttons inside forms) with data-confirm show a styled modal first.
  // Without JavaScript the form still submits normally.
  function initConfirm() {
    const modalEl = document.getElementById("confirmModal");
    if (!modalEl || !window.bootstrap) return;
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    const titleEl = modalEl.querySelector("[data-confirm-title]");
    const bodyEl = modalEl.querySelector("[data-confirm-body]");
    const okBtn = modalEl.querySelector("[data-confirm-ok]");
    let pendingForm = null;

    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmed === "1") return;
      event.preventDefault();
      pendingForm = form;
      titleEl.textContent = form.dataset.confirmTitle || "Are you sure?";
      bodyEl.textContent = form.dataset.confirm;
      okBtn.textContent = form.dataset.confirmOk || "Confirm";
      okBtn.className = "btn " + (form.dataset.confirmTone === "primary" ? "btn-primary" : "btn-danger");
      modal.show();
    }, true);

    okBtn.addEventListener("click", function () {
      if (!pendingForm) return;
      pendingForm.dataset.confirmed = "1";
      modal.hide();
      if (typeof pendingForm.requestSubmit === "function") pendingForm.requestSubmit();
      else pendingForm.submit();
    });
    modalEl.addEventListener("hidden.bs.modal", function () {
      if (pendingForm && pendingForm.dataset.confirmed !== "1") pendingForm = null;
    });
  }

  // Disable the submit button and show a spinner so double submissions are avoided.
  function initLoadingButtons() {
    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement) || event.defaultPrevented) return;
      const button = form.querySelector("[data-loading-text]");
      if (!button) return;
      button.disabled = true;
      button.innerHTML = '<span class="spinner-border" aria-hidden="true"></span> ' + button.dataset.loadingText;
    });
  }

  function initPasswordToggles() {
    document.querySelectorAll("[data-password-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const input = document.getElementById(btn.dataset.passwordToggle);
        if (!input) return;
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        btn.querySelector("i").className = show ? "bi bi-eye-slash" : "bi bi-eye";
        btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
      });
    });
  }

  function initSwatches() {
    document.querySelectorAll("[data-swatches]").forEach(function (group) {
      const input = document.getElementById(group.dataset.swatches);
      if (!input) return;
      const sync = function () {
        group.querySelectorAll(".swatch").forEach(function (s) {
          s.setAttribute("aria-pressed", s.dataset.color.toLowerCase() === input.value.toLowerCase() ? "true" : "false");
        });
      };
      group.querySelectorAll(".swatch").forEach(function (s) {
        s.addEventListener("click", function () { input.value = s.dataset.color; sync(); });
      });
      input.addEventListener("input", sync);
      sync();
    });
  }

  // Selects with data-autosubmit submit their form when changed (filters, sorting).
  function initAutoSubmit() {
    document.querySelectorAll("[data-autosubmit]").forEach(function (el) {
      el.addEventListener("change", function () { el.form && el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); });
    });
  }

  function initTooltips() {
    if (!window.bootstrap) return;
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) { bootstrap.Tooltip.getOrCreateInstance(el); });
  }

  function initBackButtons() {
    document.querySelectorAll("[data-history-back]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (window.history.length > 1) window.history.back();
        else window.location.href = "/";
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initBackButtons();
    initToasts();
    initConfirm();
    initLoadingButtons();
    initPasswordToggles();
    initSwatches();
    initAutoSubmit();
    initTooltips();
  });

  window.StudentHub = { cssVar: function (name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); } };
})();
