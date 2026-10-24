"use strict";
document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    const source = button.dataset.copy === "secret"
      ? document.querySelector(".token-secret code")
      : document.querySelector(".token-agent-message");
    if (!source) return;
    const value = "value" in source ? source.value : source.textContent;
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const field = document.querySelector(".token-agent-message");
      if (field && button.dataset.copy === "message") {
        field.select();
        document.execCommand("copy");
      }
    }
  });
});
