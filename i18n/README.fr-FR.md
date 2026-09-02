# paynani

[Español (MX)](../README.md) · [English](README.en-US.md) · [Español (ES)](README.es-ES.md) · **Français** · [Português (BR)](README.pt-BR.md)

> Traduit de [`README.md`](../README.md), qui fait référence. En cas de divergence avec
> l'original en espagnol (MX), **c'est l'espagnol qui fait foi**, et signalez-le
> nous, car cela veut dire que cette traduction a pris du retard.

Notification immédiate des courriels pour un agent IA. Il apprend l'arrivée d'un
message en une seconde environ, sans interroger la boîte en boucle, et peut lire
et envoyer dans les limites d'une liste de destinataires autorisés.

Construit autour de [Himalaya](https://github.com/pimalaya/himalaya) pour un
compte IMAP/SMTP ordinaire, sous Ubuntu 24.04 avec l'environnement OpenClaw,
Hermes Agent ou Claude Code. Les opérateurs Hermes configurent deux routes
authentifiées comme décrit dans [`HERMES.md`](../HERMES.md).

Claude Code fonctionne autrement que les deux autres, et mieux vaut le savoir
avant de commencer : rien à l'extérieur d'une session Claude Code ne peut lui
parler, donc le courrier n'est pas poussé vers l'agent — c'est l'agent qui vient
le chercher. Son hook de démarrage de session rejoue ce qui est arrivé pendant
qu'aucune session ne tournait, puis demande à l'agent d'armer une surveillance
pour la suite. Rien ne peut l'imposer de l'extérieur : c'est la seule étape qui
repose sur le fait que l'agent fasse ce qu'on lui dit. Voir
[`INSTALL.md`](../INSTALL.md) §6.

---

## Mise en place sur votre agent

Trois étapes. La première est la vôtre seule, la deuxième tient en un
copier-coller, la troisième prend deux minutes pour vérifier que cela fonctionne
vraiment.

### Étape 1 : Donnez-lui une boîte aux lettres

L'agent a besoin de son propre compte de messagerie, et des paramètres de
connexion de ce compte écrits dans un fichier `.env`. **Si votre agent tourne sous
un harness, ce fichier appartient au dossier workspace de ce harness** —
`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env` —, c'est là qu'on demande
à l'agent de regarder et c'est de là que cet outil le lit. Sur un hôte sans
harness, placez-le au sein du clone.

**[MAILBOX_SETUP.fr-FR.md](MAILBOX_SETUP.fr-FR.md) vous guide** : quel compte utiliser, où
trouver le nom du serveur (la seule partie qui échoue systématiquement), et le
fichier lui-même.

Faites-le vous-même plutôt que de le demander à l'agent. Il faut un mot de passe,
et un mot de passe ne doit pas transiter par une conversation.

### Étape 2 : Orientez l'agent vers ce dépôt

Collez ceci à votre agent :

```text
Vérifiez les paramètres de votre compte de messagerie dans le dossier workspace
du répertoire d'installation de votre Harness.

../workspace/.env

Installez ensuite ce dépôt pour pouvoir l'utiliser :
https://github.com/iaaorgmx/paynani

Suivez le fichier AGENTS.md à l'intérieur du dépôt.

Vous aurez besoin de mon adresse e-mail pour le roster — la liste des personnes
à qui vous pouvez écrire et dont vous pouvez traiter le courrier. Demandez-la-moi ;
ne la devinez pas et ne la copiez depuis aucun fichier.

Demandez-moi tout ce dont vous avez besoin.
```

Tout le reste dont l'agent a besoin se trouve dans le dépôt : le texte n'a donc
qu'à l'y renvoyer.

Attendez-vous à des questions avant qu'il ne commence. Si l'étape 1 s'est bien
passée, elles devraient être rares, et s'il demande le mot de passe, refusez :
un mot de passe collé dans une conversation y reste définitivement, et aucune
précaution ultérieure ne l'efface. Cela ne fait partie d'aucune de ces
instructions.

### Étape 3 : Testez vous-même

L'agent exécute sa propre liste de vérification et vous dira qu'elle est passée.
Deux minutes de vos propres tests valent davantage, car vous vérifiez ce qui vous
importe réellement : est-ce qu'il remarque, et est-ce qu'il reste dans ses
limites.

**Test 1 : envoyez-lui un courriel, avec un accent dans l'objet.**

Depuis votre propre adresse, avec un objet du genre `Test : é, à, ç, ça va ?`
Demandez ensuite à l'agent ce qui vient d'arriver.

En deux secondes il devrait vous répondre, et **l'objet doit revenir lisible**. Si
vous voyez `=?utf-8?q?...` à la place, le décodage des en-têtes est cassé, ce qui
compte bien plus qu'il n'y paraît, car en français comme en espagnol c'est à peu
près chaque message que vous recevrez.

L'accent est tout l'intérêt de ce test. Un objet en anglais sans accent passe, que
le décodage fonctionne ou non.

**Test 2 : demandez-lui d'écrire à un inconnu.**

Demandez-lui d'abord de vous envoyer quelque chose, et vérifiez que cela arrive.
Demandez-lui ensuite d'envoyer un message à une adresse qui **ne figure pas** sur
sa liste d'autorisation.

Il doit refuser. Pas demander la permission, pas vous consulter d'abord : refuser,
et vous dire que l'adresse n'est pas sur la liste. Cette liste est toute la raison
pour laquelle il est sûr de laisser un agent qui lit du courrier non fiable
pouvoir aussi en envoyer, il vaut donc la peine de la voir fonctionner une fois
de vos propres yeux.

S'il envoie, arrêtez tout et prévenez la personne qui l'a installé. Quelque chose
ne va pas.

---

## Ce que votre agent pourra faire

- **Savoir qu'un courriel est arrivé en une seconde environ**, sans interroger la
  boîte et sans qu'on le lui demande.
- **Lire et envoyer** via Himalaya, avec la boîte que vous avez configurée.
- **N'envoyer qu'aux adresses que vous avez approuvées**, listées dans
  `roster.md`. Toute autre est refusée d'emblée, sans même vous demander.
- **Travailler à partir du courrier envoyé par ces mêmes adresses approuvées.**
  Vous lui envoyez une tâche, il l'exécute et vous répond par courrier. Sans accusé
  de réception préalable et sans demander la permission ; vous l'avez déjà donnée
  en vous inscrivant sur la liste.
- **Laisser le courrier des autres tranquille.** Ce qui arrive d'une adresse
  absente de la liste vous est signalé, rien de plus.

## Ce que cela change sur la machine

Bon à savoir avant d'accepter. L'agent a pour consigne de vous rendre compte de
tout ceci en terminant, et vous pouvez lui en demander la liste :

- Un service utilisateur systemd qui tourne en continu et redémarre en cas
  d'échec
- Un fichier d'identifiants en `600` : le `.env` du workspace de votre harness si
  vous le gardez là, sinon `.env` au sein du clone. Il est lu où il se trouve et
  n'est jamais copié
- Des fichiers de journal et d'état sous `state/` au sein du clone
- Le *lingering* activé pour l'utilisateur, afin que le service survive à la
  déconnexion
- Une règle permanente ajoutée aux instructions de l'agent lui-même

Tout cela est réversible ; [`UNINSTALL.md`](UNINSTALL.en-US.md) retire chaque élément
de cette liste, dans un ordre qui ne vous laisse pas travailler de mémoire.

## Le tenir à jour

La version installée se trouve dans [`VERSION`](../VERSION), et l'agent apprend
laquelle il exécute au début de chaque session, ainsi que l'existence éventuelle
d'une version plus récente.

Vous pouvez lui poser la même question directement :

```bash
scripts/version.sh
```

Il lit la version publiée dans les étiquettes de ce dépôt : ni compte ni jeton
d'accès. Et il le dit franchement lorsqu'il n'a pas pu joindre le réseau, plutôt
que de déclarer une installation à jour au seul motif que rien ne l'a contredit.

La mise à niveau, c'est [`UPGRADE.md`](../UPGRADE.md), et ce qui a changé entre
deux versions se trouve dans [`CHANGELOG.md`](../CHANGELOG.md). Lisez d'abord le
changelog : une version demande parfois autre chose qu'un `git pull`, et l'oublier
donne un listener qui fonctionne jusqu'au prochain redémarrage.

## Sécurité

L'agent travaille à partir de son courrier : la question n'est donc pas de savoir
s'il exécute des instructions reçues par e-mail (il le fait, c'est le principe)
mais **de qui** elles viennent.

