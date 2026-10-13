// background.js — el "capataz" del vigía (v2, blindado). Corre mientras Chrome esté abierto.
//
// Cómo trabaja, en simple:
//  - Usa UNA sola pestaña fija y silenciada. Entra a un grupo, mira lo más nuevo (o busca una
//    palabra), lee y la deja "en reposo". Espera unos minutos (con azar) y va al siguiente.
//  - Se comporta como persona: horario, sesiones con descansos, topes por hora y por día, y
//    prioriza los grupos donde más pegas salen.
//  - Si Facebook muestra CUALQUIER aviso (iniciar sesión, verificación, bloqueo, "vas muy rápido")
//    se pausa solo por horas y te avisa. Nunca hace clic, nunca comenta, nunca escribe.
//  - Lo que lee pasa por un filtro local; solo lo que parece pega va a la IA (de a lotes).
//  - Cada pega: queda en Solicitudes con el mensaje listo + aviso en Chrome (+ en tu celular si
//    configuras ntfy) + aprende las frases que la delataron.

import { clasificarLote, probar } from "./gemini.js";
import { prefiltro, clasificarLocal, plantilla, norm } from "./filtro.js";

// ======================================================================= perfiles de seguridad
export const PERFILES = {
  seguro: { nombre: "Seguro", min_entre: 3, max_hora: 12, max_dia: 100, max_busq_hora: 4, max_busq_dia: 30, sesion_min: 25, descanso_min: 15 },
  normal: { nombre: "Normal", min_entre: 2, max_hora: 20, max_dia: 170, max_busq_hora: 6, max_busq_dia: 50, sesion_min: 40, descanso_min: 12 },
  rapido: { nombre: "Rápido", min_entre: 1.2, max_hora: 32, max_dia: 280, max_busq_hora: 10, max_busq_dia: 80, sesion_min: 60, descanso_min: 10 }
};
const TOPES = { min_entre: 1, max_hora: 40, max_dia: 350, max_busq_hora: 12, max_busq_dia: 100 };

const KW_DEF = ["busco", "eléctrico", "electricista", "gasfiter", "maestro", "sin luz", "fuga", "califont",
  "enchufe", "cortocircuito", "necesito electricista", "necesito gasfiter", "filtración", "destape"];
const KW_V1 = ["busco", "necesito", "electrico", "electricista", "gasfiter", "gasfitero", "maestro",
  "se corto la luz", "sin luz", "fuga de gas", "califont", "enchufe", "cortocircuito",
  "instalacion electrica", "cambiar", "reparar", "arreglar luz"];

export const CONFIG_DEF = {
  version: 3,
  activo: false,
  gemini_key: "", gemini_endpoint: "auto", modelos: ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"],
  grupos: [],                    // [{id, nombre, url}]
  keywords: KW_DEF,
  keywords_aprendidas: [],       // [{frase, veces, estado:'propuesta'|'activa'|'descartada'}]
  rondas_activa: true,           // recorrer los grupos solo
  ver_recientes: true,           // en cada grupo mirar lo más nuevo (orden cronológico)
  buscar_palabras: true,         // además, buscar palabras dentro del grupo
  busqueda_cada: 3,              // 1 de cada 3 visitas es búsqueda (las búsquedas son lo que más mira Facebook)
  busqueda_reciente: false,      // experimental: pedir resultados de búsqueda ordenados por fecha
  feed_activo: true,             // leer el inicio/grupos mientras navegas tú (riesgo cero)
  perfil_seguridad: "seguro",
  horario: ["07:30", "23:30"],
  dias_antiguedad: 7,            // publicaciones más viejas que esto no se toman
  pausa_bloqueo_horas: 24,
  ventana_aparte: false,         // usar una ventanita aparte en vez de una pestaña escondida
  ntfy_tema: "", webhook_url: "",
  mi_nombre: "", mi_rubro: "electricidad y gasfitería", mi_zona: "", mi_fono: "", plantilla: ""
};

const ESTADO_DEF = {
  vigiaTab: null, vigiaWin: null, pendiente: null, ultima: 0, proxima: 0, actual: { accion: "pausado" },
  sesion_inicio: 0, sesion_largo: 0, descanso_hasta: 0, pausa_hasta: 0, pausa_motivo: "",
  kw_idx: 0, n_visita: 0, cola_pausa_hasta: 0, cola_fallos: 0,
  vacios_seguidos: 0, sin_resp_seguidos: 0, importTab: null, importacion: null
};
const USO_DEF = () => ({ dia: "", v_dia: 0, b_dia: 0, mv: [], mb: [] });
const CONT_DEF = () => ({ visitas: 0, vistos: 0, pegas: 0 });

const RESERVADOS = new Set(["joins", "feed", "discover", "create", "search", "notifications", "your_groups", "joined", "learning_content", "membership"]);
const REPOSO = () => chrome.runtime.getURL("reposo.html");
const ICONO = () => chrome.runtime.getURL("iconos/128.png");

// ======================================================================= almacenamiento con candado
// Varias cosas pasan a la vez (la ronda, lo que lees tú, la IA, el panel). Todo cambio pasa por
// este candado para que nadie pise lo que escribió otro.
const get = async (k, def) => (await chrome.storage.local.get(k))[k] ?? def;
const set = (o) => chrome.storage.local.set(o);
let cadena = Promise.resolve();
function exclusivo(fn) { const p = cadena.then(() => fn()); cadena = p.catch(() => {}); return p; }
function mutar(clave, def, fn) {
  return exclusivo(async () => { const v = await get(clave, def); const r = await fn(v); if (r !== false) await set({ [clave]: v }); return r; });
}

function migrar(raw) {
  const c = { ...CONFIG_DEF, ...(raw || {}) };
  if (raw && (raw.version || 1) < 3) {
    if (!raw.horario || (raw.horario[0] === "08:00" && raw.horario[1] === "23:00")) c.horario = [...CONFIG_DEF.horario];
    if (JSON.stringify(raw.keywords || []) === JSON.stringify(KW_V1)) c.keywords = [...KW_DEF];
    delete c.minutos_entre; delete c.solo_recientes_dias;
    c.modelos = CONFIG_DEF.modelos;
  }
  if (!PERFILES[c.perfil_seguridad]) c.perfil_seguridad = "seguro";
  c.version = 3;
  return c;
}
async function cfg() { return migrar(await get("config", null)); }
function mutarConfig(fn) {
  return exclusivo(async () => { const c = await cfg(); const r = await fn(c); await set({ config: c }); return r; });
}
async function estado() {
  const s = { ...ESTADO_DEF, ...(await get("estado", {})) };
  s.uso = { ...USO_DEF(), ...(s.uso || {}) };
  s.cont = { ...CONT_DEF(), ...(s.cont || {}) };
  return s;
}
// patch(obj) o patch(fn): fn recibe el estado y lo cambia; si devuelve false no se escribe
function patch(x) {
  return exclusivo(async () => {
    const s = await estado();
    const r = typeof x === "function" ? await x(s) : Object.assign(s, x);
    if (r !== false) await set({ estado: s });
    return s;
  });
}

