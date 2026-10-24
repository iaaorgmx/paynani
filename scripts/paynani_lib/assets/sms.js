// PaynaniWeb, envío de SMS (PRD #489): el contador de caracteres y de partes debajo
// del texto (FR-4), y los estados de lo enviado desde la web, que se actualizan solos
// (FR-5, FR-7). Sin este script la página funciona igual: el límite lo pone maxlength
// y el servidor vuelve a revisarlo, y los estados se ven al recargar.
(function () {
  "use strict";
  // El alfabeto GSM 7 bits; con cualquier otro carácter el SMS va en UCS-2 (70 por parte).
  var GSM = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡" +
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
  var EXT = "^{}\\[~]|€";

  function parts(text) {
    var units = 0, gsm = true, i, c;
    for (i = 0; i < text.length; i++) {
      c = text.charAt(i);
      if (GSM.indexOf(c) >= 0) { units += 1; }
      else if (EXT.indexOf(c) >= 0) { units += 2; }
      else { gsm = false; break; }
    }
    if (!text.length) { return 0; }
    if (gsm) { return units <= 160 ? 1 : Math.ceil(units / 153); }
    return text.length <= 70 ? 1 : Math.ceil(text.length / 67);
  }

  function wire(area) {
    var out = document.getElementById(area.getAttribute("data-sms-counter"));
    var tpl = area.getAttribute("data-tpl") || "{n} · {parts}";
    if (!out) { return; }
    function update() {
      var text = area.value;
      out.textContent = tpl.replace("{n}", String(text.length)).replace("{parts}", String(parts(text)));
    }
    area.addEventListener("input", update);
    update();
  }

  var areas = document.querySelectorAll("textarea[data-sms-counter]");
  for (var i = 0; i < areas.length; i++) { wire(areas[i]); }

  // Los estados: cada pocos segundos pregunta a /messages/estados. Un estado nuevo se
  // cambia en su lugar; un mensaje nuevo, o que el teléfono se conecte o se desconecte,
  // recarga la página, salvo que haya texto a medio escribir.
  var watch = document.getElementById("sms-watch");
  if (!watch || !window.fetch) { return; }
  var EVERY_MS = 5000;
  var url = watch.getAttribute("data-url");
  var count = parseInt(watch.getAttribute("data-count"), 10) || 0;
  var offline = !!document.getElementById("sms-offline");

  function typing() {
    for (var k = 0; k < areas.length; k++) { if (areas[k].value) { return true; } }
    return false;
  }

  function apply(data) {
    var list = data.items || [], j, span;
    for (j = 0; j < list.length; j++) {
      span = document.querySelector('[data-sms-id="' + list[j].id + '"]');
      if (span && span.textContent !== list[j].label) {
        span.textContent = list[j].label;
        span.className = "estado estado-sms-" + list[j].status;
      }
    }
    if ((data.count !== count || !!data.offline !== offline) && !typing()) {
      window.location.reload();
      return false;
    }
    return true;
  }

  function tick() {
    if (document.hidden) { window.setTimeout(tick, EVERY_MS); return; }
    window.fetch(url, { credentials: "same-origin", cache: "no-store", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        // Sin sesión (o un error) deja de preguntar: la página sigue como está.
        if (data && apply(data)) { window.setTimeout(tick, EVERY_MS); }
      })
      .catch(function () { window.setTimeout(tick, EVERY_MS * 3); });
  }
  window.setTimeout(tick, EVERY_MS);
})();
