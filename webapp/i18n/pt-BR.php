<?php
declare(strict_types=1);

/** Português (BR). Traduzido do es-MX. */

return [

'page.title'        => 'paynani: configuração da caixa de e-mail',
'page.h1'           => 'Dê uma caixa de e-mail ao agente',
'page.lead'         => 'Sete dados do seu provedor de e-mail. Tudo fica neste computador. Esta página não é acessível pela internet.',
'lang.label'        => 'Idioma',
'lang.apply'        => 'Trocar',

'saved.h1'          => 'Pronto',
'saved.lead'        => 'Seu servidor de e-mail aceitou a conta e a configuração ficou salva. Já pode fechar esta página.',
'saved.where'       => 'Salvo em <code>{path}</code>, e só esta conta consegue ler.',
'saved.next_h2'     => 'O que vem agora',
'saved.next_p1'     => 'Avise o agente de que a configuração já está pronta. Ele instala o resto e confere que o e-mail chega; essa parte é trabalho dele, não seu.',
'saved.next_p2'     => 'A única coisa que vale a pena fazer você: mande um e-mail para o agente e pergunte o que acabou de chegar. Se ele responder em uns dois segundos, está tudo funcionando.',
'saved.forgot'      => 'Esta página já esqueceu a senha. Abrir de novo não mostra ela outra vez.',

'warn.existing_p1'  => '<strong>Atenção.</strong> Já existe configuração de e-mail em <code>{path}</code>. Se você terminar este formulário, ela é substituída.',
'warn.existing_p2'  => 'Se o agente já está atendendo e-mail, feche esta página e confirme com quem configurou antes de seguir.',

'help.summary'      => 'Onde eu acho esses dados?',

'help.cpanel_h3'    => 'Se o seu e-mail veio junto com a hospedagem do site (cPanel)',
'help.cpanel_p'     => 'É o caso mais comum, e os dados já estão escritos lá para você.',
'help.cpanel_li1'   => 'Entre no cPanel, normalmente <code>seudominio.example/cpanel</code>, ou o link que o seu provedor mandou.',
'help.cpanel_li2'   => 'Abra <strong>Email Accounts</strong> (Contas de e-mail).',
'help.cpanel_li3'   => 'Ache o endereço que o agente vai usar e clique em <strong>Connect Devices</strong> (em versões antigas se chama <em>Set Up Mail Client</em>).',
'help.cpanel_li4'   => 'Procure <strong>Mail Client Manual Settings</strong> e use a coluna <strong>Secure SSL/TLS Settings</strong>, não a que não tem SSL.',
'help.cpanel_after' => 'Copie <em>Incoming Server</em> e a porta IMAP para a seção de leitura abaixo, e <em>Outgoing Server</em> com a porta SMTP para a de envio. O usuário é o endereço de e-mail completo, e a senha é a que você colocou nessa caixa quando criou. Se não lembrar, o cPanel deixa trocar nessa mesma página.',

'help.gmail_h3'     => 'Gmail ou Google Workspace',
'help.gmail_p1'     => 'Os nomes de servidor são sempre os mesmos: <code>imap.gmail.com</code> porta <code>993</code> para ler, <code>smtp.gmail.com</code> porta <code>465</code> para enviar.',
'help.gmail_p2'     => 'A senha é onde todo mundo trava. O Google não aceita aqui a senha normal. Você precisa de uma <strong>senha de app</strong>, que exige ter a verificação em duas etapas ligada antes. Crie em <code>myaccount.google.com</code> → Segurança → Senhas de app, e cole o código de 16 caracteres que ele der.',
'help.gmail_p3'     => 'Confira também que o IMAP está ligado: Gmail → Configurações → Encaminhamento e POP/IMAP.',

'help.ms_h3'        => 'Outlook.com, Hotmail ou Microsoft 365',
'help.ms_p1'        => '<code>outlook.office365.com</code> porta <code>993</code> para ler, <code>smtp.office365.com</code> porta <code>587</code> para enviar.',
'help.ms_p2'        => 'Muitas contas corporativas da Microsoft já bloqueiam por política logins como este. Se a verificação abaixo recusar a senha mesmo estando certa, normalmente é por isso, e o seu administrador precisa liberar.',

'help.zoho_h3'      => 'Zoho',
'help.zoho_p'       => '<code>imappro.zoho.com</code> porta <code>993</code>, <code>smtp.zoho.com</code> porta <code>465</code>. O Zoho também pede senha de app, não a normal.',

'help.fastmail_h3'  => 'Fastmail',
'help.fastmail_p'   => '<code>imap.fastmail.com</code> porta <code>993</code>, <code>smtp.fastmail.com</code> porta <code>465</code>, com senha de app.',

'help.other_h3'     => 'Qualquer outro',
'help.other_p1'     => 'Pergunte ao seu provedor, ou busque o nome dele mais <em>configuração IMAP e SMTP</em>. Você procura quatro coisas: o nome do servidor de entrada, o de saída, e uma porta para cada um. Prefira as portas marcadas como SSL ou TLS.',
'help.other_p2'     => 'Um aviso que vale repetir: não adivinhe o nome do servidor colocando <code>mail.</code> na frente do seu domínio. Costuma funcionar o suficiente para parecer certo e depois falha no certificado de segurança, que é horrível de diagnosticar depois. A verificação abaixo detecta isso e te fala com todas as letras.',

'form.account_legend' => 'A conta',
'form.account_label'  => 'Endereço de e-mail',
'form.account_ph'     => 'agente@seudominio.example',
'form.account_hint'   => 'A caixa própria do agente, não a sua.',

'form.password_label' => 'Senha',
'form.password_kept'  => '••••••••  a anterior foi mantida',
'form.password_hint'  => 'Se o seu provedor oferece <em>senhas de app</em>, use uma dessas. É o dado que mais acaba recusado quando não.',

'form.fromname_label' => 'Nome visível',
'form.optional'       => 'opcional',
'form.fromname_ph'    => 'Atenea',
'form.fromname_hint'  => 'O nome que as pessoas veem quando o agente escreve para elas.',

'form.imap_legend'    => 'Leitura de e-mail (IMAP)',
'form.smtp_legend'    => 'Envio de e-mail (SMTP)',
'form.server'         => 'Servidor',
'form.port'           => 'Porta',
'form.imap_host_ph'   => 'imap.seuprovedor.example',
'form.smtp_host_ph'   => 'smtp.seuprovedor.example',
'form.imap_hint'      => 'Peça ao seu provedor o nome exato do servidor. Adivinhar colocando <code>imap.</code> na frente do seu domínio costuma produzir um nome que funciona em tudo menos no certificado de segurança, e essa falha é difícil de diagnosticar depois.',
'form.smtp_hint'      => '465 ou 587. As duas se verificam igual.',

'form.submit'         => 'Verificar e salvar',
'form.footnote'       => 'Isto entra na sua caixa e sai na hora; não lê, não envia nem muda nada. A configuração só é salva se o seu servidor de e-mail aceitar, então não há nada a desfazer se algo aqui estiver errado.',

'report.h2'           => 'Ainda não foi salvo: alguma coisa aqui está errada',
'report.imap_h3'      => 'Leitura de e-mail',
'report.smtp_h3'      => 'Envio de e-mail',

'v.account_missing'   => 'O agente precisa de um endereço de e-mail.',
'v.account_bad'       => 'Isso não parece um endereço de e-mail.',
'v.password_missing'  => 'Sem a senha o agente não consegue abrir a caixa.',
'v.fromname_oneline'  => 'O nome visível tem que caber numa única linha.',
'v.host_missing'      => 'Falta o nome do servidor {proto}.',
'v.host_is_port'      => 'Isso é um número de porta, não um nome de servidor. O nome se parece com isto: imap.seuprovedor.example.',
'v.host_has_junk'     => 'Aqui vai só o nome do servidor: sem https://, sem espaços, sem endereço.',
'v.host_bad_chars'    => 'Isso tem caracteres que um nome de servidor não pode ter.',
'v.port_missing'      => 'Falta a porta {proto}.',
'v.port_range'        => 'Uma porta é um número entre 1 e 65535.',

'p.cert_mismatch'     => 'O servidor respondeu, mas o certificado de segurança dele não foi emitido para “{host}”. Normalmente isso quer dizer que o nome do servidor está um pouco errado; muitos provedores querem algo como imap.seuprovedor.example e não mail.seudominio.example. Peça ao seu provedor o nome exato que ele publica.',
'p.no_dns'            => '“{host}” não resolve para nenhuma máquina. Confira como está escrito.',
'p.refused'           => 'Chega-se a “{host}”, mas ele recusou a conexão nessa porta. O mais provável é que a porta esteja errada.',
'p.timed_out'         => '“{host}” não respondeu em {seconds} segundos. Ou o nome do servidor ou a porta estão errados, ou tem um firewall atrapalhando.',
'p.failed_silent'     => 'A conexão falhou sem dizer por quê.',

'p.imap143'           => 'A porta 143 não serve com esta ferramenta.',
'p.imap143_detail'    => 'O listener abre IMAP sobre TLS de imediato (IMAP4_SSL), e a porta 143 começa sem criptografia. Use a 993, que é a que quase todo provedor oferece.',
'p.no_tls'            => 'Não foi possível abrir uma conexão criptografada com {host}:{port}.',
'p.tls_ok'            => 'Conectado a {host}:{port} por TLS, e o certificado está correto.',
'p.not_imap'          => 'Essa porta respondeu, mas não está falando IMAP.',
'p.said'              => 'Disse: {greeting}',
'p.said_nothing'      => 'Não disse absolutamente nada.',
'p.is_imap'           => 'O servidor se identificou como um servidor IMAP.',
'p.auth_rejected'     => 'O servidor recusou esse endereço e senha.',
'p.auth_rejected_d'   => 'Muitos provedores pedem aqui uma senha de app em vez da que você digita no site deles. Se o seu oferece verificação em duas etapas, quase certamente é o caso.',
'p.signed_in'         => 'Sessão iniciada com sucesso.',
'p.signed_in_smtp'    => 'Sessão iniciada com sucesso, então o agente vai conseguir responder.',
'p.idle_yes'          => 'O servidor suporta IDLE, então o e-mail novo chega em mais ou menos um segundo.',
'p.idle_no'           => 'Este servidor não oferece IDLE.',
'p.idle_no_detail'    => 'Sem isso não tem como saber do e-mail novo na hora em que ele chega, e esta ferramenta não tem a que recorrer. Vale perguntar ao seu provedor antes de seguir.',

'p.no_reach'          => 'Não foi possível chegar a {host}:{port}.',
'p.not_smtp'          => 'Essa porta respondeu, mas não está falando SMTP.',
'p.no_session'        => 'O servidor não quis iniciar uma sessão.',
'p.tls_upgraded'      => 'Conectado a {host}:{port} e elevado a TLS; o certificado está correto.',
'p.no_encryption'     => 'Este servidor não criptografa a conexão nessa porta.',
'p.no_encryption_d'   => 'Mandar uma senha por um enlace sem criptografia não é algo que esta ferramenta vá configurar. Tente a porta 465, ou a 587 se o seu provedor suportar STARTTLS.',
'p.starttls_refused'  => 'O servidor se negou a mudar para uma conexão criptografada.',
'p.tls_failed'        => 'Não foi possível estabelecer a conexão criptografada.',
'p.no_auth_offered'   => 'O servidor não oferece jeito de iniciar sessão nessa porta.',
'p.no_auth_offered_d' => 'Normalmente isso quer dizer que a porta é para outra coisa. A 465 e a 587 são as duas que vale testar.',
'p.auth_method_bad'   => 'O servidor não aceitou esta forma de iniciar sessão.',
'p.address_rejected'  => 'O servidor recusou o endereço.',
'p.send_auth_bad'     => 'O servidor recusou esse endereço e senha para enviar.',
'p.send_auth_bad_d'   => 'Se o login para leitura funcionou, tem provedor que ainda pede uma senha de app separada para enviar, ou que o SMTP seja ligado nas configurações da conta.',

'g.loopback_1'        => 'Esta página só responde a requisições do computador onde ela roda.',
'g.loopback_2'        => 'Se o agente está num host remoto, encaminhe a porta em vez disto:',
'g.token_1'           => 'Falta a chave de uso único deste link, ou a chave mudou.',
'g.token_2'           => 'Peça ao agente para rodar scripts/setup_web.sh de novo e te mandar o link novo.',
'g.csrf'              => 'Esse formulário expirou. Recarregue a página e preencha de novo.',
];
