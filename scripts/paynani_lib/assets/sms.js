// PaynaniWeb, envío de SMS (PRD #489 FR-4): el contador de caracteres y de partes
// debajo del texto. Sin este script la página funciona igual; el límite lo pone
// maxlength y el servidor vuelve a revisarlo.
(function () {
  "use strict";
  // El alfabeto GSM 7 bits; con cualquier otro carácter el SMS va en UCS-2 (70 por parte).
  var GSM = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡" +
    "ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
  var EXT = "^{}\\[~]|€";

  function parts(text) {
    var units = 0, gsm = true, i, c;
    for (i = 0; i < text.length; i++) {
      c = text.charAt(i);
      if (GSM.indexOf(c) >= 0) { units += 1; }
      else if (EXT.indexOf(c) >= 0) { units += 2; }
      else { gsm = false; break; }
    }
    if (!text.length) { return 0; }
    if (gsm) { return units <= 160 ? 1 : Math.ceil(units / 153); }
    return text.length <= 70 ? 1 : Math.ceil(text.length / 67);
  }

  function wire(area) {
    var out = document.getElementById(area.getAttribute("data-sms-counter"));
    var tpl = area.getAttribute("data-tpl") || "{n} · {parts}";
    if (!out) { return; }
    function update() {
      var text = area.value;
      out.textContent = tpl.replace("{n}", String(text.length)).replace("{parts}", String(parts(text)));
    }
    area.addEventListener("input", update);
    update();
  }

  var areas = document.querySelectorAll("textarea[data-sms-counter]");
  for (var i = 0; i < areas.length; i++) { wire(areas[i]); }
})();
