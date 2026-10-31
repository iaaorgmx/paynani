// PaynaniWeb, Dashboard de la página inicial (PRD #602 FR-18): cada 60 s pide
// /dashboard.json (sólo números y estados) y actualiza los indicadores y el estado
// general sin recargar. Si cambió algo que no son números (un servicio, lo que necesita
// atención), muestra «Hay cambios · Actualizar» en vez de recargar solo. Con la pestaña
// oculta no pide nada. Sin este script la página se ve completa al cargarla.
(function () {
  "use strict";
  var root = document.querySelector("[data-dash-src]");
  if (!root || !window.fetch) { return; }
  var src = root.getAttribute("data-dash-src");
  var PERIOD = 60000;
  var first = null;

  function pick(obj, path) {
    return path.split(".").reduce(function (o, k) { return o == null ? o : o[k]; }, obj);
  }
  function setText(key, value) {
    var el = root.querySelector('[data-dash="' + key + '"]');
    if (el && value != null && el.textContent !== String(value)) { el.textContent = String(value); }
  }
  function shape(data) {
    return JSON.stringify([data.services, data.attention]);
  }
  function apply(data) {
    setText("mail_today.received", pick(data, "mail_today.received"));
    setText("open_notices", data.open_notices);
    setText("sms_today.total", (pick(data, "sms_today.in") || 0) + (pick(data, "sms_today.out") || 0));
    setText("roster_count", data.roster_count);
    var status = root.querySelector('[data-dash="status"]');
    if (status) {
      var tone = { ok: "ok", warning: "warn", blocked: "bad" }[data.status] || "warn";
      status.className = status.className.replace(/salud-(ok|warn|bad)/, "salud-" + tone);
      var label = status.getAttribute("data-label-" + data.status);
      if (label) { setText("status.text", label); }
      var tpl = status.getAttribute("data-checks");
      if (tpl) {
        setText("checks", tpl.replace("{ok}", data.checks_ok).replace("{total}", data.checks_total));
      }
    }
    if (first === null) { first = shape(data); return; }
    var changed = root.querySelector(".dash-cambios");
    if (changed && shape(data) !== first) { changed.hidden = false; }
  }
  function tick() {
    if (document.hidden) { return; }
    fetch(src, { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data) { apply(data); } })
      .catch(function () { /* la próxima vuelta lo intenta otra vez */ });
  }
  tick();
  setInterval(tick, PERIOD);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { tick(); } });
})();
