/**
 * The time of each message of a mail thread, in the viewer's own time zone
 * (PRD #455 4.4, Julian's Q50 = A).
 *
 * Progressive enhancement, like lang.js: the server already wrote each
 * <time datetime="...Z"> in the host's zone with the page's language, so if this
 * file does not run nothing is missing, only the zone is the host's. When it
 * runs, it rewrites the same shape with Intl in the browser's zone:
 *
 *   today    "12:25 PM (9 minutes ago)"
 *   earlier  "Oct 21, 12:25 PM", with the year when it is another one
 *   title    the full date with the zone, seen on hover
 *
 * The mail and SMS lists (.correos) use it too, with data-corto: today is
 * only the time there, as in Gmail's list.
 *
 * and refreshes the "ago" once a minute.
 */
(function () {
  'use strict';

  var lang = document.documentElement.lang || undefined;

  function ago(seconds) {
    var minutes = Math.max(0, Math.floor(seconds / 60));
    var rtf = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' });
    if (minutes === 0) {
      // "now" / "ahora", like when.py; 'minute' would say "this minute" (review of #460).
      return rtf.format(0, 'second');
    }
    if (minutes < 60) {
      return rtf.format(-minutes, 'minute');
    }
    return rtf.format(-Math.floor(minutes / 60), 'hour');
  }

  function paint() {
    var now = new Date();
    var clock = new Intl.DateTimeFormat(lang, { hour: 'numeric', minute: '2-digit' });
    var nodes = document.querySelectorAll('.mensajes time[datetime], .correos time[datetime]');
    for (var i = 0; i < nodes.length; i++) {
      var node = nodes[i];
      var when = new Date(node.getAttribute('datetime'));
      if (isNaN(when.getTime())) {
        continue;
      }
      var text;
      if (when.toDateString() === now.toDateString()) {
        // In a list (data-corto), only the time, like Gmail's list.
        text = node.hasAttribute('data-corto') ? clock.format(when)
          : clock.format(when) + ' (' + ago((now - when) / 1000) + ')';
      } else {
        var date = { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' };
        if (when.getFullYear() !== now.getFullYear()) {
          date.year = 'numeric';
        }
        text = new Intl.DateTimeFormat(lang, date).format(when);
      }
      node.textContent = text;
      node.title = new Intl.DateTimeFormat(lang, { dateStyle: 'full', timeStyle: 'long' }).format(when);
    }
  }

  function start() {
    try {
      paint();
      setInterval(paint, 60 * 1000);
    } catch (err) {
      // An old browser without Intl.RelativeTimeFormat keeps the server's text.
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
