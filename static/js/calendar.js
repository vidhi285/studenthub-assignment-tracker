// Monthly calendar backed by GET /api/calendar?month=YYYY-MM (the user's own data only).
(function () {
  "use strict";

  const root = document.getElementById("calendar");
  if (!root) return;

  const grid = root.querySelector("[data-cal-grid]");
  const title = root.querySelector("[data-cal-title]");
  const loading = root.querySelector("[data-cal-loading]");
  const errorBox = root.querySelector("[data-cal-error]");
  const dayPanel = document.getElementById("dayPanel");
  const MAX_ITEMS = 3;
  const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const monthFmt = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
  const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long" });

  let state = { year: 0, month: 0, data: null, selected: null };

  function pad(n) { return String(n).padStart(2, "0"); }
  function iso(y, m, d) { return y + "-" + pad(m) + "-" + pad(d); }
  function monthKey(y, m) { return y + "-" + pad(m); }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function parseMonth(value) {
    const m = /^(\d{4})-(\d{2})$/.exec(value || "");
    return m ? { year: +m[1], month: +m[2] } : null;
  }

  function groupByDate(data) {
    const days = {};
    data.assignments.forEach(function (a) { (days[a.date] = days[a.date] || { a: [], s: [] }).a.push(a); });
    data.sessions.forEach(function (s) { (days[s.date] = days[s.date] || { a: [], s: [] }).s.push(s); });
    return days;
  }

  function assignmentLink(a, compact) {
    const link = el("a", "cal-item" + (a.status === "completed" ? " done" : "") + (a.overdue ? " overdue" : ""));
    link.href = a.url;
    link.style.setProperty("--c", a.color);
    const icon = el("i", "bi " + (a.status === "completed" ? "bi-check-circle-fill" : a.overdue ? "bi-exclamation-circle-fill" : "bi-journal-text"));
    icon.setAttribute("aria-hidden", "true");
    link.appendChild(icon);
    link.appendChild(el("span", "", (a.time && !compact ? a.time + " " : "") + a.title));
    const state = a.status === "completed" ? "completed" : a.overdue ? "overdue" : "due";
    link.setAttribute("aria-label", a.title + ", " + a.subject + ", " + state + (a.time ? " at " + a.time : ""));
    link.addEventListener("click", function (e) { e.stopPropagation(); });
    return link;
  }

  function sessionLink(s) {
    const link = el("a", "cal-item session" + (s.completed ? " done" : ""));
    link.href = s.url;
    link.style.setProperty("--c", s.color);
    const icon = el("i", "bi " + (s.completed ? "bi-check2" : "bi-clock"));
    icon.setAttribute("aria-hidden", "true");
    link.appendChild(icon);
    link.appendChild(el("span", "", s.time + " " + s.title));
    link.setAttribute("aria-label", "Study session " + s.title + " at " + s.time + (s.completed ? ", completed" : ""));
    link.addEventListener("click", function (e) { e.stopPropagation(); });
    return link;
  }

  function renderGrid() {
    const data = state.data;
    const byDate = groupByDate(data);
    grid.replaceChildren();
    WEEKDAYS.forEach(function (d) {
      const head = el("div", "cal-weekday");
      head.appendChild(el("span", "d-none d-md-inline", d));
      head.appendChild(el("span", "d-md-none", d.charAt(0)));
      head.setAttribute("aria-label", d);
      grid.appendChild(head);
    });

    const first = new Date(state.year, state.month - 1, 1);
    const daysInMonth = new Date(state.year, state.month, 0).getDate();
    const leading = (first.getDay() + 6) % 7; // Monday-first grid
    const cells = Math.ceil((leading + daysInMonth) / 7) * 7;

    for (let i = 0; i < cells; i++) {
      const dayNum = i - leading + 1;
      if (dayNum < 1 || dayNum > daysInMonth) {
        const blank = el("div", "cal-day outside");
        blank.setAttribute("aria-hidden", "true");
        grid.appendChild(blank);
        continue;
      }
      const date = iso(state.year, state.month, dayNum);
      const items = byDate[date] || { a: [], s: [] };
      const cell = el("div", "cal-day" + (date === data.today ? " today" : "") + (date === state.selected ? " selected" : ""));
      cell.tabIndex = 0;
      cell.setAttribute("role", "button");
      const count = items.a.length + items.s.length;
      cell.setAttribute("aria-label", dayFmt.format(new Date(state.year, state.month - 1, dayNum)) +
        (count ? ", " + items.a.length + " assignments, " + items.s.length + " study sessions" : ", nothing scheduled"));
      cell.appendChild(el("div", "cal-num", String(dayNum)));

      const all = items.a.map(function (a) { return assignmentLink(a, false); })
        .concat(items.s.map(sessionLink));
      all.slice(0, MAX_ITEMS).forEach(function (node) { cell.appendChild(node); });
      if (all.length > MAX_ITEMS) cell.appendChild(el("div", "cal-more", "+" + (all.length - MAX_ITEMS) + " more"));

      const dots = el("div", "cal-dots");
      items.a.forEach(function (a) {
        const d = el("i", a.overdue ? "overdue" : a.status === "completed" ? "done" : "");
        d.style.setProperty("--c", a.color);
        dots.appendChild(d);
      });
      items.s.forEach(function (s) { const d = el("i", s.completed ? "done" : ""); d.style.setProperty("--c", s.color); dots.appendChild(d); });
      cell.appendChild(dots);

      const select = function () { state.selected = date; renderGrid(); renderDayPanel(); };
      cell.addEventListener("click", select);
      cell.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); } });
      grid.appendChild(cell);
    }
  }

  function renderDayPanel() {
    if (!dayPanel) return;
    const body = dayPanel.querySelector("[data-day-body]");
    const heading = dayPanel.querySelector("[data-day-title]");
    const addLinks = dayPanel.querySelector("[data-day-actions]");
    if (!state.selected || !state.data) { dayPanel.hidden = true; return; }
    const parts = state.selected.split("-").map(Number);
    heading.textContent = dayFmt.format(new Date(parts[0], parts[1] - 1, parts[2]));
    const items = groupByDate(state.data)[state.selected] || { a: [], s: [] };
    body.replaceChildren();
    if (!items.a.length && !items.s.length) {
      body.appendChild(el("p", "text-muted small mb-0", "Nothing scheduled on this day."));
    } else {
      items.a.forEach(function (a) { const row = el("div", "mb-1"); row.appendChild(assignmentLink(a, false)); body.appendChild(row); });
      items.s.forEach(function (s) { const row = el("div", "mb-1"); row.appendChild(sessionLink(s)); body.appendChild(row); });
    }
    const today = state.data.today;
    addLinks.querySelectorAll("[data-add]").forEach(function (a) {
      const base = a.dataset.add;
      if (a.dataset.kind === "assignment" && state.selected < today) { a.hidden = true; return; }
      a.hidden = false;
      a.href = base + (base.indexOf("?") === -1 ? "?" : "&") + (a.dataset.kind === "assignment" ? "due_date=" : "date=") + state.selected;
    });
    dayPanel.hidden = false;
  }

  async function load(year, month) {
    state.year = year; state.month = month;
    title.textContent = monthFmt.format(new Date(year, month - 1, 1));
    loading.hidden = false;
    errorBox.hidden = true;
    try {
      const response = await fetch(root.dataset.api + "?month=" + monthKey(year, month), {
        headers: { "Accept": "application/json" }, credentials: "same-origin"
      });
      if (response.status === 401 || response.redirected) { window.location.reload(); return; }
      if (!response.ok) throw new Error("HTTP " + response.status);
      state.data = await response.json();
      if (!state.selected || state.selected.slice(0, 7) !== monthKey(year, month)) {
        state.selected = state.data.today.slice(0, 7) === monthKey(year, month) ? state.data.today : null;
      }
      renderGrid();
      renderDayPanel();
      const url = new URL(window.location.href);
      url.searchParams.set("month", monthKey(year, month));
      window.history.replaceState(null, "", url);
    } catch (err) {
      errorBox.hidden = false;
    } finally {
      loading.hidden = true;
    }
  }

  function shift(delta) {
    let m = state.month + delta, y = state.year;
    while (m < 1) { m += 12; y -= 1; }
    while (m > 12) { m -= 12; y += 1; }
    state.selected = null;
    load(y, m);
  }

  root.querySelector("[data-cal-prev]").addEventListener("click", function () { shift(-1); });
  root.querySelector("[data-cal-next]").addEventListener("click", function () { shift(1); });
  root.querySelector("[data-cal-today]").addEventListener("click", function () {
    const now = parseMonth(root.dataset.currentMonth);
    state.selected = null;
    load(now.year, now.month);
  });
  root.querySelector("[data-cal-retry]").addEventListener("click", function () { load(state.year, state.month); });

  const initial = parseMonth(root.dataset.initialMonth) || parseMonth(root.dataset.currentMonth);
  load(initial.year, initial.month);
})();
