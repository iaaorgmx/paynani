# Cómo se organiza paynani

Quién hace qué en paynani, PaynaniWeb y PaynaniApp, y cómo se decide. Los roles son los de la guía de código abierto [Leadership and Governance](https://opensource.guide/leadership-and-governance/). Los aprobó Julian el 2026-11-03 (Iris[Q39] = A, #686).

La lista de quién tiene cada rol está en PaynaniWeb, en **Acerca de → Development team** (`/about/team`), y en [`scripts/paynani_lib/web/team.json`](scripts/paynani_lib/web/team.json). Aquí sólo van las reglas.

## Quién colabora

Colabora quien hace un commit, abre un issue o un PR, o comenta o revisa uno, en iaaorgmx/paynani o en los repos de PaynaniApp. No hace falta escribir código: un issue, una respuesta a un issue o una prueba real cuentan igual (Julian, 2026-11-03). Pueden colaborar humanos y agentes de IA; de un agente se anota el harness donde corre.

## Los roles

| Rol | Qué es |
|---|---|
| **Maintainer** | Se hace responsable de la dirección de paynani o de una parte. Decide en su parte, revisa y cuida que lo que entra esté bien. |
| **Committer** | Hace PRs que se mezclan con regularidad, en la parte que sea, y sigue lo que cambió hasta que funciona. |
| **Contributor** | Cualquiera que colabora: issues, comentarios, revisiones, pruebas reales o algunos commits. |

Cada Maintainer tiene un alcance:

| Alcance | Qué decide |
|---|---|
| Líder del proyecto | La dirección de paynani: qué se hace, en qué orden y qué PRD se aprueba. Tiene la última palabra. |
| Núcleo de paynani | El núcleo (servicios, canales, instalación). Revisa y mezcla los PRs. |
| PaynaniWeb | La web: `scripts/paynani_lib/web`, `assets`, PAYNANI_WEB.md y sus pruebas. |
| PaynaniApp | La app de Android y su contrato con el núcleo. |

Un Committer también puede tener un alcance, como «Instalación y DevOps» o «Revisiones y pruebas».

## Cómo se decide

1. **Lo grande** (un canal nuevo, un cambio que toca varias partes) lleva un PRD en un issue. El líder del proyecto lo aprueba antes de programar. Las preguntas se le hacen numeradas, con opciones.
2. **Lo de una parte** lo decide su Maintainer, con un issue que diga qué y por qué.
3. **Todo cambio** entra por PR, con `Closes #N`, y lo revisa alguien que no lo escribió. Lo mezcla el Maintainer del núcleo, o el de la parte, cuando las pruebas de CI pasan.
4. **Si no hay acuerdo**, decide el líder del proyecto.

## Cómo se cambia de rol

- **Contributor a Committer:** después de varios PRs mezclados que se sostienen (pruebas, documentación y seguimiento), un Maintainer lo propone en un issue y el líder del proyecto lo aprueba.
- **Committer a Maintainer:** cuando alguien ya se hace cargo de una parte (la revisa, la documenta y responde por ella), el líder del proyecto le da ese alcance.
- **Al revés:** quien deja de colaborar sigue en la lista con el rol que tuvo. Si alguien quiere dejar un rol, lo dice en un issue.

Cada cambio de rol se anota en `team.json`. `scripts/update_team.py` nunca cambia un rol ni quita a nadie: eso lo hace una persona (RELEASING.md §3).
