// background.js — el "capataz" de la extensión. Corre siempre que Chrome está abierto.
//
// Qué hace:
//  - Ronda tus grupos LENTO (uno + una palabra por vez), entrando a la URL de búsqueda del grupo.
//  - Lee lo que el content.js saca de esa página (y del inicio/feed mientras navegas tú).
//  - Pasa cada post por Gemini: ¿es alguien pidiendo eléctrico/gasfíter? Si sí, lo guarda como
//    SOLICITUD con el mensaje listo, te avisa (notificación + contador), y aprende las frases nuevas.
//  - No repite: cada post queda marcado por su link.
//
// Ritmo = seguridad. Por defecto va MUY tranquilo para que Facebook te vea como una persona, no un robot.

import { clasificar, probar } from "./gemini.js";

const RECIENTES = "__recientes__";   // "palabra" especial = mirar el feed cronológico del grupo

const CONFIG_DEF = {
  activo: false,
  gemini_key: "",
  gemini_endpoint: "auto",
  modelos: ["gemini-2.5-flash", "gemini-2.5-flash-lite"],
  grupos: [],                 // [{id, nombre, url}]
  keywords: ["busco", "necesito", "electrico", "electricista", "gasfiter", "gasfitero", "maestro",
             "se corto la luz", "sin luz", "fuga de gas", "califont", "enchufe", "cortocircuito",
             "instalacion electrica", "cambiar", "reparar", "arreglar luz"],
  keywords_aprendidas: [],    // [{frase, veces, estado: 'propuesta'|'activa'|'descartada'}]
  minutos_entre: 2,           // cada cuánto hace una búsqueda (con un poco de azar encima)
  solo_recientes_dias: 10,
  ver_recientes: true,        // en cada grupo, mirar primero el feed cronológico (lo más nuevo)
  feed_activo: true,          // leer el inicio/grupos mientras navegas (riesgo cero)
  rondas_activa: true,        // hacer las búsquedas automáticas por grupo (lo que gasta "navegación")
  horario: ["08:00", "23:00"],
  webhook_url: "",            // opcional: POST del lead a tu bot de WhatsApp si algún día lo conectas
  mi_nombre: "", mi_rubro: "electricidad y gasfitería", mi_zona: "", mi_fono: "", plantilla: ""
};

const ESTADO_DEF = { g: 0, k: 0, vuelta: 0, ultima: 0, vigiaTab: null, pendiente: null };

// ----------------------------------------------------------------- almacenamiento
async function get(k, def) { return (await chrome.storage.local.get(k))[k] ?? def; }
async function set(obj) { return chrome.storage.local.set(obj); }
async function cfg() { return { ...CONFIG_DEF, ...(await get("config", {})) }; }
async function estado() { return { ...ESTADO_DEF, ...(await get("estado", {})) }; }

chrome.runtime.onInstalled.addListener(async () => {
  const c = await get("config", null);
  if (!c) await set({ config: CONFIG_DEF });
  if (!(await get("leads", null))) await set({ leads: [] });
  if (!(await get("vistos", null))) await set({ vistos: {} });
  if (!(await get("bitacora", null))) await set({ bitacora: [] });
  if (!(await get("mirados", null))) await set({ mirados: [] });
  programarRonda();
  await actualizarBadge();
});
chrome.runtime.onStartup?.addListener(() => programarRonda());

// abrir el panel al tocar el ícono
chrome.action.onClicked.addListener(() => abrirPanel());
async function abrirPanel() {
  const url = chrome.runtime.getURL("panel.html");
  const [ya] = await chrome.tabs.query({ url });
  if (ya) chrome.tabs.update(ya.id, { active: true });
  else chrome.tabs.create({ url });
}

