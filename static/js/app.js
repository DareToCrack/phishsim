/* Shared UI helpers (loaded on every page via base.html).
   Keeps confirm dialogs out of inline event handlers so the
   Content-Security-Policy can forbid inline scripts. */
(function () {
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.getAttribute) return;
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
    }
  });
})();