function perfil(c) {
  const p = { ...(PERFILES[c.perfil_seguridad] || PERFILES.seguro) };
  p.min_entre = Math.max(TOPES.min_entre, p.min_entre);
  for (const k of ["max_hora", "max_dia", "max_busq_hora", "max_busq_dia"]) p[k] = Math.min(TOPES[k], p[k]);
  return p;
}

// ======================================================================= utilidades
const dos = (n) => String(n).padStart(2, "0");
const hoyStr = (d = new Date()) => `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
const horaCorta = (t) => { const d = new Date(t); return `${dos(d.getHours())}:${dos(d.getMinutes())}`; };
const azar = (a, b) => a + Math.random() * (b - a);
const llaveOk = (c) => !!c.gemini_key && !c.gemini_key.startsWith("PEGA") && c.gemini_key.length > 20;

function dentroHorario(c, d = new Date()) {
  const h = `${dos(d.getHours())}:${dos(d.getMinutes())}`;
  const [a, b] = c.horario?.length === 2 ? c.horario : ["00:00", "23:59"];
  return a <= b ? (h >= a && h <= b) : (h >= a || h <= b);     // también sirve si cruza la medianoche
}
function idDe(url) {
  const m = String(url || "").match(/facebook\.com\/groups\/([^/?#]+)/i);
  return m && !RESERVADOS.has(m[1].toLowerCase()) ? m[1] : null;
}
function palabras(c) {
  const ap = (c.keywords_aprendidas || []).filter(x => x.estado === "activa").map(x => x.frase);
  const out = [], vis = new Set();
  for (const k of [...(c.keywords || []), ...ap]) { const n = norm(k).trim(); if (n && !vis.has(n)) { vis.add(n); out.push(k.trim()); } }
  return out;
}
function nombreGrupo(c, url) {
  const id = idDe(url);
  if (!id) return "inicio";
  const g = (c.grupos || []).find(x => x.id === id);
  return g?.nombre || id;
}
// clave única de una publicación (el mismo post puede venir con links distintos)
function clave(p) {
  const u = p.url || "";
  const m = u.match(/(?:posts|permalink)\/(\d+)/) || u.match(/story_fbid=(\d+)/) || u.match(/\/posts\/([\w]+)/);
  if (m) return "post:" + m[1];
  return "txt:" + norm(p.autor || "").slice(0, 40) + "|" + norm(p.texto || "").replace(/\s+/g, " ").slice(0, 120);
}
const huellaLead = (p) => norm(p.autor || "").trim() + "|" + norm(p.texto || "").replace(/[^a-z0-9]+/g, " ").trim().slice(0, 140);

// ======================================================================= bitácora y avisos
const ultimosLogs = new Map();
async function anota(tipo, texto) {
  console.log("[vigía]", tipo, texto);
  await mutar("bitacora", [], b => { b.unshift({ t: Date.now(), tipo, texto }); if (b.length > 500) b.length = 500; });
}
async function anotaUnaVez(tipo, texto, ms = 30 * 60000) {   // no repetir el mismo aviso a cada rato
  const t = ultimosLogs.get(texto) || 0;
  if (Date.now() - t < ms) return;
  ultimosLogs.set(texto, Date.now());
  await anota(tipo, texto);
}
async function setActual(actual, log) {
  let cambio = false;
  await patch(s => {
    const a = s.actual || {};
    if (a.accion === actual.accion && a.hasta === actual.hasta && a.motivo === actual.motivo && a.falta === actual.falta) return false;
    cambio = a.accion !== actual.accion;
    s.actual = { ...actual, desde: a.accion === actual.accion ? (a.desde || Date.now()) : Date.now() };
  });
  if (cambio && log) await anota(log[0], log[1]);
}

async function notificar(id, titulo, mensaje, botones = false) {
  try {
    await chrome.notifications.create(id, {
      type: "basic", iconUrl: ICONO(), title: titulo, message: mensaje, priority: 2,
      ...(botones ? { buttons: [{ title: "Abrir publicación" }, { title: "Ver en el panel" }] } : {})
    });
  } catch (e) { console.warn("[vigía] notificación", e); }
}
async function alCelular(c, titulo, mensaje, click, tags = ["zap"]) {
  if (!c.ntfy_tema) return { ok: false, error: "sin tema" };
  try {
    const r = await fetch("https://ntfy.sh/", {
      method: "POST",
      body: JSON.stringify({ topic: c.ntfy_tema, title: titulo, message: mensaje, tags, priority: 4, ...(click ? { click } : {}) })
    });
    return { ok: r.ok, error: r.ok ? "" : "HTTP " + r.status };
  } catch (e) { return { ok: false, error: e.message }; }
}

async function actualizarBadge() {
  const leads = await get("leads", []);
  const n = leads.filter(l => l.estado === "nuevo").length;
  await chrome.action.setBadgeBackgroundColor({ color: "#e53935" });
  await chrome.action.setBadgeText({ text: n ? String(Math.min(n, 999)) : "" });
}

// ======================================================================= arranque
chrome.runtime.onInstalled.addListener(async (det) => {
  await mutarConfig(() => {});                      // guarda la config ya migrada a v2
  for (const [k, def] of [["leads", []], ["vistos", {}], ["bitacora", []], ["mirados", []], ["cola", []], ["gstats", {}]]) {
    if ((await get(k, null)) === null) await set({ [k]: def });
  }
  await chrome.alarms.clear("ronda");               // reloj de la v1
  await patch({ pendiente: null, sesion_inicio: 0 });
  asegurarReloj();
  await actualizarBadge();
  await anota("info", `Vigía v${chrome.runtime.getManifest().version} instalado/actualizado.`);
  if (det?.reason === "install" || det?.reason === "update") abrirPanel().catch(() => {});   // que veas al tiro que quedó andando
  tick();
});
chrome.runtime.onStartup.addListener(async () => {
  await patch(s => { s.pendiente = null; s.vigiaTab = null; s.vigiaWin = null; s.sesion_inicio = 0; });
  asegurarReloj();
  await actualizarBadge();
});

function asegurarReloj() {
  chrome.alarms.get("vigia").then(a => { if (!a) chrome.alarms.create("vigia", { delayInMinutes: 0.1, periodInMinutes: 0.5 }); });
}
asegurarReloj();
chrome.alarms.onAlarm.addListener(a => { if (a.name === "vigia") tick(); });

chrome.action.onClicked.addListener(() => abrirPanel());
async function abrirPanel(seccion = "") {
  const base = chrome.runtime.getURL("panel.html");
  const tabs = await chrome.tabs.query({});
  const ya = tabs.find(t => (t.url || "").startsWith(base));
  if (ya) { await chrome.tabs.update(ya.id, { active: true, ...(seccion ? { url: base + "#" + seccion } : {}) }); await chrome.windows.update(ya.windowId, { focused: true }); }
  else await chrome.tabs.create({ url: base + (seccion ? "#" + seccion : "") });
}
chrome.notifications.onClicked.addListener(async (id) => { chrome.notifications.clear(id); await abrirPanel("solicitudes"); });
chrome.notifications.onButtonClicked.addListener(async (id, i) => {
  chrome.notifications.clear(id);
  if (i === 1) return abrirPanel("solicitudes");
  const l = (await get("leads", [])).find(x => x.id === id);
  if (l?.url) chrome.tabs.create({ url: l.url, active: true }); else abrirPanel("solicitudes");
});

// si cierras la pestaña o la ventana del vigía, la vuelve a crear en la próxima vuelta
chrome.tabs.onRemoved.addListener((tabId) => {
  patch(s => {
    if (s.importTab === tabId) { s.importTab = null; if (s.importacion && !s.importacion.fin) s.importacion.fin = true; return; }
    if (s.vigiaTab !== tabId) return false;
    s.vigiaTab = null;
    if (s.pendiente) { s.pendiente = null; s.proxima = Date.now() + 60000; s.actual = { accion: "esperando", hasta: s.proxima, desde: Date.now() }; }
  });
});
chrome.windows.onRemoved.addListener((wid) => { patch(s => { if (s.vigiaWin !== wid) return false; s.vigiaWin = null; }); });

// ======================================================================= la ronda (cada 30 s)
let tickCorriendo = false, forzarPendiente = false;
async function tick(forzar = false) {
  if (tickCorriendo) { if (forzar) forzarPendiente = true; return; }
  tickCorriendo = true;
  try { await ronda(forzar); }
  catch (e) { console.warn("[vigía] tick", e); await anotaUnaVez("error", "Error interno: " + (e?.message || e)); }
  finally {
    tickCorriendo = false;
    if (forzarPendiente) { forzarPendiente = false; setTimeout(() => tick(true), 200); }
  }
}

async function ronda(forzar) {
  const c = await cfg();
  const p = perfil(c);
  const now = Date.now();
  const st = await estado();

  // 1) hay una visita en curso: esperar al lector (máx. 50 s)
  if (st.pendiente) {
    if (now - st.pendiente.t < 50000) return;
    await terminarVisita(`${st.pendiente.grupo}: la página no respondió a tiempo`, { sinRespuesta: true });
    return;
  }
  procesarCola();                                   // si quedó algo en la fila de la IA, que siga

  // 2) ¿puede trabajar?
  if (!c.activo) return setActual({ accion: "pausado" });
  if (!c.rondas_activa) return setActual({ accion: "solo_inicio" });
  if (st.pausa_hasta > now) return setActual({ accion: "pausa_seguridad", motivo: st.pausa_motivo, hasta: st.pausa_hasta });
  if (st.pausa_hasta) {
    await patch({ pausa_hasta: 0, pausa_motivo: "", sesion_inicio: 0 });
    await anota("seguridad", "Terminó la pausa de seguridad. Retomo despacito.");
  }
  if (!dentroHorario(c)) return setActual({ accion: "fuera_horario" }, ["info", `Fuera de horario (trabajo de ${c.horario[0]} a ${c.horario[1]}). Vuelvo solo.`]);
  if (!c.grupos.length) return setActual({ accion: "sin_datos", falta: "grupos" });
  const pals = palabras(c);
  if (!c.ver_recientes && !(c.buscar_palabras && pals.length)) return setActual({ accion: "sin_datos", falta: "modo" });
  if (navigator.onLine === false) return setActual({ accion: "sin_internet" }, ["info", "Sin internet. Espero."]);

  // 3) sesiones con descanso (como una persona que mira un rato y deja el celular)
  if (!forzar) {
    if (st.descanso_hasta > now) return setActual({ accion: "descanso", hasta: st.descanso_hasta });
    const largo = p.sesion_min * azar(0.7, 1.3) * 60000;
    if (!st.sesion_inicio || now - (st.ultima || 0) > p.descanso_min * 60000) {
      await patch({ sesion_inicio: now, sesion_largo: largo });
    } else if (now - st.sesion_inicio > (st.sesion_largo || largo)) {
      const hasta = now + p.descanso_min * azar(0.7, 1.5) * 60000;
      await patch({ descanso_hasta: hasta, sesion_inicio: 0 });
      return setActual({ accion: "descanso", hasta },
        ["descanso", `Llevo ${Math.round((now - st.sesion_inicio) / 60000)} min mirando grupos: descanso hasta las ${horaCorta(hasta)}, como haría una persona.`]);
    }
  }

  // 4) topes por hora y por día
  const u = st.uso;
  if (u.dia !== hoyStr()) { u.dia = hoyStr(); u.v_dia = 0; u.b_dia = 0; }
  u.mv = u.mv.filter(t => now - t < 3600000);
  u.mb = u.mb.filter(t => now - t < 3600000);
  if (u.mv.length >= p.max_hora) {
    const hasta = Math.min(...u.mv) + 3600000;
    await patch({ uso: u });
    return setActual({ accion: "limite_hora", hasta }, ["seguridad", `Llegué al máximo de esta hora (${p.max_hora} visitas). Sigo a las ${horaCorta(hasta)}.`]);
  }
  if (u.v_dia >= p.max_dia) {
    await patch({ uso: u });
    return setActual({ accion: "limite_dia" }, ["seguridad", `Llegué al máximo de hoy (${p.max_dia} visitas). Mañana sigo.`]);
  }

  // 5) espaciado entre visitas
  if (forzar) {
    const minimo = (st.ultima || 0) + (c._debug?.piso_ms ?? 60000);   // ni apurándolo baja de 1 minuto entre visitas
    if (now < minimo) { await patch({ proxima: minimo }); return setActual({ accion: "esperando", hasta: minimo }); }
  } else if (now < (st.proxima || 0)) {
    return setActual({ accion: "esperando", hasta: st.proxima });
  }

  // 6) qué grupo y qué mirar
  const gstats = await get("gstats", {});
  const g = elegirGrupo(c, gstats, now);
  if (!g) return setActual({ accion: "sin_datos", falta: "acceso" });
  const cada = Math.max(1, Math.min(10, +c.busqueda_cada || 3));
  const tocaBuscar = c.buscar_palabras && pals.length && (!c.ver_recientes || st.n_visita % cada === cada - 1);
  const cupoBusq = u.mb.length < p.max_busq_hora && u.b_dia < p.max_busq_dia;
  let tipo = "recientes";
  if (tocaBuscar && cupoBusq) tipo = "buscar";
  else if (!c.ver_recientes) {
    const hasta = u.mb.length ? Math.min(...u.mb) + 3600000 : now + 3600000;
    return setActual({ accion: "limite_busq", hasta }, ["seguridad", `Usé las búsquedas permitidas por ahora. Sigo a las ${horaCorta(hasta)}.`]);
  }
  const palabra = tipo === "buscar" ? pals[st.kw_idx % pals.length] : "";
  const url = tipo === "buscar" ? urlBusqueda(g.id, palabra, c.busqueda_reciente)
                                : `https://www.facebook.com/groups/${g.id}/?sorting_setting=CHRONOLOGICAL`;

  // 7) ir
  u.mv.push(now); u.v_dia++;
  if (tipo === "buscar") { u.mb.push(now); u.b_dia++; }
  await patch(s => {
    s.pendiente = { t: now, tipo, grupoId: g.id, grupo: g.nombre, palabra, url, tabId: null };
    s.ultima = now; s.n_visita = (s.n_visita || 0) + 1; s.uso = u;
    if (tipo === "buscar") s.kw_idx = (s.kw_idx || 0) + 1;
    s.cont.visitas++;
    s.actual = { accion: tipo === "buscar" ? "buscando" : "recientes", grupo: g.nombre, palabra, desde: now };
  });
  let tabId;
  try { tabId = await pestanaVigia(c, url); }
  catch (e) {
    await patch({ pendiente: null, vigiaTab: null, proxima: now + 60000 });
    await anota("error", "No pude abrir la pestaña del vigía: " + e.message);
    return;
  }
  await patch(s => { s.vigiaTab = tabId; if (s.pendiente) s.pendiente.tabId = tabId; });
  await mutar("gstats", {}, gs => { const x = gs[g.id] ||= {}; x.visitas = (x.visitas || 0) + 1; x.ultima = now; });
  await anota(tipo === "buscar" ? "ronda" : "recientes",
    tipo === "buscar" ? `Busco “${palabra}” en ${g.nombre}` : `Miro lo más nuevo de ${g.nombre}`);
  setTimeout(() => tick(), 52000);                  // por si el lector no contesta
}

