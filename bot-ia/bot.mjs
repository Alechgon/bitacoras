// bot.mjs — el "cartero". Se conecta a WhatsApp como dispositivo vinculado,
// escucha SOLO el grupo configurado y tu chat privado, y conversa con el
// servidor Python (servidor.py) que tiene toda la lógica.
//
// Vincular (una vez):  node bot.mjs --codigo 569XXXXXXXX   (número del BOT)
// Correr:              bash iniciar.sh   (levanta servidor + bot y los revive)

import makeWASocket, {
  Browsers, DisconnectReason, useMultiFileAuthState, fetchLatestBaileysVersion, downloadMediaMessage
} from '@whiskeysockets/baileys'
import pino from 'pino'
import qrcode from 'qrcode-terminal'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const DIR = path.dirname(fileURLToPath(import.meta.url))
const API = 'http://127.0.0.1:8765'
const log = (...a) => console.log(new Date().toLocaleString('es-CL'), ...a)
const esperar = ms => new Promise(r => setTimeout(r, ms))
const azar = (a, b) => Math.floor(a + Math.random() * (b - a + 1))
const normal = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
const soloDigitos = s => String(s || '').replace(/\D/g, '')

const argCodigo = process.argv.indexOf('--codigo')
const TELEFONO = argCodigo > -1 ? soloDigitos(process.argv[argCodigo + 1]) : ''

// ------------------------------------------------------------ configuración (general + perfil activo)
function mezclar (base, encima) {
  const out = { ...base }
  for (const [k, v] of Object.entries(encima || {})) {
    out[k] = (v && typeof v === 'object' && !Array.isArray(v) && out[k] && typeof out[k] === 'object' && !Array.isArray(out[k]))
      ? mezclar(out[k], v) : v
  }
  return out
}
function cfg () {
  const raw = JSON.parse(fs.readFileSync(path.join(DIR, 'config.json'), 'utf8'))
  return mezclar(raw, raw.perfiles?.[raw.perfil_activo])
}

// ------------------------------------------------------------ estado que sobrevive reinicios
const RUTA_ESTADO = path.join(DIR, 'estado.json')
let estado = { casos: {}, admin_chat: null, grupo_jid: null }
try { estado = { ...estado, ...JSON.parse(fs.readFileSync(RUTA_ESTADO, 'utf8')) } } catch {}
function guardarEstado () {
  try {
    fs.writeFileSync(RUTA_ESTADO + '.tmp', JSON.stringify(estado))
    fs.renameSync(RUTA_ESTADO + '.tmp', RUTA_ESTADO)
  } catch (e) { log('⚠️ no pude guardar estado:', e.message) }
}
// mensaje mínimo para poder citar el original aunque el bot se haya reiniciado
const citable = (m, texto) => m ? { key: m.key, message: { conversation: texto || ' ' } } : null

let sock
let conectado = false
const procesados = new Set()

// ------------------------------------------------------------ cola de envío (una cosa a la vez, con pausas)
const cola = []
let enviando = false
function encolar (jid, contenido, opciones = {}, delay = null) {
  if (!jid) { log('⚠️ mensaje sin destino, descartado'); return }
  cola.push({ jid, contenido, opciones, delay })
  if (!enviando) vaciarCola()
}
async function vaciarCola () {
  enviando = true
  while (cola.length) {
    const { jid, contenido, opciones, delay } = cola.shift()
    const [min, max] = cfg().delay_respuesta_seg || [35, 95]
    await esperar(delay ?? azar(min, max) * 1000)
    for (let intento = 1; intento <= 3; intento++) {
      try {
        if (!conectado) await esperar(5000)
        if (contenido.text) {
          await sock.sendPresenceUpdate('composing', jid)
          await esperar(Math.min(8000, 1500 + contenido.text.length * 40))
          await sock.sendPresenceUpdate('paused', jid)
        }
        await sock.sendMessage(jid, contenido, opciones)
        log('📤 enviado a', jid)
        break
      } catch (e) {
        log(`❌ error enviando (intento ${intento}/3):`, e.message)
        await esperar(4000 * intento)
      }
    }
  }
  enviando = false
}

