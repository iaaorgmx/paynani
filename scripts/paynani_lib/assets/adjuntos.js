// PaynaniWeb: el clip de la barra de escribir, compartido por Webchat (#648) y «Mensajes de
// Telegram» (#662). Lo usa cada página con `paynaniAdjuntos(form)`, y lo de mandar (WebSocket
// o formulario) se queda en el script de la página.
//
// - El menú del clip («Foto», «Archivo») se cierra al tocar fuera de él o con Esc, como en
//   Telegram (Julian, #656), y al elegir.
// - Una ficha por archivo elegido, con una × para quitarlo.
// - Al elegirlos se copian a memoria: Chrome en Android a veces entrega una foto de Google
//   Fotos como un archivo «en la nube» que cambia antes de subirse, y el envío fallaba con
//   ERR_UPLOAD_FILE_CHANGED (lo vio Julian, #657). Si se toca «Enviar» mientras se copia,
//   `sendWhenReady()` lo manda al terminar.
//
// Sin script, el menú es un <details> que se abre y se cierra con el clip, y los archivos
// se mandan con el formulario.
window.paynaniAdjuntos = function (form) {
  "use strict";
  var api = {
    hasFiles: function () { return false; },
    busy: function () { return false; },
    sendWhenReady: function () {}
  };
  if (!form) { return api; }
  var inputs = Array.prototype.slice.call(form.querySelectorAll("input.wc-archivos"));
  var menu = form.querySelector(".wc-adjuntar");
  var lista = form.querySelector(".wc-adjuntos");
  var copying = 0;          // copias a memoria en curso
  var sendAfterCopy = false;

  if (menu) {
    document.addEventListener("click", function (ev) {
      if (menu.open && !menu.contains(ev.target)) { menu.open = false; }
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
    });
  }

  api.hasFiles = function () { return inputs.some(function (i) { return i.files && i.files.length; }); };
  api.busy = function () { return copying > 0; };
  api.sendWhenReady = function () { sendAfterCopy = true; form.classList.add("wc-enviando"); };

  if (!inputs.length || !lista || typeof DataTransfer === "undefined") { return api; }
  var removeLabel = lista.getAttribute("data-remove") || "{name}";

  function size(n) {
    if (n < 1024) { return n + " B"; }
    if (n < 1048576) { return Math.round(n / 1024) + " KB"; }
    return (n / 1048576).toFixed(1) + " MB";
  }

  function chip(input, file, i) {
    var item = document.createElement("span");
    item.className = "wc-adj";
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
      copy(input);           // lo que queda, a memoria otra vez
    });
    item.appendChild(name);
    item.appendChild(small);
    item.appendChild(quitar);
    return item;
  }

  function render() {
    lista.textContent = "";
    inputs.forEach(function (input) {
      Array.prototype.forEach.call(input.files, function (file, i) { lista.appendChild(chip(input, file, i)); });
    });
  }

  function snapshot(input) {
    var files = Array.prototype.slice.call(input.files);
    if (!files.length || !files[0].arrayBuffer) { return Promise.resolve(); }
    return Promise.all(files.map(function (f) {
      return f.arrayBuffer().then(function (buf) {
        return new File([buf], f.name, {type: f.type, lastModified: f.lastModified});
      }, function () { return f; });
    })).then(function (copies) {
      // Si mientras se copiaba se quitó o se cambió un archivo, la selección ya no es la
      // que se copió: no se toca (revisión de Metis en #657).
      var now = Array.prototype.slice.call(input.files);
      if (now.length !== files.length || now.some(function (f, i) { return f !== files[i]; })) { return; }
      var dt = new DataTransfer();
      copies.forEach(function (c) { dt.items.add(c); });
      input.files = dt.files;
    });
  }

  function copy(input) {
    copying += 1;
    snapshot(input).then(done, done);
    function done() {
      copying -= 1;
      render();
      // Si se tocó «Enviar» mientras se copiaba, se manda ahora.
      if (!copying && sendAfterCopy) {
        sendAfterCopy = false;
        form.classList.remove("wc-enviando");
        if (form.requestSubmit) { form.requestSubmit(); } else { form.submit(); }
      }
    }
  }

  inputs.forEach(function (input) {
    input.addEventListener("change", function () {
      if (menu) { menu.open = false; }
      render();
      copy(input);
    });
  });
  return api;
};