function urlBusqueda(gid, palabra, reciente) {
  let u = `https://www.facebook.com/groups/${gid}/search/?q=${encodeURIComponent(palabra)}`;
  if (reciente) {
    const f = btoa(JSON.stringify({ "rp_chrono_sort:0": JSON.stringify({ name: "chronosort", args: "" }) }));
    u += "&filters=" + encodeURIComponent(f);
  }
  return u;
}

// prioridad: los que llevan más rato sin mirar, y los que más pegas han dado
function elegirGrupo(c, gstats, now) {
  let mejor = null, top = -1;
  for (const g of c.grupos) {
    const s = gstats[g.id] || {};
    if (s.sin_acceso && now - s.sin_acceso < 7 * 86400000) continue;
    const min = s.ultima ? (now - s.ultima) / 60000 : 1e6;
    const pts = min * (1 + 0.6 * Math.min(s.pegas || 0, 8)) * azar(0.85, 1.15);
    if (pts > top) { top = pts; mejor = g; }
  }
  return mejor;
}

// una sola pestaña: fija, silenciada, al fondo. Se reutiliza siempre.
async function pestanaVigia(c, url) {
  const st = await estado();
  const opts = { url, muted: true, autoDiscardable: false };
  if (st.vigiaTab != null) {
    try { const t = await chrome.tabs.get(st.vigiaTab); await chrome.tabs.update(t.id, opts); return t.id; } catch {}
  }
  const quedadas = (await chrome.tabs.query({})).filter(t => (t.url || t.pendingUrl || "").startsWith(REPOSO()));
  if (quedadas.length) {
    const [t, ...resto] = quedadas;
    for (const r of resto) chrome.tabs.remove(r.id).catch(() => {});
    await chrome.tabs.update(t.id, opts);
    return t.id;
  }
  if (c.ventana_aparte) {
    const w = await chrome.windows.create({ url, focused: false, width: 520, height: 760, type: "normal" });
    const t = w.tabs[0];
    await chrome.tabs.update(t.id, { muted: true, autoDiscardable: false });
    await patch({ vigiaWin: w.id });
    return t.id;
  }
  const t = await chrome.tabs.create({ url, active: false, pinned: true, index: 0 });
  await chrome.tabs.update(t.id, { muted: true, autoDiscardable: false });
  return t.id;
}

