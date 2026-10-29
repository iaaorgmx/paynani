// PaynaniWeb, vincular WhatsApp (PRD #550 FR-7, WHATSAPP_BRIDGE.md §11): mientras la
// página del QR o del código esté abierta, pregunta cada 3 s a /whatsapp/link/current.
// Con QR cambia el QR por el vigente (WhatsApp lo rota cada ~20 s); con código sólo
// cuenta el tiempo, porque el código no se vuelve a entregar. Al terminar la
// vinculación abre /whatsapp con GET, que dice cómo terminó (recargar la página del
// código volvería a mandar su formulario). Si nadie pregunta en 60 s, el
// servicio cancela: cerrar la página basta para que el QR deje de valer.
(function () {
  "use strict";
  var box = document.getElementById("wa-qr");
  if (!box || !window.fetch) { return; }
  var EVERY_MS = 3000;
  var url = box.getAttribute("data-url");

  function countdown() {
    var left = box.querySelector("[data-wa-left]");
    if (!left) { return; }
    var s = parseInt(left.getAttribute("data-wa-left"), 10) || 0;
    if (s > 0) { s -= 1; }
    left.setAttribute("data-wa-left", String(s));
    left.textContent = (left.getAttribute("data-tpl") || "{s}").replace("{s}", String(s));
  }

  function ask() {
    fetch(url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : { state: "retry" }; })
      .then(function (data) {
        if (data.state === "ended") { window.location.assign("/whatsapp"); return; }
        if (data.state === "waiting" && typeof data.html === "string") { box.innerHTML = data.html; }
        window.setTimeout(ask, EVERY_MS);
      })
      .catch(function () { window.setTimeout(ask, EVERY_MS); });
  }

  window.setInterval(countdown, 1000);
  window.setTimeout(ask, EVERY_MS);
})();
