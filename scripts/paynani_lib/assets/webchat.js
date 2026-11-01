// Webchat (#648): los mensajes nuevos sin recargar y la vista previa de los adjuntos.
// Sin script la página funciona igual: se manda con el formulario y se recarga a mano.
(function () {
  "use strict";
  var page = document.querySelector(".wc-pag[data-after]");
  var hilo = document.getElementById("wc-hilo");
  if (!page || !hilo) { return; }
  var after = page.getAttribute("data-after") || "";
  var escribe = document.getElementById("wc-escribe");

  function bottom() { window.scrollTo(0, document.body.scrollHeight); }

  function lastDay() {
    var days = hilo.querySelectorAll(".wc-dia");
    return days.length ? days[days.length - 1].getAttribute("data-day") : "";
  }

  // Cada 3 s, sólo con la pestaña visible (#648, punto abierto 1).
  function poll() {
    if (document.hidden) { return; }
    var url = "/webchat/updates?after=" + encodeURIComponent(after) + "&day=" + encodeURIComponent(lastDay());
    fetch(url, {credentials: "same-origin", cache: "no-store"}).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (data) {
      if (!data) { return; }
      if (data.html) {
        var vacio = document.getElementById("wc-vacio");
        if (vacio) { vacio.remove(); }
        escribe.insertAdjacentHTML("beforebegin", data.html);
        after = data.after || after;
        bottom();
      }
      escribe.hidden = !data.typing;
    }).catch(function () {});
  }
  setInterval(poll, 3000);
  bottom();

  // Los adjuntos elegidos: una ficha por archivo, con una × para quitarlo.
  var input = document.getElementById("wc-archivos");
  var lista = document.getElementById("wc-adjuntos");
  if (!input || !lista || typeof DataTransfer === "undefined") { return; }
  var removeLabel = lista.getAttribute("data-remove") || "{name}";

  function size(n) {
    if (n < 1024) { return n + " B"; }
    if (n < 1048576) { return Math.round(n / 1024) + " KB"; }
    return (n / 1048576).toFixed(1) + " MB";
  }

  function render() {
    lista.textContent = "";
    Array.prototype.forEach.call(input.files, function (file, i) {
      var chip = document.createElement("span");
      chip.className = "wc-adj";
      var name = document.createElement("span");
      name.textContent = file.name;
      var small = document.createElement("small");
      small.textContent = size(file.size);
      var quitar = document.createElement("button");
      quitar.type = "button";
      quitar.textContent = "×";
      quitar.setAttribute("aria-label", removeLabel.replace("{name}", file.name));
      quitar.addEventListener("click", function () {
        var dt = new DataTransfer();
        Array.prototype.forEach.call(input.files, function (f, j) { if (j !== i) { dt.items.add(f); } });
        input.files = dt.files;
        render();
      });
      chip.appendChild(name);
      chip.appendChild(small);
      chip.appendChild(quitar);
      lista.appendChild(chip);
    });
  }
  input.addEventListener("change", render);
}());
