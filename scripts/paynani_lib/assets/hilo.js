// PaynaniWeb, las conversaciones de WhatsApp, Telegram y SMS (#680): al abrir, la página baja al
// último mensaje, como Webchat (webchat.js bottom()). Las fotos cargan después y hacen crecer la
// página, así que vuelve a bajar cada vez que una termina de cargar, hasta que la persona mueva la
// página por su cuenta o pasen unos segundos.
//
// - «Mensajes anteriores» abre una página con los mensajes de antes; también abre al final, que es
//   justo el mensaje anterior al primero que ya se veía: la lectura sigue donde iba.
// - Después de enviar, la página vuelve con #responder: el final es el mensaje nuevo.
// - Con otra ancla en la URL (#algo que no es #responder), el navegador manda: no se toca.
(function () {
  "use strict";
  var hilo = document.querySelector("ol.hilo");
  if (!hilo) { return; }
  var hash = window.location.hash;
  if (hash && hash !== "#responder") { return; }

  var WATCH_MS = 8000;           // cuánto tiempo seguir las fotos que cargan tarde
  var stuck = true;              // se suelta si la persona se mueve

  function bottom() { window.scrollTo(0, document.documentElement.scrollHeight); }
  // Sólo un gesto de la persona suelta la vista; crecer la página por una foto no cuenta.
  function release() { stuck = false; }

  ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (ev) {
    window.addEventListener(ev, release, { passive: true });
  });
  Array.prototype.forEach.call(hilo.querySelectorAll("img"), function (img) {
    // Las fotos van con loading="lazy": al bajar al final se piden, y al llegar crecen la página.
    if (!img.complete) {
      img.addEventListener("load", function () { if (stuck) { bottom(); } });
    }
  });
  bottom();
  window.addEventListener("load", function () { if (stuck) { bottom(); } });
  window.setTimeout(function () { stuck = false; }, WATCH_MS);
})();
