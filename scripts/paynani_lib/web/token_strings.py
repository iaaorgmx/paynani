"""Five-language labels for the API token owner screen."""
from ..i18n_data import CATALOGUES

WORDS = {
    "es-MX": ["Tokens API", "Crear token", "Buscar nombre o prefijo", "Estado", "Aplicar", "Todos", "Nombre", "Permisos", "Creado", "Vence", "Último uso", "Activo", "Vencido", "Revocado", "Sin tokens", "Nunca", "Fecha personalizada", "Fecha personalizada (UTC)", "SMS por hora", "SMS por día", "SMS usados hoy (UTC)", "Permitir respuestas del agente", "Contraseña de PaynaniWeb", "Copiar", "El token se muestra una sola vez. Guárdalo ahora.", "Token creado.", "Mensaje para el agente", "Vuelve a la lista", "Guardar", "Revocar token", "Cambios guardados.", "Sí", "No", "Datos inválidos.", "Token no encontrado o ya revocado.", "Entrega este token al agente: {token}\nVence (UTC): {expires}\nGuía de API: {url}"],
    "en-US": ["API Tokens", "Create token", "Search name or prefix", "Status", "Apply", "All", "Name", "Permissions", "Created", "Expires", "Last used", "Active", "Expired", "Revoked", "No tokens", "Never", "Custom date", "Custom date (UTC)", "SMS per hour", "SMS per day", "SMS used today (UTC)", "Allow agent replies", "PaynaniWeb password", "Copy", "The token is shown only once. Save it now.", "Token created.", "Message for the agent", "Back to list", "Save", "Revoke token", "Changes saved.", "Yes", "No", "Invalid values.", "Token not found or already revoked.", "Give this token to the agent: {token}\nExpires (UTC): {expires}\nAPI guide: {url}"],
    "es-ES": ["Tokens API", "Crear token", "Buscar nombre o prefijo", "Estado", "Aplicar", "Todos", "Nombre", "Permisos", "Creado", "Caduca", "Último uso", "Activo", "Caducado", "Revocado", "Sin tokens", "Nunca", "Fecha personalizada", "Fecha personalizada (UTC)", "SMS por hora", "SMS por día", "SMS usados hoy (UTC)", "Permitir respuestas del agente", "Contraseña de PaynaniWeb", "Copiar", "El token se muestra una sola vez. Guárdalo ahora.", "Token creado.", "Mensaje para el agente", "Volver a la lista", "Guardar", "Revocar token", "Cambios guardados.", "Sí", "No", "Valores no válidos.", "Token no encontrado o ya revocado.", "Entrega este token al agente: {token}\nCaduca (UTC): {expires}\nGuía de API: {url}"],
    "fr-FR": ["Jetons API", "Créer un jeton", "Chercher un nom ou préfixe", "Statut", "Appliquer", "Tous", "Nom", "Permissions", "Créé", "Expire", "Dernière utilisation", "Actif", "Expiré", "Révoqué", "Aucun jeton", "Jamais", "Date personnalisée", "Date personnalisée (UTC)", "SMS par heure", "SMS par jour", "SMS utilisés aujourd’hui (UTC)", "Autoriser les réponses de l’agent", "Mot de passe PaynaniWeb", "Copier", "Le jeton ne s’affiche qu’une fois. Enregistrez-le maintenant.", "Jeton créé.", "Message pour l’agent", "Retour à la liste", "Enregistrer", "Révoquer le jeton", "Modifications enregistrées.", "Oui", "Non", "Valeurs invalides.", "Jeton introuvable ou déjà révoqué.", "Donnez ce jeton à l’agent : {token}\nExpire (UTC) : {expires}\nGuide API : {url}"],
    "pt-BR": ["Tokens de API", "Criar token", "Buscar nome ou prefixo", "Status", "Aplicar", "Todos", "Nome", "Permissões", "Criado", "Expira", "Último uso", "Ativo", "Expirado", "Revogado", "Sem tokens", "Nunca", "Data personalizada", "Data personalizada (UTC)", "SMS por hora", "SMS por dia", "SMS usados hoje (UTC)", "Permitir respostas do agente", "Senha do PaynaniWeb", "Copiar", "O token aparece uma única vez. Guarde-o agora.", "Token criado.", "Mensagem para o agente", "Voltar à lista", "Salvar", "Revogar token", "Alterações salvas.", "Sim", "Não", "Valores inválidos.", "Token não encontrado ou já revogado.", "Entregue este token ao agente: {token}\nExpira (UTC): {expires}\nGuia da API: {url}"],
}
KEYS = ["title", "create", "search", "status", "apply", "all", "name", "permissions", "created", "expires", "last_used", "status.active", "status.expired", "status.revoked", "empty", "never", "custom", "custom_utc", "hour", "day", "used_today", "agent_replies", "password", "copy", "once", "created_ok", "agent_message_label", "back", "save", "revoke", "saved", "yes", "no", "invalid", "missing", "agent_message"]
for language, words in WORDS.items():
    assert len(KEYS) == len(words)
    CATALOGUES[language].update({"web.tokens." + key: value for key, value in zip(KEYS, words)})
    CATALOGUES[language]["web.tokens.prefix"] = "Préfixe" if language == "fr-FR" else ("Prefixo" if language == "pt-BR" else ("Prefix" if language == "en-US" else "Prefijo"))
    CATALOGUES[language]["web.tokens.filter"] = {"es-MX": "Filtrar", "en-US": "Filter", "es-ES": "Filtrar", "fr-FR": "Filtrer", "pt-BR": "Filtrar"}[language]
    CATALOGUES[language]["web.tokens.agent_replies"] = {"es-MX": "El agente local contesta las respuestas", "en-US": "Local agent replies to responses", "es-ES": "El agente local contesta las respuestas", "fr-FR": "L’agent local répond aux réponses", "pt-BR": "O agente local responde às respostas"}[language]
    # PRD #535 FR-P3 y #576 FR-13b: lo que deja hacer cada permiso del Catch-All, junto a sus casillas.
    CATALOGUES[language]["web.tokens.catchall_hint"] = {
        "es-MX": "catchall.sms.write, catchall.whatsapp.write y catchall.telegram.write dejan que este token active el Catch-All de ese canal, y entonces tu agente leerá los mensajes de ese canal de quien no está en el roster.",
        "en-US": "catchall.sms.write, catchall.whatsapp.write and catchall.telegram.write let this token turn on that channel's Catch-All, and then your agent will read that channel's messages from senders who are not on the roster.",
        "es-ES": "catchall.sms.write, catchall.whatsapp.write y catchall.telegram.write permiten que este token active el Catch-All de ese canal, y entonces tu agente leerá los mensajes de ese canal de quien no está en el roster.",
        "fr-FR": "catchall.sms.write, catchall.whatsapp.write et catchall.telegram.write permettent à ce jeton d’activer le Catch-All de ce canal : votre agent lira alors les messages de ce canal venant d’expéditeurs absents du roster.",
        "pt-BR": "catchall.sms.write, catchall.whatsapp.write e catchall.telegram.write deixam este token ativar o Catch-All desse canal, e então seu agente lerá as mensagens desse canal de quem não está no roster.",
    }[language]


