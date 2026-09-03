<?php
declare(strict_types=1);

/** English (US). Translated from es-MX. */

return [

'page.title'        => 'paynani: mailbox setup',
'page.h1'           => 'Give the agent a mailbox',
'page.lead'         => 'Seven details from your mail provider. Everything stays on this computer. This page is not reachable from the internet.',
'lang.label'        => 'Language',
'lang.apply'        => 'Change',

'saved.h1'          => 'Done',
'saved.lead'        => 'Your mail server accepted the account and the settings are saved. You can close this page.',
'saved.where'       => 'Saved to <code>{path}</code>, and only this account can read it.',
'saved.next_h2'     => 'What happens next',
'saved.next_p1'     => 'Tell the agent the settings are in place. It installs the rest and checks that mail arrives; that part is its job, not yours.',
'saved.next_p2'     => 'The one thing worth doing yourself: send the agent an email and ask what just arrived. If it answers within a couple of seconds, everything works.',
'saved.forgot'      => 'This page has already forgotten the password. Opening it again will not show it.',

'warn.existing_p1'  => '<strong>Careful.</strong> There is already mail configuration at <code>{path}</code>. Finishing this form replaces it.',
'warn.existing_p2'  => 'If the agent is already handling mail, close this page and check with whoever set it up before going on.',

'help.summary'      => 'Where do I find these?',

'help.cpanel_h3'    => 'If your mail came with your web hosting (cPanel)',
'help.cpanel_p'     => 'This is the most common case, and the details are already written down there for you.',
'help.cpanel_li1'   => 'Sign in to cPanel, usually <code>yourdomain.example/cpanel</code>, or the link your provider sent you.',
'help.cpanel_li2'   => 'Open <strong>Email Accounts</strong>.',
'help.cpanel_li3'   => 'Find the address the agent will use and click <strong>Connect Devices</strong> (older versions call it <em>Set Up Mail Client</em>).',
'help.cpanel_li4'   => 'Look for <strong>Mail Client Manual Settings</strong> and use the <strong>Secure SSL/TLS Settings</strong> column, not the one without SSL.',
'help.cpanel_after' => 'Copy <em>Incoming Server</em> and its IMAP port into the reading section below, and <em>Outgoing Server</em> with its SMTP port into the sending one. The username is the full email address, and the password is the one you gave that mailbox when you created it. If you do not remember it, cPanel lets you change it on that same page.',

'help.gmail_h3'     => 'Gmail or Google Workspace',
'help.gmail_p1'     => 'The hostnames are always the same: <code>imap.gmail.com</code> port <code>993</code> for reading, <code>smtp.gmail.com</code> port <code>465</code> for sending.',
'help.gmail_p2'     => 'The password is where people get stuck. Google will not accept the normal one here. You need an <strong>app password</strong>, which first requires two-step verification to be on. Create it at <code>myaccount.google.com</code> → Security → App passwords, and paste the 16-character code it gives you.',
'help.gmail_p3'     => 'Check that IMAP is switched on too: Gmail → Settings → Forwarding and POP/IMAP.',

'help.ms_h3'        => 'Outlook.com, Hotmail or Microsoft 365',
'help.ms_p1'        => '<code>outlook.office365.com</code> port <code>993</code> for reading, <code>smtp.office365.com</code> port <code>587</code> for sending.',
'help.ms_p2'        => 'Many Microsoft business accounts now block sign-ins like this one by policy. If the check below rejects the password even though it is right, that is usually why, and your administrator has to allow it.',

'help.zoho_h3'      => 'Zoho',
'help.zoho_p'       => '<code>imappro.zoho.com</code> port <code>993</code>, <code>smtp.zoho.com</code> port <code>465</code>. Zoho also wants an app password, not the normal one.',

'help.fastmail_h3'  => 'Fastmail',
'help.fastmail_p'   => '<code>imap.fastmail.com</code> port <code>993</code>, <code>smtp.fastmail.com</code> port <code>465</code>, with an app password.',

'help.other_h3'     => 'Anyone else',
'help.other_p1'     => 'Ask your provider, or search their name plus <em>IMAP and SMTP settings</em>. You are after four things: the incoming hostname, the outgoing one, and a port for each. Prefer the ports marked SSL or TLS.',
'help.other_p2'     => 'One warning worth repeating: do not guess the hostname by putting <code>mail.</code> in front of your domain. It often works just enough to look right and then fails on the security certificate, which is horrible to diagnose afterwards. The check below catches it and tells you plainly.',

'form.account_legend' => 'The account',
'form.account_label'  => 'Email address',
'form.account_ph'     => 'agent@yourdomain.example',
'form.account_hint'   => 'The agent\'s own mailbox, not yours.',

'form.password_label' => 'Password',
'form.password_kept'  => '••••••••  the previous one was kept',
'form.password_hint'  => 'If your provider offers <em>app passwords</em>, use one of those. It is the detail that most often ends up rejected otherwise.',

'form.fromname_label' => 'Display name',
'form.optional'       => 'optional',
'form.fromname_ph'    => 'Atenea',
'form.fromname_hint'  => 'The name people see when the agent writes to them.',

'form.imap_legend'    => 'Reading mail (IMAP)',
'form.smtp_legend'    => 'Sending mail (SMTP)',
'form.server'         => 'Server',
'form.port'           => 'Port',
'form.imap_host_ph'   => 'imap.yourprovider.example',
'form.smtp_host_ph'   => 'smtp.yourprovider.example',
'form.imap_hint'      => 'Ask your provider for the exact hostname. Guessing it by putting <code>imap.</code> in front of your domain often produces a name that works for everything except the security certificate, and that failure is hard to diagnose afterwards.',
'form.smtp_hint'      => '465 or 587. Both are checked the same way.',

'form.submit'         => 'Check and save',
'form.footnote'       => 'This signs in to your mailbox and straight back out; it does not read, send or change anything. The settings are only saved if your mail server accepts them, so there is nothing to undo if something here is wrong.',

'report.h2'           => 'Not saved yet: something here is wrong',
'report.imap_h3'      => 'Reading mail',
'report.smtp_h3'      => 'Sending mail',

'v.account_missing'   => 'The agent needs an email address.',
'v.account_bad'       => 'That does not look like an email address.',
'v.password_missing'  => 'Without the password the agent cannot open the mailbox.',
'v.fromname_oneline'  => 'The display name has to fit on a single line.',
'v.host_missing'      => 'The {proto} hostname is missing.',
'v.host_is_port'      => 'That is a port number, not a hostname. A hostname looks like this: imap.yourprovider.example.',
'v.host_has_junk'     => 'Only the hostname goes here: no https://, no spaces, no address.',
'v.host_bad_chars'    => 'That contains characters a hostname cannot have.',
'v.port_missing'      => 'The {proto} port is missing.',
'v.port_range'        => 'A port is a number between 1 and 65535.',

'p.cert_mismatch'     => 'The server answered, but its security certificate is not issued for “{host}”. That usually means the hostname is slightly wrong; many providers want something like imap.yourprovider.example rather than mail.yourdomain.example. Ask your provider for the exact name they publish.',
'p.no_dns'            => '“{host}” does not resolve to any machine. Check the spelling.',
'p.refused'           => '“{host}” is reachable but refused the connection on that port. Most likely the port is wrong.',
'p.timed_out'         => '“{host}” did not answer within {seconds} seconds. Either the hostname or the port is wrong, or a firewall is in the way.',
'p.failed_silent'     => 'The connection failed without saying why.',

'p.imap143'           => 'Port 143 does not work with this tool.',
'p.imap143_detail'    => 'The listener opens IMAP over TLS immediately (IMAP4_SSL), and port 143 starts unencrypted. Use 993, which almost every provider offers.',
'p.no_tls'            => 'Could not open an encrypted connection to {host}:{port}.',
'p.tls_ok'            => 'Connected to {host}:{port} over TLS, and the certificate checks out.',
'p.not_imap'          => 'That port answered, but it is not speaking IMAP.',
'p.said'              => 'It said: {greeting}',
'p.said_nothing'      => 'It said nothing at all.',
'p.is_imap'           => 'The server identified itself as an IMAP server.',
'p.auth_rejected'     => 'The server rejected that address and password.',
'p.auth_rejected_d'   => 'Many providers want an app password here instead of the one you type on their website. If yours offers two-step verification, that is almost certainly the case.',
'p.signed_in'         => 'Signed in successfully.',
'p.signed_in_smtp'    => 'Signed in successfully, so the agent will be able to reply.',
'p.idle_yes'          => 'The server supports IDLE, so new mail arrives within about a second.',
'p.idle_no'           => 'This server does not offer IDLE.',
'p.idle_no_detail'    => 'Without it there is no way to find out about new mail as it arrives, and this tool has nothing to fall back on. It is worth asking your provider before going on.',

'p.no_reach'          => 'Could not reach {host}:{port}.',
'p.not_smtp'          => 'That port answered, but it is not speaking SMTP.',
'p.no_session'        => 'The server would not start a session.',
'p.tls_upgraded'      => 'Connected to {host}:{port} and upgraded to TLS; the certificate checks out.',
'p.no_encryption'     => 'This server does not encrypt the connection on that port.',
'p.no_encryption_d'   => 'Sending a password over an unencrypted link is not something this tool will configure. Try port 465, or 587 if your provider supports STARTTLS.',
'p.starttls_refused'  => 'The server refused to switch to an encrypted connection.',
'p.tls_failed'        => 'The encrypted connection could not be established.',
'p.no_auth_offered'   => 'The server offers no way to sign in on that port.',
'p.no_auth_offered_d' => 'That usually means the port is for something else. 465 and 587 are the two worth trying.',
'p.auth_method_bad'   => 'The server did not accept this way of signing in.',
'p.address_rejected'  => 'The server rejected the address.',
'p.send_auth_bad'     => 'The server rejected that address and password for sending.',
'p.send_auth_bad_d'   => 'If signing in for reading worked, some providers still want a separate app password for sending, or need SMTP switched on in your account settings.',

'g.loopback_1'        => 'This page only answers requests from the computer it runs on.',
'g.loopback_2'        => 'If the agent is on a remote host, forward the port instead of this:',
'g.token_1'           => 'This link is missing its one-time key, or the key changed.',
'g.token_2'           => 'Ask the agent to run scripts/setup_web.sh again and send you the new link.',
'g.csrf'              => 'That form expired. Reload the page and fill it in again.',
];
