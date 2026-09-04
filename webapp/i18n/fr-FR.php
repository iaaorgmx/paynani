<?php
declare(strict_types=1);

/** Français (FR). Traduit depuis es-MX. */

return [

'page.title'        => 'paynani : configuration de la boîte mail',
'page.h1'           => 'Donnez une boîte mail à l\'agent',
'page.lead'         => 'Sept informations venant de votre fournisseur de messagerie. Tout reste sur cet ordinateur. Cette page n\'est pas accessible depuis internet.',
'lang.label'        => 'Langue',
'lang.apply'        => 'Changer',

'saved.h1'          => 'C\'est fait',
'saved.lead'        => 'Votre serveur de messagerie a accepté le compte et la configuration est enregistrée. Vous pouvez fermer cette page.',
'saved.where'       => 'Enregistré dans <code>{path}</code>, et seul ce compte peut le lire.',
'saved.next_h2'     => 'La suite',
'saved.next_p1'     => 'Prévenez l\'agent que la configuration est en place. Il installe le reste et vérifie que le courrier arrive ; cette partie est son travail, pas le vôtre.',
'saved.next_p2'     => 'La seule chose qui vaille la peine de votre côté : envoyez un courriel à l\'agent et demandez-lui ce qui vient d\'arriver. S\'il répond en deux secondes, tout fonctionne.',
'saved.forgot'      => 'Cette page a déjà oublié le mot de passe. La rouvrir ne l\'affichera pas de nouveau.',


'help.summary'      => 'Où est-ce que je trouve ces informations ?',

'help.cpanel_h3'    => 'Si votre messagerie est venue avec votre hébergement web (cPanel)',
'help.cpanel_p'     => 'C\'est le cas le plus courant, et les informations y sont déjà écrites pour vous.',
'help.cpanel_li1'   => 'Connectez-vous à cPanel, en général <code>votredomaine.example/cpanel</code>, ou le lien que votre hébergeur vous a envoyé.',
'help.cpanel_li2'   => 'Ouvrez <strong>Email Accounts</strong> (Comptes de messagerie).',
'help.cpanel_li3'   => 'Trouvez l\'adresse que l\'agent va utiliser et cliquez sur <strong>Connect Devices</strong> (les anciennes versions l\'appellent <em>Set Up Mail Client</em>).',
'help.cpanel_li4'   => 'Cherchez <strong>Mail Client Manual Settings</strong> et utilisez la colonne <strong>Secure SSL/TLS Settings</strong>, pas celle sans SSL.',
'help.cpanel_after' => 'Copiez <em>Incoming Server</em> et son port IMAP dans la section de lecture ci-dessous, et <em>Outgoing Server</em> avec son port SMTP dans celle d\'envoi. L\'identifiant est l\'adresse électronique complète, et le mot de passe est celui que vous avez donné à cette boîte à sa création. Si vous ne vous en souvenez pas, cPanel vous laisse le changer sur cette même page.',

'help.gmail_h3'     => 'Gmail ou Google Workspace',
'help.gmail_p1'     => 'Les noms de serveur sont toujours les mêmes : <code>imap.gmail.com</code> port <code>993</code> pour lire, <code>smtp.gmail.com</code> port <code>465</code> pour envoyer.',
'help.gmail_p2'     => 'C\'est le mot de passe qui bloque tout le monde. Google n\'accepte pas ici le mot de passe habituel. Il vous faut un <strong>mot de passe d\'application</strong>, ce qui exige d\'avoir d\'abord activé la validation en deux étapes. Créez-le sur <code>myaccount.google.com</code> → Sécurité → Mots de passe des applications, et collez le code de 16 caractères qu\'il vous donne.',
'help.gmail_p3'     => 'Vérifiez aussi qu\'IMAP est activé : Gmail → Paramètres → Transfert et POP/IMAP.',

'help.ms_h3'        => 'Outlook.com, Hotmail ou Microsoft 365',
'help.ms_p1'        => '<code>outlook.office365.com</code> port <code>993</code> pour lire, <code>smtp.office365.com</code> port <code>587</code> pour envoyer.',
'help.ms_p2'        => 'Beaucoup de comptes Microsoft d\'entreprise bloquent désormais par politique les connexions de ce type. Si la vérification ci-dessous refuse le mot de passe alors qu\'il est bon, c\'est généralement pour cette raison, et votre administrateur doit l\'autoriser.',

'help.zoho_h3'      => 'Zoho',
'help.zoho_p'       => '<code>imappro.zoho.com</code> port <code>993</code>, <code>smtp.zoho.com</code> port <code>465</code>. Zoho demande aussi un mot de passe d\'application, pas le mot de passe habituel.',

'help.fastmail_h3'  => 'Fastmail',
'help.fastmail_p'   => '<code>imap.fastmail.com</code> port <code>993</code>, <code>smtp.fastmail.com</code> port <code>465</code>, avec un mot de passe d\'application.',

'help.other_h3'     => 'N\'importe quel autre',
'help.other_p1'     => 'Demandez à votre fournisseur, ou cherchez son nom suivi de <em>configuration IMAP et SMTP</em>. Vous cherchez quatre choses : le nom du serveur entrant, celui du sortant, et un port pour chacun. Préférez les ports marqués SSL ou TLS.',
'help.other_p2'     => 'Un avertissement qui mérite d\'être répété : ne devinez pas le nom du serveur en mettant <code>mail.</code> devant votre domaine. Cela marche souvent juste assez pour avoir l\'air correct, puis échoue sur le certificat de sécurité, ce qui est horrible à diagnostiquer ensuite. La vérification ci-dessous le détecte et vous le dit clairement.',

'form.account_legend' => 'Le compte',
'form.account_label'  => 'Adresse électronique',
'form.account_ph'     => 'agent@votredomaine.example',
'form.account_hint'   => 'La boîte propre à l\'agent, pas la vôtre.',

'form.password_label' => 'Mot de passe',
'form.password_kept'  => '••••••••  le précédent a été conservé',
'form.password_hint'  => 'Si votre fournisseur propose des <em>mots de passe d\'application</em>, utilisez-en un. C\'est l\'information qui finit le plus souvent refusée sinon.',

'form.fromname_label' => 'Nom affiché',
'form.optional'       => 'facultatif',
'form.fromname_ph'    => 'Atenea',
'form.fromname_hint'  => 'Le nom que voient les gens quand l\'agent leur écrit.',

'form.imap_legend'    => 'Lecture du courrier (IMAP)',
'form.smtp_legend'    => 'Envoi du courrier (SMTP)',
'form.server'         => 'Serveur',
'form.port'           => 'Port',
'form.imap_host_ph'   => 'imap.votrehebergeur.example',
'form.smtp_host_ph'   => 'smtp.votrehebergeur.example',
'form.imap_hint'      => 'Demandez à votre fournisseur le nom exact du serveur. Le deviner en mettant <code>imap.</code> devant votre domaine produit souvent un nom qui marche partout sauf sur le certificat de sécurité, et cette panne-là est difficile à diagnostiquer ensuite.',
'form.smtp_hint'      => '465 ou 587. Les deux se vérifient de la même façon.',

'form.submit'         => 'Vérifier et enregistrer',
'form.footnote'       => 'Ceci entre dans votre boîte et en ressort aussitôt ; cela ne lit rien, n\'envoie rien et ne change rien. La configuration n\'est enregistrée que si votre serveur de messagerie l\'accepte, il n\'y a donc rien à défaire si quelque chose ici est faux.',

'report.h2'           => 'Pas encore enregistré : quelque chose ne va pas ici',
'report.imap_h3'      => 'Lecture du courrier',
'report.smtp_h3'      => 'Envoi du courrier',

'v.account_missing'   => 'L\'agent a besoin d\'une adresse électronique.',
'v.account_bad'       => 'Cela ne ressemble pas à une adresse électronique.',
'v.password_missing'  => 'Sans le mot de passe, l\'agent ne peut pas ouvrir la boîte.',
'v.fromname_oneline'  => 'Le nom affiché doit tenir sur une seule ligne.',
'v.host_missing'      => 'Le nom du serveur {proto} manque.',
'v.host_is_port'      => 'C\'est un numéro de port, pas un nom de serveur. Un nom de serveur ressemble à ceci : imap.votrehebergeur.example.',
'v.host_has_junk'     => 'Ici va uniquement le nom du serveur : sans https://, sans espaces, sans adresse.',
'v.host_bad_chars'    => 'Cela contient des caractères qu\'un nom de serveur ne peut pas avoir.',
'v.port_missing'      => 'Le port {proto} manque.',
'v.port_range'        => 'Un port est un nombre entre 1 et 65535.',

'p.cert_mismatch'     => 'Le serveur a répondu, mais son certificat de sécurité n\'est pas émis pour « {host} ». Cela signifie généralement que le nom du serveur est un peu faux ; beaucoup de fournisseurs veulent quelque chose comme imap.votrehebergeur.example et non mail.votredomaine.example. Demandez à votre fournisseur le nom exact qu\'il publie.',
'p.no_dns'            => '« {host} » ne résout vers aucune machine. Vérifiez l\'orthographe.',
'p.refused'           => 'On atteint « {host} » mais il a refusé la connexion sur ce port. Le plus probable est que le port soit faux.',
'p.timed_out'         => '« {host} » n\'a pas répondu en {seconds} secondes. Soit le nom du serveur soit le port est faux, soit un pare-feu gêne.',
'p.failed_silent'     => 'La connexion a échoué sans dire pourquoi.',

'p.imap143'           => 'Le port 143 ne convient pas à cet outil.',
'p.imap143_detail'    => 'Le listener ouvre IMAP sur TLS immédiatement (IMAP4_SSL), et le port 143 commence sans chiffrement. Utilisez le 993, que presque tous les fournisseurs proposent.',
'p.no_tls'            => 'Impossible d\'ouvrir une connexion chiffrée vers {host}:{port}.',
'p.tls_ok'            => 'Connecté à {host}:{port} en TLS, et le certificat est correct.',
'p.not_imap'          => 'Ce port a répondu, mais il ne parle pas IMAP.',
'p.said'              => 'Il a dit : {greeting}',
'p.said_nothing'      => 'Il n\'a absolument rien dit.',
'p.is_imap'           => 'Le serveur s\'est identifié comme un serveur IMAP.',
'p.auth_rejected'     => 'Le serveur a refusé cette adresse et ce mot de passe.',
'p.auth_rejected_d'   => 'Beaucoup de fournisseurs veulent ici un mot de passe d\'application plutôt que celui que vous tapez sur leur site. Si le vôtre propose la validation en deux étapes, c\'est presque certainement le cas.',
'p.signed_in'         => 'Connexion réussie.',
'p.signed_in_smtp'    => 'Connexion réussie, l\'agent pourra donc répondre.',
'p.idle_yes'          => 'Le serveur prend en charge IDLE, le courrier nouveau arrive donc en une seconde environ.',
'p.idle_no'           => 'Ce serveur ne propose pas IDLE.',
'p.idle_no_detail'    => 'Sans cela, il n\'y a aucun moyen d\'apprendre l\'arrivée du courrier au moment où il arrive, et cet outil n\'a rien vers quoi se rabattre. Cela vaut la peine d\'interroger votre fournisseur avant de continuer.',

'p.no_reach'          => 'Impossible d\'atteindre {host}:{port}.',
'p.not_smtp'          => 'Ce port a répondu, mais il ne parle pas SMTP.',
'p.no_session'        => 'Le serveur n\'a pas voulu ouvrir de session.',
'p.tls_upgraded'      => 'Connecté à {host}:{port} puis élevé en TLS ; le certificat est correct.',
'p.no_encryption'     => 'Ce serveur ne chiffre pas la connexion sur ce port.',
'p.no_encryption_d'   => 'Envoyer un mot de passe sur un lien non chiffré n\'est pas quelque chose que cet outil va configurer. Essayez le port 465, ou le 587 si votre fournisseur prend en charge STARTTLS.',
'p.starttls_refused'  => 'Le serveur a refusé de passer à une connexion chiffrée.',
'p.tls_failed'        => 'La connexion chiffrée n\'a pas pu être établie.',
'p.no_auth_offered'   => 'Le serveur n\'offre aucun moyen de se connecter sur ce port.',
'p.no_auth_offered_d' => 'Cela signifie généralement que le port sert à autre chose. Le 465 et le 587 sont les deux à essayer.',
'p.auth_method_bad'   => 'Le serveur n\'a pas accepté cette façon de se connecter.',
'p.address_rejected'  => 'Le serveur a refusé l\'adresse.',
'p.send_auth_bad'     => 'Le serveur a refusé cette adresse et ce mot de passe pour l\'envoi.',
'p.send_auth_bad_d'   => 'Si la connexion pour la lecture a fonctionné, certains fournisseurs veulent malgré tout un mot de passe d\'application distinct pour l\'envoi, ou demandent que SMTP soit activé dans les réglages du compte.',

'g.loopback_1'        => 'Cette page ne répond qu\'aux requêtes venant de l\'ordinateur où elle tourne.',
'g.loopback_2'        => 'Si l\'agent est sur un hôte distant, redirigez le port au lieu de ceci :',
'g.token_1'           => 'Il manque à ce lien sa clé à usage unique, ou la clé a changé.',
'g.token_2'           => 'Demandez à l\'agent de relancer scripts/setup_web.sh et de vous envoyer le nouveau lien.',
'g.csrf'              => 'Ce formulaire a expiré. Rechargez la page et remplissez-le de nouveau.',

'f.mkdir_failed'        => 'Impossible de créer {dir}.',
'f.write_failed'        => 'Impossible d\'écrire dans {dir}.',
'f.incomplete'          => 'Le fichier n\'a pas pu être écrit en entier.',
'f.symlink_failed'      => 'Impossible d\'écrire à travers le lien symbolique vers {target}.',
'f.rename_failed'       => 'Impossible de mettre le fichier en place dans {path}.',
];
