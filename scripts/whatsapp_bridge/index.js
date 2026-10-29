// Puente de Baileys para paynani-whatsapp (WHATSAPP_BRIDGE.md, PRD #550 FR-2).
//
// Lo arranca el servicio como proceso hijo. Lee órdenes por stdin, contesta por
// stdout, un JSON por línea, y su log va a stderr. No abre puertos ni sockets: la
// única conexión es la de Baileys con WhatsApp.

import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {
  PROTOCOL, ID_RE, E164_RE, MAX_TEXT, MAX_FILE_BYTES, CODE_TTL_MS,
  parseLine, refOf, isDirectChat, isLidJid, isPnJid, normalizeJid, pnJidToE164,
  e164ToJid, extForMime, classify, unwrap, makeLogger, receiptStatus, callOutcome,
  sendContent, quietConsole, resolveJid,
} from './lib.js';

process.umask(0o077);

// La versión del puente es la de paynani: salen juntos (WHATSAPP_BRIDGE.md §9).
const BRIDGE_VERSION = (() => {
  try { return fs.readFileSync(new URL('../../VERSION', import.meta.url), 'utf8').trim(); } catch { return null; }
})();
const log = (line) => process.stderr.write(`${String(line).slice(0, 1000)}\n`);
const out = (obj) => process.stdout.write(`${JSON.stringify(obj)}\n`);
quietConsole(console, log); // antes de cargar Baileys: libsignal escribe con console.*
const result = (ref, data = {}) => out({ type: 'result', ref, ok: true, data });
const fail = (ref, code, detail, extra = {}) => out({ type: 'error', ref, code, ...(detail ? { detail } : {}), ...extra });
const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');

let B = null; // Baileys, cargado en `start` para que un fallo de dependencias salga con código 2
let cfg = null; // lo que mandó `start`
let sock = null;
let allowed = new Set();
let state = { state: 'unlinked', me: null, since: nowIso(), reason: null };
let link = null; // {mode, number, timer, codeSent}
let reconnectTimer = null;
let reconnectStep = 0;
let closing = false;
const calls = new Map(); // call_id -> {accepted, done}

function setStatus(next, reason = null) {
  const me = sock?.user?.id ? pnJidToE164(normalizeJid(sock.user.id)) : state.me;
  if (state.state === next && state.reason === reason && state.me === me) return;
  state = { state: next, me: next === 'unlinked' ? null : me, since: nowIso(), reason };
  out({ type: 'status', ...state });
}

// --- llaves (FR-10) ---------------------------------------------------------

// lstat, nunca stat: un auth/ que es un enlace simbólico se rechaza, porque `logout`
// borraría lo que hay del otro lado (FR-10).
function realDir(dir) {
  try {
    const st = fs.lstatSync(dir);
    return st.isDirectory() && !st.isSymbolicLink() ? st : null;
  } catch {
    return null;
  }
}

function checkAuthDir(dir) {
  const st = realDir(dir);
  if (!st || (st.mode & 0o077) !== 0) return false;
  for (const name of fs.readdirSync(dir)) {
    const f = fs.lstatSync(path.join(dir, name));
    if (f.isSymbolicLink() || (f.mode & 0o077) !== 0) return false;
  }
  return true;
}

function hasCreds() {
  try {
    const creds = JSON.parse(fs.readFileSync(path.join(cfg.auth_dir, 'creds.json'), 'utf8'));
    return Boolean(creds?.me?.id) && creds.registered !== false;
  } catch {
    return false;
  }
}

function wipeAuth() {
  if (!realDir(cfg.auth_dir)) {
    log('auth_dir dejó de ser una carpeta: no se borra nada');
    process.exit(4);
  }
  for (const name of fs.readdirSync(cfg.auth_dir)) {
    fs.rmSync(path.join(cfg.auth_dir, name), { recursive: true, force: true });
  }
}

// --- la conexión ------------------------------------------------------------

async function connect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  if (sock) {
    sock.ev.removeAllListeners();
    try { sock.end(undefined); } catch { /* ya cerrado */ }
    sock = null;
  }
  const { state: auth, saveCreds } = await B.useMultiFileAuthState(cfg.auth_dir);
  const s = B.makeWASocket({
    auth,
    logger: makeLogger(log),
    browser: B.Browsers.ubuntu('Chrome'),
    markOnlineOnConnect: false, // FR-4
    syncFullHistory: false, // FR-4a
    shouldSyncHistoryMessage: () => false,
    fireInitQueries: true,
    generateHighQualityLinkPreview: false,
    getMessage: async () => undefined,
  });
  sock = s;
  if (!link) setStatus('connecting');
  s.ev.on('creds.update', saveCreds);
  s.ev.on('connection.update', (u) => onConnection(s, u).catch((e) => log(`connection: ${e?.message}`)));
  s.ev.on('messages.upsert', (u) => onUpsert(s, u).catch((e) => log(`upsert: ${e?.message}`)));
  s.ev.on('messages.update', onUpdates);
  s.ev.on('call', onCalls);
}

