// background.js — el "capataz" del vigía (v3). Corre mientras Chrome esté abierto.
//
// Cómo trabaja, como una persona:
//  1. Entra a un grupo y lee su inicio (orden "Actividad reciente") unos minutos, bajando de a poco
//     hasta ~30 publicaciones.
//  2. Busca en el buscador del grupo tus palabras, una por una (~1 min cada una, hasta ~10 resultados).
//  3. Pasa un rato por el inicio de Facebook leyendo lo que aparece.
//  4. Descansa unos segundos y sigue con el siguiente grupo. Cada cierto rato toma un descanso largo.
//  Todos los tiempos, cantidades, descansos y topes se cambian en Configuración.
//
// Lo que lee: lo de hasta 2 días que parezca pega va a Solicitudes (aviso al celular); lo de 2 a 7 días
// va a "Para revisar"; lo más viejo se descarta. Si Facebook muestra login, verificación o bloqueo,
// se pausa solo. Nunca hace clic, nunca comenta, nunca da like, nunca escribe.

import { clasificarLote, probar } from "./gemini.js";
import { prefiltro, clasificarLocal, plantilla, norm } from "./filtro.js";

// ======================================================================= configuración
export const TIEMPOS_DEF = {
  grupo_min: 3, grupo_posts: 30,               // inicio del grupo: minutos y publicaciones a leer
  palabra_min: 1, palabra_posts: 10,           // cada búsqueda: minutos y resultados a leer
  palabras_por_grupo: 0,                       // 0 = todas las palabras del buscador en cada grupo
  fb_min: 2, fb_posts: 30, fb_cada: 1,         // inicio de Facebook después de cada N grupos (0 min = no)
  entre_pasos_seg: [5, 15],                    // pausa entre una búsqueda y otra (mín–máx)
  entre_grupos_seg: [20, 60],                  // pausa entre un grupo y el siguiente
  trabajo_min: 40, descanso_min: 10,           // trabaja ~40 min y descansa ~10 (con azar)
  max_grupos_hora: 8, max_grupos_dia: 80,
  max_busq_hora: 15, max_busq_dia: 120
};
const LIM = {
  grupo_min: [0.5, 30], grupo_posts: [5, 150], palabra_min: [0.5, 10], palabra_posts: [3, 50], palabras_por_grupo: [0, 30],
  fb_min: [0, 30], fb_posts: [5, 150], fb_cada: [1, 20], trabajo_min: [5, 600], descanso_min: [1, 240],
  max_grupos_hora: [1, 20], max_grupos_dia: [1, 300], max_busq_hora: [0, 40], max_busq_dia: [0, 400]
};
export const FECHAS_DEF = { horas_util: 48, dias_revisar: 7 };

const KW_BUSCAR_DEF = ["gasfiter", "electricista", "maestro", "eléctrico", "sin luz", "fuga", "califont", "busco maestro"];
const KW_INICIO_DEF = ["electricista", "gasfiter", "gasfíter", "eléctrico", "maestro", "enchufe", "sin luz", "se cortó la luz",
  "fuga", "califont", "calefont", "filtración", "destape", "cortocircuito", "tablero", "medidor", "cañería"];
const KW_V1 = ["busco", "necesito", "electrico", "electricista", "gasfiter", "gasfitero", "maestro", "se corto la luz", "sin luz",
  "fuga de gas", "califont", "enchufe", "cortocircuito", "instalacion electrica", "cambiar", "reparar", "arreglar luz"];
const KW_V2 = ["busco", "eléctrico", "electricista", "gasfiter", "maestro", "sin luz", "fuga", "califont",
  "enchufe", "cortocircuito", "necesito electricista", "necesito gasfiter", "filtración", "destape"];

export const CONFIG_DEF = {
  version: 4,
  activo: false,
  gemini_key: "", gemini_endpoint: "auto", modelos: ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest"],
  grupos: [],                         // [{id, nombre, url, palabras?:[...] (propias del buscador)}]
  kw_buscar: KW_BUSCAR_DEF.map(p => ({ p, on: true })),     // se escriben en el buscador de cada grupo
  kw_inicio: KW_INICIO_DEF.map(p => ({ p, on: true })),     // se buscan dentro de las publicaciones que lee
  keywords_aprendidas: [],            // [{frase, veces, estado:'propuesta'|'activa'|'descartada'}]
  usar_reglas: true,                  // además de tus palabras, las reglas del vigía (oficio + alguien pidiendo)
  rondas_activa: true,                // recorrer los grupos solo
  ver_grupo: true,                    // leer el inicio de cada grupo
  buscar_palabras: true,              // usar el buscador del grupo
  orden_grupo: "RECENT_ACTIVITY",     // "RECENT_ACTIVITY" (actividad reciente) | "CHRONOLOGICAL" (publicaciones nuevas)
  orden_pasos: "inicio_primero",      // "inicio_primero" | "buscar_primero"
  busqueda_reciente: false,           // experimental: pedir resultados ordenados por fecha
  feed_activo: true,                  // leer lo que ves tú cuando navegas Facebook
  horario: ["07:30", "23:30"],
  pausa_bloqueo_horas: 24,
  ventana_aparte: true,               // una ventana del vigía a la vista (así Facebook carga las publicaciones)
  tiempos: { ...TIEMPOS_DEF },
  fechas: { ...FECHAS_DEF },
  ntfy_tema: "", webhook_url: "",
  mi_nombre: "", mi_rubro: "electricidad y gasfitería", mi_zona: "", mi_fono: "", plantilla: ""
};

const ESTADO_DEF = {
  vigiaTab: null, vigiaWin: null, pendiente: null, plan: null, ultima: 0, proxima: 0, actual: { accion: "pausado" },
  sesion_inicio: 0, sesion_largo: 0, descanso_hasta: 0, pausa_hasta: 0, pausa_motivo: "",
  kw_idx: 0, n_grupo: 0, cola_pausa_hasta: 0, cola_fallos: 0,
  vacios_seguidos: 0, sin_resp_seguidos: 0, ocultos_seguidos: 0, importTab: null, importacion: null
};
const USO_DEF = () => ({ dia: "", g_dia: 0, b_dia: 0, p_dia: 0, mg: [], mb: [] });
const CONT_DEF = () => ({ grupos: 0, pasos: 0, vistos: 0, pegas: 0, revisar: 0 });

const RESERVADOS = new Set(["joins", "feed", "discover", "create", "search", "notifications", "your_groups", "joined", "learning_content", "membership"]);
const REPOSO = () => chrome.runtime.getURL("reposo.html");
const ICONO = () => chrome.runtime.getURL("iconos/128.png");

// ======================================================================= almacenamiento con candado
const get = async (k, def) => (await chrome.storage.local.get(k))[k] ?? def;
const set = (o) => chrome.storage.local.set(o);
let cadena = Promise.resolve();
function exclusivo(fn) { const p = cadena.then(() => fn()); cadena = p.catch(() => {}); return p; }
function mutar(clave, def, fn) {
  return exclusivo(async () => { const v = await get(clave, def); const r = await fn(v); if (r !== false) await set({ [clave]: v }); return r; });
}

const aLista = (arr) => (Array.isArray(arr) ? arr : []).map(x => typeof x === "string" ? { p: x, on: true } : { p: String(x?.p || ""), on: x?.on !== false })
  .filter(x => x.p.trim()).map(x => ({ p: x.p.trim().slice(0, 40), on: x.on }));

