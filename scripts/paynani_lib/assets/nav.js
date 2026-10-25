/**
 * The side menu that collapses, like the ServiceButton /dash (PRD #537).
 *
 * Progressive enhancement, like time.js: the server already drew the page open
 * or collapsed from the paynani_web_nav cookie (FR-11), so this file only
 * changes it afterwards. Without it the collapse button stays hidden and ☰ is a
 * plain link to #menu-lateral that :target opens (FR-13, FR-16).
 *
 *   desktop  the button next to the logo collapses the menu, ☰ in the top bar
 *            opens it; the state goes to the cookie (FR-5, FR-6, FR-10)
 *   phone    the menu starts hidden whatever the cookie says; ☰ opens it over
 *            the content, and the backdrop, Esc or a menu entry close it (FR-15)
 */
(function () {
  'use strict';

  var body = document.body;
  var menu = document.getElementById('menu-lateral');
  var collapse = document.querySelector('.web-shell .colapsar');
  var expand = document.querySelector('.web-shell .mostrar');
  var backdrop = document.querySelector('.web-shell .velo');
  if (!menu || !collapse || !expand) {
    return;
  }
  // Same width as the @media of web.css.
  var phone = window.matchMedia('(max-width: 900px)');

  function remember(collapsed) {
    document.cookie = 'paynani_web_nav=' + (collapsed ? 'collapsed' : 'open') +
      '; Path=/; Max-Age=31536000; SameSite=Strict' +
      (location.protocol === 'https:' ? '; Secure' : '');
  }

  function isOpen() {
    return phone.matches ? body.classList.contains('menu-abierto')
                         : !body.classList.contains('menu-colapsado');
  }

  function paint() {
    var open = String(isOpen());
    collapse.setAttribute('aria-expanded', open);
    expand.setAttribute('aria-expanded', open);
  }

  function open() {
    if (phone.matches) {
      body.classList.add('menu-abierto');
    } else {
      body.classList.remove('menu-colapsado');
      remember(false);
    }
    paint();
    collapse.focus();
  }

  function close(keepFocus) {
    if (phone.matches) {
      body.classList.remove('menu-abierto');
    } else {
      body.classList.add('menu-colapsado');
      remember(true);
    }
    paint();
    if (!keepFocus) {
      expand.focus();
    }
  }

  // A #menu-lateral left in the address by the no-script link would keep
  // :target open on top of the classes.
  if (location.hash === '#menu-lateral') {
    history.replaceState(null, '', location.pathname + location.search);
  }

  collapse.hidden = false;
  body.classList.add('con-js');

  collapse.addEventListener('click', function () { close(false); });
  expand.addEventListener('click', function (ev) {
    ev.preventDefault();
    open();
  });
  // ☰ is a link with role="button": Space has to work too (FR-7).
  expand.addEventListener('keydown', function (ev) {
    if (ev.key === ' ') {
      ev.preventDefault();
      open();
    }
  });
  if (backdrop) {
    backdrop.addEventListener('click', function (ev) {
      ev.preventDefault();
      close(false);
    });
  }
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && phone.matches && body.classList.contains('menu-abierto')) {
      close(false);
    }
  });
  // Choosing an entry on the phone closes the menu (the page is about to change).
  menu.addEventListener('click', function (ev) {
    if (phone.matches && ev.target.closest('a')) {
      body.classList.remove('menu-abierto');
    }
  });
  // FR-17: an overlay left open on the phone does not become a collapsed
  // desktop, and the desktop state is the cookie's again.
  phone.addEventListener('change', function () {
    body.classList.remove('menu-abierto');
    paint();
  });
  paint();
})();
