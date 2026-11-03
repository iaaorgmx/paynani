// PaynaniWeb, las conversaciones de WhatsApp, Telegram y SMS (#680).
//
// 1. Al abrir, la página baja al último mensaje, como Webchat (webchat.js bottom()). Las fotos
//    cargan después y hacen crecer la página, así que vuelve a bajar cada vez que una termina de
//    cargar, hasta que la persona haga un gesto (tocar, rueda, teclado) o pasen unos segundos.
//    Después de enviar, la página vuelve con #responder: el final es el mensaje nuevo. Con otra
//    ancla en la URL, el navegador manda y no se toca nada.
// 2. Al llegar arriba con el scroll se cargan solos los mensajes anteriores (20, como la página):
//    se pide la misma URL que el enlace «Mensajes anteriores», se toman sus renglones y su nuevo
//    enlace, y se ponen arriba sin mover lo que se está leyendo (se mide el primer renglón antes y
//    después de insertar, y otra vez cuando una foto de las nuevas termina de cargar; Chrome lo
//    hace solo, Safari no). El enlace se queda como respaldo sin JavaScript.
(function () {
  "use strict";
  var hilo = document.querySelector("ol.hilo");
  if (!hilo) { return; }

  // ---- 1. Abrir en el último mensaje -----------------------------------------------------
  var hash = window.location.hash;
  var follow = !(hash && hash !== "#responder");
  var WATCH_MS = 8000;           // cuánto tiempo seguir las fotos que cargan tarde
  var stuck = follow;            // se suelta con el primer gesto de la persona

  function bottom() { window.scrollTo(0, document.documentElement.scrollHeight); }
  function release() { stuck = false; }
  ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (ev) {
    window.addEventListener(ev, release, { passive: true });
  });
  if (follow) {
    Array.prototype.forEach.call(hilo.querySelectorAll("img"), function (img) {
      // Las fotos van con loading="lazy": al bajar al final se piden, y al llegar crecen la página.
      if (!img.complete) { img.addEventListener("load", function () { if (stuck) { bottom(); } }); }
    });
    bottom();
    window.addEventListener("load", function () { if (stuck) { bottom(); } });
  }
  window.setTimeout(release, WATCH_MS);

  // ---- 2. Cargar los anteriores al llegar arriba -----------------------------------------
  var mas = hilo.previousElementSibling;
  while (mas && !(mas.classList && mas.classList.contains("mas"))) { mas = mas.previousElementSibling; }
  if (!mas || !window.fetch || !window.DOMParser || !window.IntersectionObserver) { return; }
  var loading = false;
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
  }, { passive: true });

  var observer = new IntersectionObserver(function (entries) {
    if (entries[0].isIntersecting) { older(); }
  }, { rootMargin: "200px 0px 0px 0px" });

  function older() {
    var link = mas && mas.querySelector("a[href]");
    if (loading || !link) { return; }
    loading = true;
    stuck = false;               // ya se está leyendo hacia arriba: no volver al final
    mas.classList.add("cargando");
    fetch(link.getAttribute("href"), { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.text() : null; })
      .then(function (html) {
        loading = false;
        mas.classList.remove("cargando");
        if (!html) { return; }
        var doc = new DOMParser().parseFromString(html, "text/html");
        var nuevos = doc.querySelectorAll("ol.hilo > li");
        var first = hilo.firstElementChild;
        var top = first ? first.getBoundingClientRect().top : 0;
        var frag = document.createDocumentFragment();
        Array.prototype.forEach.call(nuevos, function (li) { frag.appendChild(document.importNode(li, true)); });
        hilo.insertBefore(frag, first);
        if (first) {
          ancla = first;
          window.scrollBy(0, first.getBoundingClientRect().top - top);
          anclaTop = first.getBoundingClientRect().top;
          for (var li = hilo.firstElementChild; li && li !== first; li = li.nextElementSibling) {
            Array.prototype.forEach.call(li.querySelectorAll("img"), function (i) {
              if (!i.complete) { i.addEventListener("load", keepAnchor); }
            });
          }
        }
        // El enlace nuevo apunta a los de antes de éstos; sin él, ya no hay más.
        var siguiente = doc.querySelector("p.mas a[href]");
        if (siguiente) {
          mas.querySelector("a").setAttribute("href", siguiente.getAttribute("href"));
          // Si todavía se ve arriba (los nuevos no llenaron la pantalla), seguir pidiendo.
          observer.unobserve(mas);
          observer.observe(mas);
        } else {
          observer.disconnect();
          mas.remove();
          mas = null;
        }
      })
      .catch(function () { loading = false; if (mas) { mas.classList.remove("cargando"); } });
  }

  // Se empieza a observar ya con la página abajo: al abrir, el enlace no debe contar como «llegar arriba».
  window.setTimeout(function () { if (mas) { observer.observe(mas); } }, follow ? 300 : 0);
  // El enlace sigue sirviendo con un clic, sin salir de la página.
  mas.querySelector("a").addEventListener("click", function (ev) { ev.preventDefault(); older(); });
})();
