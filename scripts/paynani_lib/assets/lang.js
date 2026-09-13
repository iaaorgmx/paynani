/**
 * Switch language when the selector changes.
 *
 * Progressive enhancement, in that order on purpose: the page ships a real
 * submit button that works with no scripting at all, and this file hides it and
 * takes over. If the script does not run for any reason, including the
 * Content-Security-Policy refusing it, what is left on screen is the button
 * that still works. The failure mode is one extra click, never a dead control.
 *
 * That matters more than usual here: `noscript` does not help, because a script
 * blocked by CSP still counts as scripting being enabled, so a `noscript`
 * fallback would render nothing and the selector would do nothing.
 */
(function () {
  'use strict';

  function wire() {
    var select = document.getElementById('lang');
    var button = document.getElementById('langgo');
    if (!select || !button) {
      return;
    }
    // Only now, once we know the listener is about to be attached.
    button.hidden = true;
    select.addEventListener('change', function () {
      button.click();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
}());
