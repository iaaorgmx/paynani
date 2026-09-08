<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/paynani-horizontal-claro.svg">
    <img src="../brand/paynani-horizontal.svg" alt="paynani" height="52">
  </picture>
</h1>

Messager d'élite : les paynani étaient les coureurs et messagers officiels de l'Empire aztèque.

[Español (MX)](../README.md) · [English (US)](README.en-US.md) · [Español (ES)](README.es-ES.md) · **Français (FR)** · [Português (BR)](README.pt-BR.md)

Paynani permet à votre agent IA de lire automatiquement son propre courrier
électronique quelques secondes après son arrivée, de traiter les messages reçus
et de suivre leurs instructions comme le ferait un collègue humain.

Tous les courriels reçus sont lus, mais seules sont suivies les instructions
venant d'une liste de contacts autorisés. Cette liste, c'est vous qui l'écrivez,
et elle vit dans un fichier appelé `roster.md`.

Paynani est construit sur [Himalaya](https://github.com/pimalaya/himalaya) et
fonctionne avec un compte de messagerie ordinaire, du même type que celui que
vous configureriez dans n'importe quel logiciel de courrier.

**C'est entièrement gratuit !** Vous n'avez aucun service supplémentaire à payer
pour donner à votre agent une adresse électronique qu'il peut utiliser seul.

Il tourne sur votre propre ordinateur ou serveur, à l'intérieur du programme qui
héberge déjà votre agent. Ce programme hôte s'appelle un *harness*, et c'est
ainsi que le mot est employé dans le reste de cette page. Paynani est
actuellement utilisé par des agents IA comme OpenClaw, Hermes Agent, Claude Code
et OpenAI Codex.

Développé et testé sur Linux (Ubuntu 24.04) et macOS (26.4.1).

Fait avec amour par des humains et des agents IA, du Mexique vers le monde.

---

## À qui cela s'adresse

À qui veut donner à son agent une vraie adresse électronique sans y mêler sa
boîte personnelle, ses mots de passe ou ses décisions de confiance.

C'est utile si vous voulez que votre agent :

- reçoive des tâches par courriel, de vous ou de votre équipe ;
- vous prévienne quand arrive quelque chose qui mérite un coup d'œil ;
- réponde depuis son propre compte, pas le vôtre ;
- refuse d'obéir, ou d'écrire, à qui ne figure pas sur votre liste.

Ce n'est pas fait pour déléguer votre jugement au premier message venu. N'importe
qui peut envoyer un courriel, donc Paynani traite tout ce qui entre comme non
fiable tant que l'expéditeur ne correspond pas à votre liste.

## Avant de commencer

Il vous faut quatre choses :

1. un compte de messagerie dédié à l'agent, pas votre courriel personnel ;
2. l'accès à un terminal sur la machine où tourne votre agent ;
3. un moment pour écrire vous-même le mot de passe dans un fichier, sans le coller dans un chat ;
4. votre nom et votre adresse électronique, pour la liste de contacts autorisés.

C'est tout. Pas d'API de messagerie, pas de service intermédiaire, pas de nouveau
compte nulle part.

## Mise en place sur votre agent

Trois étapes. La première est à vous seul, la deuxième consiste à coller un
texte, et la troisième prend deux minutes pour vérifier que cela marche
vraiment.

### Étape 1 : donnez-lui une boîte aux lettres

L'agent a besoin de son propre compte de messagerie, et des paramètres de
connexion de ce compte écrits dans un fichier appelé `.env`. **Si votre agent
tourne sous un harness, ce fichier va dans le dossier `workspace` du harness
lui-même** (`~/.hermes/workspace/.env`, `~/.openclaw/workspace/.env`,
`~/.claude/workspace/.env`, `~/.codex/workspace/.env`), c'est-à-dire là où l'on
dit à l'agent de regarder et d'où cet outil le lit. Sans harness, le fichier peut
vivre dans le dossier du projet. Et si vous ne savez plus où il a atterri, vous
pouvez le demander à l'installation avec `python3 harness/paths.py env`.

**[MAILBOX_SETUP.fr-FR.md](MAILBOX_SETUP.fr-FR.md) vous guide** : quel compte
utiliser, où trouver le nom du serveur (la partie qui échoue toujours) et à quoi
ressemble le fichier.

> [!CAUTION]
> Faites-le vous-même, ne le demandez pas à l'agent. Il faut un mot de passe, et
> un mot de passe ne doit pas passer par un chat : celui que vous collez dans une
> conversation y reste pour toujours, et aucune précaution ultérieure ne le
> défait. Si vous préférez éviter le terminal, `scripts/setup_web.sh` ouvre un
> formulaire local qui écrit le fichier à votre place.

### Étape 2 : pointez l'agent vers ce dépôt

Collez ceci à votre agent :

```text
Revisa la configuración de tu
cuenta de correo electrónico;
está en la carpeta workspace del
directorio de instalación de tu
Harness.

../workspace/.env

Después, instala este
repositorio para poder usarla:
https://github.com/iaaorgmx/paynani

Sigue las instrucciones del
archivo AGENTS.md del
repositorio.

Vas a necesitar mi nombre y mi
dirección de correo electrónico
para el archivo roster.md.

Pregúntame lo que necesites.
```

Tout le reste de ce dont l'agent a besoin se trouve dans le dépôt, donc le texte
n'a qu'à l'y renvoyer.

Attendez-vous à des questions avant qu'il commence. Si l'étape 1 s'est bien
passée, elles devraient être peu nombreuses. S'il vous demande le mot de passe,
dites non : ce n'est une étape d'aucune de ces instructions.

### Étape 3 : testez vous-même

L'agent déroule sa propre liste de vérification et vous dira qu'elle est passée.
Deux minutes de vos propres tests valent davantage, parce que vous testeriez ce
qui vous importe vraiment : qu'il s'en aperçoive, et qu'il reste dans ses
limites.

**Test 1 : envoyez-lui un courriel, avec un accent dans l'objet.**

Depuis votre propre adresse, avec un objet comme
`Prueba de correo: ñ, á, ¿qué tal?` Puis demandez à l'agent ce qui vient
d'arriver.

En deux secondes il devrait vous le dire, et **l'objet doit s'afficher
lisiblement**. Si vous voyez `=?utf-8?q?...` à la place, quelque chose est cassé
dans sa façon de lire les en-têtes, et cela compte bien plus qu'il n'y paraît :
si vous travaillez en espagnol ou en français, c'est presque chaque message que
vous recevrez.

L'accent est tout l'intérêt de ce test. Un objet en anglais sans accent passe,
que cela fonctionne ou non.

**Test 2 : demandez-lui d'écrire à un inconnu.**

Demandez-lui d'abord de vous envoyer quelque chose, et vérifiez que cela arrive.
Puis demandez-lui d'envoyer un message à une adresse qui **ne figure pas** sur sa
liste d'autorisés.

Il doit refuser. Pas demander la permission, pas vous consulter d'abord :
refuser, et vous dire que cette adresse n'est pas sur la liste. Cette liste est
toute la raison pour laquelle il est sûr de laisser un agent qui lit du courrier
non fiable pouvoir aussi en envoyer, donc cela vaut la peine de la voir
fonctionner une fois de vos propres yeux.

S'il l'envoie, arrêtez-vous et prévenez la personne qui l'a installé. Quelque
chose ne va pas.

## Ce que votre agent pourra faire

- **Être au courant d'un nouveau courriel en une seconde environ**, sans
  interroger la boîte et sans que vous le lui demandiez.
- **Lire et envoyer** depuis la boîte que vous avez configurée.
- **N'envoyer qu'aux adresses que vous avez approuvées**, celles de votre liste.
  Toute autre est refusée d'emblée, sans même vous demander.
- **Travailler sur le courrier que ces mêmes adresses approuvées envoient.** Vous
  lui écrivez une tâche, il la fait et vous répond par courriel. Sans accusé de
  réception préalable et sans demander la permission ; vous la lui avez donnée en
  vous mettant sur la liste.
- **Laisser tranquille le courrier des autres.** Ce qui vient d'une adresse
  absente de la liste vous est signalé, et rien de plus.
- **Ne pas perdre ce qui est arrivé** si la machine redémarre en pleine tâche.
  Chaque message détecté est noté sur disque avant d'être remis.

## Ce que cela change sur la machine

Cela vaut la peine de le savoir avant d'accepter. L'agent a pour instruction de
vous rapporter tout ceci quand il aura fini, et vous pouvez lui réclamer la
liste :

- **Deux services qui restent en marche en permanence** et redémarrent seuls en
  cas de panne : celui qui écoute la boîte et celui qui remet les messages à
  votre agent. Ils s'installent comme services de votre utilisateur, pas du
  système.
- **Deux autres qui ne font que rogner les journaux** pour qu'ils ne grossissent
  pas sans fin.
- **Un fichier contenant le mot de passe de la boîte**, lisible par votre seul
  utilisateur. Il est lu là où vous l'avez laissé et jamais recopié ailleurs.
- **Des fichiers de journal et d'état** dans le dossier du projet.
- **L'autorisation pour ces services de rester vivants après votre
  déconnexion.**
- **Une règle permanente ajoutée aux instructions de l'agent lui-même.**

Tout cela est réversible ; [`UNINSTALL.md`](../UNINSTALL.md) retire chaque point
de cette liste, dans un ordre qui ne vous laisse pas travailler de mémoire.

<details>
<summary>Les noms exacts, si vous en avez besoin</summary>

Quatre unités utilisateur systemd, pas une. Deux tournent en permanence et
redémarrent seules en cas de panne : l'écouteur (`paynani-idle.service`) et le
distributeur (`paynani-dispatch.service`). Les deux autres font tourner les
journaux : `paynani-logrotate.timer`, qui s'active seul, et
`paynani-logrotate.service`, qui est `static` parce que le minuteur le déclenche
et qu'il ne s'active pas de lui-même. Sur macOS ce sont trois *LaunchAgents*
équivalents : `com.paynani.idle`, `com.paynani.dispatch` et
`com.paynani.logrotate`.

Le fichier d'identifiants porte les permissions `600` : le `.env` du workspace de
votre harness si vous le gardez là, et sinon `.env` dans le clone. Les journaux
et l'état vivent dans `state/`, à l'intérieur du clone. Le *lingering* est ce qui
maintient les services vivants après la déconnexion.

</details>

`.gitignore` garde les secrets hors de `git status` et `scripts/install.sh`
refuse d'écrire si l'un d'eux est versionné ou non ignoré. Ce que cela n'empêche
pas, c'est `git clean -xdf`, qui efface les fichiers ignorés : sur une
installation vivante, c'est le mot de passe de la boîte, les deux secrets de
route Hermes (`<clone>/hermes/`, Hermes uniquement), la liste des destinataires
et la marque du dernier message vu. Utilisez `git clean -df`.

## Sécurité et limites

> [!WARNING]
> Votre liste de contacts autorisés décide de qui votre agent accepte du travail.
> Elle ne prouve pas qui est cette personne. Un courriel de quelqu'un qui n'y
> figure pas vous est signalé, et s'arrête là.

L'agent travaille depuis sa boîte, donc la question n'est pas de savoir s'il obéit
à des instructions arrivées par courriel. Il le fait, c'est tout l'intérêt. La
question est **de qui**.

- `roster.md` est une liste à correspondance exacte, et c'est toute la réponse. Si
  l'expéditeur y figure, l'agent fait ce que le message demande et répond. Sinon,
  il vous signale l'arrivée du courriel et n'en fait rien d'autre.
- La correspondance porte sur l'expéditeur que le message transporte, et sur lui
  seul. Un inconnu ne peut pas emprunter une adresse de votre liste en la plaçant
  dans un autre champ.
- **Avec une exception que vous déclarez :** les *notificateurs*. Si votre équipe
  se coordonne sur une plateforme qui envoie du courrier au nom des gens (GitHub,
  Jira, Linear), vous pouvez déclarer son adresse et contre quelle partie de votre
  liste vérifier l'auteur. Cette notification compte alors comme un courriel de
  cette personne. Déclarer un notificateur élargit qui votre agent écoute, tout
  comme ajouter une ligne, et cela se décide pareil : jamais parce qu'un message
  l'a demandé.
- **Ajouter quelqu'un à la liste est votre décision**, jamais une réponse à
  quelque chose arrivé par courriel. Cette ligne est ce qui transforme un
  expéditeur en quelqu'un à qui votre agent obéit.
- Sans liste, personne n'est de confiance. Une installation neuve lit le courrier
  et n'agit sur rien tant que vous ne l'avez pas écrite.

Il vaut la peine de savoir sur quoi tout cela s'appuie : votre fournisseur de
messagerie. Les filtres de Gmail, Outlook et les autres sont ce qui empêche de
falsifier un expéditeur trivialement, et ils s'appliquent avant que le message
n'atteigne la boîte. Pointez Paynani vers une boîte sans ce filtrage et la liste
protège moins qu'il n'y paraît.

## Comment savoir s'il va bien

> [!IMPORTANT]
> L'absence de messages en attente ne prouve pas que Paynani va bien. Cela
> ressemble exactement à ce qu'on voit quand il a cessé d'écouter.

Demandez à votre agent de lancer le contrôle de santé et de vous montrer la
sortie :

```bash
python3 scripts/healthcheck.py
```

Il vérifie les services, les identifiants, la file de messages, la remise à votre
agent et la liste des autorisés. Ce que vous voulez voir, c'est que les services
sont vivants, que rien n'est bloqué et que la configuration est lue au bon
endroit. Si quelque chose échoue, le rapport vous dit quelle pièce, pas seulement
qu'il n'y a pas de courrier.

Les options longues et les modes de défaillance sont dans
[`INSTALL.md`](../INSTALL.md).

## Comment c'est construit, en bref

Un service maintient une connexion ouverte vers votre serveur de messagerie, du
type où le serveur annonce lui-même l'arrivée du courrier au lieu qu'on le lui
demande. Quand un message arrive, ce service le note sur disque avant toute autre
chose. Un second service lit ces notes et les remet à votre agent, et ne marque
une remise comme faite que lorsque l'agent confirme l'avoir reçue.

Cette séparation est ce qui évite de perdre du courrier quand quelque chose tombe
en cours de route. [`DESIGN.md`](../DESIGN.md) explique chaque pièce, pourquoi
elle est ainsi et ce qui casse sans elle.

## Ce qui appartient à ce dépôt

L'installation, les deux services, les scripts d'envoi, la liste des autorisés,
les tests et la documentation d'exploitation.

Pas votre boîte, pas votre mot de passe, ni une garantie que celui qui écrit est
bien qui il prétend être. Cela revient à votre fournisseur de messagerie, à votre
fichier `.env` et à votre propre jugement sur qui entre.

## Si vous voulez..., lisez...

| Si vous voulez... | Lisez |
|---|---|
| Préparer la boîte sans exposer de mots de passe | [`MAILBOX_SETUP.fr-FR.md`](MAILBOX_SETUP.fr-FR.md) |
| Installer Paynani | [`AGENTS.md`](../AGENTS.md) et [`INSTALL.md`](../INSTALL.md) |
| L'intégrer à Hermes Agent | [`HERMES.md`](../HERMES.md) |
| Comprendre pourquoi il ne doit pas échouer en silence | [`DESIGN.md`](../DESIGN.md) |
| Migrer depuis agenteiamail | [`MIGRATION.md`](../MIGRATION.md) |
| Retirer Paynani | [`UNINSTALL.md`](../UNINSTALL.md) |
| Voir les changements par version | [`CHANGELOG.md`](../CHANGELOG.md) |
| Autoriser des expéditeurs | `roster.md` et [`roster.md.example`](../roster.md.example) |
| Envoyer du courrier depuis la frontière sûre | [`scripts/send.sh`](../scripts/send.sh) |

## Le tenir à jour

La version installée est dans [`VERSION`](../VERSION), et on dit à l'agent
laquelle il exécute au début de chaque session, ainsi que s'il en existe une plus
récente.

Vous pouvez lui demander la même chose directement :

```bash
scripts/version.sh
```

Il lit la version publiée depuis les étiquettes de ce dépôt, donc aucun compte ni
jeton n'entre en jeu, et il dit clairement quand il n'a pas pu joindre le réseau,
au lieu de déclarer une installation à jour simplement parce que rien ne l'a
contredit.

Mettre à jour, c'est [`UPGRADE.md`](../UPGRADE.md), et ce qui a changé entre deux
versions est dans [`CHANGELOG.md`](../CHANGELOG.md). Lisez d'abord le changelog :
de temps en temps une version demande plus qu'un `git pull`, et la façon dont
l'oubli échoue, c'est un service qui marche jusqu'au prochain redémarrage.

## Langues

`README.md` est la source en espagnol du Mexique. Les traductions maintenues
sont :

- [`i18n/README.en-US.md`](README.en-US.md) ;
- [`i18n/README.es-ES.md`](README.es-ES.md) ;
- [`i18n/README.fr-FR.md`](README.fr-FR.md) ;
- [`i18n/README.pt-BR.md`](README.pt-BR.md).

`i18n/README.es-MX.md` n'existe pas et ne doit pas être créé : la page source est
déjà la version es-MX.

## La propriété que tout le reste sert

**Ne jamais échouer en silence.** La latence était le problème facile : elle a été
réglée en une après-midi dès que le serveur a pu annoncer le courrier lui-même.
Tout le reste existe parce que la défaillance coûteuse n'est pas d'être lent,
c'est de **dire avec assurance qu'il n'y a pas de nouveau courrier alors qu'on est
aveugle**.

C'est pourquoi le dernier message vu est enregistré un par un, pourquoi chaque
connexion vérifie que la boîte est toujours la même, pourquoi le journal d'erreurs
est surveillé à côté de celui des événements, et pourquoi le démarrage d'une
session demande si le service tourne vraiment. [`DESIGN.md`](../DESIGN.md)
explique chacun d'eux et ce qui casse sans lui.

Construit et vérifié de bout en bout le 2026-08-09.

## D'où vient le nom

**paynani** est du nahuatl classique et signifie, sans ornement, *« celui qui court
légèrement »* : du verbe `paina` (« correr ligeramente », dans le vocabulaire
d'Alonso de Molina, 1571) auquel s'ajoute le suffixe `-ni`, qui transforme une
action en celui qui l'exerce comme métier.

La graphie varie parce que les religieux du XVIe siècle ont écrit le nahuatl avec
les conventions de l'espagnol de leur temps, où `i`, `y` et `j` s'employaient
presque indifféremment. Le Gran Diccionario Náhuatl indexe les mêmes passages du
Codex de Florence sous `painani` et sous `painanj`, et enregistre `payna` comme
variante de `paina` : c'est un seul mot. Ce projet écrit `paynani`, la forme qu'un
lecteur hispanophone reconnaît.

C'est de cette qualité qu'est venu le nom du métier. Le nahuatl avait deux façons
de nommer le messager impérial : `titlantli`, « celui qu'on envoie », qui le
définit par la mission qu'il porte, et `paynani`, qui le définit par sa manière de
se déplacer. C'est la seconde qui est restée attachée à ces hommes : on les
connaissait à leur façon de courir, non à celui qui les envoyait.

Les coureurs travaillaient par relais, avec des postes appelés `techialoyan`, et
s'entraînaient dès l'enfance. De tout ce qu'on rapporte d'eux, un détail est
exactement ce que fait cet outil : **le messager classait la nouvelle avant
d'ouvrir la bouche.** Arrivait-il les cheveux dénoués et en désordre, il apportait
une défaite, et on ne lui adressait pas même un salut ; arrivait-il les cheveux
tressés et ornés d'un ruban de couleur, bouclier et massue à la main, il apportait
une victoire, et la foule le suivait jusqu'au palais. C'est ce que fait ici
l'étiquette `roster` : l'enveloppe dit comment recevoir la nouvelle avant qu'on ne
la lise.

De la même racine vient Paynal, celui qui courait à la place de Huitzilopochtli
lors des processions. Le Codex de Florence l'explique en trois mots, *« le
délégué, le substitut, le suppléant »*, parce qu'« on le pressait, on le faisait
courir ». Un agent qui va chercher le courrier à la place de qui ne peut être
partout à la fois.

<sub>Sources : [Gran Diccionario Náhuatl](https://gdn.iib.unam.mx/diccionario/painani/233892)
(UNAM) · [Nahuatl Dictionary](https://nahuatl.wired-humanities.org/content/paina)
(Wired Humanities) · [Mexicolore](https://www.mexicolore.co.uk/aztecs/ask-experts/did-they-send-post-mail).</sub>

---

<sub>Traduit de [`README.md`](../README.md), qui fait référence. En cas de divergence avec l'original en espagnol (MX), **c'est l'espagnol qui fait foi**, et signalez-le nous, car cela veut dire que cette traduction a pris du retard.</sub>
