// PaynaniWeb, «Acerca de» (#636): el botón «Copiar» copia la versión con su commit, como
// el chip de la versión en el About de PaynaniApp. Sin este script el botón no se muestra
// y el texto se puede seleccionar.
(function () {
  "use strict";
  var button = document.querySelector("button.about-copiar");
  var text = document.getElementById("about-version");
  if (!button || !text || !navigator.clipboard) { return; }
  var label = button.textContent;
  button.hidden = false;
  button.addEventListener("click", function () {
    navigator.clipboard.writeText(text.textContent.trim()).then(function () {
      button.textContent = button.getAttribute("data-copied");
      setTimeout(function () { button.textContent = label; }, 2000);
    });
  });
})();