async function cerrarVigia() {
  const st = await estado();
  if (st.pendiente) return;
  if (st.vigiaTab != null) { try { await chrome.tabs.remove(st.vigiaTab); } catch {} }
  for (const t of (await chrome.tabs.query({})).filter(t => (t.url || "").startsWith(REPOSO()))) chrome.tabs.remove(t.id).catch(() => {});
  await patch({ vigiaTab: null, vigiaWin: null });
}

async function terminarVisita(texto, { sinRespuesta = false, tipoLog = "resultado" } = {}) {
  const c = await cfg();
  const p = perfil(c);
  const now = Date.now();
  let tabId = null;
  const st = await patch(s => {
    tabId = s.vigiaTab;
    s.pendiente = null;
    const base = c._debug?.ms_entre || p.min_entre * 60000;
    let espera = base * azar(0.75, 1.35);
    if (Math.random() < 0.1) espera *= azar(1.5, 2.5);         // a veces se "distrae" más rato
    s.proxima = Math.max(s.proxima || 0, now + espera);
    s.actual = { accion: "esperando", hasta: s.proxima, desde: now };
    s.sin_resp_seguidos = sinRespuesta ? (s.sin_resp_seguidos || 0) + 1 : 0;
  });
  if (tabId != null) { try { await chrome.tabs.update(tabId, { url: REPOSO() }); } catch {} }
  if (texto) await anota(sinRespuesta ? "error" : tipoLog, texto);
  if (st.sin_resp_seguidos >= 3) {
    await patch({ sin_resp_seguidos: 0 });
    await pausar("Facebook no cargó 3 veces seguidas (¿internet lento o caído?)", 10 * 60000, false);
  }
}

async function pausar(motivo, ms, avisar = true) {
  const hasta = Date.now() + ms;
  await patch(s => { s.pausa_hasta = Math.max(s.pausa_hasta || 0, hasta); s.pausa_motivo = motivo; s.sesion_inicio = 0;
    s.actual = { accion: "pausa_seguridad", motivo, hasta: s.pausa_hasta, desde: Date.now() }; });
  const cuando = ms >= 3600000 ? `${Math.round(ms / 3600000)} h` : `${Math.round(ms / 60000)} min`;
  await anota("seguridad", `${motivo}. Me pauso ${cuando} (hasta las ${horaCorta(hasta)}) para cuidar tu cuenta.`);
  if (avisar) {
    await notificar("pausa" + Date.now(), "Vigía en pausa por seguridad", `${motivo}. Vuelvo solo en ${cuando}.`);
    await alCelular(await cfg(), "Vigía en pausa", `${motivo}. Vuelvo solo en ${cuando}.`, "", ["warning"]);
  }
}