// ----------------------------------------------------------------- utilidades
const dentroHorario = (c) => {
  const h = new Date().toTimeString().slice(0, 5);
  const [a, b] = c.horario || ["00:00", "23:59"];
  return h >= a && h <= b;
};
function idDe(url) {
  const m = String(url || "").match(/facebook\.com\/groups\/([^/?#]+)/i);
  return m ? m[1] : null;
}
function permalink(p) {
  return (p.url || "").split("?")[0].replace(/\/$/, "") || ("txt:" + (p.autor || "") + ":" + (p.texto || "").slice(0, 80));
}
async function yaVisto(link) {
  const v = await get("vistos", {});
  return !!v[link];
}
async function marcarVisto(link) {
  const v = await get("vistos", {});
  v[link] = Date.now();
  // no dejar crecer infinito: deja los 8000 más nuevos
  const ks = Object.keys(v);
  if (ks.length > 8000) {
    ks.sort((a, b) => v[a] - v[b]).slice(0, ks.length - 8000).forEach(k => delete v[k]);
  }
  await set({ vistos: v });
}

// ----------------------------------------------------------------- bitácora (lo que va haciendo)
async function anota(tipo, texto) {
  const b = await get("bitacora", []);
  b.unshift({ t: Date.now(), tipo, texto });
  await set({ bitacora: b.slice(0, 400) });
}
async function anotaMirado(e) {
  const m = await get("mirados", []);
  m.unshift(e);
  await set({ mirados: m.slice(0, 80) });
}
async function fijarActual(actual) {
  const st = await estado();
  await set({ estado: { ...st, actual } });
}

// ----------------------------------------------------------------- rondas (búsqueda grupo x palabra)
function programarRonda() {
  chrome.alarms.create("ronda", { delayInMinutes: 0.2, periodInMinutes: 1 });
}
programarRonda();   // asegura el reloj cada vez que arranca el service worker (aunque Chrome lo haya dormido)
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "ronda") tick().catch(e => console.warn("[vigía] tick", e)); });

async function tick() {
  const c = await cfg();
  const st = await estado();
  if (!c.activo || !c.rondas_activa) { if (st.actual?.accion !== "pausado") await fijarActual({ accion: "pausado" }); return; }
  if (!dentroHorario(c)) { await fijarActual({ accion: "fuera_horario" }); return; }
  if (!c.grupos.length || !(c.keywords.length + c.keywords_aprendidas.filter(x => x.estado === "activa").length)) {
    await fijarActual({ accion: "sin_datos" }); return;
  }
  // respeta el espaciado (minutos_entre) con un poco de azar para no caer en patrón
  const espera = (c.minutos_entre * 60000) * (0.8 + Math.random() * 0.6);
  if (Date.now() - (st.ultima || 0) < espera) return;    // todavía esperando: el panel muestra la cuenta regresiva
  // si quedó un tab de ronda abierto de antes, ciérralo
  if (st.vigiaTab) { try { await chrome.tabs.remove(st.vigiaTab); } catch {} }

  const palabras = (c.ver_recientes !== false ? [RECIENTES] : [])
    .concat(c.keywords, c.keywords_aprendidas.filter(x => x.estado === "activa").map(x => x.frase));
  const g = st.g % c.grupos.length;
  const k = st.k % palabras.length;
  const grupo = c.grupos[g];
  const palabra = palabras[k];
  const gid = grupo.id || idDe(grupo.url);
  // "#vigia" le avisa al content.js que esta pestaña la abrió el vigía (que lea una vez y listo)
  const url = palabra === RECIENTES
    ? `https://www.facebook.com/groups/${gid}/?sorting_setting=CHRONOLOGICAL#vigia`
    : `https://www.facebook.com/groups/${gid}/search/?q=${encodeURIComponent(palabra)}#vigia`;
  const etiqueta = palabra === RECIENTES ? "lo reciente" : palabra;

  let tab;
  try { tab = await chrome.tabs.create({ url, active: false }); }
  catch (e) { console.warn("[vigía] no pude abrir tab", e); await anota("error", "no pude abrir la pestaña: " + e.message); return; }

  const nk = (k + 1) % palabras.length;
  const ng = nk === 0 ? (g + 1) % c.grupos.length : g;
  const proxPal = palabras[nk];
  const proximo = { grupo: c.grupos[ng]?.nombre || c.grupos[ng]?.id || "", palabra: proxPal === RECIENTES ? "lo reciente" : proxPal };
  const accion = palabra === RECIENTES ? "recientes" : "buscando";
  await set({ estado: { ...st, g: ng, k: nk, vuelta: st.vuelta + (ng === 0 && nk === 0 ? 1 : 0), ultima: Date.now(),
                        vigiaTab: tab.id, pendiente: { grupo: grupo.nombre || gid, palabra: etiqueta, t: Date.now() },
                        actual: { accion, grupo: grupo.nombre || gid, palabra: etiqueta, desde: Date.now() }, proximo } });
  await anota("ronda", palabra === RECIENTES
    ? `Miré lo reciente de ${grupo.nombre || gid}`
    : `Busqué “${palabra}” en ${grupo.nombre || gid}`);

  // red de seguridad: si en 25 s el content no mandó nada, cierra igual
  setTimeout(async () => {
    const s2 = await estado();
    if (s2.vigiaTab === tab.id) {
      try { await chrome.tabs.remove(tab.id); } catch {}
      await set({ estado: { ...s2, vigiaTab: null, pendiente: null, actual: { accion: "esperando", desde: Date.now() } } });
    }
  }, 25000);
}