async function onConnection(s, u) {
  if (s !== sock) return;
  if (u.qr && link) {
    if (link.mode === 'qr') {
      out({ type: 'link.qr', qr: u.qr, expires_at: new Date(Date.now() + 20000).toISOString().replace(/\.\d{3}Z$/, 'Z') });
    } else if (!link.codeSent) {
      link.codeSent = true;
      const raw = await s.requestPairingCode(link.number.slice(1));
      const code = raw.length === 8 ? `${raw.slice(0, 4)}-${raw.slice(4)}` : raw;
      out({ type: 'link.code', code, expires_at: new Date(Date.now() + CODE_TTL_MS).toISOString().replace(/\.\d{3}Z$/, 'Z') });
    }
  }
  if (u.connection === 'open') {
    reconnectStep = 0;
    if (link) endLink('linked');
    setStatus('connected');
    return;
  }
  if (u.connection === 'close') {
    const code = u.lastDisconnect?.error?.output?.statusCode;
    const DR = B.DisconnectReason;
    if (closing) return;
    if (code === DR.loggedOut) {
      sock = null;
      wipeAuth();
      if (link) endLink('failed');
      setStatus('logged_out', 'logged_out');
      setStatus('unlinked', 'logged_out');
      return;
    }
    if (code === DR.restartRequired) { // justo después de vincular
      connect().catch((e) => log(`connect: ${e?.message}`));
      return;
    }
    if (link && (code === DR.timedOut || !hasCreds())) {
      sock = null;
      endLink('expired');
      return;
    }
    const reason = code === DR.connectionReplaced ? 'replaced' : code === DR.badSession ? 'bad_session' : 'connection_lost';
    setStatus('disconnected', reason);
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnectTimer || closing) return;
  const waits = [2, 5, 10, 30, 60];
  const wait = waits[Math.min(reconnectStep, waits.length - 1)] * 1000;
  reconnectStep += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (hasCreds()) connect().catch((e) => log(`connect: ${e?.message}`));
    else setStatus('unlinked');
  }, wait);
}

// --- vincular (FR-6, FR-6a) -------------------------------------------------

function endLink(reason) {
  if (!link) return;
  clearTimeout(link.timer);
  const ended = link;
  link = null;
  if (reason === 'linked') {
    out({ type: 'link.ended', reason, me: sock?.user?.id ? pnJidToE164(normalizeJid(sock.user.id)) : null });
    return;
  }
  out({ type: 'link.ended', reason });
  if (!ended.keepSocket && !hasCreds()) {
    if (sock) {
      sock.ev.removeAllListeners();
      try { sock.end(undefined); } catch { /* nada */ }
      sock = null;
    }
    wipeAuth();
    setStatus('unlinked');
  }
}

async function startLink(ref, msg) {
  if (msg.mode !== 'qr' && msg.mode !== 'code') return fail(ref, 'missing_field', 'mode es qr o code', { field: 'mode' });
  if (msg.mode === 'code' && !E164_RE.test(msg.number || '')) return fail(ref, 'missing_field', 'number en E.164', { field: 'number' });
  if (hasCreds() && state.state === 'connected') return fail(ref, 'already_linked');
  if (link) {
    link.keepSocket = true;
    endLink('replaced');
  }
  wipeAuth();
  link = { mode: msg.mode, number: msg.number || null, codeSent: false, keepSocket: false };
  link.timer = setTimeout(() => endLink('expired'), msg.mode === 'code' ? CODE_TTL_MS : 5 * 60 * 1000);
  setStatus('linking');
  result(ref);
  await connect();
}

// --- lo que llega (FR-11, FR-13, FR-16, FR-17, FR-18) -----------------------

function resolveSender(s, key) {
  return resolveJid(s, key.remoteJid, key.remoteJidAlt);
}