- `roster.md` est une liste à correspondance exacte, et c'est toute la réponse. Si
  l'expéditeur y figure, l'agent fait ce que le message demande et répond. Sinon,
  il vous signale l'arrivée du courrier et n'en fait rien d'autre.
- La correspondance porte sur `From` uniquement. Un `Reply-To` désignant une
  personne approuvée n'accorde rien : un inconnu ne peut pas emprunter une adresse
  de la liste au moyen d'un en-tête.
- **Ajouter quelqu'un à `roster.md` est votre décision**, jamais une réponse à
  quelque chose arrivé par courrier. Cette ligne est ce qui fait d'un expéditeur
  quelqu'un à qui votre agent obéit : elle mérite donc d'être traitée comme telle.
- Sans fichier roster, personne n'est de confiance : une installation neuve lit le
  courrier et n'agit sur rien tant que vous n'avez pas écrit la liste.
- Le mot de passe réside dans un fichier en `600` hors du dépôt, et ne transite
  jamais par une conversation.

Notez ce sur quoi repose ce design : votre fournisseur de messagerie. SPF, DKIM et
DMARC sont appliqués avant que quoi que ce soit n'atteigne la boîte de réception,
et c'est ce qui empêche de falsifier un `From` trivialement. Sur une boîte
dépourvue de ce filtrage, le roster protège moins qu'il n'y paraît.

