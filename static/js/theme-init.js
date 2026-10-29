// Loaded synchronously in <head> so the saved theme is applied before first paint.
(function () {
  var theme = null;
  try { theme = localStorage.getItem("studenthub-theme"); } catch (e) { /* storage blocked */ }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  document.documentElement.setAttribute("data-bs-theme", theme);
})();