// ----------------------------------------------------------------- recibir posts (del content.js)
chrome.runtime.onMessage.addListener((msg, sender, responder) => {
  (async () => {
    if (msg?.tipo === "posts") {
      const st = await estado();
      const esRonda = sender?.tab?.id && sender.tab.id === st.vigiaTab;
      const ctx = esRonda ? (st.pendiente || {}) : { grupo: nombreGrupo(await cfg(), sender?.tab?.url), feed: true };
      await procesarLote(msg.posts || [], ctx);
      if (esRonda) {                      // ya leímos la búsqueda: cerrar el tab y seguir
        try { await chrome.tabs.remove(st.vigiaTab); } catch {}
        await set({ estado: { ...(await estado()), vigiaTab: null, pendiente: null, actual: { accion: "esperando", desde: Date.now() } } });
      }
      responder?.({ ok: true });
      return;
    }
    if (msg?.tipo === "panel") { responder?.(await comandoPanel(msg)); return; }
  })();
  return true;  // respuesta async
});

function nombreGrupo(c, url) {
  const id = idDe(url);
  const g = (c.grupos || []).find(x => (x.id || idDe(x.url)) === id);
  return g?.nombre || id || "feed";
}

async function procesarLote(posts, ctx) {
  const c = await cfg();
  let nuevos = 0, leads = 0;
  for (const p of posts) {
    const link = permalink(p);
    if (await yaVisto(link)) continue;
    await marcarVisto(link);
    if (!p.texto || p.texto.length < 8) continue;
    nuevos++;
    let r = null;
    try { r = await clasificar(c, p.texto); } catch (e) { console.warn("[vigía] clasificar", e); }
    const esLead = !!(r && r.es_solicitud);
    await anotaMirado({ t: Date.now(), grupo: ctx.grupo || "", via: ctx.feed ? "inicio" : (ctx.palabra || ""),
                        autor: p.autor || "", snippet: ((r && r.resumen) || p.texto).slice(0, 100), veredicto: esLead ? "pega" : "no" });
    if (esLead) { leads++; await guardarLead(p, r, ctx); await aprender(r.frases_clave || []); }
  }
  // contadores + bitácora
  const st = await estado();
  await set({ estado: { ...st, posts_vistos: (st.posts_vistos || 0) + nuevos, solicitudes: (st.solicitudes || 0) + leads,
                        revisados: (st.revisados || 0) + (ctx.feed ? 0 : 1), ultimo_feed: ctx.feed ? Date.now() : st.ultimo_feed } });
  if (ctx.feed) {
    if (leads || nuevos) await anota("inicio", `En el inicio${ctx.grupo ? " (" + ctx.grupo + ")" : ""}: ${nuevos} vistas, ${leads} pega`);
  } else {
    await anota("resultado", `${ctx.grupo} · ${ctx.palabra === "lo reciente" ? "recientes" : "“" + (ctx.palabra || "") + "”"} → ${nuevos} vistas, ${leads} pega`);
  }
  return { nuevos, leads };
}

async function guardarLead(p, r, ctx) {
  const leads = await get("leads", []);
  const lead = {
    id: "L" + Date.now() + Math.floor(Math.random() * 1000),
    creado: new Date().toISOString(),
    grupo: ctx.grupo || "", via: ctx.feed ? "inicio" : (ctx.palabra === "lo reciente" ? "reciente del grupo" : "búsqueda: " + (ctx.palabra || "")),
    autor: p.autor || "", autor_url: p.autor_url || "", texto: p.texto.slice(0, 1200), url: p.url || "",
    tipo: r.tipo || "", resumen: r.resumen || "", comuna: r.comuna || "", urgencia: r.urgencia || "",
    mensaje: r.mensaje || "", estado: "nuevo"
  };
  leads.unshift(lead);
  await set({ leads: leads.slice(0, 2000) });
  await actualizarBadge();
  avisar(lead);
  const c = await cfg();
  if (c.webhook_url) { try { fetch(c.webhook_url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(lead) }); } catch {} }
}

function avisar(lead) {
  const comuna = lead.comuna ? ` · ${lead.comuna}` : "";
  chrome.notifications.create(lead.id, {
    type: "basic", iconUrl: icono(), title: `Nueva pega (${lead.tipo})${comuna}`,
    message: `${lead.resumen || lead.texto.slice(0, 80)}\n${lead.grupo}`, priority: 2
  });
}
chrome.notifications.onClicked.addListener(() => abrirPanel());

