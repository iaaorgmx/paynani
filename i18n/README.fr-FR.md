<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

[Español (MX)](../README.md) · [English (US)](README.en-US.md) · [Español (ES)](README.es-ES.md) · **Français (FR)** · [Português (BR)](README.pt-BR.md)

Paynani est un pont de messagerie pour agents IA.

Il donne à votre agent sa propre boîte aux lettres, détecte les nouveaux courriels
en quelques secondes et livre chaque événement par un chemin supervisé, sans
perdre les messages en silence et sans transformer n’importe quel courriel en
instruction autorisée.

Avec Paynani, votre agent peut :

- savoir quand un nouveau courriel arrive ;
- lire et répondre depuis sa propre boîte ;
- agir seulement lorsque l’expéditeur correspond à votre `roster.md`.

Paynani ne remplace pas votre jugement et n’authentifie pas magiquement la
personne qui écrit : il sépare la notification de courriel, l’autorisation
opérationnelle et la livraison au runtime pour que l’échec ne soit pas silencieux.

## À qui cela s’adresse

Paynani s’adresse aux personnes qui veulent donner un vrai courriel à un agent IA
sans mêler leur boîte personnelle, leurs mots de passe ni leurs décisions de
confiance à une conversation de chat.

Utilisez-le si vous voulez qu’un agent :

- reçoive des tâches par courriel ;
- vous avertisse quand quelque chose d’important arrive ;
- réponde depuis son propre compte ;
- refuse le travail ou les envois qui ne figurent pas dans une liste explicite de
  personnes et de notificateurs autorisés.

Il ne sert pas à déléguer le jugement humain à chaque message reçu. Le courriel
est une entrée non fiable ; `roster.md` définit qui peut créer du travail.

## Avant de commencer

Vous avez besoin de trois choses :

1. une boîte dédiée à l’agent, pas votre courriel personnel ;
2. une façon sûre d’écrire les identifiants dans `.env` sans les coller dans le chat ;
3. une liste `roster.md` avec les personnes ou notificateurs qui peuvent créer du travail.

> [!CAUTION]
> Ne collez jamais de mots de passe de messagerie dans un chat. Utilisez
> `MAILBOX_SETUP.md` ou le formulaire `scripts/setup_web.sh` pour que l’agent ne
> voie pas les secrets.

> [!WARNING]
> `roster.md` autorise du travail ; il ne prouve pas l’identité cryptographique.
> Un courriel non listé peut être signalé, mais ne doit pas devenir une tâche.

> [!IMPORTANT]
> Une file vide ne prouve pas que Paynani est sain. `scripts/healthcheck.py`
> vérifie le listener, le dispatcher, les identifiants, le runtime et le curseur.

## Configurez-le en trois étapes

La première étape vous revient, la deuxième est une instruction à coller et la
troisième consiste en deux tests humains. Les détails opérationnels pour l’agent
se trouvent dans [`AGENTS.md`](../AGENTS.md), [`INSTALL.md`](../INSTALL.md) et
[`HERMES.md`](../HERMES.md).

### 1. Donnez-lui une boîte aux lettres

Créez un compte de messagerie pour l’agent et écrivez ses paramètres de connexion
dans un fichier `.env`. Si votre agent tourne sous un harness, ce `.env` va dans
le workspace du harness (`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env` ou `~/.codex/workspace/.env`). Sur un hôte sans
harness, il peut vivre dans le clone.

[`MAILBOX_SETUP.fr-FR.md`](MAILBOX_SETUP.fr-FR.md) explique quel compte utiliser,
où trouver le serveur IMAP/SMTP et comment écrire le fichier sans exposer le mot
de passe à l’agent.

Faites cette étape vous-même. Si l’agent demande le mot de passe dans le chat,
refusez.

### 2. Collez l’instruction à votre agent

Collez ceci à votre agent pour lui déléguer l’installation avec des limites claires :

```text
Vérifiez les paramètres de votre
compte de messagerie ; ils se
trouvent dans le dossier
workspace du répertoire
d'installation de votre Harness.

../workspace/.env

Installez ensuite ce dépôt pour
pouvoir l'utiliser :
https://github.com/iaaorgmx/paynani

Suivez les instructions du
fichier AGENTS.md du dépôt.

Vous aurez besoin de mon nom et
de mon adresse e-mail pour le
fichier roster.md.

Demandez-moi tout ce dont vous
avez besoin.
```

L’agent doit installer depuis le dépôt, demander seulement les informations
humaines manquantes et refuser de recevoir des secrets dans le chat.

### 3. Faites deux tests humains

L’agent exécute sa propre vérification, mais ces deux tests valident ce que vous
devez voir.

**Test des accents.** Envoyez-lui un courriel depuis votre adresse autorisée avec
un objet comme `Test : é, à, ç, ça va ?`, puis demandez-lui ce qui vient
d’arriver. Il doit détecter le message en quelques secondes et afficher l’objet de
façon lisible, pas sous la forme `=?utf-8?q?...`.