// ------------------------------------------------------------ hablar con el servidor Python
async function api (ruta, datos, timeoutMs = 120000) {
  for (let intento = 1; intento <= 3; intento++) {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      const r = await fetch(API + ruta, datos
        ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(datos), signal: ctrl.signal }
        : { signal: ctrl.signal })
      return await r.json()
    } catch (e) {
      if (intento === 3) throw e
      await esperar(3000)            // servidor reiniciándose: espera y reintenta
    } finally { clearTimeout(t) }
  }
}

// ------------------------------------------------------------ lectura de mensajes
function interior (m) {
  const msg = m.message || {}
  return msg.ephemeralMessage?.message || msg.viewOnceMessage?.message ||
         msg.documentWithCaptionMessage?.message || msg
}
function textoDe (m) {
  const i = interior(m)
  return i.conversation || i.extendedTextMessage?.text || i.imageMessage?.caption ||
         i.videoMessage?.caption || i.documentMessage?.caption || ''
}
const docDe = m => interior(m).documentMessage || null
const ctxDe = m => {
  const i = interior(m)
  return i.extendedTextMessage?.contextInfo || i.documentMessage?.contextInfo || null
}

function esAdmin (m) {
  const admins = (cfg().admins || []).map(soloDigitos).filter(Boolean)
  const k = m.key
  const ids = [k.participant, k.participantAlt, k.participantPn, k.remoteJid, k.remoteJidAlt]
    .filter(Boolean).map(j => j.split('@')[0].split(':')[0])
  return ids.some(id => admins.includes(id)) || (estado.admin_chat && k.remoteJid === estado.admin_chat)
}

// ------------------------------------------------------------ grupo y destinos
const nombresGrupo = {}
async function esGrupoSupervisoras (jid) {
  if (!jid?.endsWith('@g.us')) return false
  const c = cfg()
  if (c.grupo_id) return jid === c.grupo_id
  if (!c.grupo_nombre) return false
  if (!(jid in nombresGrupo)) {
    try { nombresGrupo[jid] = (await sock.groupMetadata(jid)).subject } catch { nombresGrupo[jid] = '' }
  }
  const ok = normal(nombresGrupo[jid]).includes(normal(c.grupo_nombre))
  if (ok && estado.grupo_jid !== jid) { estado.grupo_jid = jid; guardarEstado() }
  return ok
}
function grupoDestino () {
  const c = cfg()
  if (c.grupo_id) return c.grupo_id
  // el grupo recordado solo vale si sigue calzando con el nombre del perfil activo
  const j = estado.grupo_jid
  return j && normal(nombresGrupo[j] || '').includes(normal(c.grupo_nombre)) ? j : null
}
function adminJid () {
  if (estado.admin_chat) return estado.admin_chat            // el chat real donde me hablas
  const c = cfg()
  if (c.chat_reportes) return c.chat_reportes.includes('@') ? c.chat_reportes : soloDigitos(c.chat_reportes) + '@s.whatsapp.net'
  const n = soloDigitos((c.admins || [])[0])
  return n ? n + '@s.whatsapp.net' : null
}

// ------------------------------------------------------------ casos (borradores)
const DL = path.join(DIR, 'descargas')
fs.mkdirSync(DL, { recursive: true })

async function descargar (m, nombreSugerido) {
  const buf = await downloadMediaMessage(m, 'buffer', {})
  const safe = (nombreSugerido || 'archivo.pdf').replace(/[^\w.\- ]+/g, '_').slice(-80)
  const ruta = path.join(DL, `${Date.now()}_${safe}`)
  fs.writeFileSync(ruta, buf)
  return ruta
}