// ======================================================================= lo que manda el lector
chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  (async () => {
    try {
      switch (msg?.tipo) {
        case "quien_soy": return responder(await quienSoy(sender));
        case "vigia_listo": await alListo(msg, sender); return responder({ ok: true });
        case "feed_posts": await alFeed(msg, sender); return responder({ ok: true });
        case "grupos_import": await alImportar(msg, sender); return responder({ ok: true });
        case "alerta_pagina": await alAlerta(msg); return responder({ ok: true });
        case "panel": return responder(await comandoPanel(msg));
        default: return responder({ ok: false });
      }
    } catch (e) { console.warn("[vigía] mensaje", e); responder({ ok: false, error: e.message }); }
  })();
  return true;
});

async function quienSoy(sender) {
  const [st, c] = [await estado(), await cfg()];
  const tab = sender?.tab?.id;
  const esVigia = tab != null && tab === st.vigiaTab && !!st.pendiente;
  const importar = !esVigia && tab != null && tab === st.importTab && !st.importacion?.fin &&
    Date.now() - (st.importacion?.t || 0) < 15 * 60000 && /\/groups\/joins|\/login/.test(sender.tab.url || "");
  return { vigia: esVigia, importar, inicio: !esVigia && !importar && c.activo && c.feed_activo };
}

// lo que junta la pestaña de "Importar mis grupos" (llega varias veces; la última con fin=true)
async function alImportar(msg, sender) {
  const st = await estado();
  if (sender?.tab?.id == null || sender.tab.id !== st.importTab) return;
  const lista = (Array.isArray(msg.grupos) ? msg.grupos : [])
    .map(g => ({ id: String(g?.id || "").trim(), nombre: String(g?.nombre || "").trim().slice(0, 80) }))
    .filter(g => /^[\w.-]{2,}$/.test(g.id) && !RESERVADOS.has(g.id.toLowerCase()));
  let nuevos = 0, total = 0;
  await mutarConfig(c => {
    const porId = new Map(c.grupos.map(g => [g.id, g]));
    for (const g of lista) {
      const ya = porId.get(g.id);
      if (ya) { if (g.nombre && (!ya.nombre || ya.nombre === ya.id)) ya.nombre = g.nombre; continue; }
      const n = { id: g.id, nombre: g.nombre || g.id, url: `https://www.facebook.com/groups/${g.id}/` };
      c.grupos.push(n); porId.set(g.id, n); nuevos++;
    }
    total = c.grupos.length;
  });
  const fin = !!msg.fin;
  const s2 = await patch(s => {
    const prev = s.importacion || { t: Date.now(), nuevos: 0 };
    s.importacion = { ...prev, n: lista.length, nuevos: (prev.nuevos || 0) + nuevos, total, fin };
    if (fin) s.importTab = null;
  });
  if (fin) {
    const imp = s2.importacion;
    await anota("info", imp.n ? `Importé tus grupos de Facebook: encontré ${imp.n}, ${imp.nuevos} nuevos. Ahora tienes ${imp.total} grupos.`
                              : "No encontré grupos en tu lista (¿sesión de Facebook iniciada?).");
    await notificar("import" + Date.now(), "Grupos importados", imp.n ? `${imp.n} grupos encontrados, ${imp.nuevos} nuevos. Total: ${imp.total}.` : "No encontré grupos.");
  }
}

async function alListo(msg, sender) {
  const st = await estado();
  if (!st.pendiente || sender?.tab?.id !== st.vigiaTab) return;      // ya no la esperaba
  const pend = st.pendiente;
  const c = await cfg();
  const pg = msg.pagina || {};
  const posts = Array.isArray(msg.posts) ? msg.posts : [];
  const que = pend.tipo === "buscar" ? `“${pend.palabra}”` : "recientes";
  const gstat = (fn) => mutar("gstats", {}, gs => { fn(gs[pend.grupoId] ||= {}); });

  switch (pg.estado) {
    case "login":
      await gstat(x => { x.ultimo_estado = "pidió iniciar sesión"; });
      await terminarVisita("");
      return pausar("Facebook pide iniciar sesión: abre Facebook en Chrome y entra con tu cuenta", 20 * 60000);
    case "checkpoint":
      await gstat(x => { x.ultimo_estado = "verificación de Facebook"; });
      await terminarVisita("");
      await setPerfilSeguro(c);
      return pausar("Facebook mostró una verificación de seguridad (resuélvela tú a mano)", c.pausa_bloqueo_horas * 3600000);
    case "bloqueo":
      await gstat(x => { x.ultimo_estado = "aviso de bloqueo"; });
      await terminarVisita("");
      await setPerfilSeguro(c);
      return pausar("Facebook mostró un aviso de bloqueo / “vas muy rápido”", c.pausa_bloqueo_horas * 3600000);
    case "sin_acceso":
      await gstat(x => { x.sin_acceso = Date.now(); x.ultimo_estado = "sin acceso"; });
      return terminarVisita(`${pend.grupo}: no tengo acceso (grupo privado o ya no estás). Lo salto 7 días.`, { tipoLog: "info" });
    case "sin_resultados":
      await gstat(x => { x.ultimo_estado = "ok"; x.fallos = 0; });
      await patch({ vacios_seguidos: 0 });
      return terminarVisita(`${pend.grupo} · ${que} → sin resultados`);
    case "ok": {
      await patch({ vacios_seguidos: 0 });
      const r = await encolar(posts, { via: pend.tipo === "buscar" ? "búsqueda: " + pend.palabra : "reciente del grupo", grupo: pend.grupo, grupoId: pend.grupoId });
      await gstat(x => { x.ultimo_estado = "ok"; x.fallos = 0; x.sin_acceso = 0; x.vistas = (x.vistas || 0) + posts.length; });
      const extra = [r.nuevas < posts.length ? `${posts.length - r.nuevas} ya vistas` : "", r.viejas ? `${r.viejas} antiguas` : "",
                     r.candidatas ? `${r.candidatas} parecen pega → IA` : ""].filter(Boolean).join(", ");
      await terminarVisita(`${pend.grupo} · ${que} → ${posts.length} publicaciones, ${r.nuevas} nuevas${extra ? " (" + extra + ")" : ""}`);
      procesarCola();
      return;
    }
    default: {   // "vacio": cargó pero no mostró publicaciones
      const s2 = await patch(s => { s.vacios_seguidos = (s.vacios_seguidos || 0) + 1; });
      await gstat(x => { x.fallos = (x.fallos || 0) + 1; x.ultimo_estado = "vacío"; });
      await terminarVisita(`${pend.grupo} · ${que}: la página cargó pero no mostró publicaciones${pg.visible === "hidden" ? " (pestaña en segundo plano)" : ""}`, { tipoLog: "info" });
      if (s2.vacios_seguidos >= 3 && !c.ventana_aparte && (pg.visible === "hidden" || c._debug?.oculta)) {
        await mutarConfig(x => { x.ventana_aparte = true; });
        await patch({ vacios_seguidos: 0 });
        await cerrarVigia();
        await anota("info", "Facebook no está mostrando publicaciones en la pestaña escondida. Desde ahora uso una ventanita aparte (déjala abierta, puede quedar detrás). Lo puedes cambiar en Configuración.");
      }
    }
  }
}