async function saveMedia(s, msg, info) {
  const maxBytes = (Number(cfg.max_media_mb) || 25) * 1024 * 1024;
  const media = { mime: info.mime, bytes: info.bytes, sha256: null, path: null,
    filename: info.filename, seconds: info.seconds, voice_note: info.voice_note };
  if (info.bytes && info.bytes > maxBytes) return { ...media, skipped: 'too_large' };
  try {
    const buf = await B.downloadMediaMessage(msg, 'buffer', {}, { logger: makeLogger(log), reuploadRequest: s.updateMediaMessage });
    if (buf.length > maxBytes) return { ...media, skipped: 'too_large' };
    const sha = createHash('sha256').update(buf).digest('hex');
    const file = path.join(cfg.media_dir, `${sha}.${extForMime(info.mime)}`);
    try { fs.writeFileSync(file, buf, { mode: 0o600, flag: 'wx' }); } catch (e) { if (e.code !== 'EEXIST') throw e; }
    return { ...media, sha256: sha, bytes: buf.length, path: file };
  } catch (e) {
    log(`media: descarga fallida (${e?.name || 'error'})`);
    return { ...media, skipped: 'download_failed' };
  }
}

async function onUpsert(s, { messages, type }) {
  if (type !== 'notify') return; // `append` es historial (FR-4a)
  for (const msg of messages) {
    const key = msg.key || {};
    if (key.fromMe || !isDirectChat(key.remoteJid) || !msg.message) continue;
    if (unwrap(msg.message)?.protocolMessage?.type === 5 /* HISTORY_SYNC_NOTIFICATION */) continue;
    const info = classify(msg.message);
    if (!info) continue;
    const from = await resolveSender(s, key);
    let media = null;
    if (info.media) {
      const { key: _k, ...m } = info.media;
      media = await saveMedia(s, msg, m);
    }
    const ts = Number(msg.messageTimestamp || 0);
    out({
      type: 'message', key_id: key.id, chat: from.jid, from,
      push_name: msg.pushName || null,
      sent_at: ts ? new Date(ts * 1000).toISOString().replace(/\.\d{3}Z$/, 'Z') : nowIso(),
      kind: info.kind, text: info.text, media,
    });
  }
}

function onUpdates(updates) {
  for (const { key, update } of updates) {
    if (!key?.fromMe || update?.status == null) continue;
    const status = receiptStatus(update.status);
    if (status) out({ type: 'receipt', key_id: key.id, chat: normalizeJid(key.remoteJid), status, at: nowIso() });
  }
}

function onCalls(list) {
  for (const c of list) {
    const seen = calls.get(c.id) || { accepted: false, done: false };
    const outcome = callOutcome(c.status, seen.accepted);
    if (c.status === 'accept') seen.accepted = true;
    if (outcome && !seen.done && (!c.isGroup)) {
      seen.done = true;
      const at = nowIso();
      resolveJid(sock, c.from, c.callerPn).then((from) => out({ type: 'call', call_id: c.id,
        from, status: outcome, video: Boolean(c.isVideo), at }));
    }
    calls.set(c.id, seen);
    if (calls.size > 200) calls.delete(calls.keys().next().value);
  }
}

// --- lo que sale (FR-19 a FR-23) --------------------------------------------

async function send(ref, msg) {
  if (state.state !== 'connected' || !sock) return fail(ref, 'not_connected');
  if (!E164_RE.test(msg.to || '')) return fail(ref, 'missing_field', 'to en E.164', { field: 'to' });
  if (!allowed.has(msg.to)) return fail(ref, 'not_allowed', 'el número no está en allowed');
  const text = typeof msg.text === 'string' ? msg.text : '';
  if (text.length > MAX_TEXT) return fail(ref, 'too_large', 'text de más de 4,000');
  if (!msg.file && !text) return fail(ref, 'missing_field', 'text vacío', { field: 'text' });
  if (msg.file) {
    let st;
    try { st = fs.lstatSync(msg.file.path); } catch { return fail(ref, 'not_allowed', 'el archivo no existe'); }
    if (!st.isFile()) return fail(ref, 'not_allowed', 'no es un archivo regular');
    if (st.size > MAX_FILE_BYTES) return fail(ref, 'too_large', 'archivo de más de 64 MB');
  }
  try {
    const sent = await sock.sendMessage(e164ToJid(msg.to), sendContent(text, msg.file));
    result(ref, { key_id: sent?.key?.id || null, chat: normalizeJid(sent?.key?.remoteJid || e164ToJid(msg.to)), sent_at: nowIso() });
  } catch (e) {
    fail(ref, 'send_failed', String(e?.output?.statusCode || e?.name || 'error'));
  }
}

// --- órdenes ----------------------------------------------------------------