function borradorCitado (m) {
  const q = ctxDe(m)?.quotedMessage
  const t = q?.conversation || q?.extendedTextMessage?.text || ''
  const mm = t.match(/Caso #(\d+)/)
  return mm ? Number(mm[1]) : null
}

function registrarCasos (ids, mOriginal, texto) {
  for (const bid of ids || []) estado.casos[bid] = citable(mOriginal, texto)
  guardarEstado()
}

async function enviarAlGrupo (bid, textos) {
  const g = grupoDestino()
  if (!g) { log('⚠️ sin grupo destino; revisa el perfil'); encolar(adminJid(), { text: '⚠️ No encuentro el grupo del perfil activo. Revisa con !diagnostico.' }, {}, 1500); return }
  const orig = estado.casos[bid] || null
  const op = orig ? { quoted: orig } : {}
  for (const t of textos) encolar(g, { text: t }, op)
  try {
    const { archivos } = await api('/adjuntos', { borrador_id: bid })
    for (const a of (archivos || [])) {
      if (fs.existsSync(a)) encolar(g, { document: fs.readFileSync(a), fileName: path.basename(a).replace(/^\d+_/, ''), mimetype: 'application/pdf' }, op, 2500)
    }
  } catch {}
  delete estado.casos[bid]
  guardarEstado()
}

function infoWA () {
  const g = grupoDestino()
  return {
    conectado, yo: sock?.user?.id?.split(':')[0] || null,
    grupo: g, grupo_nombre: g ? nombresGrupo[g] : null,
    admin: adminJid(), admin_ok: Boolean(estado.admin_verificado)
  }
}

// ------------------------------------------------------------ el corazón: qué hacer con cada mensaje
async function manejar (m) {
  if (!m.message || m.key.fromMe) return
  if (procesados.has(m.key.id)) return
  procesados.add(m.key.id)
  if (procesados.size > 5000) procesados.clear()

  const c = cfg()
  const ts = Number(m.messageTimestamp || 0) * 1000
  if (ts && Date.now() - ts > (c.procesar_atrasados_min ?? 720) * 60000) return   // demasiado viejo

  const jid = m.key.remoteJid
  const texto = textoDe(m).trim()
  const doc = docDe(m)
  const enGrupo = await esGrupoSupervisoras(jid)
  const admin = esAdmin(m)
  const privadoAdmin = admin && !jid.endsWith('@g.us')

  // de cualquier otro chat de la cuenta (clientes, otros grupos) no se hace NADA
  if (!enGrupo && !privadoAdmin) {
    if (admin && texto.toLowerCase() === '!id') encolar(jid, { text: `🆔 ${jid}` }, { quoted: m }, 1500)
    return
  }
  if (privadoAdmin && estado.admin_chat !== jid) { estado.admin_chat = jid; guardarEstado() }

  // ---------------- comandos
  if (texto.startsWith('!')) {
    if (texto.toLowerCase() === '!id') { encolar(jid, { text: `🆔 ${jid}` }, { quoted: m }, 1500); return }
    try {
      const r = await api('/comando', { texto, autor: m.pushName || '', es_admin: admin, privado: privadoAdmin, wa: infoWA() })
      const [dmin, dmax] = c.delay_comando_seg || [3, 8]
      if (r.texto) encolar(jid, { text: r.texto }, { quoted: m }, azar(dmin, dmax) * 1000)
      if (r.archivo) encolar(jid, { document: fs.readFileSync(r.archivo), fileName: path.basename(r.archivo), mimetype: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }, {}, 3000)
      if (r.borradores?.length) registrarCasos(r.borradores, null, '')        // !simular
      for (const t of (r.admin || [])) encolar(adminJid(), { text: t }, {}, 2000)
    } catch (e) { log('❌ comando:', e.message) }
    return
  }

  // ---------------- PDF
  if (doc) {
    const esPDF = /pdf/i.test(doc.mimetype || '') || /\.pdf$/i.test(doc.fileName || '')
    const conFormato = /^(.*?),\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})/.exec(texto)
    const bidCit = borradorCitado(m)
    if (enGrupo && !(esPDF && conFormato)) return           // en el grupo solo bitácoras con "Nombre, fecha"
    try {
      const ruta = await descargar(m, doc.fileName || 'archivo.pdf')
      if (privadoAdmin && (bidCit || (!conFormato && !/bit|folio/i.test(doc.fileName || '')))) {
        const r = await api('/adjuntar', { ruta, autor: m.pushName || '', borrador_id: bidCit })
        for (const t of (r.admin || [])) encolar(jid, { text: t }, {}, 1500)
      } else {
        const r = await api('/bitacora', { ruta, nombre: conFormato ? conFormato[1].trim() : '', fecha: conFormato ? conFormato[2] : '' })
        const malo = (r.texto || '').startsWith('❌')
        if (enGrupo && malo) encolar(adminJid(), { text: `${r.texto}\n(lo mandó ${m.pushName || '?'} al grupo)` }, {}, 1500)
        else encolar(jid, { text: r.texto || '📥 Recibido.' }, { quoted: m }, 1500)
      }
    } catch (e) {
      log('❌ pdf:', e.message)
      encolar(privadoAdmin ? jid : adminJid(), { text: '❌ No pude procesar el archivo: ' + e.message }, {}, 1500)
    }
    return
  }

  if (!texto) return

  // ---------------- tu privado: aprobar, sumar o subir un caso
  if (privadoAdmin) {
    const low = normal(texto)
    const bidCit = borradorCitado(m)
    const OK = (c.palabras_ok || ['ok']).map(normal)
    const NO = (c.palabras_no || ['no']).map(normal)
    const esDecision = OK.includes(low) || NO.includes(low) || bidCit || texto.startsWith('+')
    try {
      if (esDecision) {
        const decision = texto.startsWith('+') ? texto.slice(1).trim() : texto
        const r = await api('/aprobar', { decision, autor: m.pushName || 'Manuel', borrador_id: bidCit })
        for (const t of (r.admin || [])) encolar(jid, { text: t }, {}, 1500)
        if (r.enviar_borrador) await enviarAlGrupo(r.enviar_borrador, r.grupo || [])
      } else {
        const r = await api('/entrada', { origen: 'admin', texto, autor: m.pushName || 'Manuel' })
        registrarCasos(r.borradores, null, '')
        for (const t of (r.admin || [])) encolar(jid, { text: t }, {}, 1500)
        if (r.grupo?.length) for (const t of r.grupo) encolar(grupoDestino(), { text: t })   // modo directo
        if (!r.admin?.length && !r.grupo?.length) encolar(jid, { text: '🤷 No detecté establecimiento ni falla. Dime el nombre o RBD y qué pasa. (*!ayuda* para comandos)' }, {}, 1500)
      }
    } catch (e) { log('❌ privado:', e.message); encolar(jid, { text: '❌ El servidor no respondió. Revisa con !diagnostico.' }, {}, 1500) }
    return
  }

  // ---------------- grupo de supervisoras
  log(`📥 ${m.pushName || '?'}: ${texto.slice(0, 80)}`)
  try {
    const r = await api('/entrada', { origen: 'grupo', texto, autor: m.pushName || 'supervisora' })
    if (r.error) { log('❌ servidor:', r.error); return }
    if (r.borradores?.length) {                                  // modo borrador: te llega a ti
      registrarCasos(r.borradores, m, texto)
      for (const t of (r.admin || [])) encolar(adminJid(), { text: t }, {}, azar(2, 6) * 1000)
    }
    if (r.grupo?.length) encolar(jid, { text: r.grupo.join('\n\n') }, { quoted: m })   // modo directo
  } catch (e) {
    log('❌ ¿está corriendo servidor.py?', e.message)
  }
}

