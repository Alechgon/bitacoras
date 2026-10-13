// panel.js — la pantalla del vigía (v3).
// Lee directo del almacenamiento de la extensión y se actualiza sola cuando algo cambia.
// Los cambios se los pide al background (que es el único que escribe).

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const bg = (accion, extra = {}) => chrome.runtime.sendMessage({ tipo: "panel", accion, ...extra });

let DEF = {}, TDEF = {}, FDEF = {}, CONFIG = {}, ESTADO = {}, LEADS = [], BITA = [], MIR = [], GSTATS = {}, COLA = 0;
let filtro = "nuevo", leadsPendiente = false;

// ======================================================================= utilidades
const dos = (n) => String(n).padStart(2, "0");
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const hora = (t) => { try { return new Date(t).toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return ""; } };
const horaCorta = (t) => { const d = new Date(t); return `${dos(d.getHours())}:${dos(d.getMinutes())}`; };
const fecha = (iso) => { try { return new Date(iso).toLocaleString("es-CL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return ""; } };
function reloj(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s >= 3600) return `${Math.floor(s / 3600)} h ${dos(Math.floor(s % 3600 / 60))} min`;
  return `${dos(Math.floor(s / 60))}:${dos(s % 60)}`;
}
function edadAhora(l) {          // horas desde que se publicó, a este momento
  if (l.edad_h == null) return null;
  return l.edad_h + (Date.now() - Date.parse(l.creado)) / 3600000;
}
function edadTxt(h) {
  if (h == null) return "fecha ?";
  if (h < 1) return `hace ${Math.max(1, Math.round(h * 60))} min`;
  if (h < 24) return `hace ${Math.round(h)} h`;
  return `hace ${Math.round(h / 24)} d`;
}
const inicioHoy = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };
const hoyStr = () => { const d = new Date(); return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`; };
const T = () => ({ ...TDEF, ...(CONFIG.tiempos || {}) });
const F = () => ({ ...FDEF, ...(CONFIG.fechas || {}) });
const sinLlave = () => !CONFIG.gemini_key || CONFIG.gemini_key.startsWith("PEGA") || CONFIG.gemini_key.length < 20;
const lista = (k) => (CONFIG[k] || []).map(x => typeof x === "string" ? { p: x, on: true } : x);
const activas = (k) => lista(k).filter(x => x.on !== false);
const VERSION = chrome.runtime.getManifest().version;
$("#version").textContent = "v" + VERSION;

// ======================================================================= pestañas
function irA(t) {
  if (!$("#" + t)) return;
  $$(".tab").forEach(x => x.classList.toggle("activo", x.dataset.t === t));
  $$(".pag").forEach(x => x.classList.toggle("activo", x.id === t));
  history.replaceState(null, "", "#" + t);
  if (t === "config") pintarConfig();
  if (t === "grupos") { pintarGruposTxt(); pintarTablaGrupos(); }
  if (t === "solicitudes") pintarLeads(true);
  if (t === "palabras") pintarPalabras();
}
$$(".tab").forEach(t => t.onclick = () => irA(t.dataset.t));
$$(".filtro").forEach(f => f.onclick = () => {
  $$(".filtro").forEach(x => x.classList.remove("activo"));
  f.classList.add("activo"); filtro = f.dataset.f; pintarLeads(true);
});
window.addEventListener("hashchange", () => irA(location.hash.slice(1)));

// ======================================================================= carga y cambios en vivo
$("#btnRecargar").onclick = () => chrome.runtime.reload();
$("#btnExtensiones").onclick = () => chrome.tabs.create({ url: "chrome://extensions/?id=" + chrome.runtime.id });

async function inicio() {
  let r = null;
  try { r = await bg("estado"); } catch (e) { console.warn("[vigía] el motor no responde", e); }
  if (!r || !r.tiempos_def || !r.config) {          // motor viejo (no se recargó) o que no responde
    $("#bannerRecargar").hidden = false;
    const d0 = await chrome.storage.local.get(["config", "estado"]);
    r = { config: d0.config || {}, estado: d0.estado || {}, config_def: {}, tiempos_def: { grupo_min: 3, grupo_posts: 30, palabra_min: 1,
      palabra_posts: 10, palabras_por_grupo: 0, fb_min: 2, fb_posts: 30, fb_cada: 1, entre_pasos_seg: [5, 15], entre_grupos_seg: [20, 60],
      trabajo_min: 40, descanso_min: 10, max_grupos_hora: 8, max_grupos_dia: 80, max_busq_hora: 15, max_busq_dia: 120 }, fechas_def: { horas_util: 48, dias_revisar: 7 } };
  }
  DEF = r.config_def || {}; TDEF = r.tiempos_def || {}; FDEF = r.fechas_def || {}; CONFIG = r.config || {}; ESTADO = r.estado || {};
  const d = await chrome.storage.local.get(["leads", "bitacora", "mirados", "gstats", "cola"]);
  LEADS = d.leads || []; BITA = d.bitacora || []; MIR = d.mirados || []; GSTATS = d.gstats || {}; COLA = (d.cola || []).length;
  pintarCabecera(); pintarActividad(); pintarLeads(true); pintarPalabras(); pintarTablaGrupos();
  pintarGruposTxt(); pintarConfig(); pintarImport();
  const h = location.hash.slice(1);
  if (h) irA(h);
}

let cambios = new Set(), timerPintar = null;
chrome.storage.onChanged.addListener((ch, area) => {
  if (area !== "local") return;
  if (ch.config) CONFIG = { ...DEF, ...(ch.config.newValue || {}) };
  if (ch.estado) ESTADO = ch.estado.newValue || {};
  if (ch.leads) LEADS = ch.leads.newValue || [];
  if (ch.bitacora) BITA = ch.bitacora.newValue || [];
  if (ch.mirados) MIR = ch.mirados.newValue || [];
  if (ch.gstats) GSTATS = ch.gstats.newValue || {};
  if (ch.cola) COLA = (ch.cola.newValue || []).length;
  Object.keys(ch).forEach(k => cambios.add(k));
  clearTimeout(timerPintar);
  timerPintar = setTimeout(() => {
    const c = cambios; cambios = new Set();
    pintarCabecera();
    if (c.has("estado") || c.has("bitacora") || c.has("mirados") || c.has("config") || c.has("gstats") || c.has("cola")) pintarActividad();
    if (c.has("leads")) pintarLeads();
    if (c.has("config")) { pintarPalabras(); if (document.activeElement !== $("#txtGrupos")) pintarGruposTxt(); }
    if (c.has("gstats") || c.has("config")) pintarTablaGrupos();
    if (c.has("estado")) pintarImport();
  }, 250);
});
setInterval(() => pintarAhora(), 1000);

// ======================================================================= cabecera
function pintarCabecera() {
  const chip = $("#estadoChip");
  const pausaSeg = (ESTADO.pausa_hasta || 0) > Date.now();
  chip.textContent = !CONFIG.activo ? "Pausado" : pausaSeg ? "Pausa de seguridad" : "Activo";
  chip.className = "chip " + (!CONFIG.activo || pausaSeg ? "off" : "on");
  $("#btnActivo").textContent = CONFIG.activo ? "Pausar" : "Activar";
  $("#cuentaNuevas").textContent = LEADS.filter(l => l.estado === "nuevo").length || "";
  $("#cuentaRevisar").textContent = LEADS.filter(l => l.estado === "revisar").length || "";
}
$("#btnActivo").onclick = async () => {
  const prende = !CONFIG.activo;
  await bg("set_config", { config: { activo: prende } });
  if (prende) await bg("forzar_ronda");
};
$("#btnRonda").onclick = async () => {
  const b = $("#btnRonda");
  if (!CONFIG.activo) { b.textContent = "Primero Activar"; setTimeout(() => b.textContent = "Mirar ahora", 1800); return; }
  await bg("forzar_ronda");
  b.textContent = "Pedido ✓"; setTimeout(() => b.textContent = "Mirar ahora", 1800);
};
$("#btnSaltar").onclick = () => bg("saltar_grupo");

// ======================================================================= actividad
function pintarAhora() {
  const a = ESTADO.actual || {};
  const p = ESTADO.pendiente;
  const plan = ESTADO.plan;
  const pulso = $("#pulso"), txt = $("#ahoraTxt"), sub = $("#ahoraSub");
  const nG = (CONFIG.grupos || []).length;
  const falta = a.hasta ? a.hasta - Date.now() : 0;
  let clase = "", t = "", s = "";
  const pausaSeg = (ESTADO.pausa_hasta || 0) > Date.now();
  $("#bannerPausa").hidden = !(CONFIG.activo && pausaSeg);
  if (pausaSeg) $("#pausaTxt").textContent = `${ESTADO.pausa_motivo || "Aviso de Facebook"}. Vuelve solo a las ${horaCorta(ESTADO.pausa_hasta)} (en ${reloj(ESTADO.pausa_hasta - Date.now())}).`;
  let enPaso = false;

  if (!CONFIG.activo) { t = "Pausado"; s = "Dale a Activar (arriba a la derecha) para que empiece."; }
  else if (nG === 0) { clase = "alerta"; t = "Falta cargar grupos"; s = "Anda a la pestaña Grupos y toca «Importar mis grupos»."; }
  else if (p && ["leyendo_grupo", "buscando", "leyendo_fb"].includes(a.accion)) {
    enPaso = true; clase = "busca";
    t = a.accion === "buscando" ? `Buscando “${a.palabra}” en ${a.grupo}` : a.accion === "leyendo_grupo" ? `Leyendo el inicio de ${a.grupo}` : "Leyendo el inicio de Facebook";
    const el = Date.now() - p.t;
    s = `${reloj(el)} de ${reloj(p.dur)} · ${p.vistos || 0} publicaciones (meta ${p.objetivo})` +
        (p.res?.candidatas ? ` · ${p.res.candidatas} parecen pega` : "") +
        (p.visible === "hidden" ? " · ⚠️ la ventana del vigía está tapada o minimizada" : "");
    $("#pasoFill").style.width = Math.min(100, el / p.dur * 100).toFixed(1) + "%";
  } else switch (a.accion) {
    case "entre_pasos": clase = "on"; t = `En ${a.grupo || "el grupo"}: siguiente paso en ${reloj(falta)}`; s = "Una pausa corta, como quien escribe la siguiente búsqueda."; break;
    case "esperando": clase = "on"; t = "Atento"; s = falta > 0 ? `Siguiente grupo en ${reloj(falta)}` : "Partiendo en instantes…"; break;
    case "descanso": clase = "descanso"; t = "Descansando ☕"; s = `Como una persona, entre sesiones. Sigue a las ${horaCorta(a.hasta)} (en ${reloj(falta)}).`; break;
    case "pausa_seguridad": clase = "alerta"; t = "En pausa de seguridad"; s = `${a.motivo || ""}. Vuelve solo a las ${horaCorta(a.hasta)}.`; break;
    case "fuera_horario": t = "Fuera de horario"; s = `Trabaja de ${CONFIG.horario?.[0]} a ${CONFIG.horario?.[1]}. Vuelve solo.`; break;
    case "limite_hora": clase = "descanso"; t = "Llegó al tope de grupos de esta hora"; s = `Para cuidar tu cuenta. Sigue a las ${horaCorta(a.hasta)} (en ${reloj(falta)}).`; break;
    case "limite_dia": clase = "descanso"; t = "Llegó al tope de grupos de hoy"; s = "Mañana sigue solo. Los topes se cambian en Configuración."; break;
    case "sin_internet": clase = "alerta"; t = "Sin internet"; s = "Espera a que vuelva la conexión."; break;
    case "solo_inicio": clase = "on"; t = "Solo leyendo lo que navegas"; s = "El recorrido automático está apagado en Configuración."; break;
    case "sin_datos": clase = "alerta";
      t = a.falta === "acceso" ? "Ningún grupo disponible" : a.falta === "modo" ? "No tiene qué hacer" : "Faltan datos";
      s = a.falta === "acceso" ? "Todos tus grupos salieron sin acceso. Revisa la pestaña Grupos." : "Activa leer el inicio del grupo o el buscador en Configuración."; break;
    default: clase = "on"; t = "Arrancando…"; s = "En unos segundos parte (revisa cada 30 s).";
  }
  pulso.className = "pulso " + clase;
  txt.textContent = t;
  sub.textContent = s;
  if (CONFIG.activo && sinLlave() && nG && !enPaso) sub.textContent += " · sin llave de IA: decide con reglas simples";
  $("#pasoBar").hidden = !enPaso;
  $("#btnSaltar").hidden = !(CONFIG.activo && plan);
  $("#planTxt").innerHTML = plan && CONFIG.activo ? plan.pasos.map((x, i) => {
    const n = x.tipo === "grupo" ? "inicio del grupo" : x.tipo === "buscar" ? `“${esc(x.palabra)}”` : "inicio de Facebook";
    const cl = i < plan.i ? "hecho" : (i === plan.i && enPaso ? "ahora" : "");
    return `<span class="p ${cl}">${i < plan.i ? "✓ " : ""}${n}</span>`;
  }).join("") : "";
}

function pintarActividad() {
  pintarAhora();
  const t = T();
  const chip = (ok, txt) => `<span class="chip ${ok === true ? "on" : ok === false ? "off" : ""}">${txt}</span>`;
  const nG = (CONFIG.grupos || []).length;
  $("#salud").innerHTML = [
    chip(!sinLlave(), `IA ${sinLlave() ? "✗ sin llave" : "✓"}`),
    chip(nG > 0, `Grupos <b>${nG}</b>`),
    chip(activas("kw_buscar").length > 0 || !CONFIG.buscar_palabras ? true : false, `Buscador <b>${activas("kw_buscar").length}</b>`),
    chip(activas("kw_inicio").length > 0 || CONFIG.usar_reglas ? true : false, `Inicio <b>${activas("kw_inicio").length}</b>${CONFIG.usar_reglas ? " + reglas" : ""}`),
    chip(null, `Horario ${CONFIG.horario?.[0] || ""}–${CONFIG.horario?.[1] || ""}`),
    chip(CONFIG.ntfy_tema ? true : null, CONFIG.ntfy_tema ? "Celular ✓" : "Celular —"),
    chip(null, CONFIG.ventana_aparte ? "Ventana aparte" : "Pestaña fija")
  ].join("");

  const u = ESTADO.uso || {};
  const hoy = u.dia === hoyStr();
  const enHora = (arr) => (arr || []).filter(x => Date.now() - x < 3600000).length;
  const barra = (id, idt, v, max) => {
    const f = max ? Math.min(1, v / max) : 0;
    const i = $(id); i.style.width = (f * 100).toFixed(0) + "%";
    i.className = f >= 1 ? "lleno" : f >= 0.75 ? "medio" : "";
    $(idt).textContent = `${v} / ${max}`;
  };
  barra("#bHora", "#tHora", enHora(u.mg), t.max_grupos_hora);
  barra("#bDia", "#tDia", hoy ? u.g_dia || 0 : 0, t.max_grupos_dia);
  barra("#bBusqH", "#tBusqH", enHora(u.mb), t.max_busq_hora);
  barra("#bBusq", "#tBusq", hoy ? u.b_dia || 0 : 0, t.max_busq_dia);

  const h0 = inicioHoy();
  $("#sGrupos").textContent = `${(CONFIG.grupos || []).filter(g => (GSTATS[g.id]?.ultima || 0) >= h0).length}/${nG}`;
  $("#sVistos").textContent = ESTADO.cont?.vistos || 0;
  $("#sPegas").textContent = ESTADO.cont?.pegas || 0;
  $("#sRevisar").textContent = ESTADO.cont?.revisar || 0;
  $("#sCola").textContent = COLA;

  const icon = { grupo: "👥", ronda: "🔎", recientes: "🕒", resultado: "✓", inicio: "🏠", ia: "🤖", pega: "⚡", seguridad: "🛡️", descanso: "☕", error: "⚠️", info: "·" };
  const ver = { ia: "→ IA", revisar: "revisar", no: "no", vieja: "vieja", ya: "ya vista" };
  $("#bitacora").innerHTML = BITA.length ? BITA.slice(0, 200).map(b => {
    const det = b.det?.length ? `<details><summary>ver ${b.det.length} publicaciones</summary><div class="det">${b.det.map(d =>
      `<div><span class="v ${esc(d.v)}">${ver[d.v] || esc(d.v)}</span><span class="a">${esc(d.a || "—")}</span><span class="e">${esc(d.e || "")}</span>` +
      `<span class="s">${d.u ? `<a href="${esc(d.u)}" target="_blank" rel="noopener">${esc(d.s)}</a>` : esc(d.s)}${d.k?.length ? ` <i class="dim">(${esc(d.k.join(", "))})</i>` : ""}</span></div>`).join("")}</div></details>` : "";
    return `<div class="bl ${esc(b.tipo)}"><span class="h">${hora(b.t)}</span><span class="x">${icon[b.tipo] || "·"} ${esc(b.texto)}</span>${det}</div>`;
  }).join("") : '<div class="dim" style="padding:6px">Todavía no hace nada. Actívalo arriba.</div>';

  const etq = { pega: "PEGA", no: "no", vieja: "vieja", revisar: "revisar" };
  $("#mirados").innerHTML = MIR.length ? MIR.slice(0, 60).map(m =>
    `<div class="mir"><span class="v ${esc(m.veredicto)}">${etq[m.veredicto] || esc(m.veredicto)}</span>
      <div><b>${esc(m.autor || "—")}</b> <span class="dim">· ${esc(m.grupo)} · ${esc(m.via)} · ${esc(m.edad || "")} · ${hora(m.t)}</span>
      <div>${m.url ? `<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.snippet)}</a>` : esc(m.snippet)}</div></div></div>`).join("")
    : '<div class="dim">Nada todavía.</div>';
}
$("#btnLimpiarBita").onclick = () => bg("limpiar_bitacora");
$("#btnReanudar").onclick = async () => {
  if (!confirm("Facebook mostró un aviso hace poco. Lo más seguro es esperar a que termine la pausa.\n\n¿Reanudar igual?")) return;
  await bg("reanudar");
};

// ======================================================================= solicitudes
function pintarLeads(forzar = false) {
  const editando = document.activeElement?.classList?.contains("msg") && $("#listaLeads").contains(document.activeElement);
  if (editando && !forzar) { leadsPendiente = true; return; }
  leadsPendiente = false;
  const cont = $("#listaLeads");
  cont.innerHTML = "";
  $("#ayudaRevisar").hidden = filtro !== "revisar";
  const lista = LEADS.filter(l => filtro === "todos" ? true : l.estado === filtro).slice(0, 300);
  $("#vacioLeads").style.display = lista.length ? "none" : "block";
  for (const l of lista) {
    const n = $("#tplLead").content.cloneNode(true);
    const card = $(".lead", n);
    $(".tipo", n).textContent = l.tipo === "gasfiteria" ? "gasfitería" : (l.tipo || "pega");
    if (l.urgencia) { const u = $(".urg", n); u.textContent = l.urgencia === "alta" ? "urgente" : l.urgencia; u.classList.add(l.urgencia); }
    const h = edadAhora(l);
    const ed = document.createElement("span");
    ed.className = "edad" + (h != null && h <= 1 ? " recien" : h != null && h <= 24 ? " hoy" : "");
    ed.textContent = (h != null && h <= 1 ? "🔥 " : "") + "publicado " + edadTxt(h) + (l.fecha_txt && h != null && h > 24 ? ` (${l.fecha_txt})` : "");
    $(".cab", n).insertBefore(ed, $(".meta", n));
    if (l.sin_ia) $(".sinia", n).hidden = false;
    $(".meta", n).textContent = [l.comuna, l.via, "visto " + fecha(l.creado)].filter(Boolean).join(" · ");
    $(".autor", n).innerHTML = l.autor_url ? `<a href="${esc(l.autor_url)}" target="_blank" rel="noopener">${esc(l.autor || "(sin nombre)")}</a>` : esc(l.autor || "(sin nombre)");
    const links = [];
    if (l.autor_url) links.push(`<a href="${esc(l.autor_url)}" target="_blank" rel="noopener">👤 Perfil de ${esc(l.autor || "la persona")}</a>`);
    if (l.messenger) links.push(`<a href="${esc(l.messenger)}" target="_blank" rel="noopener">💬 Escribirle por Messenger</a>`);
    if (l.url) links.push(`<a href="${esc(l.url)}" target="_blank" rel="noopener">📄 Ver publicación</a> <span class="url">${esc(l.url)}</span>`);
    if (l.grupo) links.push(l.grupo_url ? `<a href="${esc(l.grupo_url)}" target="_blank" rel="noopener">👥 ${esc(l.grupo)}</a>` : `<span>👥 ${esc(l.grupo)}</span>`);
    $(".links", n).innerHTML = links.join("");
    $(".texto", n).textContent = l.resumen && !l.sin_ia ? (l.resumen + "\n\n" + l.texto) : l.texto;
    if (l.otros_grupos?.length) { const o = $(".otros", n); o.hidden = false; o.textContent = "También lo publicó en: " + l.otros_grupos.join(", "); }
    const msg = $(".msg", n);
    msg.value = l.mensaje || "";
    msg.addEventListener("change", () => bg("lead_mensaje", { id: l.id, mensaje: msg.value }));
    msg.addEventListener("blur", () => { if (leadsPendiente) setTimeout(() => pintarLeads(), 50); });
    if (!l.url) $(".copiarAbrir", n).style.display = "none";
    if (!l.messenger) $(".copiarMsgr", n).style.display = "none";
    $(".copiar", n).onclick = async (e) => { await navigator.clipboard.writeText(msg.value); e.target.textContent = "¡Copiado!"; setTimeout(() => e.target.textContent = "Copiar mensaje", 1500); };
    $(".copiarAbrir", n).onclick = async () => { await navigator.clipboard.writeText(msg.value); chrome.tabs.create({ url: l.url, active: true }); };
    $(".copiarMsgr", n).onclick = async () => { await navigator.clipboard.writeText(msg.value); chrome.tabs.create({ url: l.messenger, active: true }); };
    $(".ok", n).onclick = () => cambiarLead(l.id, "contactado");
    $(".desc", n).onclick = () => cambiarLead(l.id, "descartado");
    if (l.estado === "contactado") $(".ok", n).textContent = "✓ Contactado";
    if (l.estado === "descartado") $(".desc", n).textContent = "✓ Descartado";
    card.dataset.id = l.id;
    cont.appendChild(n);
  }
}
async function cambiarLead(id, estado) {
  const l = LEADS.find(x => x.id === id);
  await bg("lead_estado", { id, estado: l?.estado === estado ? "nuevo" : estado });
}
$("#btnLimpiar").onclick = () => { if (confirm("¿Borrar todas las descartadas?")) bg("borrar_leads", { cuales: "descartado" }); };

$("#btnCsv").onclick = () => {
  const cols = [["creado", "Visto"], ["publicado", "Publicado aprox."], ["fecha_txt", "Fecha según Facebook"], ["estado", "Estado"], ["tipo", "Tipo"],
    ["urgencia", "Urgencia"], ["comuna", "Comuna"], ["resumen", "Resumen"], ["autor", "Persona"], ["autor_url", "Perfil"], ["messenger", "Messenger"],
    ["grupo", "Grupo"], ["grupo_url", "Link del grupo"], ["via", "Cómo"], ["url", "Link publicación"], ["mensaje", "Mensaje"], ["texto", "Texto"]];
  const celda = (v) => `"${String(v ?? "").replace(/"/g, '""').replace(/\r?\n/g, " ")}"`;
  const lst = LEADS.filter(l => filtro === "todos" ? true : l.estado === filtro);
  const filas = [cols.map(c => celda(c[1])).join(";"),
    ...lst.map(l => cols.map(([k]) => celda(k === "creado" || k === "publicado" ? (l[k] ? fecha(l[k]) : "") : l[k])).join(";"))];
  descargar(`solicitudes-${hoyStr()}.csv`, "﻿" + filas.join("\r\n"), "text/csv;charset=utf-8");
};
function descargar(nombre, contenido, tipo) {
  const url = URL.createObjectURL(new Blob([contenido], { type: tipo }));
  const a = document.createElement("a"); a.href = url; a.download = nombre; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ======================================================================= grupos
function pintarGruposTxt() {
  $("#txtGrupos").value = (CONFIG.grupos || []).map(g => g.url + (g.nombre && g.nombre !== g.id ? " | " + g.nombre : "")).join("\n");
  $("#nGrupos").textContent = (CONFIG.grupos || []).length + " grupos cargados";
}
$("#btnGrupos").onclick = async () => {
  const r = await bg("grupos_set", { texto: $("#txtGrupos").value });
  $("#nGrupos").textContent = r.n + " grupos cargados ✓";
  setTimeout(pintarGruposTxt, 300);
};
$("#btnCopiarSnippet").onclick = async (e) => { await navigator.clipboard.writeText($("#snippet").textContent); e.target.textContent = "¡Copiado!"; setTimeout(() => e.target.textContent = "Copiar ese código", 1500); };
$("#btnImportar").onclick = async () => {
  await bg("importar_grupos");
  $("#impMsg").textContent = "Abrí tu lista de grupos en otra pestaña. Déjala a la vista hasta que diga Listo.";
};
function pintarImport() {
  const imp = ESTADO.importacion;
  if (!imp || Date.now() - (imp.t || 0) > 3 * 3600000) return;
  const el = $("#impMsg");
  if (!imp.fin) { el.textContent = `Juntando… ${imp.n || 0} encontrados hasta ahora (deja la pestaña de Facebook a la vista).`; el.className = "dim"; }
  else { el.textContent = imp.n ? `✓ Listo: encontré ${imp.n} grupos, ${imp.nuevos} nuevos. Ahora tienes ${imp.total}.` : "No encontré grupos (¿iniciaste sesión en Facebook?)."; el.className = imp.n ? "ok-txt" : "dim"; }
}
$("#filtroGrupos").addEventListener("input", () => pintarTablaGrupos());

function pintarTablaGrupos() {
  const q = (($("#filtroGrupos").value || "").toLowerCase()).trim();
  const todos = (CONFIG.grupos || []).map(g => ({ g, s: GSTATS[g.id] || {} }));
  const filas = todos.filter(({ g }) => !q || g.nombre.toLowerCase().includes(q) || g.url.toLowerCase().includes(q))
    .sort((a, b) => (b.s.pegas || 0) - (a.s.pegas || 0) || (b.s.visitas || 0) - (a.s.visitas || 0) || a.g.nombre.localeCompare(b.g.nombre));
  $("#nFiltro").textContent = q ? `${filas.length} de ${todos.length}` : "";
  const nBus = activas("kw_buscar").length;
  $("#tablaGrupos").innerHTML = filas.slice(0, 1000).map(({ g, s }) => {
    const sinAcc = s.sin_acceso && Date.now() - s.sin_acceso < 7 * 86400000;
    const est = sinAcc ? `<span class="mal">sin acceso</span> <button class="btn chico fantasma reint" data-id="${esc(g.id)}">Reintentar</button>`
      : s.ultimo_estado === "vacío" ? `<span class="mal">no mostró posts</span>`
      : s.ultimo_estado && s.ultimo_estado !== "ok" ? `<span class="mal">${esc(s.ultimo_estado)}</span>`
      : s.visitas ? `<span class="bien">ok</span>` : `<span class="dim">pendiente</span>`;
    const pal = g.palabras?.length ? esc(g.palabras.join(", ")) : `<span class="dim">las de Palabras (${nBus})</span>`;
    return `<tr><td><a href="${esc(g.url)}" target="_blank" rel="noopener"><b>${esc(g.nombre)}</b></a></td>
      <td class="lnk"><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.url)}</a></td>
      <td class="pal">${pal} <button class="btn chico fantasma edpal" data-id="${esc(g.id)}" title="Elegir palabras para este grupo">✏️</button></td>
      <td>${s.visitas || 0}</td><td>${s.ultima ? fecha(s.ultima) : "—"}</td><td>${s.vistas || 0}</td><td>${s.pegas ? "<b>" + s.pegas + "</b>" : 0}</td><td>${est}</td></tr>`;
  }).join("") || '<tr><td colspan="8" class="dim">Sin grupos todavía.</td></tr>';
  $$(".reint").forEach(b => b.onclick = () => bg("grupo_reintentar", { id: b.dataset.id }));
  $$(".edpal").forEach(b => b.onclick = async () => {
    const g = (CONFIG.grupos || []).find(x => x.id === b.dataset.id);
    const actual = (g?.palabras || []).join(", ");
    const r = prompt(`Palabras del buscador SOLO para «${g?.nombre}», separadas por coma.\nDéjalo vacío para usar las de la pestaña Palabras.`, actual);
    if (r === null) return;
    await bg("grupo_palabras", { id: b.dataset.id, palabras: r });
  });
}

// ======================================================================= palabras
function chips(cont, k, nombre) {
  cont.innerHTML = "";
  for (const w of lista(k)) {
    const el = document.createElement("span");
    el.className = "kw" + (w.on === false ? " off" : "");
    el.title = w.on === false ? "Apagada: toca para prenderla" : "Toca para apagarla";
    const t = document.createElement("span"); t.textContent = w.p;
    t.onclick = () => bg("kw_toggle", { lista: nombre, p: w.p });
    const ed = document.createElement("span"); ed.className = "ed"; ed.textContent = "✏️"; ed.title = "Cambiar";
    ed.onclick = async () => { const r = prompt("Cambiar palabra:", w.p); if (r && r.trim() && r.trim() !== w.p) await bg("kw_edit", { lista: nombre, p: w.p, nuevo: r.trim() }); };
    const x = document.createElement("span"); x.className = "x"; x.textContent = "✕"; x.title = "Borrar";
    x.onclick = () => bg("kw_del", { lista: nombre, p: w.p });
    el.append(t, ed, x);
    cont.appendChild(el);
  }
  if (!lista(k).length) cont.innerHTML = '<span class="dim">Sin palabras todavía.</span>';
}
function pintarPalabras() {
  chips($("#chipsBuscar"), "kw_buscar", "buscar");
  chips($("#chipsInicio"), "kw_inicio", "inicio");
  const t = T(), n = activas("kw_buscar").length;
  const porGrupo = t.palabras_por_grupo > 0 ? Math.min(n, t.palabras_por_grupo) : n;
  $("#resBuscar").textContent = n ? `En cada grupo busca ${porGrupo} palabra${porGrupo === 1 ? "" : "s"}${t.palabras_por_grupo > 0 && n > porGrupo ? " (va rotando)" : ""}, ~${t.palabra_min} min cada una. Tope: ${t.max_busq_hora} búsquedas por hora y ${t.max_busq_dia} por día.` : "";
  $("#cReglas").checked = CONFIG.usar_reglas !== false;
  const ap = $("#aprendidas"); ap.innerHTML = "";
  const props = (CONFIG.keywords_aprendidas || []).filter(x => x.estado !== "descartada").sort((a, b) => b.veces - a.veces);
  if (!props.length) ap.innerHTML = '<p class="dim">Nada aprendido todavía.</p>';
  for (const a of props) {
    const row = document.createElement("div"); row.className = "apr";
    row.innerHTML = `<span class="f">${esc(a.frase)}</span><span class="v">visto ${a.veces}× · ${a.estado === "activa" ? "ya está en inicio" : "propuesta"}</span>`;
    const ok = document.createElement("button"); ok.className = "btn chico"; ok.textContent = a.estado === "activa" ? "✓ activa" : "Activar";
    ok.onclick = () => bg("kw_aprendida", { frase: a.frase, estado: "activa" });
    const no = document.createElement("button"); no.className = "btn chico fantasma"; no.textContent = "No";
    no.onclick = () => bg("kw_aprendida", { frase: a.frase, estado: "descartada" });
    row.append(ok, no); ap.appendChild(row);
  }
}
for (const [inp, btn, nombre] of [["#inpBuscar", "#btnBuscarAdd", "buscar"], ["#inpInicio", "#btnInicioAdd", "inicio"]]) {
  $(btn).onclick = async () => { const v = $(inp).value.trim(); if (!v) return; await bg("kw_add", { lista: nombre, texto: v }); $(inp).value = ""; };
  $(inp).addEventListener("keydown", e => { if (e.key === "Enter") $(btn).click(); });
}
$("#cReglas").onchange = () => bg("set_config", { config: { usar_reglas: $("#cReglas").checked } });

// ======================================================================= configuración
function pintarConfig() {
  const t = T(), f = F();
  const val = (id, v) => { $(id).value = v; };
  val("#cGemini", CONFIG.gemini_key || ""); val("#cNombre", CONFIG.mi_nombre || ""); val("#cFono", CONFIG.mi_fono || "");
  val("#cRubro", CONFIG.mi_rubro || ""); val("#cZona", CONFIG.mi_zona || ""); val("#cPlantilla", CONFIG.plantilla || "");
  $("#cRondas").checked = CONFIG.rondas_activa !== false;
  val("#tGrupoMin", t.grupo_min); val("#tGrupoPosts", t.grupo_posts); val("#cOrden", CONFIG.orden_grupo || "RECENT_ACTIVITY");
  val("#tPalMin", t.palabra_min); val("#tPalPosts", t.palabra_posts); val("#tPalGrupo", t.palabras_por_grupo);
  val("#tFbMin", t.fb_min); val("#tFbPosts", t.fb_posts); val("#tFbCada", t.fb_cada);
  $("#cVerGrupo").checked = CONFIG.ver_grupo !== false; $("#cBuscar").checked = CONFIG.buscar_palabras !== false;
  $("#cBuscarPrimero").checked = CONFIG.orden_pasos === "buscar_primero"; $("#cBusqRec").checked = !!CONFIG.busqueda_reciente;
  val("#tPasoA", t.entre_pasos_seg[0]); val("#tPasoB", t.entre_pasos_seg[1]);
  val("#tGrupoA", t.entre_grupos_seg[0]); val("#tGrupoB", t.entre_grupos_seg[1]);
  val("#cH1", CONFIG.horario?.[0] || "07:30"); val("#cH2", CONFIG.horario?.[1] || "23:30");
  val("#tTrabajo", t.trabajo_min); val("#tDescanso", t.descanso_min); val("#cPausaH", CONFIG.pausa_bloqueo_horas || 24);
  val("#tGH", t.max_grupos_hora); val("#tGD", t.max_grupos_dia); val("#tBH", t.max_busq_hora); val("#tBD", t.max_busq_dia);
  val("#fUtil", f.horas_util); val("#fRevisar", f.dias_revisar);
  $("#cVentana").checked = !!CONFIG.ventana_aparte; $("#cFeed").checked = CONFIG.feed_activo !== false;
  val("#cNtfy", CONFIG.ntfy_tema || ""); val("#cWebhook", CONFIG.webhook_url || "");
  resumenPlan();
}
function leerTiempos() {
  const n = (id) => +$(id).value;
  return {
    grupo_min: n("#tGrupoMin"), grupo_posts: n("#tGrupoPosts"), palabra_min: n("#tPalMin"), palabra_posts: n("#tPalPosts"),
    palabras_por_grupo: n("#tPalGrupo"), fb_min: n("#tFbMin"), fb_posts: n("#tFbPosts"), fb_cada: n("#tFbCada"),
    entre_pasos_seg: [n("#tPasoA"), n("#tPasoB")], entre_grupos_seg: [n("#tGrupoA"), n("#tGrupoB")],
    trabajo_min: n("#tTrabajo"), descanso_min: n("#tDescanso"),
    max_grupos_hora: n("#tGH"), max_grupos_dia: n("#tGD"), max_busq_hora: n("#tBH"), max_busq_dia: n("#tBD")
  };
}
function resumenPlan() {
  const t = leerTiempos();
  const nb = activas("kw_buscar").length;
  const pal = $("#cBuscar").checked ? (t.palabras_por_grupo > 0 ? Math.min(nb, t.palabras_por_grupo) : nb) : 0;
  const palConTope = Math.min(pal, t.max_busq_hora);
  const min = ($("#cVerGrupo").checked ? t.grupo_min : 0) + palConTope * t.palabra_min + (t.fb_min / Math.max(1, t.fb_cada)) +
              (palConTope * ((t.entre_pasos_seg[0] + t.entre_pasos_seg[1]) / 2) + (t.entre_grupos_seg[0] + t.entre_grupos_seg[1]) / 2) / 60;
  const porHora = Math.min(t.max_grupos_hora, 60 / Math.max(min, 0.5) * (t.trabajo_min / (t.trabajo_min + t.descanso_min)));
  const nG = (CONFIG.grupos || []).length;
  const horasDia = (() => { const [a, b] = [$("#cH1").value || "07:30", $("#cH2").value || "23:30"].map(x => +x.slice(0, 2) + +x.slice(3) / 60); return b >= a ? b - a : 24 - a + b; })();
  const porDia = Math.min(t.max_grupos_dia, porHora * horasDia);
  $("#resumenPlan").textContent = `Con esto, cada grupo toma ~${min.toFixed(1)} min (inicio del grupo + ${palConTope} búsqueda${palConTope === 1 ? "" : "s"} + Facebook + pausas) → ~${porHora.toFixed(1)} grupos por hora, ~${Math.round(porDia)} por día.` +
    (nG ? ` Una vuelta completa a tus ${nG} grupos: ~${Math.max(1, Math.ceil(nG / Math.max(1, porDia)))} día(s).` : "") +
    (pal * porHora > t.max_busq_hora ? ` Ojo: con ${pal} palabras por grupo llegas al tope de ${t.max_busq_hora} búsquedas por hora; los grupos que vengan después de eso solo leen el inicio hasta que se libere.` : "");
}
$$("#config input, #config select").forEach(el => el.addEventListener("input", () => { if (el.id.startsWith("t") || el.id.startsWith("c")) resumenPlan(); }));
$("#btnConfig").onclick = async () => {
  const config = {
    gemini_key: $("#cGemini").value.trim(), mi_nombre: $("#cNombre").value.trim(), mi_fono: $("#cFono").value.trim(),
    mi_rubro: $("#cRubro").value.trim(), mi_zona: $("#cZona").value.trim(), plantilla: $("#cPlantilla").value.trim(),
    rondas_activa: $("#cRondas").checked, ver_grupo: $("#cVerGrupo").checked, buscar_palabras: $("#cBuscar").checked,
    orden_grupo: $("#cOrden").value, orden_pasos: $("#cBuscarPrimero").checked ? "buscar_primero" : "inicio_primero",
    busqueda_reciente: $("#cBusqRec").checked, horario: [$("#cH1").value || "07:30", $("#cH2").value || "23:30"],
    pausa_bloqueo_horas: +$("#cPausaH").value || 24, tiempos: leerTiempos(),
    fechas: { horas_util: +$("#fUtil").value || 48, dias_revisar: +$("#fRevisar").value || 7 },
    ventana_aparte: $("#cVentana").checked, feed_activo: $("#cFeed").checked,
    ntfy_tema: $("#cNtfy").value.trim(), webhook_url: $("#cWebhook").value.trim()
  };
  await bg("set_config", { config });
  $("#configMsg").textContent = "Guardado ✓"; setTimeout(() => $("#configMsg").textContent = "", 2200);
  setTimeout(pintarConfig, 300);
};
$("#btnRecomendados").onclick = async () => {
  if (!confirm("¿Volver todos los tiempos, descansos, topes y fechas a los valores recomendados?")) return;
  await bg("restaurar_tiempos"); setTimeout(pintarConfig, 300);
};
$("#btnProbar").onclick = async () => {
  $("#probarMsg").textContent = "Probando…";
  await bg("set_config", { config: { gemini_key: $("#cGemini").value.trim() } });
  const r = await bg("probar");
  $("#probarMsg").textContent = (r.ok ? "✓ " : "✗ ") + r.detalle;
};
$("#btnNtfyGen").onclick = () => {
  const a = new Uint8Array(8); crypto.getRandomValues(a);
  $("#cNtfy").value = "vigia-" + [...a].map(x => (x % 36).toString(36)).join("");
};
$("#btnNtfyProbar").onclick = async () => {
  $("#ntfyMsg").textContent = "Enviando…";
  await bg("set_config", { config: { ntfy_tema: $("#cNtfy").value.trim() } });
  const r = await bg("probar_ntfy");
  $("#ntfyMsg").textContent = (r.ok ? "✓ " : "✗ ") + r.detalle;
};
$("#btnRespaldo").onclick = async () => {
  const d = await bg("respaldo");
  descargar(`vigia-respaldo-${hoyStr()}.json`, JSON.stringify(d, null, 1), "application/json");
  $("#respMsg").textContent = "Descargado ✓ (la llave no va en el archivo)";
};
$("#inpRespaldo").onchange = async (e) => {
  const f = e.target.files?.[0]; if (!f) return;
  try {
    const datos = JSON.parse(await f.text());
    const r = await bg("restaurar", { datos });
    $("#respMsg").textContent = r.ok ? "Respaldo cargado ✓" : "✗ " + r.error;
    setTimeout(() => { pintarConfig(); pintarGruposTxt(); }, 400);
  } catch { $("#respMsg").textContent = "✗ ese archivo no es un respaldo del vigía"; }
  e.target.value = "";
};
$("#btnOlvidar").onclick = async () => {
  if (!confirm("Va a volver a leer publicaciones que ya revisó (puede repetir solicitudes). ¿Seguro?")) return;
  await bg("reiniciar_vistos"); $("#respMsg").textContent = "Listo ✓";
};

inicio();