async function setPerfilSeguro(c) {
  if (c.perfil_seguridad === "seguro") return;
  await mutarConfig(x => { x.perfil_seguridad = "seguro"; });
  await anota("seguridad", "Cambié el ritmo a «Seguro» por el aviso de Facebook.");
}

// lo que lees tú en el inicio o en los grupos (se junta y se anota cada minuto para no llenar la bitácora)
let feedAcum = { nuevas: 0, candidatas: 0, donde: new Set(), t: 0 };
async function alFeed(msg, sender) {
  const c = await cfg();
  if (!c.activo || !c.feed_activo) return;
  const st = await estado();
  if (sender?.tab?.id === st.vigiaTab) return;
  const grupo = nombreGrupo(c, msg.url);
  const r = await encolar(msg.posts || [], { via: "inicio", grupo, grupoId: idDe(msg.url) });
  feedAcum.nuevas += r.nuevas; feedAcum.candidatas += r.candidatas; feedAcum.donde.add(grupo);
  if (feedAcum.nuevas && Date.now() - feedAcum.t > 60000) {
    const donde = [...feedAcum.donde].slice(0, 3).join(", ");
    await anota("inicio", `Mientras navegas (${donde}): ${feedAcum.nuevas} publicaciones nuevas${feedAcum.candidatas ? `, ${feedAcum.candidatas} parecen pega → IA` : ""}`);
    feedAcum = { nuevas: 0, candidatas: 0, donde: new Set(), t: Date.now() };
  }
  if (r.candidatas) procesarCola();
}

async function alAlerta(msg) {
  const c = await cfg();
  const st = await estado();
  if (!c.activo || st.pausa_hasta > Date.now()) return;
  await pausar(msg.estado === "checkpoint" ? "Viste una verificación de Facebook mientras navegabas"
                                           : "Facebook te mostró un aviso de bloqueo mientras navegabas", c.pausa_bloqueo_horas * 3600000);
}

// ======================================================================= fila → filtro → IA → solicitudes
async function encolar(posts, ctx) {
  const c = await cfg();
  const now = Date.now();
  const maxEdad = (+c.dias_antiguedad || 7) * 24;
  const res = { nuevas: 0, viejas: 0, candidatas: 0, descartadas: 0 };
  const nuevos = [];
  await mutar("vistos", {}, v => {
    for (const p of posts) {
      if (!p || typeof p.texto !== "string" || p.texto.length < 12) continue;
      const k = clave(p);
      if (v[k]) continue;
      v[k] = now; nuevos.push(p);
    }
    const ks = Object.keys(v);
    if (ks.length > 15000) ks.sort((a, b) => v[a] - v[b]).slice(0, ks.length - 12000).forEach(k => delete v[k]);
  });
  const mir = [], aCola = [];
  for (const p of nuevos) {
    res.nuevas++;
    if (p.edad_h != null && p.edad_h > maxEdad) { res.viejas++; mir.push(mirado(p, ctx, "vieja")); continue; }
    if (!prefiltro(p.texto, c)) { res.descartadas++; mir.push(mirado(p, ctx, "no")); continue; }
    res.candidatas++;
    aCola.push({ p: { ...p, texto: p.texto.slice(0, 1800) }, ctx, t: now });
  }
  if (aCola.length) await mutar("cola", [], q => { q.push(...aCola); if (q.length > 400) q.splice(0, q.length - 400); });
  if (mir.length) await anotarMirados(mir);
  if (res.nuevas) await patch(s => { s.cont.vistos += res.nuevas; });
  return res;
}
function mirado(p, ctx, veredicto, resumen = "") {
  return { t: Date.now(), grupo: ctx.grupo || "", via: ctx.via || "", autor: p.autor || "", url: p.url || "",
           snippet: (resumen || p.texto || "").replace(/\s+/g, " ").slice(0, 110), veredicto };
}
async function anotarMirados(lista) {
  await mutar("mirados", [], m => { m.unshift(...lista.reverse()); if (m.length > 100) m.length = 100; });
}

let colaCorriendo = false;
async function procesarCola() {
  if (colaCorriendo) return;
  colaCorriendo = true;
  try {
    for (let vuelta = 0; vuelta < 8; vuelta++) {
      const c = await cfg();
      const st = await estado();
      const now = Date.now();
      const cola = await get("cola", []);
      if (!cola.length) return;
      const hayIA = llaveOk(c);
      const iaLibre = hayIA && !(st.cola_pausa_hasta > now);
      let lote;
      if (iaLibre) lote = cola.slice(0, 8);
      else if (!hayIA) lote = cola.slice(0, 60);
      else { lote = cola.filter(x => now - x.t > 20 * 60000).slice(0, 60); if (!lote.length) return; }   // IA en espera: solo las que llevan rato

      let resultados;
      if (iaLibre) {
        const r = await clasificarLote(c, lote.map(x => x.p.texto));
        if (r.error && r.limite) {
          const f = (st.cola_fallos || 0) + 1;
          const min = Math.min(30, 2 ** f);
          await patch({ cola_fallos: f, cola_pausa_hasta: now + min * 60000 });
          await anota("ia", `Gemini dice “demasiadas consultas”. Espero ${min} min y sigo (quedan ${cola.length} en fila).`);
          return;
        }
        if (r.error) {
          await anotaUnaVez("ia", `Gemini no respondió (${r.error}). Mientras, decido con reglas simples.`);
          await patch({ cola_pausa_hasta: now + 5 * 60000 });
          resultados = lote.map(x => clasificarLocal(x.p.texto, c));
        } else {
          if (st.cola_fallos) await patch({ cola_fallos: 0 });
          resultados = r.r.map((x, i) => x ? normalizar(x, c) : clasificarLocal(lote[i].p.texto, c));
        }
      } else {
        resultados = lote.map(x => clasificarLocal(x.p.texto, c));
      }

      const quitar = new Set(lote.map(x => clave(x.p)));
      await mutar("cola", [], q => { const resto = q.filter(x => !quitar.has(clave(x.p))); q.length = 0; q.push(...resto); });
      const mir = [];
      for (let i = 0; i < lote.length; i++) {
        const x = lote[i], r = resultados[i];
        mir.push(mirado(x.p, x.ctx, r.es_solicitud ? "pega" : "no", r.resumen));
        if (r.es_solicitud) {
          await guardarLead(x.p, r, x.ctx);
          if (!r.sin_ia) await aprender(r.frases_clave || []);
        }
      }
      await anotarMirados(mir);
    }
  } catch (e) {
    console.warn("[vigía] cola", e);
    await anotaUnaVez("error", "Error revisando la fila: " + e.message);
  } finally { colaCorriendo = false; }
}