// ------------------------------------------------------------ tareas programadas
const hecho = {}
setInterval(async () => {
  if (!conectado || TELEFONO) return
  const c = cfg()
  const ahora = new Date()
  const hhmm = ahora.toTimeString().slice(0, 5)
  const dia = ahora.toDateString()
  const habil = ahora.getDay() >= 1 && ahora.getDay() <= 5
  try {
    // cada minuto: recordatorios, gas automático, respaldo
    if (hecho.tick !== hhmm) {
      hecho.tick = hhmm
      const r = await api('/tick', {})
      for (const t of (r.admin || [])) encolar(adminJid(), { text: t }, {}, 1500)
      for (const e of (r.envios_grupo || [])) await enviarAlGrupo(e.borrador_id, e.textos)
    }
    if (habil && c.agenda_matutina?.activa && grupoDestino() && hhmm === c.agenda_matutina.hora && hecho.agenda !== dia) {
      hecho.agenda = dia
      const r = await api('/agenda_dia')
      encolar(grupoDestino(), { text: r.texto }, {}, azar(5, 40) * 1000)
    }
    if (habil && c.reporte_diario?.activo && adminJid() && hhmm === c.reporte_diario.hora && hecho.reporte !== dia) {
      hecho.reporte = dia
      const r = await api('/reporte')
      encolar(adminJid(), { document: fs.readFileSync(r.archivo), fileName: path.basename(r.archivo), mimetype: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', caption: '📊 Reporte diario de mantención' }, {}, 2000)
    }
  } catch (e) { log('❌ tarea programada:', e.message) }
}, 15000)

// ------------------------------------------------------------ conexión
async function conectar () {
  const { state, saveCreds } = await useMultiFileAuthState(path.join(DIR, 'auth'))
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'warn' }),
    browser: Browsers.ubuntu('Chrome'),
    markOnlineOnConnect: false,
    syncFullHistory: false
  })
  sock.ev.on('creds.update', saveCreds)

  if (TELEFONO && !state.creds.registered) {
    await esperar(3000)
    const crudo = String(await sock.requestPairingCode(TELEFONO)).replace(/[^A-Za-z0-9]/g, '').toUpperCase()
    const codigo = crudo.length === 8 ? `${crudo.slice(0, 4)}-${crudo.slice(4)}` : crudo
    console.log('\n\n==============================')
    console.log('   CÓDIGO:  ' + codigo)
    console.log('==============================')
    console.log(`(son 8 caracteres: ${crudo.split('').join(' ')})`)
    console.log('WhatsApp del BOT > ⋮ > Dispositivos vinculados > Vincular dispositivo')
    console.log('> "Vincular con número de teléfono" y escribe las 8 letras/números.')
    console.log('El código vence en ~1 minuto. Si vence: Ctrl+C y corre de nuevo')
    console.log(`   node bot.mjs --codigo ${TELEFONO}\n`)
  }

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr && !TELEFONO) {
      log('📷 Escanea este QR desde WhatsApp > Dispositivos vinculados:')
      qrcode.generate(qr, { small: true })
    }
    if (connection === 'open') {
      conectado = true
      log('✅ Conectado a WhatsApp como', sock.user?.id)
      try {
        const grupos = await sock.groupFetchAllParticipating()
        log('👥 Grupos donde está el bot:')
        for (const g of Object.values(grupos)) {
          nombresGrupo[g.id] = g.subject
          const marca = await esGrupoSupervisoras(g.id) ? '  ✅ ESTE ES EL GRUPO QUE LEO' : ''
          log(`   ${g.subject}  ->  ${g.id}${marca}`)
        }
        if (!grupoDestino()) log('⚠️  No encontré el grupo del perfil activo: revisa grupo_nombre (o usa !perfil)')
      } catch {}
      try {
        const n = soloDigitos((cfg().admins || [])[0])
        if (n) {
          const [r] = await sock.onWhatsApp(n)
          estado.admin_verificado = Boolean(r?.exists)
          guardarEstado()
          log(r?.exists ? `👤 Admin ${n} verificado en WhatsApp` : `⚠️ El admin ${n} no aparece en WhatsApp`)
        }
      } catch {}
      if (TELEFONO) {
        log('🔗 Vinculación lista. La sesión quedó guardada en auth/.')
        await esperar(4000)
        process.exit(0)
      }
    }
    if (connection === 'close') {
      conectado = false
      const code = lastDisconnect?.error?.output?.statusCode
      if (code === DisconnectReason.loggedOut) {
        log('🚪 Sesión cerrada desde el teléfono. Borra la carpeta auth/ y vuelve a vincular.')
        process.exit(1)
      }
      log('🔄 Reconectando en 5 s... (código', code, ')')
      setTimeout(conectar, 5000)
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const m of messages) manejar(m).catch(e => log('❌', e.message))
  })
}

process.on('unhandledRejection', e => log('⚠️ promesa sin manejar:', e?.message || e))
conectar()