# El detalle de un token (#760, mockup aprobado por Julian, Iris[Q72]=A): cabecera, tarjetas
# y «Delete this token» para los vencidos o revocados.
DETAIL = {
    "es-MX": {
        "sec.details": "Detalles", "sec.limits": "Límites de SMS", "sec.agent": "Agente",
        "per_hour": "por hora", "per_day": "por día", "sent_today": "enviados hoy (UTC)",
        "line.expires": "Vence el {when} · {rel}", "line.expired": "Venció el {when} · {rel}",
        "line.revoked": "Revocado el {when}", "line.never": "No vence",
        "rel.today": "hoy", "rel.in_days": "en {n} días", "rel.in_day": "mañana",
        "rel.days_ago": "hace {n} días", "rel.day_ago": "ayer",
        "readonly": "Los ajustes no se pueden cambiar en un token que ya no está activo.",
        "revoke_title": "Revocar este token",
        "revoke_hint": "Todo lo que lo use deja de funcionar de inmediato. Un token revocado se puede borrar después.",
        "delete_title": "Borrar este token",
        "delete_hint": "Ya nada que lo use funciona. Borrarlo lo quita de esta lista para siempre. La bitácora de la API conserva su prefijo y lo que hizo.",
        "delete": "Borrar token", "deleted": "Token borrado.",
        "delete_active": "Este token sigue activo: primero revócalo.",
    },
    "en-US": {
        "sec.details": "Details", "sec.limits": "SMS limits", "sec.agent": "Agent",
        "per_hour": "per hour", "per_day": "per day", "sent_today": "sent today (UTC)",
        "line.expires": "Expires {when} · {rel}", "line.expired": "Expired {when} · {rel}",
        "line.revoked": "Revoked {when}", "line.never": "Never expires",
        "rel.today": "today", "rel.in_days": "in {n} days", "rel.in_day": "tomorrow",
        "rel.days_ago": "{n} days ago", "rel.day_ago": "yesterday",
        "readonly": "Settings can’t be changed on a token that is no longer active.",
        "revoke_title": "Revoke this token",
        "revoke_hint": "Anything that uses it stops working right away. A revoked token can then be deleted.",
        "delete_title": "Delete this token",
        "delete_hint": "Nothing that uses it works any more. Deleting removes it from this list for good. The API log keeps its prefix and what it did.",
        "delete": "Delete token", "deleted": "Token deleted.",
        "delete_active": "This token is still active: revoke it first.",
    },
    "es-ES": {
        "sec.details": "Detalles", "sec.limits": "Límites de SMS", "sec.agent": "Agente",
        "per_hour": "por hora", "per_day": "por día", "sent_today": "enviados hoy (UTC)",
        "line.expires": "Caduca el {when} · {rel}", "line.expired": "Caducó el {when} · {rel}",
        "line.revoked": "Revocado el {when}", "line.never": "No caduca",
        "rel.today": "hoy", "rel.in_days": "dentro de {n} días", "rel.in_day": "mañana",
        "rel.days_ago": "hace {n} días", "rel.day_ago": "ayer",
        "readonly": "Los ajustes no se pueden cambiar en un token que ya no está activo.",
        "revoke_title": "Revocar este token",
        "revoke_hint": "Todo lo que lo use deja de funcionar de inmediato. Un token revocado se puede borrar después.",
        "delete_title": "Borrar este token",
        "delete_hint": "Ya nada que lo use funciona. Borrarlo lo quita de esta lista para siempre. El registro de la API conserva su prefijo y lo que hizo.",
        "delete": "Borrar token", "deleted": "Token borrado.",
        "delete_active": "Este token sigue activo: primero revócalo.",
    },
    "fr-FR": {
        "sec.details": "Détails", "sec.limits": "Limites de SMS", "sec.agent": "Agent",
        "per_hour": "par heure", "per_day": "par jour", "sent_today": "envoyés aujourd’hui (UTC)",
        "line.expires": "Expire le {when} · {rel}", "line.expired": "A expiré le {when} · {rel}",
        "line.revoked": "Révoqué le {when}", "line.never": "N’expire jamais",
        "rel.today": "aujourd’hui", "rel.in_days": "dans {n} jours", "rel.in_day": "demain",
        "rel.days_ago": "il y a {n} jours", "rel.day_ago": "hier",
        "readonly": "Les réglages ne peuvent pas être modifiés sur un jeton qui n’est plus actif.",
        "revoke_title": "Révoquer ce jeton",
        "revoke_hint": "Tout ce qui l’utilise cesse de fonctionner tout de suite. Un jeton révoqué peut ensuite être supprimé.",
        "delete_title": "Supprimer ce jeton",
        "delete_hint": "Plus rien de ce qui l’utilise ne fonctionne. Le supprimer le retire définitivement de cette liste. Le journal de l’API garde son préfixe et ce qu’il a fait.",
        "delete": "Supprimer le jeton", "deleted": "Jeton supprimé.",
        "delete_active": "Ce jeton est encore actif : révoquez-le d’abord.",
    },
    "pt-BR": {
        "sec.details": "Detalhes", "sec.limits": "Limites de SMS", "sec.agent": "Agente",
        "per_hour": "por hora", "per_day": "por dia", "sent_today": "enviados hoje (UTC)",
        "line.expires": "Expira em {when} · {rel}", "line.expired": "Expirou em {when} · {rel}",
        "line.revoked": "Revogado em {when}", "line.never": "Não expira",
        "rel.today": "hoje", "rel.in_days": "em {n} dias", "rel.in_day": "amanhã",
        "rel.days_ago": "há {n} dias", "rel.day_ago": "ontem",
        "readonly": "Os ajustes não podem ser alterados em um token que não está mais ativo.",
        "revoke_title": "Revogar este token",
        "revoke_hint": "Tudo o que o usa para de funcionar na hora. Um token revogado pode ser apagado depois.",
        "delete_title": "Apagar este token",
        "delete_hint": "Nada que o use funciona mais. Apagar o remove desta lista para sempre. O registro da API guarda o prefixo e o que ele fez.",
        "delete": "Apagar token", "deleted": "Token apagado.",
        "delete_active": "Este token ainda está ativo: revogue-o primeiro.",
    },
}
for language, words in DETAIL.items():
    CATALOGUES[language].update({"web.tokens." + key: value for key, value in words.items()})
