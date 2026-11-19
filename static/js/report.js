/* Report page: clicks-by-device doughnut chart.
   Data comes from the data-devices attribute on the canvas element
   (no inline scripts, so the Content-Security-Policy can stay strict). */
(function () {
  var canvas = document.getElementById("deviceChart");
  if (!canvas || typeof Chart === "undefined") return;
  var devices = [];
  try {
    devices = JSON.parse(canvas.dataset.devices || "[]");
  } catch (e) {
    devices = [];
  }
  if (!devices.length) return;
  new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: devices.map(function (d) { return d.device; }),
      datasets: [{
        data: devices.map(function (d) { return d.count; }),
        backgroundColor: ["#2563eb", "#38bdf8", "#f59e0b", "#94a3b8"]
      }]
    },
    options: { responsive: true, plugins: { legend: { position: "bottom" } } }
  });
})();
