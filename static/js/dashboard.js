/* Dashboard funnel chart (Chart.js via CDN).
   Data comes from data-* attributes on the canvas element (no inline
   scripts, so the Content-Security-Policy can stay strict). */
(function () {
  var canvas = document.getElementById("funnelChart");
  if (!canvas || typeof Chart === "undefined") return;
  var d = canvas.dataset;
  var num = function (v) { return parseInt(v, 10) || 0; };
  new Chart(canvas, {
    type: "bar",
    data: {
      labels: ["Sent", "Opened", "Clicked", "Submitted", "Reported"],
      datasets: [{
        data: [num(d.sent), num(d.opened), num(d.clicked), num(d.submitted), num(d.reported)],
        backgroundColor: ["#2563eb", "#38bdf8", "#f59e0b", "#dc2626", "#16a34a"]
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
    }
  });
})();