function icono() {
  // ícono simple generado al vuelo (un cuadrado verde) para no depender de un .png
  return "data:image/svg+xml;base64," + btoa('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" rx="12" fill="#1877f2"/><text x="32" y="44" font-size="38" text-anchor="middle" fill="#fff">⚡</text></svg>');
}

async function actualizarBadge() {
  const leads = await get("leads", []);
  const n = leads.filter(l => l.estado === "nuevo").length;
  chrome.action.setBadgeBackgroundColor({ color: "#e53935" });
  chrome.action.setBadgeText({ text: n ? String(n) : "" });
}

// ----------------------------------------------------------------- aprender palabras nuevas
async function aprender(frases) {
  if (!frases.length) return;
  const c = await cfg();
  const base = new Set(c.keywords.map(norm));
  const ap = c.keywords_aprendidas;
  let cambio = false;
  for (const f0 of frases) {
    const f = (f0 || "").toLowerCase().trim();
    if (!f || f.length < 3 || f.length > 40) continue;
    if (base.has(norm(f))) continue;
    const ya = ap.find(x => norm(x.frase) === norm(f));
    if (ya) { ya.veces++; if (ya.estado === "propuesta" && ya.veces >= 3) ya.estado = "activa"; cambio = true; }
    else { ap.push({ frase: f, veces: 1, estado: "propuesta" }); cambio = true; }
  }
  if (cambio) await set({ config: { ...c, keywords_aprendidas: ap.slice(-200) } });
}
const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();

// ----------------------------------------------------------------- órdenes del panel
async function comandoPanel(msg) {
  const c = await cfg();
  switch (msg.accion) {
    case "estado": {
      const leads = await get("leads", []);
      const st = await estado();
      const bitacora = await get("bitacora", []);
      const mirados = await get("mirados", []);
      return { config: c, leads, estado: st, bitacora, mirados,
               total_palabras: c.keywords.length + c.keywords_aprendidas.filter(x => x.estado === "activa").length };
    }
    case "limpiar_bitacora": await set({ bitacora: [], mirados: [] }); return { ok: true };
    case "set_config": await set({ config: { ...c, ...msg.config } }); programarRonda(); return { ok: true };
    case "probar": return await probar(c);
    case "lead_estado": {
      const leads = await get("leads", []);
      const l = leads.find(x => x.id === msg.id);
      if (l) l.estado = msg.estado;
      await set({ leads }); await actualizarBadge(); return { ok: true };
    }
    case "borrar_leads": {
      const leads = (await get("leads", [])).filter(l => msg.cuales === "todos" ? false : l.estado !== msg.cuales);
      await set({ leads }); await actualizarBadge(); return { ok: true };
    }
    case "kw_add": {
      const nuevas = (msg.texto || "").split(/[,;\n]/).map(x => x.trim()).filter(Boolean);
      const set1 = new Set(c.keywords.map(norm));
      for (const n of nuevas) if (!set1.has(norm(n))) c.keywords.push(n);
      await set({ config: c }); return { ok: true, keywords: c.keywords };
    }
    case "kw_del": {
      c.keywords = c.keywords.filter(k => norm(k) !== norm(msg.texto));
      c.keywords_aprendidas = c.keywords_aprendidas.filter(k => norm(k.frase) !== norm(msg.texto));
      await set({ config: c }); return { ok: true, keywords: c.keywords };
    }
    case "kw_aprendida": {   // aprobar/descartar una palabra que el bot propuso
      const a = c.keywords_aprendidas.find(x => x.frase === msg.frase);
      if (a) a.estado = msg.estado;   // 'activa' | 'descartada'
      await set({ config: c }); return { ok: true };
    }
    case "grupos_set": {
      c.grupos = parsearGrupos(msg.texto);
      await set({ config: c, estado: { ...(await estado()), g: 0, k: 0 } }); return { ok: true, n: c.grupos.length };
    }
    case "forzar_ronda": { await set({ estado: { ...(await estado()), ultima: 0 } }); tick(); return { ok: true }; }
    default: return { ok: false, error: "acción desconocida" };
  }
}

function parsearGrupos(texto) {
  const out = [], visto = new Set();
  for (const linea of (texto || "").split("\n")) {
    const t = linea.trim();
    if (!t) continue;
    let url = t, nombre = "";
    const sep = t.split("|");                  // permite "url | Nombre del grupo"
    if (sep.length === 2) { url = sep[0].trim(); nombre = sep[1].trim(); }
    const id = idDe(url) || (/^[\w.]+$/.test(url) ? url : null);
    if (!id || visto.has(id)) continue;
    visto.add(id);
    out.push({ id, nombre: nombre || id, url: `https://www.facebook.com/groups/${id}/` });
  }
  return out;
}
