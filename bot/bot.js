// SOSER San Pablo — bot de WhatsApp
// Lee el grupo de supervisoras, detecta establecimiento y falla, y empuja
// bot-datos.json al repositorio. La página lo lee en la siguiente carga.
//
// Uso:  npm install  &&  npm start
// La primera vez muestra un QR: escanéalo desde WhatsApp → Dispositivos vinculados.

import { makeWASocket, useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys';
import qrcode from 'qrcode-terminal';
import pino from 'pino';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const CFG = JSON.parse(fs.readFileSync(path.join(AQUI, 'config.json'), 'utf8'));
const DATOS = path.join(AQUI, '..', 'datos.js');
const SALIDA = path.join(AQUI, 'estado.json');

// ---------- diccionario de establecimientos, sacado de datos.js ----------
function cargarAlias() {
  const txt = fs.readFileSync(DATOS, 'utf8');
  const json = JSON.parse(txt.slice(txt.indexOf('{'), txt.lastIndexOf('}') + 1));
  const E = {};
  json.ESTAB.forEach(e => (E[e.rbd] = e));
  return { ALIAS: json.ALIAS || {}, E };
}
const { ALIAS, E } = cargarAlias();
const CLAVES = Object.keys(ALIAS).sort((a, b) => b.length - a.length);

const norm = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

const PALABRAS = {
  GAS:    ['fuga de gas', 'olor a gas', 'huele a gas', 'olor a la gas', 'gas'],
  FRIO:   ['refrigerador', 'visicooler', 'congelador', 'frigobar', 'camara', 'no enfria', 'temperatura', 'cadena de frio'],
  AGUA:   ['calefont', 'califont', 'agua caliente', 'llave', 'griferia', 'sifon', 'filtracion', 'gotera', 'inundad', 'presion'],
  ELEC:   ['foco', 'luminaria', 'enchufe', 'corte de luz', 'electric', 'interruptor', 'tablero', 'sin luz', 'corriente'],
  EQUIPO: ['horno', 'anafe', 'cocinilla', 'campana', 'extractor', 'bano maria', 'balanza', 'salad bar', 'meson'],
};
function criticidad(t) {
  const n = norm(t);
  for (const k of ['GAS', 'FRIO', 'AGUA', 'ELEC', 'EQUIPO'])
    if (PALABRAS[k].some(w => n.includes(w))) return k;
  return 'OTRO';
}

function analizar(texto, autor, fechaISO) {
  const t = norm(texto);
  if (!t || t.includes('multimedia omitido')) return [];
  const hits = new Set();
  (texto.match(/\b(\d{4,6})\b/g) || []).forEach(x => { if (E[+x]) hits.add(+x); });
  CLAVES.forEach(k => { if (k.length > 3 && t.includes(k)) hits.add(ALIAS[k]); });
  return [...hits].filter(r => E[r]).map(rbd => ({
    fecha: fechaISO, autor, rbd, texto: texto.slice(0, 400),
    crit: criticidad(texto), estab: E[rbd].nombre, sup: E[rbd].sup,
  }));
}

// ---------- estado local ----------
function leerEstado() {
  try { return JSON.parse(fs.readFileSync(SALIDA, 'utf8')); }
  catch { return { generado: null, hallazgos: [] }; }
}
function guardarEstado(st) {
  fs.writeFileSync(SALIDA, JSON.stringify(st, null, 1));
}

// ---------- empujar a GitHub ----------
async function empujar(st) {
  const url = `https://api.github.com/repos/${CFG.repo}/contents/${CFG.archivo}`;
  const cab = {
    Authorization: `Bearer ${CFG.token}`,
    Accept: 'application/vnd.github+json',
    'Content-Type': 'application/json',
  };
  let sha;
  try {
    const r = await fetch(`${url}?ref=${CFG.rama}`, { headers: cab });
    if (r.ok) sha = (await r.json()).sha;
  } catch { /* el archivo todavía no existe */ }

  const cuerpo = {
    message: `bot: ${st.hallazgos.length} hallazgo(s) al ${st.generado}`,
    content: Buffer.from(JSON.stringify(st, null, 1), 'utf8').toString('base64'),
    branch: CFG.rama,
    ...(sha ? { sha } : {}),
  };
  const r = await fetch(url, { method: 'PUT', headers: cab, body: JSON.stringify(cuerpo) });
  if (!r.ok) throw new Error(`GitHub respondió ${r.status}: ${(await r.text()).slice(0, 200)}`);
  console.log(`  → subido a ${CFG.repo}/${CFG.archivo}`);
}

// ---------- WhatsApp ----------
async function arrancar() {
  const { state, saveCreds } = await useMultiFileAuthState(path.join(AQUI, 'sesion'));
  const sock = makeWASocket({ auth: state, logger: pino({ level: 'silent' }) });

  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log('\nEscanea este QR desde WhatsApp → Dispositivos vinculados:\n');
      qrcode.generate(qr, { small: true });
    }
    if (connection === 'open') console.log('\nConectado. Escuchando el grupo...\n');
    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.log('Sesión cerrada desde el teléfono. Borra la carpeta sesion/ y vuelve a escanear.');
        process.exit(1);
      }
      console.log('Se cortó la conexión, reconectando...');
      setTimeout(arrancar, 4000);
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const m of messages) {
      const jid = m.key.remoteJid || '';
      if (!jid.endsWith('@g.us')) continue;                 // solo grupos

      let nombreGrupo = '';
      try { nombreGrupo = (await sock.groupMetadata(jid)).subject; } catch { }
      if (CFG.grupo && !norm(nombreGrupo).includes(norm(CFG.grupo))) continue;

      const autor = m.pushName || 'desconocido';
      if ((CFG.ignorar || []).some(x => norm(autor).includes(norm(x)))) continue;

      const texto = m.message?.conversation
        || m.message?.extendedTextMessage?.text
        || m.message?.imageMessage?.caption
        || '';
      if (!texto.trim()) continue;

      const fecha = new Date((m.messageTimestamp || Date.now() / 1000) * 1000)
        .toISOString().slice(0, 10);
      const nuevos = analizar(texto, autor, fecha);
      if (!nuevos.length) continue;

      const st = leerEstado();
      let agregados = 0;
      nuevos.forEach(h => {
        const dup = st.hallazgos.some(z => z.rbd === h.rbd && z.texto === h.texto);
        if (!dup) { st.hallazgos.push(h); agregados++; }
      });
      if (!agregados) continue;

      // conservar solo lo reciente
      const corte = new Date(Date.now() - (CFG.diasMemoria || 30) * 86400000)
        .toISOString().slice(0, 10);
      st.hallazgos = st.hallazgos.filter(h => h.fecha >= corte);
      st.generado = new Date().toISOString().slice(0, 16).replace('T', ' ');
      guardarEstado(st);

      nuevos.forEach(h => console.log(`[${h.fecha}] ${autor}: ${h.rbd} ${h.estab} · ${h.crit}`));
      try { await empujar(st); }
      catch (e) { console.log('  ! no pude subir:', e.message); }
    }
  });
}

arrancar().catch(e => { console.error(e); process.exit(1); });
