"""Five-language labels for the message menu of PaynaniWeb's conversations (PRD #685)."""
from ..i18n_data import CATALOGUES

STRINGS = {
    "es-MX": {"label": "Opciones del mensaje", "copy": "Copiar", "copied": "Copiado",
              "copy_failed": "No se pudo copiar. Selecciona el texto y cópialo a mano."},
    "en-US": {"label": "Message options", "copy": "Copy", "copied": "Copied",
              "copy_failed": "Could not copy. Select the text and copy it by hand."},
    "es-ES": {"label": "Opciones del mensaje", "copy": "Copiar", "copied": "Copiado",
              "copy_failed": "No se ha podido copiar. Selecciona el texto y cópialo a mano."},
    "fr-FR": {"label": "Options du message", "copy": "Copier", "copied": "Copié",
              "copy_failed": "Impossible de copier. Sélectionnez le texte et copiez-le à la main."},
    "pt-BR": {"label": "Opções da mensagem", "copy": "Copiar", "copied": "Copiado",
              "copy_failed": "Não foi possível copiar. Selecione o texto e copie à mão."},
}

for language, words in STRINGS.items():
    assert words.keys() == STRINGS["es-MX"].keys(), language
    CATALOGUES[language].update({"web.msgmenu." + key: value for key, value in words.items()})
