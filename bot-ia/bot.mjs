// bot.mjs — el "cartero": se conecta a WhatsApp (como WhatsApp Web), lee el
// grupo de supervisoras, le pasa cada mensaje al servidor Python y responde
// con un delay aleatorio para no parecer robot.
//
// Primera vez (el bot corre en el MISMO celu que tiene el WhatsApp del bot):
//   node bot.mjs --codigo 56912345678      -> te da un código de 8 letras
//   En WhatsApp: Dispositivos vinculados > Vincular > "con número de teléfono"
// Si lo corres en otro equipo, basta con: node bot.mjs   (muestra un QR)

import makeWASocket, { Browsers, DisconnectReason, useMultiFileAuthState, fetchLatestBaileysVersion } from '@whiskeysockets/baileys'
import pino from 'pino'
import qrcode from 'qrcode-terminal'
import fs from 'fs'
import path from 'path'

import { fileURLToPath } from 'url'
const DIR = path.dirname(fileURLToPath(import.meta.url))
const API = 'http://127.0.0.1:8765'
const cfg = () => JSON.parse(fs.readFileSync(path.join(DIR, 'config.json'), 'utf8'))
const log = (...a) => console.log(new Date().toLocaleString('es-CL'), ...a)
const esperar = ms => new Promise(r => setTimeout(r, ms))
const azar = (a, b) => Math.floor(a + Math.random() * (b - a + 1))

const argCodigo = process.argv.indexOf('--codigo')
const TELEFONO = argCodigo > -1 ? (process.argv[argCodigo + 1] || '').replace(/\D/g, '') : ''

let sock
const procesados = new Set()

// ------------------------------------------------------------ cola de envío con delay
const cola = []
let enviando = false
function encolar (jid, contenido, opciones = {}, delay = null) {
  cola.push({ jid, contenido, opciones, delay })
  if (!enviando) vaciarCola()
}
async function vaciarCola () {
  enviando = true
  while (cola.length) {
    const { jid, contenido, opciones, delay } = cola.shift()
    const [min, max] = cfg().delay_respuesta_seg || [35, 95]
    const ms = delay ?? azar(min, max) * 1000
    await esperar(ms)
    try {
      if (contenido.text) {
        await sock.sendPresenceUpdate('composing', jid)
        await esperar(Math.min(8000, 1500 + contenido.text.length * 40)) // "escribiendo..."
        await sock.sendPresenceUpdate('paused', jid)
      }
      await sock.sendMessage(jid, contenido, opciones)
      log('📤 enviado a', jid)
    } catch (e) {
      log('❌ error enviando:', e.message)
    }
  }
  enviando = false
}

// ------------------------------------------------------------ hablar con Python
async function api (ruta, datos) {
  const r = await fetch(API + ruta, datos
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(datos) }
    : {})
  return r.json()
}

function textoDe (m) {
  const msg = m.message || {}
  const inner = msg.ephemeralMessage?.message || msg.viewOnceMessage?.message || msg
  return inner.conversation || inner.extendedTextMessage?.text ||
    inner.imageMessage?.caption || inner.videoMessage?.caption || inner.documentMessage?.caption || ''
}

function esAdmin (m) {
  const admins = (cfg().admins || []).map(n => String(n).replace(/\D/g, ''))
  const k = m.key
  const ids = [k.participant, k.participantAlt, k.participantPn, k.remoteJid, k.remoteJidAlt]
    .filter(Boolean).map(j => j.split('@')[0].split(':')[0])
  return ids.some(id => admins.includes(id))
}

