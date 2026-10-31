// Lo que el puente hace sin Baileys (WHATSAPP_BRIDGE.md): leer líneas, reconocer
// chats directos, pasar JID a E.164 y clasificar un mensaje. Va aparte para que
// las pruebas (test/lib.test.js) no necesiten `npm ci` ni red.

export const PROTOCOL = 1;
export const MAX_LINE_BYTES = 1024 * 1024;
export const ID_RE = /^c_[0-9a-f]{32}$/;
export const E164_RE = /^\+[1-9][0-9]{6,14}$/;
export const MAX_TEXT = 4000;
export const MAX_FILE_BYTES = 64 * 1024 * 1024;
export const CODE_TTL_MS = 3 * 60 * 1000;

// Una línea de stdin -> {msg} o {error: {code, detail}}. Nunca lanza.
export function parseLine(line) {
  if (Buffer.byteLength(line, 'utf8') > MAX_LINE_BYTES) {
    return { error: { code: 'bad_json', detail: 'línea de más de 1 MiB' } };
  }
  let msg;
  try {
    msg = JSON.parse(line);
  } catch {
    return { error: { code: 'bad_json', detail: 'no es JSON' } };
  }
  if (msg === null || typeof msg !== 'object' || Array.isArray(msg)) {
    return { error: { code: 'bad_json', detail: 'no es un objeto' } };
  }
  if (typeof msg.type !== 'string') {
    return { error: { code: 'missing_field', field: 'type', ref: refOf(msg) } };
  }
  return { msg };
}

export function refOf(msg) {
  return msg && typeof msg.id === 'string' && ID_RE.test(msg.id) ? msg.id : null;
}

// Sólo chats directos (FR-17): nada de grupos, estados, difusión ni canales.
export function isDirectChat(jid) {
  if (typeof jid !== 'string' || !jid.includes('@')) return false;
  if (jid === 'status@broadcast') return false;
  const server = jid.slice(jid.lastIndexOf('@') + 1);
  return server === 's.whatsapp.net' || server === 'lid';
}

export function isLidJid(jid) {
  return typeof jid === 'string' && jid.endsWith('@lid');
}

export function isPnJid(jid) {
  return typeof jid === 'string' && jid.endsWith('@s.whatsapp.net');
}

// "15550001111:12@s.whatsapp.net" -> "15550001111@s.whatsapp.net"
export function normalizeJid(jid) {
  if (typeof jid !== 'string' || !jid.includes('@')) return null;
  const at = jid.lastIndexOf('@');
  const user = jid.slice(0, at).split(':')[0];
  return `${user}@${jid.slice(at + 1)}`;
}

export function pnJidToE164(jid) {
  if (!isPnJid(jid)) return null;
  const user = normalizeJid(jid).split('@')[0];
  const e164 = `+${user}`;
  return E164_RE.test(e164) ? e164 : null;
}

export function e164ToJid(e164) {
  return E164_RE.test(e164) ? `${e164.slice(1)}@s.whatsapp.net` : null;
}

// Un nombre de archivo del remitente, sin rutas ni caracteres de control, a 120.
export function cleanFilename(name) {
  if (typeof name !== 'string') return null;
  // eslint-disable-next-line no-control-regex
  const clean = name.replace(/[\/\\\u0000-\u001f\u007f]/g, '_').trim().slice(0, 120);
  return clean && clean !== '.' && clean !== '..' ? clean : null;
}

const EXT = {
  'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif',
  'video/mp4': 'mp4', 'video/3gpp': '3gp', 'audio/ogg': 'ogg', 'audio/mpeg': 'mp3',
  'audio/mp4': 'm4a', 'audio/aac': 'aac', 'application/pdf': 'pdf',
  'text/plain': 'txt', 'application/zip': 'zip',
};

export function extForMime(mime) {
  const base = typeof mime === 'string' ? mime.split(';')[0].trim().toLowerCase() : '';
  return EXT[base] || 'bin';
}

// Quita las envolturas (efímero, ver una vez, documento con pie, editado).
export function unwrap(message) {
  let m = message;
  for (let i = 0; i < 5 && m; i++) {
    const inner = m.ephemeralMessage?.message || m.viewOnceMessage?.message
      || m.viewOnceMessageV2?.message || m.viewOnceMessageV2Extension?.message
      || m.documentWithCaptionMessage?.message;
    if (!inner) break;
    m = inner;
  }
  return m;
}

const NUM = (v) => (v == null ? null : Number(v));