function migrar(raw) {
  const c = { ...CONFIG_DEF, ...(raw || {}) };
  const v = raw ? (raw.version || 1) : 4;
  if (raw && v < 4) {
    let kws = Array.isArray(raw.keywords) ? raw.keywords : KW_BUSCAR_DEF;
    if (JSON.stringify(kws) === JSON.stringify(KW_V1) || JSON.stringify(kws) === JSON.stringify(KW_V2)) kws = KW_BUSCAR_DEF;
    c.kw_buscar = aLista(kws);
    c.kw_inicio = aLista(KW_INICIO_DEF);
    for (const a of raw.keywords_aprendidas || []) if (a?.estado === "activa" && a.frase) c.kw_inicio.push({ p: a.frase, on: true });
    if (v < 3 && (!raw.horario || (raw.horario[0] === "08:00" && raw.horario[1] === "23:00"))) c.horario = [...CONFIG_DEF.horario];
    c.ver_grupo = raw.ver_recientes !== false;
    c.fechas = { ...FECHAS_DEF, dias_revisar: Math.max(2, Math.min(30, +raw.dias_antiguedad || 7)) };
    c.tiempos = { ...TIEMPOS_DEF };
    if (c.kw_buscar.length > 6) c.tiempos.palabras_por_grupo = 3;     // muchas palabras: 3 por grupo, rotando (cuida el tope)
    c.ventana_aparte = true;
    c.modelos = CONFIG_DEF.modelos;
    for (const k of ["keywords", "perfil_seguridad", "busqueda_cada", "ver_recientes", "dias_antiguedad", "minutos_entre", "solo_recientes_dias"]) delete c[k];
  }
  c.kw_buscar = aLista(c.kw_buscar); c.kw_inicio = aLista(c.kw_inicio);
  c.tiempos = { ...TIEMPOS_DEF, ...(c.tiempos || {}) };
  c.fechas = { ...FECHAS_DEF, ...(c.fechas || {}) };
  if (!["RECENT_ACTIVITY", "CHRONOLOGICAL"].includes(c.orden_grupo)) c.orden_grupo = "RECENT_ACTIVITY";
  c.version = 4;
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
function patch(x) {        // patch(obj) o patch(fn); si fn devuelve false no se escribe
  return exclusivo(async () => {
    const s = await estado();
    const r = typeof x === "function" ? await x(s) : Object.assign(s, x);
    if (r !== false) await set({ estado: s });
    return s;
  });
}

// tiempos con límites sanos (aunque en Configuración pongan algo extremo)
function tiempos(c) {
  const t = { ...TIEMPOS_DEF, ...(c.tiempos || {}) };
  for (const [k, [a, b]] of Object.entries(LIM)) t[k] = Math.max(a, Math.min(b, Number.isFinite(+t[k]) ? +t[k] : TIEMPOS_DEF[k]));
  for (const k of ["entre_pasos_seg", "entre_grupos_seg"]) {
    const [mn, mx] = k === "entre_pasos_seg" ? [2, 300] : [5, 1800];
    let [x, y] = Array.isArray(t[k]) ? t[k].map(Number) : TIEMPOS_DEF[k];
    x = Math.max(mn, Math.min(mx, x || TIEMPOS_DEF[k][0])); y = Math.max(x, Math.min(mx, y || x));
    t[k] = [x, y];
  }
  t.escala = +c._debug?.escala || 1;                  // solo para pruebas (acelera todo)
  return t;
}
function fechas(c) {
  const f = { ...FECHAS_DEF, ...(c.fechas || {}) };
  f.horas_util = Math.max(1, Math.min(168, +f.horas_util || 48));
  f.dias_revisar = Math.max(f.horas_util / 24, Math.min(30, +f.dias_revisar || 7));
  return f;
}

// ======================================================================= utilidades
const dos = (n) => String(n).padStart(2, "0");
const hoyStr = (d = new Date()) => `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
const horaCorta = (t) => { const d = new Date(t); return `${dos(d.getHours())}:${dos(d.getMinutes())}`; };
const azar = (a, b) => a + Math.random() * (b - a);
const llaveOk = (c) => !!c.gemini_key && !c.gemini_key.startsWith("PEGA") && c.gemini_key.length > 20;
const minTxt = (ms) => { const s = Math.round(ms / 1000); return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${dos(s % 60)} min`; };
const escRx = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function dentroHorario(c, d = new Date()) {
  const h = `${dos(d.getHours())}:${dos(d.getMinutes())}`;
  const [a, b] = c.horario?.length === 2 ? c.horario : ["00:00", "23:59"];
  return a <= b ? (h >= a && h <= b) : (h >= a || h <= b);     // también si cruza la medianoche
}
function idDe(url) {
  const m = String(url || "").match(/facebook\.com\/groups\/([^/?#]+)/i);
  return m && !RESERVADOS.has(m[1].toLowerCase()) ? m[1] : null;
}
const urlGrupo = (id) => `https://www.facebook.com/groups/${id}/`;
const activas = (lista) => aLista(lista).filter(x => x.on).map(x => x.p);
function palabrasBuscar(c, g) {
  const propias = Array.isArray(g?.palabras) ? g.palabras.filter(Boolean) : [];
  return propias.length ? propias : activas(c.kw_buscar);
}
function coincidencias(texto, c) {
  const n = norm(texto);
  const vistas = new Set();
  return activas(c.kw_inicio).filter(w => {
    const k = norm(w).trim();
    if (!k || vistas.has(k)) return false;
    vistas.add(k);
    return k.includes(" ") ? n.includes(k) : new RegExp(`(^|[^a-z0-9])${escRx(k)}`).test(n);
  });
}
function nombreGrupo(c, url) {
  const id = idDe(url);
  if (!id) return "Inicio de Facebook";
  return (c.grupos || []).find(x => x.id === id)?.nombre || id;
}
function clave(p) {                // el mismo post puede venir con links distintos
  const u = p.url || "";
  const m = u.match(/(?:posts|permalink)\/(\d+)/) || u.match(/story_fbid=(\d+)/) || u.match(/\/posts\/([\w]+)/);
  if (m) return "post:" + m[1];
  return "txt:" + norm(p.autor || "").slice(0, 40) + "|" + norm(p.texto || "").replace(/\s+/g, " ").slice(0, 120);
}
const huellaLead = (p) => norm(p.autor || "").trim() + "|" + norm(p.texto || "").replace(/[^a-z0-9]+/g, " ").trim().slice(0, 140);
function messengerDe(autorUrl) {
  const u = String(autorUrl || "");
  const m = u.match(/\/user\/(\d+)/) || u.match(/profile\.php\?id=(\d+)/) || u.match(/facebook\.com\/(\d{6,})\/?$/);
  if (m) return `https://www.facebook.com/messages/t/${m[1]}`;
  const v = u.match(/facebook\.com\/([A-Za-z0-9.]{3,})\/?$/);
  if (v && !/^(groups|profile\.php|people|pages|watch|marketplace|events)$/i.test(v[1])) return `https://m.me/${v[1]}`;
  return "";
}
function edadTxt(h) {
  if (h == null) return "fecha ?";
  if (h < 1) return `hace ${Math.max(1, Math.round(h * 60))} min`;
  if (h < 24) return `hace ${Math.round(h)} h`;
  return `hace ${Math.round(h / 24)} d`;
}

// ======================================================================= bitácora y avisos
const ultimosLogs = new Map();
async function anota(tipo, texto, det) {
  console.log("[vigía]", tipo, texto);
  await mutar("bitacora", [], b => {
    b.unshift({ t: Date.now(), tipo, texto, ...(det?.length ? { det: det.slice(0, 60) } : {}) });
    if (b.length > 400) b.length = 400;
  });
}
async function anotaUnaVez(tipo, texto, ms = 30 * 60000) {
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
    const r = await fetch("https://ntfy.sh/", { method: "POST",
      body: JSON.stringify({ topic: c.ntfy_tema, title: titulo, message: mensaje, tags, priority: 4, ...(click ? { click } : {}) }) });
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
  const antes = await get("config", null);
  await mutarConfig(() => {});                      // guarda la config ya migrada
  for (const [k, def] of [["leads", []], ["vistos", {}], ["bitacora", []], ["mirados", []], ["cola", []], ["gstats", {}]]) {
    if ((await get(k, null)) === null) await set({ [k]: def });
  }
  await chrome.alarms.clear("ronda");
  await patch({ pendiente: null, plan: null, sesion_inicio: 0 });
  asegurarReloj();
  await actualizarBadge();
  await anota("info", `Vigía v${chrome.runtime.getManifest().version} instalado/actualizado.`);
  if (antes && (antes.version || 1) < 4) {
    const c4 = await cfg();
    await anota("info", "Nuevo: ahora entra a cada grupo y se queda leyendo como una persona (inicio del grupo → tus palabras en el buscador → inicio de Facebook). Usa una ventana aparte del vigía: déjala a la vista para que Facebook cargue las publicaciones." +
      (c4.tiempos.palabras_por_grupo ? ` Tienes ${c4.kw_buscar.length} palabras para el buscador: busco ${c4.tiempos.palabras_por_grupo} por grupo, rotando, para no pasar el tope de búsquedas (en Configuración pon 0 para buscarlas todas).` : ""));
  }
  if (det?.reason === "install" || det?.reason === "update") abrirPanel().catch(() => {});
  tick();
});
chrome.runtime.onStartup.addListener(async () => {
  await patch(s => { s.pendiente = null; s.plan = null; s.vigiaTab = null; s.vigiaWin = null; s.sesion_inicio = 0; });
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

chrome.tabs.onRemoved.addListener((tabId) => {
  patch(s => {
    if (s.importTab === tabId) { s.importTab = null; if (s.importacion && !s.importacion.fin) s.importacion.fin = true; return; }
    if (s.vigiaTab !== tabId) return false;
    s.vigiaTab = null;
    if (s.pendiente) { s.pendiente = null; s.plan = null; s.proxima = Date.now() + 60000; s.actual = { accion: "esperando", hasta: s.proxima, desde: Date.now() }; }
  });
});
chrome.windows.onRemoved.addListener((wid) => { patch(s => { if (s.vigiaWin !== wid) return false; s.vigiaWin = null; }); });

// ======================================================================= el reloj
let tickCorriendo = false, forzarPendiente = false, timer = null;
function programar(ms) { clearTimeout(timer); timer = setTimeout(() => tick(), Math.max(200, ms)); }
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
  const T = tiempos(c);
  const E = T.escala;
  const now = Date.now();
  const st = await estado();

  // 1) hay un paso en curso: esperar al lector (su tiempo + margen)
  if (st.pendiente) {
    const limite = Math.max(st.pendiente.dur * 1.5, st.pendiente.dur + 45000);
    if (now - st.pendiente.t < limite) return;
    await terminarPaso(`${st.pendiente.grupo || "Facebook"}: la página no respondió a tiempo`, { sinRespuesta: true });
    return;
  }
  procesarCola();

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
  if (!c.ver_grupo && !(c.buscar_palabras && activas(c.kw_buscar).length) && !T.fb_min) return setActual({ accion: "sin_datos", falta: "modo" });
  if (navigator.onLine === false) return setActual({ accion: "sin_internet" }, ["info", "Sin internet. Espero."]);

  const u = st.uso;
  if (u.dia !== hoyStr()) { u.dia = hoyStr(); u.g_dia = 0; u.b_dia = 0; u.p_dia = 0; }
  u.mg = u.mg.filter(t => now - t < 3600000);
  u.mb = u.mb.filter(t => now - t < 3600000);

  let plan = st.plan && st.plan.i < st.plan.pasos.length ? st.plan : null;

  // 3) entre grupos: descansos, topes y elegir el siguiente grupo
  if (!plan) {
    if (!forzar) {
      if (st.descanso_hasta > now) return setActual({ accion: "descanso", hasta: st.descanso_hasta });
      const largo = T.trabajo_min * azar(0.75, 1.25) * 60000 * E;
      if (!st.sesion_inicio || now - (st.ultima || 0) > T.descanso_min * 60000 * E) {
        await patch({ sesion_inicio: now, sesion_largo: largo });
      } else if (now - st.sesion_inicio > (st.sesion_largo || largo)) {
        const hasta = now + T.descanso_min * azar(0.7, 1.4) * 60000 * E;
        await patch({ descanso_hasta: hasta, sesion_inicio: 0 });
        return setActual({ accion: "descanso", hasta },
          ["descanso", `Llevo ${Math.round((now - st.sesion_inicio) / 60000)} min mirando grupos: descanso hasta las ${horaCorta(hasta)}, como haría una persona.`]);
      }
    }
    if (u.mg.length >= T.max_grupos_hora) {
      const hasta = Math.min(...u.mg) + 3600000;
      await patch({ uso: u });
      return setActual({ accion: "limite_hora", hasta }, ["seguridad", `Llegué al máximo de grupos de esta hora (${T.max_grupos_hora}). Sigo a las ${horaCorta(hasta)}.`]);
    }
    if (u.g_dia >= T.max_grupos_dia) {
      await patch({ uso: u });
      return setActual({ accion: "limite_dia" }, ["seguridad", `Llegué al máximo de grupos de hoy (${T.max_grupos_dia}). Mañana sigo.`]);
    }
  }

  // 4) espaciado (entre pasos o entre grupos)
  if (forzar) {
    const minimo = (st.ultima || 0) + (c._debug?.piso_ms ?? 20000);
    if (now < minimo) { await patch({ proxima: minimo }); programar(minimo - now + 100); return setActual({ accion: "esperando", hasta: minimo }); }
  } else if (now < (st.proxima || 0)) {
    programar(st.proxima - now + 100);
    return setActual({ accion: plan ? "entre_pasos" : "esperando", hasta: st.proxima, grupo: plan?.grupo });
  }

  // 5) armar el plan del siguiente grupo
  if (!plan) {
    const gstats = await get("gstats", {});
    const g = elegirGrupo(c, gstats, now);
    if (!g) return setActual({ accion: "sin_datos", falta: "acceso" });
    plan = armarPlan(c, T, st, g, u, now);
    u.mg.push(now); u.g_dia++;
    await patch(s => { s.plan = plan; s.uso = u; s.n_grupo = (s.n_grupo || 0) + 1; s.cont.grupos++;
      if (plan.rotar) s.kw_idx = (s.kw_idx || 0) + plan.rotar; });
    await mutar("gstats", {}, gs => { const x = gs[g.id] ||= {}; x.visitas = (x.visitas || 0) + 1; x.ultima = now; });
    const desc = plan.pasos.map(p => p.tipo === "grupo" ? `inicio del grupo ${minTxt(p.dur)}` : p.tipo === "buscar" ? `“${p.palabra}”` : `inicio de Facebook ${minTxt(p.dur)}`).join(" → ");
    await anota("grupo", `Entro a ${g.nombre}: ${desc}${plan.omitidas ? ` (${plan.omitidas} palabras quedan para después: tope de búsquedas)` : ""}`);
  }

  // 6) ejecutar el paso que toca
  const paso = plan.pasos[plan.i];
  if (paso.tipo === "buscar" && (u.mb.length >= T.max_busq_hora || u.b_dia >= T.max_busq_dia)) {
    await anota("seguridad", `Salto la búsqueda “${paso.palabra}” en ${plan.grupo}: llegué al tope de búsquedas (${u.mb.length >= T.max_busq_hora ? "esta hora" : "hoy"}).`);
    await patch(s => { if (s.plan) s.plan.i++; s.uso = u; });
    programar(500);
    return;
  }
  const dur = Math.round(paso.dur * azar(0.9, 1.15));
  if (paso.tipo === "buscar") { u.mb.push(now); u.b_dia++; }
  u.p_dia++;
  const pid = "P" + now.toString(36) + Math.floor(Math.random() * 1e4).toString(36);
  await patch(s => {
    s.pendiente = { id: pid, t: now, dur, objetivo: paso.objetivo, tipo: paso.tipo, palabra: paso.palabra || "", url: paso.url,
      grupoId: plan.grupoId, grupo: plan.grupo, tabId: null, vistos: 0, visible: "",
      res: { total: 0, ya: 0, recientes: 0, semana: 0, viejas: 0, candidatas: 0, revisar: 0 }, det: [] };
    s.uso = u; s.cont.pasos++;
    s.actual = { accion: paso.tipo === "buscar" ? "buscando" : paso.tipo === "grupo" ? "leyendo_grupo" : "leyendo_fb",
      grupo: plan.grupo, palabra: paso.palabra || "", desde: now, hasta: now + dur, paso: plan.i + 1, de: plan.pasos.length };
  });
  let tabId;
  try { tabId = await pestanaVigia(c, paso.url); }
  catch (e) {
    await patch({ pendiente: null, plan: null, vigiaTab: null, proxima: now + 60000 });
    await anota("error", "No pude abrir la ventana/pestaña del vigía: " + e.message);
    return;
  }
  await patch(s => { s.vigiaTab = tabId; if (s.pendiente?.id === pid) s.pendiente.tabId = tabId; });
  await anota(paso.tipo === "buscar" ? "ronda" : paso.tipo === "grupo" ? "recientes" : "inicio",
    paso.tipo === "buscar" ? `Busco “${paso.palabra}” en ${plan.grupo} (${minTxt(dur)}, hasta ${paso.objetivo} resultados)`
    : paso.tipo === "grupo" ? `Leo el inicio de ${plan.grupo} — ${c.orden_grupo === "CHRONOLOGICAL" ? "publicaciones nuevas" : "actividad reciente"} (${minTxt(dur)}, ~${paso.objetivo} publicaciones)`
    : `Leo el inicio de Facebook (${minTxt(dur)}, ~${paso.objetivo} publicaciones)`);
  programar(Math.max(dur * 1.5, dur + 45000) + 2000);       // por si el lector no contesta
}

function urlBusqueda(gid, palabra, reciente) {
  let u = `https://www.facebook.com/groups/${gid}/search/?q=${encodeURIComponent(palabra)}`;
  if (reciente) {
    const f = btoa(JSON.stringify({ "rp_chrono_sort:0": JSON.stringify({ name: "chronosort", args: "" }) }));
    u += "&filters=" + encodeURIComponent(f);
  }
  return u;
}

function armarPlan(c, T, st, g, u, now) {
  const E = T.escala;
  const pasos = [];
  const inicio = { tipo: "grupo", url: `${urlGrupo(g.id)}?sorting_setting=${c.orden_grupo}`, dur: T.grupo_min * 60000 * E, objetivo: T.grupo_posts };
  let pal = c.buscar_palabras ? palabrasBuscar(c, g) : [];
  let rotar = 0;
  if (T.palabras_por_grupo > 0 && pal.length > T.palabras_por_grupo) {
    const k = (st.kw_idx || 0) % pal.length;
    pal = [...pal.slice(k), ...pal.slice(0, k)].slice(0, T.palabras_por_grupo);
    rotar = T.palabras_por_grupo;
  }
  const cupo = Math.max(0, Math.min(T.max_busq_hora - u.mb.length, T.max_busq_dia - u.b_dia));
  const usar = pal.slice(0, cupo);
  const busq = usar.map(w => ({ tipo: "buscar", palabra: w, url: urlBusqueda(g.id, w, c.busqueda_reciente), dur: T.palabra_min * 60000 * E, objetivo: T.palabra_posts }));
  if (c.ver_grupo && c.orden_pasos !== "buscar_primero") pasos.push(inicio);
  pasos.push(...busq);
  if (c.ver_grupo && c.orden_pasos === "buscar_primero") pasos.push(inicio);
  if (!pasos.length) pasos.push(inicio);                 // sin búsquedas posibles: al menos el inicio
  if (T.fb_min > 0 && ((st.n_grupo || 0) % T.fb_cada === T.fb_cada - 1 || T.fb_cada === 1)) {
    pasos.push({ tipo: "facebook", url: "https://www.facebook.com/", dur: T.fb_min * 60000 * E, objetivo: T.fb_posts });
  }
  return { grupoId: g.id, grupo: g.nombre, pasos, i: 0, t: now, omitidas: pal.length - usar.length, rotar };
}

// prioridad: los que llevan más rato sin mirar y los que más pegas han dado.
// Un grupo mirado hace menos de 1 hora no se repite mientras haya otros disponibles (una persona no vuelve al tiro).
function elegirGrupo(c, gstats, now) {
  const cands = [];
  for (const g of c.grupos) {
    const s = gstats[g.id] || {};
    if (s.sin_acceso && now - s.sin_acceso < 7 * 86400000) continue;
    const min = s.ultima ? (now - s.ultima) / 60000 : 1e6;
    cands.push({ g, min, pts: min * (1 + 0.6 * Math.min(s.pegas || 0, 8)) * azar(0.85, 1.15) });
  }
  const descansados = cands.filter(x => x.min >= 60);
  const pool = descansados.length ? descansados : cands;
  let mejor = null;
  for (const x of pool) if (!mejor || x.pts > mejor.pts) mejor = x;
  return mejor?.g || null;
}

// la ventana (o pestaña fija) del vigía: siempre la misma, silenciada
async function pestanaVigia(c, url) {
  const st = await estado();
  const opts = { url, muted: true, autoDiscardable: false };
  if (st.vigiaTab != null) {
    try {
      const t = await chrome.tabs.get(st.vigiaTab);
      const enVentana = st.vigiaWin != null && t.windowId === st.vigiaWin;
      if (!!c.ventana_aparte === enVentana) { await chrome.tabs.update(t.id, opts); return t.id; }
      await chrome.tabs.remove(t.id).catch(() => {});      // cambió el modo: se rehace
    } catch {}
  }
  if (!c.ventana_aparte) {
    const quedadas = (await chrome.tabs.query({})).filter(t => (t.url || t.pendingUrl || "").startsWith(REPOSO()));
    if (quedadas.length) {
      const [t, ...resto] = quedadas;
      for (const r of resto) chrome.tabs.remove(r.id).catch(() => {});
      await chrome.tabs.update(t.id, { ...opts, pinned: true });
      await patch({ vigiaWin: null });
      return t.id;
    }
    const t = await chrome.tabs.create({ url, active: false, pinned: true, index: 0 });
    await chrome.tabs.update(t.id, { muted: true, autoDiscardable: false });
    await patch({ vigiaWin: null });
    return t.id;
  }
  if (st.vigiaWin != null) {                       // ventana del vigía ya abierta: usar su pestaña
    try {
      const w = await chrome.windows.get(st.vigiaWin, { populate: true });
      if (w?.tabs?.length) { await chrome.tabs.update(w.tabs[0].id, opts); return w.tabs[0].id; }
    } catch {}
  }
  const w = await chrome.windows.create({ url, focused: false, width: 900, height: 760, type: "normal" });
  const t = w.tabs[0];
  await chrome.tabs.update(t.id, { muted: true, autoDiscardable: false });
  await patch({ vigiaWin: w.id });
  return t.id;
}
async function cerrarVigia() {
  const st = await estado();
  if (st.pendiente) return;
  if (st.vigiaTab != null) { try { await chrome.tabs.remove(st.vigiaTab); } catch {} }
  for (const t of (await chrome.tabs.query({})).filter(t => (t.url || "").startsWith(REPOSO()))) chrome.tabs.remove(t.id).catch(() => {});
  await patch({ vigiaTab: null, vigiaWin: null });
}

// cierra el paso en curso, anota el resumen y deja listo el siguiente (o el siguiente grupo)
async function terminarPaso(texto, { sinRespuesta = false, tipoLog = "resultado", det = null, cancelar = false } = {}) {
  const c = await cfg();
  const T = tiempos(c);
  const now = Date.now();
  let tabId = null, finGrupo = false;
  const st = await patch(s => {
    tabId = s.vigiaTab;
    s.pendiente = null;
    if (s.plan) { s.plan.i++; if (cancelar || s.plan.i >= s.plan.pasos.length) { s.plan = null; finGrupo = true; } }
    else finGrupo = true;
    const [a, b] = finGrupo ? T.entre_grupos_seg : T.entre_pasos_seg;
    let espera = azar(a, b) * 1000 * T.escala;
    if (finGrupo && Math.random() < 0.1) espera *= azar(1.5, 2.5);       // a veces se "distrae" más rato
    s.ultima = now;
    s.proxima = now + espera;
    s.actual = { accion: finGrupo ? "esperando" : "entre_pasos", hasta: s.proxima, desde: now, grupo: s.plan?.grupo };
    s.sin_resp_seguidos = sinRespuesta ? (s.sin_resp_seguidos || 0) + 1 : 0;
  });
  if (finGrupo && tabId != null) { try { await chrome.tabs.update(tabId, { url: REPOSO() }); } catch {} }
  if (texto) await anota(sinRespuesta ? "error" : tipoLog, texto, det);
  if (st.sin_resp_seguidos >= 3) {
    await patch({ sin_resp_seguidos: 0, plan: null });
    await pausar("Facebook no cargó 3 veces seguidas (¿internet lento o caído?)", 10 * 60000, false);
    return;
  }
  programar(st.proxima - now + 200);
}

async function pausar(motivo, ms, avisar = true) {
  const hasta = Date.now() + ms;
  await patch(s => { s.pausa_hasta = Math.max(s.pausa_hasta || 0, hasta); s.pausa_motivo = motivo; s.sesion_inicio = 0; s.plan = null;
    s.actual = { accion: "pausa_seguridad", motivo, hasta: s.pausa_hasta, desde: Date.now() }; });
  const cuando = ms >= 3600000 ? `${Math.round(ms / 3600000)} h` : `${Math.round(ms / 60000)} min`;
  await anota("seguridad", `${motivo}. Me pauso ${cuando} (hasta las ${horaCorta(hasta)}) para cuidar tu cuenta.`);
  if (avisar) {
    await notificar("pausa" + Date.now(), "Vigía en pausa por seguridad", `${motivo}. Vuelvo solo en ${cuando}.`);
    await alCelular(await cfg(), "Vigía en pausa", `${motivo}. Vuelvo solo en ${cuando}.`, "", ["warning"]);
  }
}
// tras un aviso de Facebook: bajar los topes a la mitad
async function bajarRitmo() {
  let antes, despues;
  await mutarConfig(c => {
    const t = { ...TIEMPOS_DEF, ...(c.tiempos || {}) };
    antes = `${t.max_busq_hora} búsquedas y ${t.max_grupos_hora} grupos por hora`;
    t.max_busq_hora = Math.max(2, Math.floor(t.max_busq_hora / 2));
    t.max_grupos_hora = Math.max(2, Math.floor(t.max_grupos_hora / 2));
    despues = `${t.max_busq_hora} búsquedas y ${t.max_grupos_hora} grupos por hora`;
    c.tiempos = t;
  });
  if (antes !== despues) await anota("seguridad", `Bajé el ritmo por el aviso de Facebook: de ${antes} a ${despues} (lo puedes cambiar en Configuración).`);
}

// ======================================================================= mensajes
chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  (async () => {
    try {
      switch (msg?.tipo) {
        case "quien_soy": return responder(await quienSoy(sender));
        case "vigia_parcial": await alParcial(msg, sender); return responder({ ok: true });
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
  const p = st.pendiente;
  const esVigia = tab != null && tab === st.vigiaTab && !!p;     // cada página nueva de esa pestaña toma el paso en curso
  if (esVigia) {
    return { vigia: true, paso: { id: p.id, tipo: p.tipo, dur: Math.max(8000, p.dur - (Date.now() - p.t)), objetivo: p.objetivo } };
  }
  const importar = tab != null && tab === st.importTab && !st.importacion?.fin &&
    Date.now() - (st.importacion?.t || 0) < 15 * 60000 && /\/groups\/joins|\/login/.test(sender.tab.url || "");
  return { vigia: false, importar, inicio: tab !== st.vigiaTab && !importar && c.activo && c.feed_activo };
}

function ctxDe(p) {
  return { tipo: p.tipo, grupo: p.grupo, grupoId: p.grupoId,
    via: p.tipo === "buscar" ? "búsqueda: " + p.palabra : p.tipo === "grupo" ? "inicio del grupo" : "inicio de Facebook" };
}

async function alParcial(msg, sender) {
  const st = await estado();
  const p = st.pendiente;
  if (!p || sender?.tab?.id !== st.vigiaTab || (msg.pid && msg.pid !== p.id)) return;     // de un paso anterior: se ignora
  const r = await encolar(Array.isArray(msg.posts) ? msg.posts : [], ctxDe(p));
  await patch(s => {
    const x = s.pendiente;
    if (!x || x.id !== p.id) return false;
    for (const k of Object.keys(x.res)) x.res[k] += r.res[k] || 0;
    x.det = [...x.det, ...r.det].slice(-60);
    x.vistos = Math.max(x.vistos || 0, +msg.total || 0, x.res.total);
    x.visible = msg.visible || x.visible;
  });
  if (r.res.candidatas) procesarCola();
}

async function alListo(msg, sender) {
  const st = await estado();
  const p = st.pendiente;
  if (!p || sender?.tab?.id !== st.vigiaTab || (msg.pid && msg.pid !== p.id)) return;
  if (msg.posts?.length) await alParcial({ pid: msg.pid, posts: msg.posts, total: msg.pagina?.total }, sender);
  const c = await cfg();
  const pg = msg.pagina || {};
  const st2 = await estado();
  const res = st2.pendiente?.id === p.id ? st2.pendiente.res : p.res;
  const det = st2.pendiente?.id === p.id ? st2.pendiente.det : p.det;
  const donde = p.tipo === "buscar" ? `“${p.palabra}” en ${p.grupo}` : p.tipo === "grupo" ? `Inicio de ${p.grupo}` : "Inicio de Facebook";
  const gstat = (fn) => p.grupoId ? mutar("gstats", {}, gs => { fn(gs[p.grupoId] ||= {}); }) : Promise.resolve();

  switch (pg.estado) {
    case "login":
      await terminarPaso("", { cancelar: true });
      return pausar("Facebook pide iniciar sesión: abre Facebook en Chrome y entra con tu cuenta", 20 * 60000);
    case "checkpoint":
      await terminarPaso("", { cancelar: true });
      await bajarRitmo();
      return pausar("Facebook mostró una verificación de seguridad (resuélvela tú a mano)", c.pausa_bloqueo_horas * 3600000);
    case "bloqueo":
      if (p.tipo !== "facebook") await gstat(x => { x.ultimo_estado = "aviso de bloqueo"; });
      await terminarPaso("", { cancelar: true });
      await bajarRitmo();
      return pausar("Facebook mostró un aviso de bloqueo / “vas muy rápido”", c.pausa_bloqueo_horas * 3600000);
    case "sin_acceso":
      if (p.tipo !== "facebook") {
        await gstat(x => { x.sin_acceso = Date.now(); x.ultimo_estado = "sin acceso"; });
        return terminarPaso(`${p.grupo}: no tengo acceso (grupo privado o ya no estás). Lo salto 7 días.`, { tipoLog: "info", cancelar: true });
      }
      return terminarPaso("Inicio de Facebook: no cargó", { tipoLog: "info" });
    case "sin_resultados":
      await patch({ vacios_seguidos: 0 });
      return terminarPaso(`${donde} → sin resultados`);
  }

  const n = res.total;
  const oculto = !!pg.oculto;
  if (!n) {        // cargó pero no mostró publicaciones
    const s2 = await patch(s => { s.vacios_seguidos = (s.vacios_seguidos || 0) + 1; });
    if (p.tipo !== "facebook") await gstat(x => { x.fallos = (x.fallos || 0) + 1; x.ultimo_estado = "vacío"; });
    await terminarPaso(`${donde}: la página cargó pero no mostró publicaciones${oculto || pg.visible === "hidden" ? " (la ventana del vigía estaba tapada o en segundo plano)" : ""}`, { tipoLog: "info" });
    if (s2.vacios_seguidos >= 3 && !c.ventana_aparte && (pg.visible === "hidden" || c._debug?.oculta)) {
      await mutarConfig(x => { x.ventana_aparte = true; });
      await patch({ vacios_seguidos: 0 });
      await anota("info", "Facebook no está mostrando publicaciones en la pestaña escondida. Desde ahora uso una ventana aparte del vigía (déjala a la vista). Lo puedes cambiar en Configuración.");
    }
    return;
  }
  await patch(s => { s.vacios_seguidos = 0; s.ocultos_seguidos = oculto ? (s.ocultos_seguidos || 0) + 1 : 0; });
  if (p.tipo !== "facebook") await gstat(x => { x.ultimo_estado = "ok"; x.fallos = 0; x.sin_acceso = 0; x.vistas = (x.vistas || 0) + n; });
  const f = fechas(c);
  const partes = [
    res.recientes ? `${res.recientes} de las últimas ${f.horas_util} h` : "",
    res.semana ? `${res.semana} de hace 2–${Math.round(f.dias_revisar)} días` : "",
    res.viejas ? `${res.viejas} más viejas` : "",
    res.ya ? `${res.ya} ya vistas` : ""
  ].filter(Boolean).join(", ");
  const ia = res.candidatas ? ` · ${res.candidatas} parecen pega → IA${res.revisar ? ` (${res.revisar} para revisar)` : ""}` : "";
  const tapada = oculto ? " · ⚠️ ventana tapada: Facebook carga menos así" : "";
  await terminarPaso(`${donde} (${minTxt((pg.seg || 0) * 1000)}): ${n} publicaciones — ${partes || "sin detalle"}${ia}${tapada}`, { det });
  const s3 = await estado();
  if (s3.ocultos_seguidos === 3 && c.ventana_aparte) {
    await notificar("oculta" + Date.now(), "Deja la ventana del vigía a la vista", "Si está minimizada o tapada, Facebook no carga más publicaciones y el vigía ve muy pocas.");
  }
  procesarCola();
}

// lo que lees tú en el inicio o en los grupos (se resume cada minuto en la bitácora)
let feedAcum = { res: null, det: [], donde: new Set(), t: 0 };
async function alFeed(msg, sender) {
  const c = await cfg();
  if (!c.activo || !c.feed_activo) return;
  const st = await estado();
  if (sender?.tab?.id === st.vigiaTab) return;
  const grupo = nombreGrupo(c, msg.url);
  const r = await encolar(msg.posts || [], { tipo: "tu", via: "mientras navegabas", grupo, grupoId: idDe(msg.url) });
  if (!feedAcum.res) feedAcum.res = { total: 0, ya: 0, recientes: 0, semana: 0, viejas: 0, candidatas: 0, revisar: 0 };
  for (const k of Object.keys(feedAcum.res)) feedAcum.res[k] += r.res[k] || 0;
  feedAcum.det.push(...r.det.filter(d => d.v !== "ya")); feedAcum.donde.add(grupo);
  const nuevas = feedAcum.res.total - feedAcum.res.ya;
  if (nuevas && Date.now() - feedAcum.t > 60000) {
    const donde = [...feedAcum.donde].slice(0, 3).join(", ");
    await anota("inicio", `Mientras navegabas (${donde}): ${nuevas} publicaciones nuevas${feedAcum.res.candidatas ? `, ${feedAcum.res.candidatas} parecen pega → IA` : ""}`, feedAcum.det);
    feedAcum = { res: null, det: [], donde: new Set(), t: Date.now() };
  }
  if (r.res.candidatas) procesarCola();
}

async function alAlerta(msg) {
  const c = await cfg();
  const st = await estado();
  if (!c.activo || st.pausa_hasta > Date.now()) return;
  await pausar(msg.estado === "checkpoint" ? "Viste una verificación de Facebook mientras navegabas"
                                           : "Facebook te mostró un aviso de bloqueo mientras navegabas", c.pausa_bloqueo_horas * 3600000);
}

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
      const n = { id: g.id, nombre: g.nombre || g.id, url: urlGrupo(g.id) };
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

// ======================================================================= filtro de fechas y palabras → fila de la IA
// Por cada publicación: ¿ya la vi?, ¿qué tan nueva es?, ¿trae tus palabras o parece pedido?
async function encolar(posts, ctx) {
  const c = await cfg();
  const f = fechas(c);
  const now = Date.now();
  const res = { total: 0, ya: 0, recientes: 0, semana: 0, viejas: 0, candidatas: 0, revisar: 0 };
  const det = [], aCola = [], mir = [];
  const nuevos = new Set();
  const validos = posts.filter(p => p && typeof p.texto === "string" && p.texto.length >= 12);
  await mutar("vistos", {}, v => {
    for (const p of validos) { const k = clave(p); if (!v[k]) { v[k] = now; nuevos.add(p); } }
    const ks = Object.keys(v);
    if (ks.length > 20000) ks.sort((a, b) => v[a] - v[b]).slice(0, ks.length - 16000).forEach(k => delete v[k]);
  });
  for (const p of validos) {
    res.total++;
    const e = p.edad_h == null ? null : +p.edad_h;
    const d = { a: (p.autor || "").slice(0, 40), s: p.texto.replace(/\s+/g, " ").slice(0, 100), e: edadTxt(e), u: p.url || "" };
    if (!nuevos.has(p)) { res.ya++; det.push({ ...d, v: "ya" }); continue; }
    const grupo = ctx.tipo === "facebook" || ctx.tipo === "tu" ? (p.grupo_nombre || ctx.grupo) : ctx.grupo;
    const grupoId = ctx.tipo === "facebook" || ctx.tipo === "tu" ? (p.grupo_id || ctx.grupoId) : ctx.grupoId;
    const cx = { ...ctx, grupo, grupoId };
    if (e != null && e > f.dias_revisar * 24) { res.viejas++; det.push({ ...d, v: "vieja" }); mir.push(mirado(p, cx, "vieja")); continue; }
    const revisar = e != null && e > f.horas_util;
    if (revisar) res.semana++; else res.recientes++;
    const coincide = coincidencias(p.texto, c);
    const cand = coincide.length > 0 || (c.usar_reglas && prefiltro(p.texto, c));
    if (!cand) { det.push({ ...d, v: "no" }); mir.push(mirado(p, cx, "no")); continue; }
    res.candidatas++;
    if (revisar) res.revisar++;
    det.push({ ...d, v: revisar ? "revisar" : "ia", k: coincide.slice(0, 3) });
    aCola.push({ p: { ...p, texto: p.texto.slice(0, 1800) }, ctx: cx, t: now, revisar, coincide: coincide.slice(0, 5) });
  }
  if (aCola.length) await mutar("cola", [], q => { q.push(...aCola); if (q.length > 500) q.splice(0, q.length - 500); });
  if (mir.length) await anotarMirados(mir);
  if (nuevos.size) await patch(s => { s.cont.vistos += nuevos.size; });
  return { res, det };
}
function mirado(p, ctx, veredicto, resumen = "") {
  return { t: Date.now(), grupo: ctx.grupo || "", via: ctx.via || "", autor: p.autor || "", url: p.url || "", edad: edadTxt(p.edad_h ?? null),
           snippet: (resumen || p.texto || "").replace(/\s+/g, " ").slice(0, 110), veredicto };
}
async function anotarMirados(lista) {
  await mutar("mirados", [], m => { m.unshift(...lista.reverse()); if (m.length > 120) m.length = 120; });
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
      else { lote = cola.filter(x => now - x.t > 20 * 60000).slice(0, 60); if (!lote.length) return; }

      let resultados;
      if (iaLibre) {
        const r = await clasificarLote(c, lote.map(x => x.p.texto));
        if (r.error && r.limite) {
          const fx = (st.cola_fallos || 0) + 1;
          const min = Math.min(30, 2 ** fx);
          await patch({ cola_fallos: fx, cola_pausa_hasta: now + min * 60000 });
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
      } else resultados = lote.map(x => clasificarLocal(x.p.texto, c));

      const quitar = new Set(lote.map(x => clave(x.p)));
      await mutar("cola", [], q => { const resto = q.filter(x => !quitar.has(clave(x.p))); q.length = 0; q.push(...resto); });
      const mir = [];
      for (let i = 0; i < lote.length; i++) {
        const x = lote[i], r = resultados[i];
        mir.push(mirado(x.p, x.ctx, r.es_solicitud ? (x.revisar ? "revisar" : "pega") : "no", r.resumen));
        if (r.es_solicitud) {
          await guardarLead(x.p, r, x.ctx, x);
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

async function guardarLead(p, r, ctx, item = {}) {
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
      grupo: ctx.grupo || "", grupoId: ctx.grupoId || "", grupo_url: ctx.grupoId ? urlGrupo(ctx.grupoId) : "", via: ctx.via || "",
      autor: p.autor || "", autor_url: p.autor_url || "", messenger: messengerDe(p.autor_url),
      texto: (p.texto || "").slice(0, 1500), url: p.url || "",
      edad_h: p.edad_h ?? null, fecha_txt: p.fecha_txt || "",
      publicado: p.edad_h != null ? new Date(now - p.edad_h * 3600000).toISOString() : "",
      tipo: r.tipo || "", resumen: r.resumen || "", comuna: r.comuna || "", urgencia: r.urgencia || "media",
      mensaje: r.mensaje || "", sin_ia: !!r.sin_ia, coincide: item.coincide || [], otros_grupos: [],
      estado: item.revisar ? "revisar" : "nuevo"
    };
    L.unshift(nuevo);
    if (L.length > 3000) L.length = 3000;
  });
  if (!nuevo) {
    if (dup && dup.grupo !== ctx.grupo) await anotaUnaVez("pega", `${p.autor || "Alguien"} publicó lo mismo en ${ctx.grupo || "otro grupo"} (ya la tenías en Solicitudes).`, 6 * 3600000);
    return;
  }
  await patch(s => { if (nuevo.estado === "revisar") s.cont.revisar++; else s.cont.pegas++; });
  if (ctx.grupoId) await mutar("gstats", {}, gs => { const x = gs[ctx.grupoId] ||= {}; x.pegas = (x.pegas || 0) + 1; x.ultima_pega = now; });
  await actualizarBadge();
  const edad = edadTxt(nuevo.edad_h);
  if (nuevo.estado === "revisar") {
    await anota("pega", `📋 Para revisar (${edad}): ${nuevo.resumen || nuevo.texto.slice(0, 70)} — ${nuevo.autor || "?"} (${nuevo.grupo})`);
    return;
  }
  const c = await cfg();
  const recien = nuevo.edad_h != null && nuevo.edad_h <= 1;
  const lugar = nuevo.comuna ? ` · ${nuevo.comuna}` : "";
  const titulo = `${recien ? "🔥 Recién: " : "Pega: "}${nuevo.tipo}${lugar}${nuevo.urgencia === "alta" ? " · URGENTE" : ""}`;
  const cuerpo = `${nuevo.resumen || nuevo.texto.slice(0, 90)}\n${nuevo.autor} · ${nuevo.grupo} · ${edad}`;
  await anota("pega", `⚡ ${recien ? "RECIÉN " : ""}(${edad}) ${nuevo.resumen || nuevo.texto.slice(0, 70)} — ${nuevo.autor || "?"} (${nuevo.grupo})`);
  await notificar(nuevo.id, titulo, cuerpo, true);
  alCelular(c, titulo, cuerpo, nuevo.url);
  if (c.webhook_url) fetch(c.webhook_url, { method: "POST", mode: "no-cors", body: JSON.stringify(nuevo) }).catch(() => {});
}

// frases que delatan una solicitud: se proponen; si se repiten 3 veces (y son de 2+ palabras) pasan solas
// a tus palabras de inicio
async function aprender(frases) {
  if (!frases.length) return;
  await mutarConfig(c => {
    const base = new Set([...c.kw_inicio, ...c.kw_buscar].map(k => norm(k.p).trim()));
    const ap = c.keywords_aprendidas || (c.keywords_aprendidas = []);
    for (const f0 of frases) {
      const f = String(f0 || "").toLowerCase().replace(/\s+/g, " ").trim();
      if (f.length < 4 || f.length > 40 || base.has(norm(f))) continue;
      const ya = ap.find(x => norm(x.frase) === norm(f));
      if (ya) {
        ya.veces++;
        if (ya.estado === "propuesta" && ya.veces >= 3 && f.includes(" ") && c.kw_inicio.length < 80) {
          ya.estado = "activa"; c.kw_inicio.push({ p: f, on: true }); base.add(norm(f));
        }
      } else ap.push({ frase: f, veces: 1, estado: "propuesta" });
    }
    if (ap.length > 200) c.keywords_aprendidas = ap.sort((a, b) => b.veces - a.veces).slice(0, 200);
  });
}

// ======================================================================= órdenes del panel
const listaDe = (msg) => msg.lista === "buscar" ? "kw_buscar" : "kw_inicio";
async function comandoPanel(msg) {
  switch (msg.accion) {
    case "estado": {
      const c = await cfg();
      return { config: c, estado: await estado(), config_def: CONFIG_DEF, tiempos_def: TIEMPOS_DEF, fechas_def: FECHAS_DEF, lim: LIM, perfiles: { v3: true } };
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
    case "restaurar_tiempos": {
      await mutarConfig(c => { c.tiempos = { ...TIEMPOS_DEF }; c.fechas = { ...FECHAS_DEF }; });
      return { ok: true };
    }
    case "probar": return await probar(await cfg());
    case "probar_ntfy": {
      const r = await alCelular(await cfg(), "Vigía de pegas", "¡Funciona! Aquí te llegarán las pegas que encuentre.", "");
      return { ok: r.ok, detalle: r.ok ? "enviado ✓ revisa tu celular" : r.error };
    }
    case "forzar_ronda": await patch({ descanso_hasta: 0 }); tick(true); return { ok: true };
    case "saltar_grupo": {
      await patch(s => { if (s.plan) s.plan.i = s.plan.pasos.length - 1; });
      return { ok: true };
    }
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
      await mutarConfig(c => { const L = c[listaDe(msg)]; const s = new Set(L.map(k => norm(k.p))); for (const k of nuevas) if (!s.has(norm(k))) { L.push({ p: k, on: true }); s.add(norm(k)); } });
      return { ok: true };
    }
    case "kw_del": {
      await mutarConfig(c => {
        c[listaDe(msg)] = c[listaDe(msg)].filter(k => k.p !== msg.p);
        const a = (c.keywords_aprendidas || []).find(k => norm(k.frase) === norm(msg.p));
        if (a) a.estado = "descartada";
      });
      return { ok: true };
    }
    case "kw_toggle": {
      await mutarConfig(c => { const k = c[listaDe(msg)].find(x => x.p === msg.p); if (k) k.on = !k.on; });
      return { ok: true };
    }
    case "kw_edit": {
      const nuevo = String(msg.nuevo || "").trim().slice(0, 40);
      if (nuevo.length < 2) return { ok: false };
      await mutarConfig(c => { const k = c[listaDe(msg)].find(x => x.p === msg.p); if (k) k.p = nuevo; });
      return { ok: true };
    }
    case "kw_aprendida": {
      await mutarConfig(c => {
        const a = (c.keywords_aprendidas || []).find(x => x.frase === msg.frase);
        if (!a) return;
        a.estado = msg.estado;
        if (msg.estado === "activa" && !c.kw_inicio.some(k => norm(k.p) === norm(a.frase))) c.kw_inicio.push({ p: a.frase, on: true });
      });
      return { ok: true };
    }
    case "grupos_set": {
      const viejos = new Map((await cfg()).grupos.map(g => [g.id, g]));
      const grupos = parsearGrupos(msg.texto).map(g => viejos.get(g.id)?.palabras ? { ...g, palabras: viejos.get(g.id).palabras } : g);
      await mutarConfig(c => { c.grupos = grupos; });
      return { ok: true, n: grupos.length };
    }
    case "grupo_palabras": {
      const pal = (Array.isArray(msg.palabras) ? msg.palabras : String(msg.palabras || "").split(/[,;\n]/)).map(x => String(x).trim()).filter(x => x.length >= 2).slice(0, 30);
      await mutarConfig(c => { const g = c.grupos.find(x => x.id === msg.id); if (!g) return; if (pal.length) g.palabras = pal; else delete g.palabras; });
      return { ok: true };
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
      return { version: 3, fecha: new Date().toISOString(), config: sinLlave, leads: await get("leads", []), gstats: await get("gstats", {}) };
    }
    case "restaurar": {
      const d = msg.datos || {};
      if (!d.config || !Array.isArray(d.leads)) return { ok: false, error: "archivo no válido" };
      const dc = migrar(d.config);
      await mutarConfig(c => {
        const llave = c.gemini_key;
        Object.assign(c, limpiarConfig(dc), { gemini_key: llave });
        for (const k of ["grupos", "kw_buscar", "kw_inicio", "keywords_aprendidas"]) if (Array.isArray(dc[k])) c[k] = dc[k];
      });
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
  const bool = ["activo", "rondas_activa", "ver_grupo", "buscar_palabras", "busqueda_reciente", "feed_activo", "ventana_aparte", "usar_reglas"];
  const txt = ["gemini_key", "gemini_endpoint", "ntfy_tema", "webhook_url", "mi_nombre", "mi_rubro", "mi_zona", "mi_fono", "plantilla"];
  for (const k of bool) if (k in n) out[k] = !!n[k];
  for (const k of txt) if (k in n) out[k] = String(n[k] ?? "").trim().slice(0, k === "plantilla" ? 600 : 300);
  if ("ntfy_tema" in out) out.ntfy_tema = out.ntfy_tema.replace(/^https?:\/\/ntfy\.sh\//, "").replace(/[^\w-]/g, "").slice(0, 64);
  if ("webhook_url" in out && out.webhook_url && !/^https?:\/\//.test(out.webhook_url)) out.webhook_url = "";
  if ("gemini_endpoint" in out && !["auto", "aistudio", "vertex"].includes(out.gemini_endpoint)) out.gemini_endpoint = "auto";
  if (["RECENT_ACTIVITY", "CHRONOLOGICAL"].includes(n.orden_grupo)) out.orden_grupo = n.orden_grupo;
  if (["inicio_primero", "buscar_primero"].includes(n.orden_pasos)) out.orden_pasos = n.orden_pasos;
  if ("pausa_bloqueo_horas" in n && Number.isFinite(+n.pausa_bloqueo_horas)) out.pausa_bloqueo_horas = Math.max(1, Math.min(72, Math.round(+n.pausa_bloqueo_horas)));
  if (Array.isArray(n.horario) && n.horario.length === 2 && n.horario.every(h => /^\d\d:\d\d$/.test(h))) out.horario = [...n.horario];
  if (n.tiempos && typeof n.tiempos === "object") {
    const t = {};
    for (const k of Object.keys(TIEMPOS_DEF)) {
      if (!(k in n.tiempos)) continue;
      if (Array.isArray(TIEMPOS_DEF[k])) { const a = n.tiempos[k]; if (Array.isArray(a) && a.length === 2 && a.every(x => Number.isFinite(+x))) t[k] = a.map(Number); }
      else if (Number.isFinite(+n.tiempos[k])) { const [a, b] = LIM[k]; t[k] = Math.max(a, Math.min(b, +n.tiempos[k])); }
    }
    out.tiempos = { ...TIEMPOS_DEF, ...t };
  }
  if (n.fechas && typeof n.fechas === "object") {
    out.fechas = { horas_util: Math.max(1, Math.min(168, +n.fechas.horas_util || 48)), dias_revisar: Math.max(1, Math.min(30, +n.fechas.dias_revisar || 7)) };
  }
  if (n._debug && typeof n._debug === "object") out._debug = n._debug;          // solo para pruebas
  return out;
}

export function parsearGrupos(texto) {
  const out = [], visto = new Set();
  for (const linea of String(texto || "").split(/\r?\n/)) {
    const t = linea.trim();
    if (!t) continue;
    let url = t, nombre = "";
    const i = t.indexOf("|");
    if (i > 0) { url = t.slice(0, i).trim(); nombre = t.slice(i + 1).trim(); }
    const id = idDe(url) || (/^[\w.-]+$/.test(url) && !RESERVADOS.has(url.toLowerCase()) ? url : null);
    if (!id || visto.has(id)) continue;
    visto.add(id);
    out.push({ id, nombre: (nombre || id).slice(0, 80), url: urlGrupo(id) });
  }
  return out;
}