const normal = s => String(s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
const nombresGrupo = {}
let grupoActivo = ''
async function esGrupoSupervisoras (jid) {
  if (!jid?.endsWith('@g.us')) return false
  const c = cfg()
  if (c.grupo_id) return jid === c.grupo_id
  if (!c.grupo_nombre) return false
  if (!(jid in nombresGrupo)) {
    try { nombresGrupo[jid] = (await sock.groupMetadata(jid)).subject } catch { nombresGrupo[jid] = '' }
  }
  const ok = normal(nombresGrupo[jid]).includes(normal(c.grupo_nombre))
  if (ok) grupoActivo = jid
  return ok
}
const grupoDestino = () => cfg().grupo_id || grupoActivo

async function manejar (m) {
  if (!m.message || m.key.fromMe) return
  const id = m.key.id
  if (procesados.has(id)) return
  procesados.add(id)
  if (procesados.size > 5000) procesados.clear()

  const jid = m.key.remoteJid
  const texto = textoDe(m).trim()
  if (!texto) return
  const c = cfg()
  const enGrupo = await esGrupoSupervisoras(jid)
  const admin = esAdmin(m)

  // !id funciona en cualquier chat para descubrir el ID del grupo
  if (texto.toLowerCase() === '!id') {
    log('🆔 ID de este chat:', jid)
    encolar(jid, { text: `🆔 ${jid}` }, { quoted: m }, 2000)
    return
  }

  if (texto.startsWith('!') && (enGrupo || admin)) {
    try {
      const r = await api('/comando', { texto, autor: m.pushName || '', es_admin: admin })
      if (r.texto) encolar(jid, { text: r.texto }, { quoted: m }, azar(3, 8) * 1000)
      if (r.archivo) {
        encolar(jid, {
          document: fs.readFileSync(r.archivo),
          fileName: path.basename(r.archivo),
          mimetype: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        }, {}, 3000)
      }
    } catch (e) { log('❌ comando:', e.message) }
    return
  }

  if (!enGrupo) return
  log(`📥 ${m.pushName || '?'}: ${texto.slice(0, 80)}`)
  try {
    const r = await api('/mensaje', { texto, autor: m.pushName || 'supervisora' })
    if (r.respuestas?.length) encolar(jid, { text: r.respuestas.join('\n\n') }, { quoted: m })
    if (r.error) log('❌ servidor:', r.error)
  } catch (e) {
    log('❌ ¿está corriendo servidor.py?', e.message)
  }
}

// ------------------------------------------------------------ tareas programadas
const hecho = {}
setInterval(async () => {
  if (!sock?.user) return
  const c = cfg()
  const ahora = new Date()
  const hhmm = ahora.toTimeString().slice(0, 5)
  const dia = ahora.toISOString().slice(0, 10) + ahora.getDay()
  const habil = ahora.getDay() >= 1 && ahora.getDay() <= 5
  try {
    if (habil && c.agenda_matutina?.activa && grupoDestino() && hhmm === c.agenda_matutina.hora &&
        hecho.agenda !== dia) {
      hecho.agenda = dia
      const r = await api('/agenda_dia')
      encolar(grupoDestino(), { text: r.texto }, {}, azar(5, 40) * 1000)
    }
    if (habil && c.reporte_diario?.activo && c.chat_reportes && hhmm === c.reporte_diario.hora &&
        hecho.reporte !== dia) {
      hecho.reporte = dia
      const r = await api('/reporte')
      encolar(c.chat_reportes, {
        document: fs.readFileSync(r.archivo),
        fileName: path.basename(r.archivo),
        mimetype: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        caption: '📊 Reporte diario de mantención'
      }, {}, 2000)
    }
  } catch (e) { log('❌ tarea programada:', e.message) }
}, 20000)

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
    // en su propia línea, sin fecha delante, para que Termux no lo corte
    console.log('\n\n==============================')
    console.log('   CÓDIGO:  ' + codigo)
    console.log('==============================')
    console.log(`(son 8 caracteres: ${crudo.split('').join(' ')})`)
    console.log('WhatsApp del bot > ⋮ > Dispositivos vinculados > Vincular dispositivo')
    console.log('> "Vincular con número de teléfono" y escribe las 8 letras/números.')
    console.log('El código vence en ~1 minuto. Si vence, presiona Ctrl+C y corre de nuevo:')
    console.log(`   node bot.mjs --codigo ${TELEFONO}\n`)
  }

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr && !TELEFONO) {
      log('📷 Escanea este QR desde WhatsApp > Dispositivos vinculados:')
      qrcode.generate(qr, { small: true })
    }
    if (connection === 'open') {
      log('✅ Conectado a WhatsApp como', sock.user?.id)
      try {
        const grupos = await sock.groupFetchAllParticipating()
        log('👥 Grupos donde está el bot:')
        for (const g of Object.values(grupos)) {
          nombresGrupo[g.id] = g.subject
          const marca = await esGrupoSupervisoras(g.id) ? '  ✅ ESTE ES EL GRUPO QUE LEO' : ''
          log(`   ${g.subject}  ->  ${g.id}${marca}`)
        }
        if (!grupoDestino()) log('⚠️  No encontré el grupo: revisa grupo_nombre o grupo_id en config.json')
      } catch {}
      if (TELEFONO) {   // modo vinculación: dejar la sesión guardada y salir
        log('🔗 Vinculación lista. La sesión quedó guardada en auth/.')
        await esperar(4000)
        process.exit(0)
      }
    }
    if (connection === 'close') {
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

conectar()
