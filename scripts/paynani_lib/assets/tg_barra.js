// PaynaniWeb, «Mensajes de Telegram»: la barra de escribir es la de Webchat (Julian, Q337).
// El cuadro crece solo mientras se escribe, hasta su max-height (unas 6 líneas), y un
// segundo toque en «Enviar» no manda el mensaje otra vez. Con el clip (#662), las fichas y
// la copia a memoria son las de Webchat (assets/adjuntos.js). Sin script, el cuadro es de
// una línea con scroll y el formulario funciona igual.
(function () {
  "use strict";
  var form = document.querySelector(".tg-escribir");
  var texto = form ? form.querySelector("textarea") : null;
  if (!texto) { return; }
  function grow() {
    texto.style.height = "auto";
    texto.style.height = texto.scrollHeight + 2 + "px";
  }
  texto.addEventListener("input", grow);
  grow();
  var adjuntos = window.paynaniAdjuntos ? window.paynaniAdjuntos(form) : null;
  form.addEventListener("submit", function (ev) {
    if (form.classList.contains("wc-enviando")) { ev.preventDefault(); return; }
    // Sin texto ni archivos no hay nada que mandar (con el clip el cuadro no es required).
    if (!texto.value.trim() && !(adjuntos && adjuntos.hasFiles())) { ev.preventDefault(); texto.focus(); return; }
    if (adjuntos && adjuntos.busy()) { ev.preventDefault(); adjuntos.sendWhenReady(); return; }
    form.classList.add("wc-enviando");
  });
  // Al volver con «Atrás» la página puede salir de la caché con el envío a medias.
  window.addEventListener("pageshow", function () { form.classList.remove("wc-enviando"); });
})();