async function handle(msg) {
  const ref = refOf(msg);
  if (!ref) return fail(null, 'missing_field', 'id c_ + 32 hex', { field: 'id' });
  if (msg.type !== 'start' && !cfg) return fail(ref, 'not_started');
  switch (msg.type) {
    case 'start': return start(ref, msg);
    case 'status': return result(ref, { ...state });
    case 'ping': return result(ref, { state: state.state });
    case 'link': return startLink(ref, msg);
    case 'link.cancel':
      if (link) endLink('canceled');
      return result(ref);
    case 'allow':
      if (!Array.isArray(msg.allowed)) return fail(ref, 'missing_field', null, { field: 'allowed' });
      allowed = new Set(msg.allowed.filter((n) => E164_RE.test(n)));
      return result(ref, { count: allowed.size });
    case 'send': return send(ref, msg);
    case 'read':
      if (!cfg.read_receipts) return result(ref);
      if (state.state !== 'connected') return fail(ref, 'not_connected');
      await sock.readMessages((msg.key_ids || []).map((id) => ({ remoteJid: msg.chat, id, fromMe: false })));
      return result(ref);
    case 'logout': return logout(ref);
    case 'shutdown': return shutdown(ref);
    default: return fail(ref, 'unknown_type', `type '${String(msg.type).slice(0, 40)}' no existe`);
  }
}

async function start(ref, msg) {
  if (cfg) return result(ref, { protocol: PROTOCOL, bridge_version: BRIDGE_VERSION, baileys_version: baileysVersion() });
  if (msg.protocol !== PROTOCOL) {
    fail(ref, 'unsupported_protocol', `protocolo ${PROTOCOL}`);
    process.exit(3);
  }
  for (const f of ['auth_dir', 'media_dir']) {
    if (typeof msg[f] !== 'string' || !path.isAbsolute(msg[f])) return fail(ref, 'missing_field', null, { field: f });
  }
  if (!checkAuthDir(msg.auth_dir)) {
    log('auth_dir con permisos abiertos: se esperan 0700 y archivos 0600');
    process.exit(4);
  }
  try { fs.mkdirSync(msg.media_dir, { mode: 0o700 }); } catch (e) { if (e.code !== 'EEXIST') throw e; }
  if (!realDir(msg.media_dir)) {
    log('media_dir es un enlace simbólico o no es una carpeta');
    process.exit(4);
  }
  try {
    B = await import('baileys');
  } catch (e) {
    log(`no se pudo cargar baileys (${e?.code || e?.name}): corre npm ci en scripts/whatsapp_bridge`);
    process.exit(2);
  }
  cfg = { auth_dir: msg.auth_dir, media_dir: msg.media_dir, read_receipts: msg.read_receipts === true,
    max_media_mb: msg.max_media_mb };
  allowed = new Set((Array.isArray(msg.allowed) ? msg.allowed : []).filter((n) => E164_RE.test(n)));
  result(ref, { protocol: PROTOCOL, bridge_version: BRIDGE_VERSION, baileys_version: baileysVersion() });
  if (hasCreds()) await connect();
  else out({ type: 'status', ...state });
}

function baileysVersion() {
  try {
    return JSON.parse(fs.readFileSync(new URL('./node_modules/baileys/package.json', import.meta.url), 'utf8')).version;
  } catch {
    return null;
  }
}

async function logout(ref) {
  if (!sock || !hasCreds()) return fail(ref, 'not_connected');
  closing = true;
  let remote = true;
  try {
    await Promise.race([sock.logout(), new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 10000))]);
  } catch {
    remote = false;
  }
  if (sock) sock.ev.removeAllListeners();
  sock = null;
  wipeAuth();
  closing = false;
  setStatus('unlinked');
  result(ref, { remote });
}

function shutdown(ref) {
  closing = true;
  clearTimeout(reconnectTimer);
  if (link) clearTimeout(link.timer);
  if (sock) {
    sock.ev.removeAllListeners();
    try { sock.end(undefined); } catch { /* nada */ }
  }
  if (ref) result(ref);
  setTimeout(() => process.exit(0), 50);
}

// --- stdin ------------------------------------------------------------------

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
let chain = Promise.resolve();
rl.on('line', (line) => {
  if (!line.trim()) return;
  const parsed = parseLine(line);
  if (parsed.error) {
    out({ type: 'error', ref: parsed.error.ref ?? null, code: parsed.error.code,
      ...(parsed.error.field ? { field: parsed.error.field } : {}), detail: parsed.error.detail });
    return;
  }
  // En orden, una a la vez; una orden que falla no tumba el puente.
  chain = chain.then(() => handle(parsed.msg)).catch((e) => {
    log(`orden ${parsed.msg.type}: ${e?.name || 'error'}`);
    const ref = refOf(parsed.msg);
    if (ref) fail(ref, 'send_failed', 'error interno');
  });
});
rl.on('close', () => shutdown(null));
process.on('SIGTERM', () => shutdown(null));
process.on('uncaughtException', (e) => log(`excepción: ${e?.name}: ${String(e?.message).slice(0, 200)}`));
process.on('unhandledRejection', (e) => log(`promesa: ${e?.name || 'error'}`));