**Test de refus.** Demandez-lui d’abord de vous envoyer un courriel et confirmez
qu’il arrive. Ensuite, demandez-lui d’écrire à une adresse absente de `roster.md`.
Il doit refuser clairement et dire que cette adresse n’est pas autorisée.

Si l’un de ces tests échoue, arrêtez-vous et révisez l’installation avant
d’utiliser la boîte pour du vrai travail.

## Ce que votre agent peut faire

Une fois Paynani configuré, votre agent peut :

- recevoir des notifications de nouveau courriel sans qu’on lui demande de vérifier la boîte ;
- lire les messages depuis son propre compte ;
- répondre ou envoyer du courrier avec `scripts/send.sh` et le backend SMTP configuré ;
- transformer en travail les messages qui correspondent à `roster.md` ;
- signaler les courriels non autorisés sans leur obéir ;
- conserver les événements dans un journal pour qu’un redémarrage n’efface pas le travail en attente.

## Sécurité et limites

Paynani sépare trois choses souvent confondues :

| Chose | Signification |
|---|---|
| Courriel reçu | Un message est présent dans la boîte. |
| Correspondance dans `roster.md` | Cet expéditeur ou notificateur est autorisé à créer du travail. |
| Identité authentifiée | Paynani ne la promet pas à lui seul. Elle dépend du fournisseur et de validations externes. |

Paynani est responsable de :

- livrer les événements de courriel par un chemin observable ;
- maintenir un curseur pour ne pas sauter les messages acceptés par le runtime ;
- séparer notification et autorisation ;
- refuser les destinataires hors roster depuis la frontière d’envoi sûre ;
- exposer des vérifications de santé pour l’installation et l’exploitation.

Paynani n’est pas responsable de :

- décider si le contenu d’un courriel est vrai ;
- authentifier cryptographiquement une personne ;
- protéger un mot de passe collé dans un chat ;
- remplacer les contrôles de sécurité du fournisseur de messagerie ;
- convertir un courriel non listé en instruction opérationnelle.

## Comment savoir s’il est sain

Voir qu’il n’y a pas de messages en attente ne suffit pas. Pour vérifier le
système, exécutez :

```bash
python3 scripts/healthcheck.py
```

Ce contrôle vérifie les identifiants, le listener, le dispatcher, le runtime, le
journal et le curseur. Si vous devez examiner une installation cassée, suivez
[`INSTALL.md`](../INSTALL.md) et [`HERMES.md`](../HERMES.md) avant de toucher aux
identifiants ou aux services.

## Comment c’est construit, en bref

```text
Boîte IMAP
   ↓
idle listener
   ↓ écrit un événement durable
state/events.jsonl
   ↓ curseur
dispatcher
   ↓ adapter
Hermes / OpenClaw / Claude Code / Codex
```

Le listener écoute la boîte et écrit des événements durables. Le journal conserve
ce qui est arrivé. Le dispatcher livre chaque événement et avance le curseur
seulement quand le runtime l’accepte. L’adapter traduit cette livraison vers le
harness utilisé.

[`DESIGN.md`](../DESIGN.md) explique pourquoi Paynani est construit ainsi et quels
échecs il cherche à éviter.

## Ce qui appartient à ce dépôt

Ce dépôt contient l’installation, le listener, le dispatcher, les scripts d’envoi,
la configuration du roster, les tests et la documentation d’exploitation.

Il ne contient pas votre boîte, vos mots de passe ni une garantie d’identité de
tiers. Ces pièces relèvent de votre fournisseur de messagerie, de votre `.env`
local et de vos propres règles de confiance.

## Si vous voulez..., lisez...

| Si vous voulez... | Lisez |
|---|---|
| Préparer la boîte sans exposer les mots de passe | [`MAILBOX_SETUP.fr-FR.md`](MAILBOX_SETUP.fr-FR.md) |
| Installer Paynani | [`AGENTS.md`](../AGENTS.md) et [`INSTALL.md`](../INSTALL.md) |
| L’intégrer avec Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Comprendre pourquoi il ne doit pas échouer en silence | [`DESIGN.md`](../DESIGN.md) |
| Migrer depuis agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| Voir les changements par version | [`CHANGELOG.md`](../CHANGELOG.md) |
| Autoriser les expéditeurs | `roster.md` et [`roster.md.example`](../roster.md.example) |
| Envoyer du courrier depuis la frontière sûre | [`scripts/send.sh`](../scripts/send.sh) |

## Langues et maintenance

`README.md` est la source en espagnol du Mexique. Les traductions maintenues sont :

- [`i18n/README.en-US.md`](README.en-US.md) ;
- [`i18n/README.es-ES.md`](README.es-ES.md) ;
- [`i18n/README.fr-FR.md`](README.fr-FR.md) ;
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

Il n’existe pas de `i18n/README.es-MX.md` et il ne faut pas en créer : le README
racine est déjà la version es-MX.

## D’où vient le nom

Les paynani étaient des coureurs et messagers officiels de l’Empire aztèque. Ce
projet reprend ce nom pour cette fonction : porter les messages rapidement, par
un chemin clair, sans les perdre en silence.

Fait avec amour par des humains et des agents IA, du Mexique vers le monde.