// El contenido de un mensaje -> {kind, text, media} sin descargar nada, o null si no
// es algo que el dueño escribió (reacciones, ediciones, mensajes de protocolo).
export function classify(message) {
  const m = unwrap(message);
  if (!m) return null;
  if (typeof m.conversation === 'string') return { kind: 'text', text: m.conversation, media: null };
  if (m.extendedTextMessage) return { kind: 'text', text: m.extendedTextMessage.text ?? '', media: null };
  const pick = (key, kind, extra) => {
    const c = m[key];
    return {
      kind,
      text: c.caption || null,
      media: { key, mime: c.mimetype || null, bytes: NUM(c.fileLength), ...extra(c) },
    };
  };
  if (m.imageMessage) return pick('imageMessage', 'image', () => ({ filename: null, seconds: null, voice_note: false }));
  if (m.videoMessage) return pick('videoMessage', 'video', (c) => ({ filename: null, seconds: NUM(c.seconds), voice_note: false }));
  if (m.audioMessage) {
    const r = pick('audioMessage', 'audio', (c) => ({ filename: null, seconds: NUM(c.seconds), voice_note: Boolean(c.ptt) }));
    r.text = null;
    return r;
  }
  if (m.documentMessage) return pick('documentMessage', 'document', (c) => ({ filename: cleanFilename(c.fileName), seconds: null, voice_note: false }));
  if (m.stickerMessage) return { kind: 'sticker', text: null, media: null };
  if (m.locationMessage || m.liveLocationMessage) return { kind: 'location', text: null, media: null };
  if (m.contactMessage || m.contactsArrayMessage) return { kind: 'contact', text: null, media: null };
  if (m.reactionMessage || m.protocolMessage || m.senderKeyDistributionMessage
      || m.pollUpdateMessage || m.editedMessage || m.keepInChatMessage) return null;
  return { kind: 'other', text: null, media: null };
}

// Lo que Baileys necesita de un logger (pino). Sólo pasan los errores, y sólo su
// texto: nunca el objeto, que puede traer un mensaje, un JID o una llave (§8).
export function makeLogger(write) {
  const noop = () => {};
  const logger = {
    level: 'error',
    child: () => logger,
    trace: noop, debug: noop, info: noop, warn: noop,
    error: (obj, msg) => write(`baileys: ${String(typeof obj === 'string' ? obj : msg || 'error').slice(0, 300)}`),
    fatal: (obj, msg) => write(`baileys fatal: ${String(typeof obj === 'string' ? obj : msg || 'fatal').slice(0, 300)}`),
  };
  return logger;
}

// libsignal, debajo de Baileys, escribe con console.* y a veces le pasa la sesión
// cifrada entera, con sus llaves: console.info("Closing session:", session),
// console.warn("Session already closed", session). console.log e info salen por
// stdout, que es el canal del protocolo; warn y error, por stderr, que termina en
// state/whatsapp.log. Así que log, info y debug no escriben nada, y de warn y error
// sólo queda el primer argumento si es texto, recortado. Un objeto nunca sale (FR-10).
export function quietConsole(target, write) {
  const noop = () => {};
  for (const k of ['log', 'info', 'debug', 'trace', 'dir', 'dirxml', 'table']) target[k] = noop;
  const keep = (first, ...rest) => {
    if (typeof first !== 'string') return;
    write(`consola: ${first.slice(0, 200)}${rest.length ? ' (sin los datos)' : ''}`);
  };
  target.warn = keep;
  target.error = keep;
}

// Quién escribió o llamó, como número. WhatsApp puede mandar un LID (un id interno)
// en lugar del número: un mensaje trae el número en remoteJidAlt y una llamada en
// callerPn. Si no viene, se busca en el mapa LID -> número de Baileys. Sin número,
// e164 queda null y el servicio lo trata como «número sin resolver».
export async function resolveJid(s, rawJid, rawAlt) {
  const jid = normalizeJid(rawJid || '');
  const alt = normalizeJid(rawAlt || '');
  if (isPnJid(jid)) return { e164: pnJidToE164(jid), jid, lid: isLidJid(alt) ? alt : null };
  if (isLidJid(jid)) {
    let pn = isPnJid(alt) ? alt : null;
    if (!pn) {
      try { pn = normalizeJid(await s?.signalRepository?.lidMapping?.getPNForLID(jid) || ''); } catch { pn = null; }
      if (!isPnJid(pn)) pn = null;
    }
    return { e164: pn ? pnJidToE164(pn) : null, jid: pn || jid, lid: jid };
  }
  return { e164: null, jid, lid: null };
}

// ¿Estas credenciales son de una vinculación terminada? (#604)
// Baileys guarda `account` (la identidad firmada del dispositivo) sólo al recibir
// pair-success, igual con QR que con código. `me.id` solo no basta: pedir un código
// ya lo escribe antes de que el teléfono acepte. `registered` tampoco sirve: con QR
// se queda en false para siempre, porque sólo lo pone el flujo de código.
export function credsLinked(creds) {
  return Boolean(creds?.me?.id) && Boolean(creds?.account);
}

// Estado de un envío (WAMessageStatus) -> receipt.status
export function receiptStatus(ack) {
  if (ack === 2) return 'server';
  if (ack === 3) return 'delivered';
  if (ack === 4 || ack === 5) return 'read';
  return null;
}

// Una llamada que cambia de estado -> 'missed', 'answered' o null mientras suena.
export function callOutcome(status, wasAccepted) {
  if (status === 'accept') return 'answered';
  if (status === 'timeout' || status === 'reject') return 'missed';
  if (status === 'terminate') return wasAccepted ? null : 'missed';
  return null;
}

export function sendContent(text, file) {
  if (!file) return { text };
  const mime = file.mime || 'application/octet-stream';
  const src = { url: file.path };
  const caption = text || undefined;
  if (mime.startsWith('image/')) return { image: src, caption, mimetype: mime };
  if (mime.startsWith('video/')) return { video: src, caption, mimetype: mime };
  if (mime.startsWith('audio/')) return { audio: src, mimetype: mime };
  return { document: src, caption, mimetype: mime, fileName: cleanFilename(file.filename) || 'archivo' };
}