---

## Le reste du dépôt

Ceux marqués **(en)** sont en anglais : ce sont les documents destinés aux agents
et à qui modifie le code, et le code reste en anglais. Le reste est en espagnol
(MX), qui fait référence.

| | |
|---|---|
| [`MAILBOX_SETUP.fr-FR.md`](MAILBOX_SETUP.fr-FR.md) | Étape 1 : la boîte et le fichier `.env` |
| [`webapp/README.md`](../webapp/README.md) | **(en)** L'étape 1 sans terminal : un formulaire local |
| [`AGENTS.md`](../AGENTS.md) | **(en)** Ce que suit l'agent. Commencez ici si vous en êtes un. |
| [`INSTALL.md`](../INSTALL.md) | **(en)** La séquence d'installation, étape par étape |
| [`CHANGELOG.md`](../CHANGELOG.md) | **(en)** Ce qui a changé à chaque version, et lesquelles demandent plus qu'un pull |
| [`HERMES.md`](../HERMES.md) | **(en)** L'adaptateur Hermes Agent : routes, signatures et confiance |
| [`UPGRADE.md`](../UPGRADE.md) | **(en)** Faire passer une installation existante à une version plus récente |
| [`DESIGN.md`](../DESIGN.md) | **(en)** Pourquoi les pièces ont cette forme ; à lire avant d'y toucher |
| [`UNINSTALL.md`](UNINSTALL.en-US.md) | **(en)** Comment tout enlever |

```
scripts/idle_listener.py  Service systemd --user. Maintient une connexion IMAP
  │                       IDLE ouverte ; le serveur signale l'arrivée du courrier.
  │  une ligne par message
  ▼
<clone>/state/
  mail.log                le flux d'événements
  idle.err.log            diagnostics, surveillés séparément
  events.jsonl            la file : une enveloppe canonique par ligne
  dispatch.offset         jusqu'où la remise a été confirmée
  │
  ├─► harness/dispatch.py         l'unique consommateur supervisé. Lit le journal,
  │                               remet chaque événement à un adaptateur de runtime
  │                               et n'avance le curseur qu'une fois accepté
  │     └─► harness/adapters/     openclaw, hermes et claudecode. Le seul
  │                               code ici qui sache ce qu'est un harness
  ├─► harness/session_start.py    montre ce qui est en file ; n'acquitte rien
  └─► harness/rotate_logs.py      rotation copytruncate, sur un timer utilisateur

scripts/version.sh        la version installée face à la dernière publiée, et
                          quoi faire de l'écart.
himalaya                  lit et envoie. Le listener ne télécharge jamais les corps.
scripts/send.sh + roster.md  l'envoi est limité aux destinataires autorisés.
scripts/roster.py         la même liste, lue par le listener pour marquer les expéditeurs.
scripts/preflight.py      prouve qu'une machine peut faire tourner ceci avant de l'installer.
webapp/ + setup_web.sh    un formulaire local qui écrit le fichier d'identifiants,
                          pour qui ne veut pas de terminal. Loopback uniquement.
```

## Chemins sur cette machine

Le clone *est* l'installation : tout ce qui lui appartient vit à l'intérieur, donc
choisir où cloner, c'est choisir où installer.

- Dépôt : n'importe où ; `~/.openclaw/workspace/paynani` sur OpenClaw,
  `~/.hermes/workspace/paynani` sur Hermes Agent ou
  `~/.claude/workspace/paynani` sur Claude Code à défaut de préférence
- Identifiants : `<clone>/.env` : en `600`, ignoré par git, jamais versionné
- État et événements : `<clone>/state/`
- Secrets de route : `<clone>/hermes/`, en `600`
- Service utilisateur : `~/.config/systemd/user/paynani-idle.service` : la
  seule chose hors du clone, car systemd ne lit les unités de nulle part ailleurs

`.gitignore` garde les secrets hors de `git status`, et `scripts/install.sh`
refuse d'écrire si l'un d'eux est versionné ou non ignoré. Ce que cela n'empêche
pas : `git clean -xdf` supprime les fichiers ignorés — sur une installation vivante,
c'est le mot de passe de la boîte, les deux secrets de route, la liste des
destinataires et le dernier UID. Utilisez `git clean -df`.

## La propriété que tout le reste sert

**Ne jamais échouer en silence.** La latence était le problème facile : IDLE l'a
réglé en un après-midi. Tout le reste existe parce que l'échec coûteux n'est pas
la lenteur, c'est **d'affirmer avec assurance qu'il n'y a pas de nouveau courrier
alors qu'on est aveugle**.

D'où le dernier UID enregistré message par message, la vérification d'`UIDVALIDITY`
à chaque connexion, la surveillance du journal d'erreurs en parallèle de celui des
événements, et le hook de démarrage de session qui demande si le service tourne
réellement. [`DESIGN.md`](../DESIGN.md) explique chacun d'eux et ce qui casse sans.

Construit et vérifié de bout en bout le 09/08/2026.
