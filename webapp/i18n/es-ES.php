<?php
declare(strict_types=1);

/** Español (ES). Traducido de es-MX: ordenador, léxico peninsular. */

return [

'page.title'        => 'paynani: configuración del buzón',
'page.h1'           => 'Dale un buzón al agente',
'page.lead'         => 'Siete datos de tu proveedor de correo. Todo se queda en este ordenador. Esta página no es accesible desde internet.',
'lang.label'        => 'Idioma',
'lang.apply'        => 'Cambiar',

'saved.h1'          => 'Listo',
'saved.lead'        => 'Tu servidor de correo aceptó la cuenta y la configuración ha quedado guardada. Ya puedes cerrar esta página.',
'saved.where'       => 'Se ha guardado en <code>{path}</code>, y solo esta cuenta puede leerlo.',
'saved.next_h2'     => 'Qué viene ahora',
'saved.next_p1'     => 'Avisa al agente de que la configuración ya está. Él instala el resto y comprueba que el correo llegue; esa parte es su trabajo, no el tuyo.',
'saved.next_p2'     => 'Lo único que merece la pena hacer tú: mándale un correo al agente y pregúntale qué acaba de llegar. Si te contesta en un par de segundos, todo funciona.',
'saved.forgot'      => 'Esta página ya ha olvidado la contraseña. Volver a abrirla no la muestra otra vez.',

'warn.existing_p1'  => '<strong>Cuidado.</strong> Ya hay configuración de correo en <code>{path}</code>. Si terminas este formulario, la reemplaza.',
'warn.existing_p2'  => 'Si el agente ya está atendiendo correo, cierra esta página y confírmalo con quien lo configuró antes de seguir.',

'help.summary'      => '¿Dónde encuentro estos datos?',

'help.cpanel_h3'    => 'Si tu correo vino con tu alojamiento web (cPanel)',
'help.cpanel_p'     => 'Es el caso más común, y los datos ya están escritos ahí para ti.',
'help.cpanel_li1'   => 'Entra en cPanel, normalmente <code>tudominio.example/cpanel</code>, o el enlace que te mandó tu proveedor.',
'help.cpanel_li2'   => 'Abre <strong>Email Accounts</strong> (Cuentas de correo).',
'help.cpanel_li3'   => 'Busca la dirección que va a usar el agente y haz clic en <strong>Connect Devices</strong> (en versiones antiguas se llama <em>Set Up Mail Client</em>).',
'help.cpanel_li4'   => 'Busca <strong>Mail Client Manual Settings</strong> y usa la columna <strong>Secure SSL/TLS Settings</strong>, no la que no lleva SSL.',
'help.cpanel_after' => 'Copia <em>Incoming Server</em> y su puerto IMAP en la sección de lectura de abajo, y <em>Outgoing Server</em> con su puerto SMTP en la de envío. El usuario es la dirección de correo completa, y la contraseña es la que le pusiste a ese buzón al crearlo. Si no la recuerdas, cPanel te deja cambiarla en esa misma página.',

'help.gmail_h3'     => 'Gmail o Google Workspace',
'help.gmail_p1'     => 'Los nombres de servidor son siempre los mismos: <code>imap.gmail.com</code> puerto <code>993</code> para leer, <code>smtp.gmail.com</code> puerto <code>465</code> para enviar.',
'help.gmail_p2'     => 'La contraseña es donde se atasca la gente. Google no acepta aquí la normal. Necesitas una <strong>contraseña de aplicación</strong>, que requiere tener activada antes la verificación en dos pasos. Créala en <code>myaccount.google.com</code> → Seguridad → Contraseñas de aplicaciones, y pega el código de 16 caracteres que te dé.',
'help.gmail_p3'     => 'Comprueba también que IMAP esté activado: Gmail → Configuración → Reenvío y correo POP/IMAP.',

'help.ms_h3'        => 'Outlook.com, Hotmail o Microsoft 365',
'help.ms_p1'        => '<code>outlook.office365.com</code> puerto <code>993</code> para leer, <code>smtp.office365.com</code> puerto <code>587</code> para enviar.',
'help.ms_p2'        => 'Muchas cuentas de empresa de Microsoft ya bloquean por política los inicios de sesión como este. Si la comprobación de abajo rechaza la contraseña aunque sea correcta, normalmente es por eso, y tu administrador tiene que permitirlo.',

'help.zoho_h3'      => 'Zoho',
'help.zoho_p'       => '<code>imappro.zoho.com</code> puerto <code>993</code>, <code>smtp.zoho.com</code> puerto <code>465</code>. Zoho también pide una contraseña de aplicación, no la normal.',

'help.fastmail_h3'  => 'Fastmail',
'help.fastmail_p'   => '<code>imap.fastmail.com</code> puerto <code>993</code>, <code>smtp.fastmail.com</code> puerto <code>465</code>, con contraseña de aplicación.',

'help.other_h3'     => 'Cualquier otro',
'help.other_p1'     => 'Pregunta a tu proveedor, o busca su nombre más <em>configuración IMAP y SMTP</em>. Buscas cuatro cosas: el nombre del servidor de entrada, el de salida, y un puerto para cada uno. Prefiere los puertos marcados como SSL o TLS.',
'help.other_p2'     => 'Una advertencia que merece la pena repetir: no adivines el nombre del servidor poniendo <code>mail.</code> delante de tu dominio. A menudo funciona lo justo para parecer correcto y luego falla en el certificado de seguridad, que es horrible de diagnosticar después. La comprobación de abajo lo detecta y te lo dice claro.',

'form.account_legend' => 'La cuenta',
'form.account_label'  => 'Dirección de correo',
'form.account_ph'     => 'agente@tudominio.example',
'form.account_hint'   => 'El buzón propio del agente, no el tuyo.',

'form.password_label' => 'Contraseña',
'form.password_kept'  => '••••••••  se ha conservado la anterior',
'form.password_hint'  => 'Si tu proveedor ofrece <em>contraseñas de aplicación</em>, usa una de esas. Es el dato que más a menudo acaba rechazado si no.',

'form.fromname_label' => 'Nombre visible',
'form.optional'       => 'opcional',
'form.fromname_ph'    => 'Atenea',
'form.fromname_hint'  => 'El nombre que ve la gente cuando el agente les escribe.',

'form.imap_legend'    => 'Lectura de correo (IMAP)',
'form.smtp_legend'    => 'Envío de correo (SMTP)',
'form.server'         => 'Servidor',
'form.port'           => 'Puerto',
'form.imap_host_ph'   => 'imap.tuproveedor.example',
'form.smtp_host_ph'   => 'smtp.tuproveedor.example',
'form.imap_hint'      => 'Pide a tu proveedor el nombre exacto del servidor. Adivinarlo poniendo <code>imap.</code> delante de tu dominio produce a menudo un nombre que funciona en todo menos en el certificado de seguridad, y ese fallo es difícil de diagnosticar después.',
'form.smtp_hint'      => '465 o 587. Los dos se comprueban igual.',

'form.submit'         => 'Comprobar y guardar',
'form.footnote'       => 'Esto entra en tu buzón y sale de inmediato; no lee, no envía ni cambia nada. La configuración se guarda solo si tu servidor de correo la acepta, así que no hay nada que deshacer si algo aquí está mal.',

'report.h2'           => 'Todavía no se guarda: algo aquí no está bien',
'report.imap_h3'      => 'Lectura de correo',
'report.smtp_h3'      => 'Envío de correo',

'v.account_missing'   => 'El agente necesita una dirección de correo.',
'v.account_bad'       => 'Eso no parece una dirección de correo.',
'v.password_missing'  => 'Sin la contraseña el agente no puede abrir el buzón.',
'v.fromname_oneline'  => 'El nombre visible tiene que caber en una sola línea.',
'v.host_missing'      => 'Falta el nombre del servidor {proto}.',
'v.host_is_port'      => 'Eso es un número de puerto, no un nombre de servidor. El nombre se ve así: imap.tuproveedor.example.',
'v.host_has_junk'     => 'Aquí va solo el nombre del servidor: sin https://, sin espacios, sin dirección.',
'v.host_bad_chars'    => 'Eso lleva caracteres que un nombre de servidor no puede tener.',
'v.port_missing'      => 'Falta el puerto {proto}.',
'v.port_range'        => 'Un puerto es un número entre 1 y 65535.',

'p.cert_mismatch'     => 'El servidor contestó, pero su certificado de seguridad no está emitido para «{host}». Normalmente eso significa que el nombre del servidor está un poco mal; muchos proveedores quieren algo como imap.tuproveedor.example y no mail.tudominio.example. Pide a tu proveedor el nombre exacto que publica.',
'p.no_dns'            => '«{host}» no resuelve a ninguna máquina. Revisa cómo está escrito.',
'p.refused'           => 'Se llega a «{host}» pero rechazó la conexión en ese puerto. Lo más probable es que el puerto esté mal.',
'p.timed_out'         => '«{host}» no contestó en {seconds} segundos. O el nombre del servidor o el puerto están mal, o hay un cortafuegos estorbando.',
'p.failed_silent'     => 'La conexión falló sin decir por qué.',

'p.imap143'           => 'El puerto 143 no sirve con esta herramienta.',
'p.imap143_detail'    => 'El listener abre IMAP sobre TLS de inmediato (IMAP4_SSL), y el puerto 143 empieza sin cifrar. Usa el 993, que es el que ofrece casi cualquier proveedor.',
'p.no_tls'            => 'No se pudo abrir una conexión cifrada a {host}:{port}.',
'p.tls_ok'            => 'Conectado a {host}:{port} por TLS, y el certificado es correcto.',
'p.not_imap'          => 'Ese puerto contestó, pero no está hablando IMAP.',
'p.said'              => 'Dijo: {greeting}',
'p.said_nothing'      => 'No dijo absolutamente nada.',
'p.is_imap'           => 'El servidor se identificó como un servidor IMAP.',
'p.auth_rejected'     => 'El servidor rechazó esa dirección y contraseña.',
'p.auth_rejected_d'   => 'Muchos proveedores piden aquí una contraseña de aplicación en lugar de la que escribes en su web. Si el tuyo ofrece verificación en dos pasos, casi seguro es el caso.',
'p.signed_in'         => 'Sesión iniciada correctamente.',
'p.signed_in_smtp'    => 'Sesión iniciada correctamente, así que el agente va a poder responder.',
'p.idle_yes'          => 'El servidor soporta IDLE, así que el correo nuevo llega en un segundo aproximadamente.',
'p.idle_no'           => 'Este servidor no ofrece IDLE.',
'p.idle_no_detail'    => 'Sin eso no hay manera de enterarse del correo nuevo cuando llega, y esta herramienta no tiene nada a lo que recurrir. Merece la pena preguntar a tu proveedor antes de seguir.',

'p.no_reach'          => 'No se pudo llegar a {host}:{port}.',
'p.not_smtp'          => 'Ese puerto contestó, pero no está hablando SMTP.',
'p.no_session'        => 'El servidor no quiso iniciar una sesión.',
'p.tls_upgraded'      => 'Conectado a {host}:{port} y elevado a TLS; el certificado es correcto.',
'p.no_encryption'     => 'Este servidor no cifra la conexión en ese puerto.',
'p.no_encryption_d'   => 'Mandar una contraseña por un enlace sin cifrar no es algo que esta herramienta vaya a configurar. Prueba el puerto 465, o el 587 si tu proveedor soporta STARTTLS.',
'p.starttls_refused'  => 'El servidor se negó a cambiar a una conexión cifrada.',
'p.tls_failed'        => 'No se pudo establecer la conexión cifrada.',
'p.no_auth_offered'   => 'El servidor no ofrece manera de iniciar sesión en ese puerto.',
'p.no_auth_offered_d' => 'Normalmente eso significa que el puerto es para otra cosa. El 465 y el 587 son los dos que hay que probar.',
'p.auth_method_bad'   => 'El servidor no aceptó esta forma de iniciar sesión.',
'p.address_rejected'  => 'El servidor rechazó la dirección.',
'p.send_auth_bad'     => 'El servidor rechazó esa dirección y contraseña para enviar.',
'p.send_auth_bad_d'   => 'Si el inicio de sesión para leer sí funcionó, hay proveedores que además piden una contraseña de aplicación distinta para enviar, o que se active SMTP en la configuración de la cuenta.',

'g.loopback_1'        => 'Esta página solo responde a peticiones desde el ordenador donde se ejecuta.',
'g.loopback_2'        => 'Si el agente está en un host remoto, reenvía el puerto en lugar de esto:',
'g.token_1'           => 'A este enlace le falta su llave de un solo uso, o la llave ha cambiado.',
'g.token_2'           => 'Pide al agente que ejecute scripts/setup_web.sh otra vez y te mande el enlace nuevo.',
'g.csrf'              => 'Ese formulario ha caducado. Recarga la página y rellénalo de nuevo.',
];
