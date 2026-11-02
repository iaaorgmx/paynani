// Webchat (#648): la conversación en vivo por /webchat/ws (Q309 = A), con la respuesta que
// el agente va escribiendo; si el WebSocket no conecta, polling de /webchat/updates cada
// 3 s. Sin script la página funciona igual: se manda con el formulario y se recarga a mano.
(function () {
  "use strict";
  var page = document.querySelector(".wc-pag[data-after]");
  var hilo = document.getElementById("wc-hilo");
  if (!page || !hilo) { return; }
  var after = page.getAttribute("data-after") || "";
  var escribe = document.getElementById("wc-escribe");
  var borrador = document.getElementById("wc-borrador");
  var form = document.querySelector(".wc-escribir");
  var texto = form ? form.querySelector("textarea[name=text]") : null;
  var csrf = form ? form.querySelector("input[name=csrf]") : null;
  var inputs = Array.prototype.slice.call(document.querySelectorAll("input.wc-archivos"));
  var menu = document.querySelector(".wc-adjuntar");
  var socket = null;
  var pending = {};
  var polling = null;

  function bottom() { window.scrollTo(0, document.body.scrollHeight); }

  function lastDay() {
    var days = hilo.querySelectorAll(".wc-dia");
    return days.length ? days[days.length - 1].getAttribute("data-day") : "";
  }

  function addHtml(html, newAfter) {
    if (!html) { return; }
    var vacio = document.getElementById("wc-vacio");
    if (vacio) { vacio.remove(); }
    escribe.insertAdjacentHTML("beforebegin", html);
    after = newAfter || after;
    bottom();
  }

  function showDraft(text) {
    if (!borrador) { return; }
    if (text === null || text === undefined || text === "") {
      borrador.hidden = true;
      return;
    }
    borrador.querySelector(".texto").textContent = text;
    borrador.hidden = false;
    escribe.hidden = true;
    bottom();
  }

  function showError(message) {
    if (!form) { return; }
    var box = form.querySelector(".error-caja");
    if (!box) {
      box = document.createElement("p");
      box.className = "error-caja";
      box.setAttribute("role", "alert");
      form.insertBefore(box, form.firstChild);
    }
    box.textContent = message;
  }

  // ---- Polling, si el WebSocket no está ------------------------------------------------
  function poll() {
    if (document.hidden) { return; }
    var url = "/webchat/updates?after=" + encodeURIComponent(after) + "&day=" + encodeURIComponent(lastDay());
    fetch(url, {credentials: "same-origin", cache: "no-store"}).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (data) {
      if (!data) { return; }
      addHtml(data.html, data.after);
      escribe.hidden = !data.typing;
    }).catch(function () {});
  }
  function startPolling() {
    if (!polling) { polling = setInterval(poll, 3000); }
  }

  // ---- WebSocket -----------------------------------------------------------------------
  function connect() {
    if (!("WebSocket" in window) || !csrf) { startPolling(); return; }
    var url = (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/webchat/ws";
    var opened = false;
    try { socket = new WebSocket(url); } catch (e) { startPolling(); return; }
    socket.onopen = function () {
      opened = true;
      socket.send(JSON.stringify({type: "connect", csrf: csrf.value, after: after, day: lastDay()}));
    };
    socket.onmessage = function (ev) {
      var data;
      try { data = JSON.parse(ev.data); } catch (e) { return; }
      if (data.type === "connected" && polling) { clearInterval(polling); polling = null; }
      else if (data.type === "messages") { showDraft(null); addHtml(data.html, data.after); }
      else if (data.type === "typing") { escribe.hidden = !data.on || (borrador && !borrador.hidden); }
      else if (data.type === "message.delta") { showDraft(data.text); }
      else if (data.type === "message.accepted") {
        if (pending[data.request_id] && texto) { texto.value = ""; grow(); }
        delete pending[data.request_id];
      } else if (data.type === "error") {
        delete pending[data.request_id];
        showError(data.message || "");
      }
    };
    socket.onclose = function () {
      socket = null;
      // Si nunca abrió (gateway viejo, red), polling; si se cayó, se reintenta en 5 s.
      if (!opened) { startPolling(); } else { startPolling(); setTimeout(connect, 5000); }
    };
  }
  connect();
  bottom();

  // El cuadro crece solo mientras se escribe, hasta su max-height (unas 6 líneas; Q321).
  function grow() {
    if (!texto) { return; }
    texto.style.height = "auto";
    texto.style.height = texto.scrollHeight + 2 + "px";
  }
  if (texto) { texto.addEventListener("input", grow); grow(); }

  // Mandar: el texto solo va por el WebSocket; con archivos, por el formulario (POST).
  if (form) {
    form.addEventListener("submit", function (ev) {
      var hasFiles = inputs.some(function (i) { return i.files && i.files.length; });
      if (!socket || socket.readyState !== 1 || hasFiles || !texto || !texto.value.trim()) { return; }
      ev.preventDefault();
      var id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random();
      pending[id] = true;
      socket.send(JSON.stringify({type: "message.create", request_id: id, content: texto.value}));
    });
  }

  // Los adjuntos elegidos, de «Foto» y de «Archivo»: una ficha por archivo, con una × para
  // quitarlo. Al elegir, el menú del clip se cierra.
  var lista = document.getElementById("wc-adjuntos");
  if (!inputs.length || !lista || typeof DataTransfer === "undefined") { return; }
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
  inputs.forEach(function (input) {
    input.addEventListener("change", function () {
      if (menu) { menu.open = false; }
      render();
    });
  });
}());