function normalizar(x, c) {
  const es = x.es_solicitud === true || x.es_solicitud === "true";
  const tipo = ["electricidad", "gasfiteria", "ambos", "otro"].includes(x.tipo) ? x.tipo : "otro";
  return {
    es_solicitud: es, tipo,
    resumen: String(x.resumen || "").slice(0, 120), comuna: String(x.comuna || "").slice(0, 40),
    urgencia: ["alta", "media", "baja"].includes(x.urgencia) ? x.urgencia : "media",
    mensaje: es ? (String(x.mensaje || "").trim() || plantilla(c)) : "",
    frases_clave: Array.isArray(x.frases_clave) ? x.frases_clave.slice(0, 4) : []
  };
}

async function guardarLead(p, r, ctx) {
  const now = Date.now();
  const h = huellaLead(p);
  let nuevo = null, dup = null;
  await mutar("leads", [], L => {
    const ya = L.find(l => l.huella === h && now - Date.parse(l.creado) < 10 * 86400000);
    if (ya) {
      if (ctx.grupo && ctx.grupo !== ya.grupo && !(ya.otros_grupos || []).includes(ctx.grupo)) { (ya.otros_grupos ||= []).push(ctx.grupo); dup = ya; return; }
      dup = ya; return false;
    }
    nuevo = {
      id: "L" + now + Math.floor(Math.random() * 1000), creado: new Date(now).toISOString(), huella: h,
      grupo: ctx.grupo || "", grupoId: ctx.grupoId || "", via: ctx.via || "",
      autor: p.autor || "", autor_url: p.autor_url || "", texto: (p.texto || "").slice(0, 1500), url: p.url || "",
      edad_h: p.edad_h ?? null, publicado: p.edad_h != null ? new Date(now - p.edad_h * 3600000).toISOString() : "",
      tipo: r.tipo || "", resumen: r.resumen || "", comuna: r.comuna || "", urgencia: r.urgencia || "media",
      mensaje: r.mensaje || "", sin_ia: !!r.sin_ia, otros_grupos: [], estado: "nuevo"
    };
    L.unshift(nuevo);
    if (L.length > 3000) L.length = 3000;
  });
  if (!nuevo) {
    if (dup && dup.grupo !== ctx.grupo) await anotaUnaVez("pega", `${p.autor || "Alguien"} publicó lo mismo en ${ctx.grupo || "otro grupo"} (ya la tenías en Solicitudes).`, 6 * 3600000);
    return;
  }
  await patch(s => { s.cont.pegas++; });
  if (ctx.grupoId) await mutar("gstats", {}, gs => { const x = gs[ctx.grupoId] ||= {}; x.pegas = (x.pegas || 0) + 1; x.ultima_pega = now; });
  await actualizarBadge();
  const c = await cfg();
  const lugar = nuevo.comuna ? ` · ${nuevo.comuna}` : "";
  const titulo = `Pega: ${nuevo.tipo}${lugar}${nuevo.urgencia === "alta" ? " · URGENTE" : ""}`;
  const cuerpo = `${nuevo.resumen || nuevo.texto.slice(0, 90)}\n${nuevo.autor} · ${nuevo.grupo}`;
  await anota("pega", `⚡ ${nuevo.resumen || nuevo.texto.slice(0, 70)} — ${nuevo.autor || "?"} (${nuevo.grupo})`);
  await notificar(nuevo.id, titulo, cuerpo, true);
  alCelular(c, titulo, cuerpo, nuevo.url);
  if (c.webhook_url) fetch(c.webhook_url, { method: "POST", mode: "no-cors", body: JSON.stringify(nuevo) }).catch(() => {});
}

// frases que delatan una solicitud: se proponen; si se repiten 3 veces (y son de 2+ palabras) se activan solas
async function aprender(frases) {
  if (!frases.length) return;
  await mutarConfig(c => {
    const base = new Set((c.keywords || []).map(k => norm(k).trim()));
    const ap = c.keywords_aprendidas || (c.keywords_aprendidas = []);
    const activas = ap.filter(x => x.estado === "activa").length;
    for (const f0 of frases) {
      const f = String(f0 || "").toLowerCase().replace(/\s+/g, " ").trim();
      if (f.length < 4 || f.length > 40 || base.has(norm(f))) continue;
      const ya = ap.find(x => norm(x.frase) === norm(f));
      if (ya) {
        ya.veces++;
        if (ya.estado === "propuesta" && ya.veces >= 3 && f.includes(" ") && activas < 25) ya.estado = "activa";
      } else ap.push({ frase: f, veces: 1, estado: "propuesta" });
    }
    if (ap.length > 200) c.keywords_aprendidas = ap.sort((a, b) => b.veces - a.veces).slice(0, 200);
  });
}

