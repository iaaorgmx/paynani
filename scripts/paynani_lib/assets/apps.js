// PaynaniWeb, «Apps conectadas» (#742): el icono de copiar de la dirección y del código, como en
// Business Information de ServiceButtonWebApp, y la cuenta atrás de «Vence en». Sin este script
// los iconos no se muestran, el texto se puede seleccionar y «Vence en» dice los minutos.
(function () {
  "use strict";
  var buttons = document.querySelectorAll("button.icono-copiar[data-copiar]");
  if (navigator.clipboard && window.isSecureContext) {
    Array.prototype.forEach.call(buttons, function (button) {
      var tip = button.querySelector(".tip");
      var label = tip ? tip.textContent : "";
      button.hidden = false;
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(button.getAttribute("data-copiar")).then(function () {
          if (!tip) { return; }
          tip.textContent = button.getAttribute("data-copied");
          button.classList.add("copiado");
          setTimeout(function () { tip.textContent = label; button.classList.remove("copiado"); }, 2000);
        });
      });
    });
  }
  var left = document.querySelector(".apps-vence[data-segundos]");
  if (!left) { return; }
  var end = Date.now() + parseInt(left.getAttribute("data-segundos"), 10) * 1000;
  function tick() {
    var s = Math.max(0, Math.round((end - Date.now()) / 1000));
    left.textContent = Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
    if (s > 0) { setTimeout(tick, 1000); }
  }
  tick();
})();
