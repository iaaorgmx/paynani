# Configurer le fichier de la boîte aux lettres

[Español (MX)](../MAILBOX_SETUP.md) · [English (US)](MAILBOX_SETUP.en-US.md) · [Español (ES)](MAILBOX_SETUP.es-ES.md) · **Français (FR)** · [Português (BR)](MAILBOX_SETUP.pt-BR.md)

Étape 1 du [README](README.fr-FR.md#mise-en-place-sur-votre-agent). Vous faites
ceci vous-même, avant d'impliquer l'agent, parce qu'il faut un mot de passe et
qu'un mot de passe ne doit pas transiter par une conversation.

Dix minutes, dont l'essentiel passe à trouver un nom de serveur.

> **Il existe un formulaire pour cela.** Si taper un fichier dans un terminal ne
> vous dit rien, demandez à l'agent de lancer `scripts/setup_web.sh`. Cela ne
> contrevient pas à la règle ci-dessus : l'agent ne fait qu'ouvrir une page sur sa
> propre machine et vous en donner le lien. C'est vous qui saisissez le mot de
> passe dans la page, il ne transite donc toujours pas par la conversation.
>
> La page demande les mêmes réglages que décrit ce document, les vérifie auprès de
> votre serveur de messagerie et écrit le fichier à votre place, y compris pour le
> problème de nom d'hôte exposé plus bas, qu'elle diagnostique nommément au lieu de
> vous laisser le découvrir. Voir [`webapp/README.md`](../webapp/README.md).
>
> Le reste de cette page est la voie manuelle, et reste utile à lire : elle explique
> *pourquoi* chaque réglage est ce qu'il est, ce que le formulaire ne peut pas
> faire.

---

## Ce qu'il vous faut d'abord

**Une boîte aux lettres à lui.** Pas la vôtre. L'agent lira tout ce qui y arrive et
pourra envoyer depuis ce compte : donnez-lui donc un compte que vous confieriez à
une nouvelle recrue le jour de son arrivée.

**Un mot de passe d'application, si votre fournisseur en propose.** Fastmail, Zoho,
la plupart des hébergeurs professionnels et Google Workspace en proposent. Il peut
être révoqué sans changer votre propre mot de passe, ce qui compte le jour où vous
voudrez retirer l'accès.

**Le vrai nom du serveur de messagerie.** C'est la partie que tout le monde rate,
elle a donc sa propre section plus bas.

---

## Le nom du serveur, et pourquoi c'est la partie délicate

Votre adresse se termine par un domaine, `exemple.com`. Le serveur où vit
réellement votre courrier n'est en général **pas** `exemple.com`, ni
`mail.exemple.com`. C'est plutôt quelque chose comme `nc-ph-2488.xmhosting.com` ou
`imappro.zoho.com`.

`mail.exemple.com` résout pourtant souvent, et c'est là le piège : cela a l'air
correct, la connexion s'établit, puis il s'avère que le certificat TLS est émis
pour le serveur sous-jacent et non pour votre nom de façade. La vérification
échoue, et comme une erreur de certificat arrive sous les traits d'une erreur
réseau, le listener réessaie indéfiniment avec `connection lost` dans le journal et
rien qui explique pourquoi.

**Où trouver le bon :**

- **cPanel :** Comptes de messagerie → *Connecter des appareils* (ou *Configurer un
  client de messagerie*). Utilisez les paramètres **sécurisés/SSL**, pas les
  autres.
- **Google Workspace :** `imap.gmail.com` / `smtp.gmail.com`, et le mot de passe
  d'application est obligatoire.
- **Zoho :** `imappro.zoho.com` / `smtppro.zoho.com`.
- **Ailleurs :** cherchez « IMAP settings » dans leur documentation.

**Vérifiez-le avant de le noter.** Ceci affiche les noms que le certificat couvre
réellement. Celui que vous utiliserez doit en faire partie :

```bash
openssl s_client -connect VOTRE_SERVEUR:993 -servername VOTRE_SERVEUR </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -ext subjectAltName
```

Si le nom que vous avez tapé n'apparaît pas dans cette sortie, prenez-en un qui y
figure.

---

## Créez le fichier

Si votre agent tourne sous un harness, ce fichier appartient au dossier workspace
de ce harness, c'est là qu'on demande à l'agent de regarder :

```bash
cd ~/.hermes/workspace        # ou ~/.openclaw/workspace, ~/.claude/workspace — votre harness
touch .env
chmod 600 .env
```

Sur un hôte sans harness, placez-le à la racine du clone :

```bash
cd /chemin/vers/votre/clone
touch .env
chmod 600 .env
```

`chmod 600` signifie que seul votre utilisateur peut le lire. Faites-le **avant**
d'y mettre le mot de passe, pas après ; un fichier brièvement lisible par tous a
peut-être déjà été lu.

Ouvrez-le ensuite dans un éditeur et remplissez :

```bash
AGENT_EMAIL_ACCOUNT=agent@exemple.com
AGENT_EMAIL_PASSWORD=
AGENT_EMAIL_FROM_NAME=Votre Agent

AGENT_EMAIL_INCOMING_SERVER_IMAP_HOST=
AGENT_EMAIL_INCOMING_SERVER_IMAP_PORT=993

AGENT_EMAIL_OUTGOING_SERVER_SMTP_HOST=
AGENT_EMAIL_OUTGOING_SERVER_SMTP_PORT=465
```

**Ports :** `993` pour IMAP est quasi universel. Pour SMTP, `465` est du TLS
implicite et `587` du STARTTLS ; la page de votre fournisseur précisera lequel. En
cas de doute, essayez `465` d'abord.

**Utilisez un éditeur, pas `echo`.** Tout ce que vous tapez en ligne de commande
atterrit dans l'historique de votre shell, et cet historique est un fichier qui
vit des mois.

---

## Ensuite

Retournez au [README](README.fr-FR.md#mise-en-place-sur-votre-agent) et collez le
texte de l'étape 2. L'agent prend le relais à partir de là, et il vous posera la
question si quelque chose ici se révèle manquant ou faux.

**Une chose qu'il ne devrait jamais demander : le mot de passe.** Il a le chemin du
fichier et peut le lire au moment voulu. S'il vous demande de coller le mot de
passe dans la conversation, refusez, cela ne fait partie d'aucune de ces
instructions.

---

<sub>Traduit de [`MAILBOX_SETUP.md`](../MAILBOX_SETUP.md) au commit `a7b1040`, qui fait référence. En cas de divergence avec l'original en espagnol (MX), **c'est l'espagnol qui fait foi**, et signalez-le nous, car cela veut dire que cette traduction a pris du retard.</sub>
