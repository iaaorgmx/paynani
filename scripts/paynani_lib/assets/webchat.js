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
  // El clip, las fichas y la copia a memoria: assets/adjuntos.js (compartido con Telegram).
  var adjuntos = window.paynaniAdjuntos ? window.paynaniAdjuntos(form) : null;
  var socket = null;
  var pending = {};
  var polling = null;

  function bottom() { window.scrollTo(0, document.body.scrollHeight); }
  // ¿Se está viendo el final de la conversación? Lo dice el último scroll del usuario: una
  // foto que termina de cargar alarga la página sin mover el scroll, y no cuenta como «subir».
  var follow = true;
  function nearBottom() { return window.innerHeight + window.scrollY >= document.body.scrollHeight - 160; }
  window.addEventListener("scroll", function () { follow = nearBottom(); }, {passive: true});
  // Una foto nueva crece al cargar: si se veía el final, se vuelve a bajar.
  hilo.addEventListener("load", function (ev) {
    if (ev.target.tagName === "IMG" && follow) { bottom(); }
  }, true);

  // «Escribiendo…» aparece al final: si se veía el final, la página baja para que la barra de
  // escribir no lo tape (Julian, al mandar una foto desde su celular); si se lee más arriba, no.
  function showTyping(on) {
    var was = escribe.hidden;
    escribe.hidden = !on;
    if (on && was && follow) { bottom(); }
  }

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
      showTyping(!!data.typing);
    }).catch(function () {});
  }
  function startPolling() {
    if (!polling) { polling = setInterval(poll, 3000); }
  }

  // ---- «Mensajes anteriores» (Q336 = A) ------------------------------------------------
  // Los PAGE de antes del primero que se ve, arriba, sin mover lo que se está leyendo: se
  // mide el primer renglón que había antes y después de insertar, y lo mismo cuando una
  // foto de las nuevas termina de cargar (Chrome lo hace solo; Safari no).
  var antes = document.getElementById("wc-antes");
  var antesBtn = antes ? antes.querySelector("button") : null;
  var ancla = null;
  var anclaTop = 0;
  function keepAnchor() {
    if (ancla && ancla.isConnected) {
      window.scrollBy(0, ancla.getBoundingClientRect().top - anclaTop);
      anclaTop = ancla.getBoundingClientRect().top;
    }
  }
  window.addEventListener("scroll", function () {
    if (ancla && ancla.isConnected) { anclaTop = ancla.getBoundingClientRect().top; }
  }, {passive: true});
  if (antesBtn) {
    antesBtn.addEventListener("click", function () {
      if (antesBtn.disabled) { return; }
      var label = antesBtn.textContent;
      antesBtn.disabled = true;
      antesBtn.textContent = antesBtn.getAttribute("data-loading");
      var url = "/webchat/updates?before=" + encodeURIComponent(antes.getAttribute("data-before"));
      fetch(url, {credentials: "same-origin", cache: "no-store"}).then(function (r) {
        return r.ok ? r.json() : null;
      }).then(function (data) {
        antesBtn.disabled = false;
        antesBtn.textContent = label;
        if (!data) { return; }
        var first = antes.nextElementSibling;
        // Se mide también el renglón que sigue al separador, por si el separador sobra.
        var tops = [];
        for (var r = first; r && tops.length < 2; r = r.nextElementSibling) { tops.push(r.getBoundingClientRect().top); }
        var top = tops[0] || 0;
        antes.insertAdjacentHTML("afterend", data.html || "");
        // El último día de lo cargado ya trae su separador: si el primero que había es del
        // mismo día, sobra.
        if (first && first.classList.contains("wc-dia")) {
          for (var el = first.previousElementSibling; el && el !== antes; el = el.previousElementSibling) {
            if (el.classList.contains("wc-dia")) {
              if (el.getAttribute("data-day") === first.getAttribute("data-day")) {
                var next = first.nextElementSibling;
                first.remove();
                first = next;
                top = tops[1] || 0;
              }
              break;
            }
          }
        }
        if (first) {
          ancla = first;
          window.scrollBy(0, first.getBoundingClientRect().top - top);
          anclaTop = first.getBoundingClientRect().top;
          for (var img = antes.nextElementSibling; img && img !== first; img = img.nextElementSibling) {
            Array.prototype.forEach.call(img.querySelectorAll("img"), function (i) {
              if (!i.complete) { i.addEventListener("load", keepAnchor); }
            });
          }
        }
        antes.setAttribute("data-before", data.before || "");
        antes.hidden = !data.more;
      }).catch(function () {
        antesBtn.disabled = false;
        antesBtn.textContent = label;
      });
    });
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
      else if (data.type === "typing") { showTyping(!!data.on && !(borrador && !borrador.hidden)); }
      else if (data.type === "message.delta") { showDraft(data.text); }
      else if (data.type === "message.accepted") {
        delete pending[data.request_id];
      } else if (data.type === "error") {
        // El cuadro se vació al mandar: si no se guardó, el texto regresa (revisión de Metis, #656).
        var lost = pending[data.request_id];
        delete pending[data.request_id];
        if (typeof lost === "string" && texto && !texto.value) { texto.value = lost; grow(); }
        showError(data.message || "");
      }
    };
    socket.onclose = function () {
      socket = null;
      // Si se cerró después de mandar y antes de la respuesta, el texto regresa al cuadro
      // (revisión de Metis en #656).
      var waiting = Object.keys(pending).map(function (k) { return pending[k]; })
        .filter(function (t) { return typeof t === "string"; });
      pending = {};
      if (waiting.length && texto && !texto.value) { texto.value = waiting[waiting.length - 1]; grow(); }
      // Si nunca abrió (gateway viejo, red), polling; si se cayó, se reintenta en 5 s.
      if (!opened) { startPolling(); } else { startPolling(); setTimeout(connect, 5000); }
    };
  }
  connect();
  bottom();

  // #680: al llegar arriba con el scroll, «Mensajes anteriores» se pide solo (el botón sigue
  // ahí, y sin JavaScript no hay nada que cambie). Se empieza a observar ya con la página abajo.
  if (antes && antesBtn && window.IntersectionObserver) {
    var autoAntes = new IntersectionObserver(function (entries) {
      if (entries[0].isIntersecting && !antes.hidden && !antesBtn.disabled) { antesBtn.click(); }
    }, {rootMargin: "200px 0px 0px 0px"});
    setTimeout(function () { autoAntes.observe(antes); }, 300);
  }

  // El cuadro crece solo mientras se escribe, hasta su max-height (unas 6 líneas; Q321).
  function grow() {
    if (!texto) { return; }
    texto.style.height = "auto";
    texto.style.height = texto.scrollHeight + 2 + "px";
  }
  if (texto) { texto.addEventListener("input", grow); grow(); }

  // Mandar: el texto solo va por el WebSocket; con archivos, por el formulario (POST).
  if (form) {
    // Al volver con atrás/adelante (bfcache) el formulario no se queda bloqueado (Metis, #656).
    window.addEventListener("pageshow", function () { form.classList.remove("wc-enviando"); });
    form.addEventListener("submit", function (ev) {
      var hasFiles = !!adjuntos && adjuntos.hasFiles();
      if (!socket || socket.readyState !== 1 || hasFiles || !texto || !texto.value.trim()) {
        // Por el formulario (con archivos, o sin WebSocket): una sola vez. Subir una foto
        // por datos móviles tarda, y un segundo toque la mandaba dos veces (#656).
        if (form.classList.contains("wc-enviando")) { ev.preventDefault(); return; }
        if (adjuntos && adjuntos.busy()) { ev.preventDefault(); adjuntos.sendWhenReady(); return; }
        form.classList.add("wc-enviando");
        return;
      }
      ev.preventDefault();
      var id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()) + Math.random();
      // El cuadro se vacía al mandar, así un segundo toque no manda el mismo texto otra vez.
      pending[id] = texto.value;
      // PRD #685 F2: la cita que puso msgmenu.js, si hay; al salir se quita la barra.
      var cita = form.querySelector('input[name="reply_to"]');
      var packet = {type: "message.create", request_id: id, content: texto.value};
      if (cita && cita.value) { packet.reply_to = cita.value; }
      socket.send(JSON.stringify(packet));
      texto.value = "";
      grow();
      document.dispatchEvent(new CustomEvent("msgmenu:sent"));
    });
  }
}());