// ======================================================================= órdenes del panel
async function comandoPanel(msg) {
  switch (msg.accion) {
    case "estado": {
      const c = await cfg();
      return { config: c, estado: await estado(), perfiles: PERFILES, config_def: CONFIG_DEF, palabras: palabras(c) };
    }
    case "set_config": {
      const antes = await cfg();
      const n = limpiarConfig(msg.config || {});
      await mutarConfig(c => { Object.assign(c, n); });
      if ("ventana_aparte" in n && n.ventana_aparte !== antes.ventana_aparte) await cerrarVigia();
      if (n.activo === true && !antes.activo) {
        await patch({ sesion_inicio: 0, descanso_hasta: 0, vacios_seguidos: 0, sin_resp_seguidos: 0 });
        await anota("info", "Activado.");
      }
      if (n.activo === false && antes.activo) await anota("info", "Pausado por ti.");
      asegurarReloj();
      return { ok: true };
    }
    case "probar": return await probar(await cfg());
    case "probar_ntfy": {
      const r = await alCelular(await cfg(), "Vigía de pegas", "¡Funciona! Aquí te llegarán las pegas que encuentre.", "");
      return { ok: r.ok, detalle: r.ok ? "enviado ✓ revisa tu celular" : r.error };
    }
    case "forzar_ronda": await patch({ descanso_hasta: 0 }); tick(true); return { ok: true };
    case "reanudar": {
      await patch({ pausa_hasta: 0, pausa_motivo: "", descanso_hasta: 0, sesion_inicio: 0 });
      await anota("seguridad", "Reanudado a mano antes de terminar la pausa.");
      tick(); return { ok: true };
    }
    case "lead_estado": {
      await mutar("leads", [], L => { const l = L.find(x => x.id === msg.id); if (!l) return false; l.estado = msg.estado; if (msg.estado === "contactado") l.contactado = new Date().toISOString(); });
      await actualizarBadge(); return { ok: true };
    }
    case "lead_mensaje": {
      await mutar("leads", [], L => { const l = L.find(x => x.id === msg.id); if (!l) return false; l.mensaje = String(msg.mensaje || "").slice(0, 1000); });
      return { ok: true };
    }
    case "borrar_leads": {
      await mutar("leads", [], L => { const r = L.filter(l => msg.cuales === "todos" ? false : l.estado !== msg.cuales); L.length = 0; L.push(...r); });
      await actualizarBadge(); return { ok: true };
    }
    case "kw_add": {
      const nuevas = String(msg.texto || "").split(/[,;\n]/).map(x => x.trim()).filter(x => x.length >= 2 && x.length <= 40);
      await mutarConfig(c => { const s = new Set(c.keywords.map(k => norm(k))); for (const k of nuevas) if (!s.has(norm(k))) { c.keywords.push(k); s.add(norm(k)); } });
      return { ok: true };
    }
    case "kw_del": {
      await mutarConfig(c => {
        c.keywords = c.keywords.filter(k => norm(k) !== norm(msg.texto));
        const a = (c.keywords_aprendidas || []).find(k => norm(k.frase) === norm(msg.texto));
        if (a) a.estado = "descartada";
      });
      return { ok: true };
    }
    case "kw_aprendida": {
      await mutarConfig(c => { const a = (c.keywords_aprendidas || []).find(x => x.frase === msg.frase); if (a) a.estado = msg.estado; });
      return { ok: true };
    }
    case "grupos_set": {
      const grupos = parsearGrupos(msg.texto);
      await mutarConfig(c => { c.grupos = grupos; });
      return { ok: true, n: grupos.length };
    }
    case "importar_grupos": {
      const t = await chrome.tabs.create({ url: "https://www.facebook.com/groups/joins/?nav_source=tab", active: true });
      await patch({ importTab: t.id, importacion: { t: Date.now(), n: 0, nuevos: 0, total: 0, fin: false } });
      await anota("info", "Abrí tu lista de grupos de Facebook para importarlos.");
      return { ok: true };
    }
    case "grupo_reintentar": {
      await mutar("gstats", {}, gs => { if (gs[msg.id]) { gs[msg.id].sin_acceso = 0; gs[msg.id].ultimo_estado = ""; } });
      return { ok: true };
    }
    case "limpiar_bitacora": await set({ bitacora: [], mirados: [] }); return { ok: true };
    case "reiniciar_vistos": await set({ vistos: {} }); await anota("info", "Olvidé las publicaciones ya vistas (las revisará de nuevo)."); return { ok: true };
    case "respaldo": {
      const c = await cfg();
      const { gemini_key, ...sinLlave } = c;
      return { version: 2, fecha: new Date().toISOString(), config: sinLlave, leads: await get("leads", []), gstats: await get("gstats", {}) };
    }
    case "restaurar": {
      const d = msg.datos || {};
      if (!d.config || !Array.isArray(d.leads)) return { ok: false, error: "archivo no válido" };
      await mutarConfig(c => { const llave = c.gemini_key; Object.assign(c, limpiarConfig(d.config), { gemini_key: llave, grupos: Array.isArray(d.config.grupos) ? d.config.grupos : c.grupos, keywords: Array.isArray(d.config.keywords) ? d.config.keywords : c.keywords, keywords_aprendidas: Array.isArray(d.config.keywords_aprendidas) ? d.config.keywords_aprendidas : c.keywords_aprendidas }); });
      await mutar("leads", [], L => { const ids = new Set(L.map(l => l.id)); for (const l of d.leads) if (l?.id && !ids.has(l.id)) L.push(l); L.sort((a, b) => String(b.creado).localeCompare(String(a.creado))); });
      if (d.gstats && typeof d.gstats === "object") await mutar("gstats", {}, gs => { for (const [k, v] of Object.entries(d.gstats)) gs[k] = { ...(gs[k] || {}), ...v }; });
      await actualizarBadge();
      await anota("info", "Respaldo cargado.");
      return { ok: true };
    }
    default: return { ok: false, error: "acción desconocida" };
  }
}

// solo deja pasar campos conocidos y valores con sentido
function limpiarConfig(n) {
  const out = {};
  const bool = ["activo", "rondas_activa", "ver_recientes", "buscar_palabras", "busqueda_reciente", "feed_activo", "ventana_aparte"];
  const txt = ["gemini_key", "gemini_endpoint", "ntfy_tema", "webhook_url", "mi_nombre", "mi_rubro", "mi_zona", "mi_fono", "plantilla"];
  for (const k of bool) if (k in n) out[k] = !!n[k];
  for (const k of txt) if (k in n) out[k] = String(n[k] ?? "").trim().slice(0, k === "plantilla" ? 600 : 300);
  if ("ntfy_tema" in out) out.ntfy_tema = out.ntfy_tema.replace(/^https?:\/\/ntfy\.sh\//, "").replace(/[^\w-]/g, "").slice(0, 64);
  if ("webhook_url" in out && out.webhook_url && !/^https?:\/\//.test(out.webhook_url)) out.webhook_url = "";
  if ("gemini_endpoint" in out && !["auto", "aistudio", "vertex"].includes(out.gemini_endpoint)) out.gemini_endpoint = "auto";
  if ("perfil_seguridad" in n && PERFILES[n.perfil_seguridad]) out.perfil_seguridad = n.perfil_seguridad;
  const num = (k, a, b) => { if (k in n && Number.isFinite(+n[k])) out[k] = Math.max(a, Math.min(b, Math.round(+n[k]))); };
  num("busqueda_cada", 1, 10); num("dias_antiguedad", 1, 60); num("pausa_bloqueo_horas", 1, 72);
  if (Array.isArray(n.horario) && n.horario.length === 2 && n.horario.every(h => /^\d\d:\d\d$/.test(h))) out.horario = [...n.horario];
  if (n._debug && typeof n._debug === "object") out._debug = n._debug;          // solo para pruebas
  return out;
}

export function parsearGrupos(texto) {
  const out = [], visto = new Set();
  for (const linea of String(texto || "").split(/\r?\n/)) {
    const t = linea.trim();
    if (!t) continue;
    let url = t, nombre = "";
    const i = t.indexOf("|");                        // "url | Nombre del grupo"
    if (i > 0) { url = t.slice(0, i).trim(); nombre = t.slice(i + 1).trim(); }
    const id = idDe(url) || (/^[\w.-]+$/.test(url) && !RESERVADOS.has(url.toLowerCase()) ? url : null);
    if (!id || visto.has(id)) continue;
    visto.add(id);
    out.push({ id, nombre: (nombre || id).slice(0, 80), url: `https://www.facebook.com/groups/${id}/` });
  }
  return out;
}
