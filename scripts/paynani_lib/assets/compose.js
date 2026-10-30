// PaynaniWeb, «Nuevo correo» (#590 cambio 2): al elegir un contacto de la libreta, su
// dirección se agrega al campo Para, CC o CCO donde estaba el cursor (Para si no había
// ninguno), separada por coma y sin repetirla. Sin este script la libreta se ve igual
// y la dirección se copia a mano; el servidor vuelve a revisar todo.
(function () {
  "use strict";
  var fields = document.querySelectorAll("input[data-libreta]");
  if (!fields.length) { return; }
  var last = fields[0];
  for (var i = 0; i < fields.length; i++) {
    fields[i].addEventListener("focus", function (ev) { last = ev.target; });
  }
  var buttons = document.querySelectorAll("button.contacto-libreta");
  for (var j = 0; j < buttons.length; j++) {
    buttons[j].addEventListener("click", function (ev) {
      var email = ev.currentTarget.getAttribute("data-email");
      var parts = last.value.split(/[,;]/).map(function (p) { return p.trim(); }).filter(Boolean);
      var lower = parts.map(function (p) { return p.toLowerCase(); });
      if (lower.indexOf(email.toLowerCase()) < 0) { parts.push(email); }
      last.value = parts.join(", ");
      last.focus();
    });
  }
})();
