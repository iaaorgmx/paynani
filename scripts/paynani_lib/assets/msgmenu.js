// PaynaniWeb, el menú al tocar un mensaje (PRD #685, F1: «Copiar»).
//
// Los renglones con menú traen `data-menu` (msgmenu.py): tocar el globo, el clic derecho o
// Enter con el renglón enfocado abren un menú junto al globo, como el de Telegram Web. Tocar un
// enlace, una foto, un archivo o un botón dentro del globo hace lo de siempre, y si la persona
// está seleccionando texto tampoco se abre. Escape, un toque fuera o elegir una opción lo cierran.
// Funciona igual con los mensajes que llegan después (Webchat, «Mensajes anteriores»): todo va
// por delegación en el documento. Los textos vienen en la lista del hilo (`data-msgmenu-*`).
//
// F2, «Responder» (FR-6 a FR-8): sólo si la lista trae `data-msgmenu-reply` (el canal cita) y la
// página tiene el campo `reply_to`. Pone la barra «Respondiendo a…» arriba del cuadro, con una ✕,
// y el ref en el campo. Tocar una cita dentro de un globo lleva al original y lo resalta; si no
// está cargado, pide «Mensajes anteriores» hasta 5 veces.
(function () {
  "use strict";
  var menu = null;       // el menú abierto: {box, row}
  var notice = null;     // el aviso «Copiado»
  var noticeTimer = 0;

  var ICON_COPY = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/>' +
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  var ICON_REPLY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 17 4 12l5-5"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/></svg>';
  var ICON_X = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';

  function words(row) {
    var list = (row && row.closest("ol")) || document.querySelector("ol[data-msgmenu-label]") || document.body;
    function a(name) { return list.getAttribute("data-msgmenu-" + name) || ""; }
    return { label: a("label"), copy: a("copy") || "Copy", copied: a("copied"), failed: a("failed"),
             reply: a("reply"), replying: a("replying"), remove: a("remove"), hidden: a("hidden"), notloaded: a("notloaded") };
  }

  function replyField() { return document.querySelector('form input[name="reply_to"]'); }

  // El texto del mensaje, sin el nombre, el estado ni la hora (FR-5).
  function textOf(row) {
    var parts = [];
    Array.prototype.forEach.call(row.querySelectorAll(".texto, .wa-pie"), function (el) {
      var copy = el.cloneNode(true);   // sin los avisos en gris («sin texto», «[foto]»…)
      Array.prototype.forEach.call(copy.querySelectorAll(".quiet"), function (q) { q.remove(); });
      var t = copy.textContent.replace(/\s+$/, "");
      if (t.trim()) { parts.push(t); }
    });
    return parts.join("\n");
  }

  function close(focusRow) {
    if (!menu) { return; }
    var row = menu.row;
    menu.box.remove();
    row.classList.remove("msj-activo");
    row.setAttribute("aria-expanded", "false");
    menu = null;
    if (focusRow) { row.focus(); }
  }

  function say(text) {
    if (!text) { return; }
    if (!notice) {
      notice = document.createElement("div");
      notice.className = "msj-aviso";
      notice.setAttribute("role", "status");
      document.body.appendChild(notice);
    }
    notice.textContent = text;
    notice.hidden = false;
    window.clearTimeout(noticeTimer);
    noticeTimer = window.setTimeout(function () { notice.hidden = true; }, 2000);
  }

  function fallbackCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (err) { ok = false; }
    area.remove();
    return ok;
  }

  function copy(row) {
    var w = words(row);
    var text = textOf(row);
    close(true);
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { say(w.copied); }, function () {
        say(fallbackCopy(text) ? w.copied : w.failed);
      });
    } else {
      say(fallbackCopy(text) ? w.copied : w.failed);
    }
  }

  function place(box, row) {
    var globo = row.querySelector(".globo") || row;
    var r = globo.getBoundingClientRect();
    var gap = 6, margin = 8;
    var w = box.offsetWidth, h = box.offsetHeight;
    var vw = document.documentElement.clientWidth, vh = window.innerHeight;
    var top = r.bottom + gap;
    if (top + h > vh - margin) { top = Math.max(margin, r.top - gap - h); }   // arriba si abajo no cabe
    var left = row.classList.contains("sms-received") || row.classList.contains("wc-agente") ? r.left : r.right - w;
    left = Math.min(Math.max(margin, left), vw - w - margin);
    box.style.top = top + "px";
    box.style.left = left + "px";
  }

  function open(row) {
    close(false);
    var w = words(row);
    var box = document.createElement("div");
    box.className = "menu-msj";
    box.setAttribute("role", "menu");
    if (w.label) { box.setAttribute("aria-label", w.label); }
    var items = [];
    if (w.reply && row.getAttribute("data-ref") && replyField()) {
      items.push({ label: w.reply, icon: ICON_REPLY, run: function () { close(false); startReply(row); } });
    }
    if (textOf(row)) {
      items.push({ label: w.copy, icon: ICON_COPY, run: function () { copy(row); } });
    }
    if (!items.length) { return; }   // sin opciones no hay menú (una foto sin pie, en F1)
    var list = document.createElement("div");
    list.className = "menu-lista";
    items.forEach(function (it) {
      var b = document.createElement("button");
      b.type = "button";
      b.setAttribute("role", "menuitem");
      b.innerHTML = it.icon;   // un SVG fijo de arriba, nunca texto del mensaje
      var span = document.createElement("span");
      span.textContent = it.label;
      b.appendChild(span);
      b.addEventListener("click", function (ev) { ev.stopPropagation(); it.run(); });
      list.appendChild(b);
    });
    box.appendChild(list);
    document.body.appendChild(box);
    place(box, row);
    row.classList.add("msj-activo");
    row.setAttribute("aria-expanded", "true");
    menu = { box: box, row: row };
    var first = box.querySelector("button");
    if (first) { first.focus({ preventScroll: true }); }
  }

  // ---- F2: responder ------------------------------------------------------------------------
  function clearReply() {
    var field = replyField();
    if (field) { field.value = ""; }
    var bar = document.querySelector(".cita-barra");
    if (bar) { bar.remove(); }
  }

  function showBar(row) {
    var field = replyField();
    if (!field) { return; }
    var w = words(row);
    var bar = document.querySelector(".cita-barra");
    if (!bar) {
      bar = document.createElement("div");
      bar.className = "cita-barra";
      bar.setAttribute("role", "group");
      var form = field.form;
      var anchor = form.querySelector(".wc-barra, .wc-fila, textarea");
      if (anchor && anchor.parentNode === form) { form.insertBefore(bar, anchor); } else { form.insertBefore(bar, form.firstChild); }
    }
    var name = row.getAttribute("data-name") || "";
    var title = (w.replying || "{name}").replace("{name}", name);
    var excerpt = (textOf(row).split("\n")[0] || "").slice(0, 100) || w.hidden;
    bar.innerHTML = ICON_REPLY + "<div><b></b><span></span></div>" +
      '<button type="button" class="cita-quitar">' + ICON_X + "</button>";
    bar.querySelector("b").textContent = title;
    bar.querySelector("span").textContent = excerpt;
    bar.setAttribute("aria-label", title);
    var x = bar.querySelector(".cita-quitar");
    x.setAttribute("aria-label", w.remove);
    x.title = w.remove;
    x.addEventListener("click", function () {
      clearReply();
      var text = field.form.querySelector("textarea");
      if (text) { text.focus(); }
    });
  }

  function startReply(row) {
    var field = replyField();
    if (!field) { return; }
    field.value = row.getAttribute("data-ref") || "";
    showBar(row);
    var text = field.form.querySelector("textarea");
    if (text) { text.focus({ preventScroll: false }); }
  }

  function findRow(ref) {
    var rows = document.querySelectorAll("li[data-ref]");
    for (var i = 0; i < rows.length; i++) { if (rows[i].getAttribute("data-ref") === ref) { return rows[i]; } }
    return null;
  }

  function flash(row) {
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    row.classList.add("msj-resaltado");
    window.setTimeout(function () { row.classList.remove("msj-resaltado"); }, 1600);
  }

  // Tocar una cita: al original; si no está cargado, «Mensajes anteriores» hasta 5 veces (FR-8).
  function goTo(ref, tries) {
    var row = findRow(ref);
    if (row) { flash(row); return; }
    var older = document.querySelector("p.mas a, #wc-antes:not([hidden]) button");
    if (!older || tries >= 5) { say(words(null).notloaded); return; }
    var before = document.querySelectorAll("li[data-ref]").length;
    older.click();
    var waited = 0;
    var timer = window.setInterval(function () {
      waited += 250;
      if (document.querySelectorAll("li[data-ref]").length !== before || waited >= 6000) {
        window.clearInterval(timer);
        goTo(ref, tries + 1);
      }
    }, 250);
  }

  document.addEventListener("click", function (ev) {
    var cita = ev.target.closest && ev.target.closest("a.cita[data-cita]");
    if (!cita) { return; }
    ev.preventDefault();
    ev.stopPropagation();
    goTo(cita.getAttribute("data-cita"), 0);
  }, true);

  // Webchat manda por WebSocket sin recargar: al salir el mensaje se quita la cita.
  document.addEventListener("msgmenu:sent", clearReply);

  // Después de un error, el formulario vuelve con el `reply_to` que traía: se vuelve a ver la barra.
  (function restore() {
    var field = replyField();
    if (field && field.value) {
      var row = findRow(field.value);
      if (row) { showBar(row); } else { field.value = ""; }
    }
  }());

  function rowFrom(target) {
    var row = target && target.closest ? target.closest("li[data-menu]") : null;
    return row && row.querySelector(".globo") ? row : null;
  }

  // Dentro del globo, lo que ya hace algo no abre el menú.
  function interactive(target) {
    return !!(target.closest && target.closest("a, button, img, video, audio, input, textarea, select, label, summary"));
  }

  function selecting() {
    var sel = window.getSelection && window.getSelection();
    return !!(sel && !sel.isCollapsed && String(sel).trim());
  }

  document.addEventListener("click", function (ev) {
    if (menu && !menu.box.contains(ev.target)) {
      var same = rowFrom(ev.target) === menu.row;
      close(false);
      if (same) { return; }   // tocar otra vez el mismo globo sólo lo cierra
    }
    var row = rowFrom(ev.target);
    if (!row || interactive(ev.target) || selecting()) { return; }
    if (!(ev.target.closest(".globo"))) { return; }
    open(row);
  });

  document.addEventListener("contextmenu", function (ev) {
    var row = rowFrom(ev.target);
    if (!row || interactive(ev.target) || !ev.target.closest(".globo")) { return; }
    ev.preventDefault();
    open(row);
  });

  document.addEventListener("keydown", function (ev) {
    if (menu && ev.key === "Escape") { ev.preventDefault(); close(true); return; }
    if (menu && (ev.key === "ArrowDown" || ev.key === "ArrowUp")) {
      var buttons = Array.prototype.slice.call(menu.box.querySelectorAll("button"));
      var i = buttons.indexOf(document.activeElement);
      var next = ev.key === "ArrowDown" ? i + 1 : i - 1;
      if (buttons.length) { ev.preventDefault(); buttons[(next + buttons.length) % buttons.length].focus(); }
      return;
    }
    if (menu && ev.key === "Tab") { close(false); return; }
    var row = ev.target && ev.target.matches && ev.target.matches("li[data-menu]") ? ev.target : null;
    if (row && (ev.key === "Enter" || ev.key === " " || ev.key === "ContextMenu")) {
      ev.preventDefault();
      open(row);
    }
  });

  // Al moverse la página o cambiar de tamaño, el menú quedaría lejos de su globo: se cierra.
  window.addEventListener("scroll", function () { close(false); }, { passive: true });
  window.addEventListener("resize", function () { close(false); });
})();
