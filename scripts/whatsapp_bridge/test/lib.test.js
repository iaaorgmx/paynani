// node --test scripts/whatsapp_bridge/test  (sin npm ci: lib.js no carga Baileys)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseLine, isDirectChat, normalizeJid, pnJidToE164, e164ToJid, cleanFilename,
  extForMime, classify, receiptStatus, callOutcome, sendContent, makeLogger, quietConsole,
} from '../lib.js';

test('parseLine: JSON, no JSON, sin type, demasiado largo', () => {
  assert.equal(parseLine('{"type":"ping","id":"c_1"}').msg.type, 'ping');
  assert.equal(parseLine('hola').error.code, 'bad_json');
  assert.equal(parseLine('[1]').error.code, 'bad_json');
  assert.equal(parseLine('{"id":"x"}').error.code, 'missing_field');
  assert.equal(parseLine(`{"type":"x","t":"${'a'.repeat(1024 * 1024)}"}`).error.code, 'bad_json');
});

test('isDirectChat: sólo directos (FR-17)', () => {
  assert.ok(isDirectChat('15550001111@s.whatsapp.net'));
  assert.ok(isDirectChat('123456789@lid'));
  for (const j of ['120363@g.us', 'status@broadcast', '1234@broadcast', '1203@newsletter', '', null]) {
    assert.equal(isDirectChat(j), false, String(j));
  }
});

test('JID y E.164', () => {
  assert.equal(normalizeJid('15550001111:12@s.whatsapp.net'), '15550001111@s.whatsapp.net');
  assert.equal(pnJidToE164('15550001111:3@s.whatsapp.net'), '+15550001111');
  assert.equal(pnJidToE164('123@lid'), null);
  assert.equal(e164ToJid('+15550001111'), '15550001111@s.whatsapp.net');
  assert.equal(e164ToJid('5550001111'), null);
});

test('cleanFilename: sin rutas ni controles', () => {
  assert.equal(cleanFilename('../../.env'), '.._.._.env');
  assert.equal(cleanFilename('a\u0000b\nc.pdf'), 'a_b_c.pdf');
  assert.equal(cleanFilename('..'), null);
  assert.equal(cleanFilename(null), null);
});

test('extForMime', () => {
  assert.equal(extForMime('image/jpeg'), 'jpg');
  assert.equal(extForMime('audio/ogg; codecs=opus'), 'ogg');
  assert.equal(extForMime('application/x-raro'), 'bin');
});

test('classify: texto, envolturas, archivos y lo que se descarta', () => {
  assert.deepEqual(classify({ conversation: 'hola' }), { kind: 'text', text: 'hola', media: null });
  assert.equal(classify({ ephemeralMessage: { message: { extendedTextMessage: { text: 'x' } } } }).text, 'x');
  const voice = classify({ audioMessage: { mimetype: 'audio/ogg', seconds: 12, ptt: true, fileLength: 900 } });
  assert.equal(voice.kind, 'audio');
  assert.equal(voice.media.voice_note, true);
  assert.equal(voice.media.seconds, 12);
  const doc = classify({ documentWithCaptionMessage: { message: { documentMessage: { fileName: '../factura.pdf', caption: 'aquí', mimetype: 'application/pdf' } } } });
  assert.equal(doc.kind, 'document');
  assert.equal(doc.media.filename, '.._factura.pdf');
  assert.equal(doc.text, 'aquí');
  assert.equal(classify({ reactionMessage: { text: '👍' } }), null);
  assert.equal(classify({ protocolMessage: { type: 0 } }), null);
  assert.equal(classify({ stickerMessage: {} }).kind, 'sticker');
  assert.equal(classify({ algoNuevo: {} }).kind, 'other');
});

test('acuses y llamadas', () => {
  assert.equal(receiptStatus(2), 'server');
  assert.equal(receiptStatus(3), 'delivered');
  assert.equal(receiptStatus(4), 'read');
  assert.equal(receiptStatus(1), null);
  assert.equal(callOutcome('offer', false), null);
  assert.equal(callOutcome('timeout', false), 'missed');
  assert.equal(callOutcome('reject', false), 'missed');
  assert.equal(callOutcome('accept', false), 'answered');
  assert.equal(callOutcome('terminate', true), null);
  assert.equal(callOutcome('terminate', false), 'missed');
});

test('sendContent', () => {
  assert.deepEqual(sendContent('hola', null), { text: 'hola' });
  assert.equal(sendContent('', { path: '/x.jpg', mime: 'image/jpeg' }).image.url, '/x.jpg');
  assert.equal(sendContent('pie', { path: '/x.pdf', mime: 'application/pdf', filename: 'a/b.pdf' }).fileName, 'a_b.pdf');
});

test('makeLogger: sólo errores y sólo el texto, nunca el objeto', () => {
  const lines = [];
  const l = makeLogger((x) => lines.push(x));
  l.info({ msg: 'secreto' }, 'info');
  l.child({}).warn('aviso');
  l.error({ message: { conversation: 'texto privado' } }, 'falló algo');
  assert.deepEqual(lines, ['baileys: falló algo']);
});

test('quietConsole: las llaves de libsignal no salen ni por stdout ni al log', () => {
  const lines = [];
  const fake = { log() { throw new Error('stdout'); }, info() { throw new Error('stdout'); },
    warn() { throw new Error('stderr'); }, error() { throw new Error('stderr'); } };
  quietConsole(fake, (x) => lines.push(x));
  const session = { currentRatchet: { rootKey: Buffer.from('raiz-secreta'), ephemeralKeyPair: { privKey: 'llave-privada' } } };
  fake.info('Closing session:', session);
  fake.log('Opening session:', session);
  fake.debug(session);
  fake.dir(session);
  fake.warn('Session already closed', session);
  fake.error(session);
  fake.warn('Decrypted message with closed session.');
  fake.warn('x'.repeat(500));
  assert.deepEqual(lines.slice(0, 2), ['consola: Session already closed (sin los datos)',
    'consola: Decrypted message with closed session.']);
  assert.equal(lines[2].length, 'consola: '.length + 200);
  assert.equal(lines.length, 3);
  assert.ok(!lines.join('\n').match(/secreta|privada|privKey|rootKey/));
});
