"""Five-language labels for the message menu of PaynaniWeb's conversations (PRD #685)."""
from ..i18n_data import CATALOGUES

STRINGS = {
    "es-MX": {"you": "Tú", "reply": "Responder", "replying": "Respondiendo a {name}", "remove_quote": "Quitar la cita", "hidden_quote": "Mensaje oculto", "not_loaded": "No encontré el mensaje original en esta conversación.", "quote_missing": "Se mandó sin cita: el original ya no estaba.", "label": "Opciones del mensaje", "copy": "Copiar", "copied": "Copiado",
              "copy_failed": "No se pudo copiar. Selecciona el texto y cópialo a mano."},
    "en-US": {"you": "You", "reply": "Reply", "replying": "Replying to {name}", "remove_quote": "Remove the quote", "hidden_quote": "Hidden message", "not_loaded": "The original message is not in this conversation.", "quote_missing": "Sent without the quote: the original was gone.", "label": "Message options", "copy": "Copy", "copied": "Copied",
              "copy_failed": "Could not copy. Select the text and copy it by hand."},
    "es-ES": {"you": "Tú", "reply": "Responder", "replying": "Respondiendo a {name}", "remove_quote": "Quitar la cita", "hidden_quote": "Mensaje oculto", "not_loaded": "No he encontrado el mensaje original en esta conversación.", "quote_missing": "Se ha enviado sin cita: el original ya no estaba.", "label": "Opciones del mensaje", "copy": "Copiar", "copied": "Copiado",
              "copy_failed": "No se ha podido copiar. Selecciona el texto y cópialo a mano."},
    "fr-FR": {"you": "Vous", "reply": "Répondre", "replying": "Réponse à {name}", "remove_quote": "Retirer la citation", "hidden_quote": "Message masqué", "not_loaded": "Le message d’origine n’est pas dans cette conversation.", "quote_missing": "Envoyé sans citation : l’original n’existait plus.", "label": "Options du message", "copy": "Copier", "copied": "Copié",
              "copy_failed": "Impossible de copier. Sélectionnez le texte et copiez-le à la main."},
    "pt-BR": {"you": "Você", "reply": "Responder", "replying": "Respondendo a {name}", "remove_quote": "Remover a citação", "hidden_quote": "Mensagem oculta", "not_loaded": "Não encontrei a mensagem original nesta conversa.", "quote_missing": "Enviada sem citação: a original não existia mais.", "label": "Opções da mensagem", "copy": "Copiar", "copied": "Copiado",
              "copy_failed": "Não foi possível copiar. Selecione o texto e copie à mão."},
}

for language, words in STRINGS.items():
    assert words.keys() == STRINGS["es-MX"].keys(), language
    CATALOGUES[language].update({"web.msgmenu." + key: value for key, value in words.items()})
