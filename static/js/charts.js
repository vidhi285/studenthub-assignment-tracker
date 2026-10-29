// Renders the dashboard and analytics charts from server-calculated data embedded
// in <script id="chart-data" type="application/json">. Charts are re-created when
// the theme changes so colours always match the active theme.
(function () {
  "use strict";

  const dataEl = document.getElementById("chart-data");
  if (!dataEl || !window.Chart) return;
  const data = JSON.parse(dataEl.textContent);
  const charts = [];

  function v(name) { return window.StudentHub.cssVar(name); }

  function alpha(hex, a) {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map(function (c) { return c + c; }).join("") : h, 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  function baseOptions() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 350 },
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 16, color: v("--sh-text-2") } },
        tooltip: {
          backgroundColor: v("--sh-surface"), titleColor: v("--sh-text"), bodyColor: v("--sh-text-2"),
          borderColor: v("--sh-border"), borderWidth: 1, padding: 10, cornerRadius: 8, boxPadding: 4, usePointStyle: true
        }
      },
      scales: {
        x: { grid: { display: false }, border: { color: v("--sh-border") }, ticks: { color: v("--sh-muted"), font: { size: 11 } } },
        y: { beginAtZero: true, grid: { color: v("--sh-chart-grid") }, border: { display: false }, ticks: { color: v("--sh-muted"), font: { size: 11 }, precision: 0 } }
      }
    };
  }

  function weeklyChart(canvas, d) {
    const o = baseOptions();
    o.scales.y.title = { display: true, text: "Study hours", color: v("--sh-muted"), font: { size: 11 } };
    o.scales.y.ticks.precision = undefined;
    o.scales.y1 = { position: "right", beginAtZero: true, grid: { display: false }, border: { display: false },
      ticks: { color: v("--sh-muted"), font: { size: 11 }, precision: 0 },
      title: { display: true, text: "Assignments", color: v("--sh-muted"), font: { size: 11 } } };
    return new Chart(canvas, {
      data: {
        labels: d.labels,
        datasets: [
          { type: "bar", label: "Study hours (completed)", data: d.study_hours, yAxisID: "y",
            backgroundColor: alpha(v("--sh-chart-1"), 0.85), hoverBackgroundColor: v("--sh-chart-1"), borderRadius: 6, maxBarThickness: 34 },
          { type: "line", label: "Assignments completed", data: d.assignments_completed, yAxisID: "y1",
            borderColor: v("--sh-chart-3"), backgroundColor: v("--sh-chart-3"), cubicInterpolationMode: "monotone", pointRadius: 3, pointHoverRadius: 5, borderWidth: 2 }
        ]
      },
      options: o
    });
  }

  function doughnut(canvas, labels, values, colors) {
    return new Chart(canvas, {
      type: "doughnut",
      data: { labels: labels, datasets: [{ data: values, backgroundColor: colors, borderColor: v("--sh-surface"), borderWidth: 3, hoverOffset: 6 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "68%",
        plugins: { legend: baseOptions().plugins.legend, tooltip: baseOptions().plugins.tooltip }
      }
    });
  }

  function subjectChart(canvas, d) {
    const o = baseOptions();
    o.indexAxis = "y";
    o.scales.x = { stacked: true, beginAtZero: true, grid: { color: v("--sh-chart-grid") }, border: { display: false }, ticks: { color: v("--sh-muted"), precision: 0 } };
    o.scales.y = { stacked: true, grid: { display: false }, border: { color: v("--sh-border") }, ticks: { color: v("--sh-text-2") } };
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: d.labels,
        datasets: [
          { label: "Completed", data: d.completed, backgroundColor: d.colors, borderRadius: 4, maxBarThickness: 22 },
          { label: "Remaining", data: d.remaining, backgroundColor: d.colors.map(function (c) { return alpha(c, 0.22); }), borderRadius: 4, maxBarThickness: 22 }
        ]
      },
      options: o
    });
  }

  function workloadChart(canvas, d) {
    const o = baseOptions();
    o.scales.y.title = { display: true, text: "Assignments due", color: v("--sh-muted"), font: { size: 11 } };
    o.scales.y1 = { position: "right", beginAtZero: true, grid: { display: false }, border: { display: false },
      ticks: { color: v("--sh-muted"), font: { size: 11 } },
      title: { display: true, text: "Planned study hours", color: v("--sh-muted"), font: { size: 11 } } };
    return new Chart(canvas, {
      data: {
        labels: d.labels,
        datasets: [
          { type: "bar", label: "Assignments due", data: d.assignments, yAxisID: "y",
            backgroundColor: alpha(v("--sh-chart-4"), 0.85), borderRadius: 6, maxBarThickness: 26 },
          { type: "line", label: "Planned study hours", data: d.study_hours, yAxisID: "y1",
            borderColor: v("--sh-chart-2"), backgroundColor: v("--sh-chart-2"), cubicInterpolationMode: "monotone", pointRadius: 3, borderWidth: 2 }
        ]
      },
      options: o
    });
  }

  function render() {
    while (charts.length) charts.pop().destroy();
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = v("--sh-muted");

    const el = function (id) { return document.getElementById(id); };
    if (el("weeklyChart") && data.weekly) charts.push(weeklyChart(el("weeklyChart"), data.weekly));
    if (el("priorityChart") && data.priority) {
      charts.push(doughnut(el("priorityChart"), data.priority.labels, data.priority.values,
        [v("--sh-chart-3"), v("--sh-chart-4"), v("--sh-chart-5")]));
    }
    if (el("statusChart") && data.status) {
      charts.push(doughnut(el("statusChart"), data.status.labels, data.status.values,
        [v("--sh-chart-3"), v("--sh-chart-2"), v("--sh-border-strong"), v("--sh-chart-5")]));
    }
    if (el("subjectChart") && data.subjects) charts.push(subjectChart(el("subjectChart"), data.subjects));
    if (el("workloadChart") && data.workload) charts.push(workloadChart(el("workloadChart"), data.workload));
  }

  document.addEventListener("DOMContentLoaded", render);
  document.addEventListener("studenthub:themechange", function () { if (charts.length) render(); });
})();
