// panel.js — la pantalla del vigía (v2).
// Lee directo del almacenamiento de la extensión y se actualiza solo cuando algo cambia
// (no despierta al background a cada rato). Los cambios se los pide al background.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const bg = (accion, extra = {}) => chrome.runtime.sendMessage({ tipo: "panel", accion, ...extra });

let DEF = {}, PERFILES = {}, CONFIG = {}, ESTADO = {}, LEADS = [], BITA = [], MIR = [], GSTATS = {}, COLA = 0;
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
function haceTxt(h) {
  if (h == null) return "";
  if (h < 1) return "hace minutos";
  if (h < 24) return `hace ~${Math.round(h)} h`;
  return `hace ~${Math.round(h / 24)} d`;
}
const inicioHoy = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime(); };
const hoyStr = () => { const d = new Date(); return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`; };
const perfil = () => PERFILES[CONFIG.perfil_seguridad] || PERFILES.seguro || {};
const sinLlave = () => !CONFIG.gemini_key || CONFIG.gemini_key.startsWith("PEGA") || CONFIG.gemini_key.length < 20;
function nPalabras() {
  const n = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
  return new Set([...(CONFIG.keywords || []), ...(CONFIG.keywords_aprendidas || []).filter(x => x.estado === "activa").map(x => x.frase)].map(n)).size;
}

// ======================================================================= pestañas
function irA(t) {
  if (!$("#" + t)) return;
  $$(".tab").forEach(x => x.classList.toggle("activo", x.dataset.t === t));
  $$(".pag").forEach(x => x.classList.toggle("activo", x.id === t));
  history.replaceState(null, "", "#" + t);
  if (t === "config") pintarConfig();
  if (t === "grupos") { pintarGruposTxt(); pintarTablaGrupos(); }
  if (t === "solicitudes") pintarLeads(true);
}
$$(".tab").forEach(t => t.onclick = () => irA(t.dataset.t));
$$(".filtro").forEach(f => f.onclick = () => {
  $$(".filtro").forEach(x => x.classList.remove("activo"));
  f.classList.add("activo"); filtro = f.dataset.f; pintarLeads(true);
});
window.addEventListener("hashchange", () => irA(location.hash.slice(1)));

// ======================================================================= carga y cambios en vivo
async function inicio() {
  const r = await bg("estado");
  DEF = r.config_def || {}; PERFILES = r.perfiles || {}; CONFIG = r.config || {}; ESTADO = r.estado || {};
  const d = await chrome.storage.local.get(["leads", "bitacora", "mirados", "gstats", "cola"]);
  LEADS = d.leads || []; BITA = d.bitacora || []; MIR = d.mirados || []; GSTATS = d.gstats || {}; COLA = (d.cola || []).length;
  pintarCabecera(); pintarActividad(); pintarLeads(true); pintarPalabras(); pintarTablaGrupos();
  pintarGruposTxt(); pintarConfig();
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
    pintarCabecera(); pintarActividad();
    if (c.has("leads")) pintarLeads();
    if (c.has("config")) pintarPalabras();
    if (c.has("gstats") || c.has("config")) pintarTablaGrupos();
  }, 200);
});
setInterval(() => pintarAhora(), 1000);       // la cuenta regresiva

// ======================================================================= cabecera
function pintarCabecera() {
  const chip = $("#estadoChip");
  const pausaSeg = (ESTADO.pausa_hasta || 0) > Date.now();
  chip.textContent = !CONFIG.activo ? "Pausado" : pausaSeg ? "Pausa de seguridad" : "Activo";
  chip.className = "chip " + (!CONFIG.activo || pausaSeg ? "off" : "on");
  $("#btnActivo").textContent = CONFIG.activo ? "Pausar" : "Activar";
  const nuevas = LEADS.filter(l => l.estado === "nuevo").length;
  $("#cuentaNuevas").textContent = nuevas || "";
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

// ======================================================================= actividad
function pintarAhora() {
  const a = ESTADO.actual || {};
  const pulso = $("#pulso"), txt = $("#ahoraTxt"), sub = $("#ahoraSub");
  const nG = (CONFIG.grupos || []).length, nP = nPalabras();
  const falta = a.hasta ? a.hasta - Date.now() : 0;
  let clase = "", t = "", s = "";
  const pausaSeg = (ESTADO.pausa_hasta || 0) > Date.now();
  $("#bannerPausa").hidden = !(CONFIG.activo && pausaSeg);
  if (pausaSeg) $("#pausaTxt").textContent = `${ESTADO.pausa_motivo || "Aviso de Facebook"}. Vuelve solo a las ${horaCorta(ESTADO.pausa_hasta)} (en ${reloj(ESTADO.pausa_hasta - Date.now())}).`;

  if (!CONFIG.activo) { t = "Pausado"; s = "Dale a Activar (arriba a la derecha) para que empiece."; }
  else if (nG === 0) { clase = "alerta"; t = "Falta cargar grupos"; s = "Anda a la pestaña Grupos, pega los links y guarda."; }
  else switch (a.accion) {
    case "buscando": clase = "busca"; t = `Buscando “${a.palabra}”`; s = `en ${a.grupo} · leyendo la página…`; break;
    case "recientes": clase = "busca"; t = "Mirando lo más nuevo"; s = `en ${a.grupo} · leyendo la página…`; break;
    case "esperando": clase = "on"; t = "Atento";
      s = falta > 0 ? `Próxima mirada en ${reloj(falta)}` : "Mirando en instantes…"; break;
    case "descanso": clase = "descanso"; t = "Descansando ☕";
      s = `Como una persona, entre sesiones. Sigue a las ${horaCorta(a.hasta)} (en ${reloj(falta)}).`; break;
    case "pausa_seguridad": clase = "alerta"; t = "En pausa de seguridad";
      s = `${a.motivo || ""}. Vuelve solo a las ${horaCorta(a.hasta)}.`; break;
    case "fuera_horario": t = "Fuera de horario"; s = `Trabaja de ${CONFIG.horario?.[0]} a ${CONFIG.horario?.[1]}. Vuelve solo.`; break;
    case "limite_hora": clase = "descanso"; t = "Llegó al máximo de esta hora"; s = `Para cuidar tu cuenta. Sigue a las ${horaCorta(a.hasta)} (en ${reloj(falta)}).`; break;
    case "limite_dia": clase = "descanso"; t = "Llegó al máximo de hoy"; s = "Mañana sigue solo. El ritmo se cambia en Configuración."; break;
    case "limite_busq": clase = "descanso"; t = "Usó las búsquedas permitidas"; s = `Sigue a las ${horaCorta(a.hasta)}.`; break;
    case "sin_internet": clase = "alerta"; t = "Sin internet"; s = "Espera a que vuelva la conexión."; break;
    case "solo_inicio": clase = "on"; t = "Solo leyendo lo que navegas"; s = "El recorrido automático está apagado en Configuración."; break;
    case "sin_datos": clase = "alerta";
      t = a.falta === "acceso" ? "Ningún grupo disponible" : a.falta === "modo" ? "No tiene qué hacer" : "Faltan datos";
      s = a.falta === "acceso" ? "Todos tus grupos salieron sin acceso. Revisa la pestaña Grupos." : "Activa “mirar lo más nuevo” o “buscar palabras” en Configuración."; break;
    default: clase = "on"; t = "Arrancando…"; s = "En unos segundos parte.";
  }
  pulso.className = "pulso " + clase;
  txt.textContent = t;
  sub.textContent = s;
  if (CONFIG.activo && sinLlave() && nG) sub.textContent += " · sin llave de IA: decide con reglas simples";
  if (nP === 0 && CONFIG.buscar_palabras) sub.textContent += " · sin palabras para buscar";
}

function pintarActividad() {
  pintarAhora();
  const p = perfil();
  const chip = (ok, txt) => `<span class="chip ${ok === true ? "on" : ok === false ? "off" : ""}">${txt}</span>`;
  const nG = (CONFIG.grupos || []).length;
  $("#salud").innerHTML = [
    chip(!sinLlave(), `IA ${sinLlave() ? "✗ sin llave" : "✓"}`),
    chip(nG > 0, `Grupos <b>${nG}</b>`),
    chip(nPalabras() > 0, `Palabras <b>${nPalabras()}</b>`),
    chip(null, `Ritmo <b>${p.nombre || "—"}</b>`),
    chip(null, `Horario ${CONFIG.horario?.[0] || ""}–${CONFIG.horario?.[1] || ""}`),
    chip(CONFIG.ntfy_tema ? true : null, CONFIG.ntfy_tema ? "Celular ✓" : "Celular —"),
    chip(null, CONFIG.ventana_aparte ? "Ventanita aparte" : "Pestaña fija")
  ].join("");

  const u = ESTADO.uso || {};
  const hoy = u.dia === hoyStr();
  const enHora = (u.mv || []).filter(t => Date.now() - t < 3600000).length;
  const barra = (id, idt, v, max) => {
    const f = max ? Math.min(1, v / max) : 0;
    const i = $(id); i.style.width = (f * 100).toFixed(0) + "%";
    i.className = f >= 1 ? "lleno" : f >= 0.75 ? "medio" : "";
    $(idt).textContent = `${v} / ${max}`;
  };
  barra("#bHora", "#tHora", enHora, p.max_hora);
  barra("#bDia", "#tDia", hoy ? u.v_dia || 0 : 0, p.max_dia);
  barra("#bBusq", "#tBusq", hoy ? u.b_dia || 0 : 0, p.max_busq_dia);

  const h0 = inicioHoy();
  $("#sGrupos").textContent = `${(CONFIG.grupos || []).filter(g => (GSTATS[g.id]?.ultima || 0) >= h0).length}/${nG}`;
  $("#sVistos").textContent = ESTADO.cont?.vistos || 0;
  $("#sPegas").textContent = ESTADO.cont?.pegas || 0;
  $("#sCola").textContent = COLA;

  const icon = { ronda: "🔎", recientes: "🕒", resultado: "✓", inicio: "🏠", ia: "🤖", pega: "⚡", seguridad: "🛡️", descanso: "☕", error: "⚠️", info: "·" };
  $("#bitacora").innerHTML = BITA.length ? BITA.slice(0, 250).map(b =>
    `<div class="bl ${esc(b.tipo)}"><span class="h">${hora(b.t)}</span><span class="x">${icon[b.tipo] || "·"} ${esc(b.texto)}</span></div>`).join("")
    : '<div class="dim" style="padding:6px">Todavía no hace nada. Actívalo arriba.</div>';

  const etq = { pega: "PEGA", no: "no", vieja: "vieja" };
  $("#mirados").innerHTML = MIR.length ? MIR.slice(0, 60).map(m =>
    `<div class="mir"><span class="v ${esc(m.veredicto)}">${etq[m.veredicto] || esc(m.veredicto)}</span>
      <div><b>${esc(m.autor || "—")}</b> <span class="dim">· ${esc(m.grupo)} · ${esc(m.via)} · ${hora(m.t)}</span>
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
  const lista = LEADS.filter(l => filtro === "todos" ? true : l.estado === filtro).slice(0, 300);
  $("#vacioLeads").style.display = lista.length ? "none" : "block";
  for (const l of lista) {
    const n = $("#tplLead").content.cloneNode(true);
    const card = $(".lead", n);
    $(".tipo", n).textContent = l.tipo === "gasfiteria" ? "gasfitería" : (l.tipo || "pega");
    if (l.urgencia) { const u = $(".urg", n); u.textContent = l.urgencia === "alta" ? "urgente" : l.urgencia; u.classList.add(l.urgencia); }
    if (l.sin_ia) $(".sinia", n).hidden = false;
    $(".meta", n).textContent = [l.grupo, l.comuna, l.via, l.edad_h != null ? haceTxt(l.edad_h + (Date.now() - Date.parse(l.creado)) / 3600000) : "", "visto " + fecha(l.creado)].filter(Boolean).join(" · ");
    $(".autor", n).innerHTML = l.autor_url ? `<a href="${esc(l.autor_url)}" target="_blank" rel="noopener">${esc(l.autor || "(sin nombre)")}</a>` : esc(l.autor || "(sin nombre)");
    $(".texto", n).textContent = l.resumen && !l.sin_ia ? (l.resumen + "\n\n" + l.texto) : l.texto;
    if (l.otros_grupos?.length) { const o = $(".otros", n); o.hidden = false; o.textContent = "También lo publicó en: " + l.otros_grupos.join(", "); }
    const msg = $(".msg", n);
    msg.value = l.mensaje || "";
    msg.addEventListener("change", () => bg("lead_mensaje", { id: l.id, mensaje: msg.value }));
    msg.addEventListener("blur", () => { if (leadsPendiente) setTimeout(() => pintarLeads(), 50); });
    const abrir = $(".abrir", n);
    if (l.url) abrir.href = l.url; else { abrir.style.display = "none"; $(".copiarAbrir", n).style.display = "none"; }
    $(".copiar", n).onclick = async (e) => { await navigator.clipboard.writeText(msg.value); e.target.textContent = "¡Copiado!"; setTimeout(() => e.target.textContent = "Copiar mensaje", 1500); };
    $(".copiarAbrir", n).onclick = async () => { await navigator.clipboard.writeText(msg.value); chrome.tabs.create({ url: l.url, active: true }); };
    $(".ok", n).onclick = () => cambiarLead(l.id, "contactado");
    $(".desc", n).onclick = () => cambiarLead(l.id, "descartado");
    if (l.estado !== "nuevo") $(l.estado === "contactado" ? ".ok" : ".desc", n).textContent = "✓ " + (l.estado === "contactado" ? "Contactado" : "Descartado");
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
  const cols = [["creado", "Visto"], ["publicado", "Publicado aprox."], ["estado", "Estado"], ["tipo", "Tipo"], ["urgencia", "Urgencia"],
    ["comuna", "Comuna"], ["resumen", "Resumen"], ["autor", "Autor"], ["autor_url", "Perfil"], ["grupo", "Grupo"], ["via", "Cómo"],
    ["url", "Link"], ["mensaje", "Mensaje"], ["texto", "Texto"]];
  const celda = (v) => `"${String(v ?? "").replace(/"/g, '""').replace(/\r?\n/g, " ")}"`;
  const lista = LEADS.filter(l => filtro === "todos" ? true : l.estado === filtro);
  const filas = [cols.map(c => celda(c[1])).join(";"),
    ...lista.map(l => cols.map(([k]) => celda(k === "creado" || k === "publicado" ? (l[k] ? fecha(l[k]) : "") : l[k])).join(";"))];
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

function pintarTablaGrupos() {
  const filas = (CONFIG.grupos || []).map(g => ({ g, s: GSTATS[g.id] || {} }))
    .sort((a, b) => (b.s.pegas || 0) - (a.s.pegas || 0) || (b.s.visitas || 0) - (a.s.visitas || 0) || a.g.nombre.localeCompare(b.g.nombre))
    .slice(0, 600);
  $("#tablaGrupos").innerHTML = filas.map(({ g, s }) => {
    const sinAcc = s.sin_acceso && Date.now() - s.sin_acceso < 7 * 86400000;
    const est = sinAcc ? `<span class="mal">sin acceso</span> <button class="btn chico fantasma reint" data-id="${esc(g.id)}">Reintentar</button>`
      : s.ultimo_estado === "vacío" ? `<span class="mal">no mostró posts</span>`
      : s.ultimo_estado && s.ultimo_estado !== "ok" ? `<span class="mal">${esc(s.ultimo_estado)}</span>`
      : s.visitas ? `<span class="bien">ok</span>` : `<span class="dim">pendiente</span>`;
    return `<tr><td><a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.nombre)}</a></td><td>${s.visitas || 0}</td>
      <td>${s.ultima ? fecha(s.ultima) : "—"}</td><td>${s.vistas || 0}</td><td>${s.pegas ? "<b>" + s.pegas + "</b>" : 0}</td><td>${est}</td></tr>`;
  }).join("") || '<tr><td colspan="6" class="dim">Sin grupos todavía.</td></tr>';
  $$(".reint").forEach(b => b.onclick = () => bg("grupo_reintentar", { id: b.dataset.id }));
}

// ======================================================================= palabras
function pintarPalabras() {
  $("#nCada").textContent = `1 de cada ${CONFIG.busqueda_cada || 3}`;
  const cont = $("#chipsKw"); cont.innerHTML = "";
  for (const k of (CONFIG.keywords || [])) {
    const el = document.createElement("span"); el.className = "kw"; el.textContent = k;
    el.title = "Quitar";
    el.onclick = () => bg("kw_del", { texto: k });
    cont.appendChild(el);
  }
  const ap = $("#aprendidas"); ap.innerHTML = "";
  const props = (CONFIG.keywords_aprendidas || []).filter(x => x.estado !== "descartada").sort((a, b) => b.veces - a.veces);
  if (!props.length) ap.innerHTML = '<p class="dim">Nada aprendido todavía.</p>';
  for (const a of props) {
    const row = document.createElement("div"); row.className = "apr";
    row.innerHTML = `<span class="f">${esc(a.frase)}</span><span class="v">visto ${a.veces}× · ${a.estado === "activa" ? "la busca" : "propuesta"}</span>`;
    const ok = document.createElement("button"); ok.className = "btn chico"; ok.textContent = a.estado === "activa" ? "✓ activa" : "Activar";
    ok.onclick = () => bg("kw_aprendida", { frase: a.frase, estado: "activa" });
    const no = document.createElement("button"); no.className = "btn chico fantasma"; no.textContent = "No";
    no.onclick = () => bg("kw_aprendida", { frase: a.frase, estado: "descartada" });
    row.append(ok, no); ap.appendChild(row);
  }
}
$("#btnKw").onclick = async () => { const v = $("#inpKw").value.trim(); if (!v) return; await bg("kw_add", { texto: v }); $("#inpKw").value = ""; };
$("#inpKw").addEventListener("keydown", e => { if (e.key === "Enter") $("#btnKw").click(); });

// ======================================================================= configuración
function textoPerfil(k) {
  const p = PERFILES[k] || {};
  const extra = k === "seguro" ? " Recomendado para partir." : k === "rapido" ? " ⚠️ Más riesgo: úsalo solo si llevas semanas sin avisos de Facebook." : "";
  return `Una mirada cada ~${p.min_entre} min · máx ${p.max_hora} por hora y ${p.max_dia} por día · búsquedas máx ${p.max_busq_hora}/hora y ${p.max_busq_dia}/día · descansa ~${p.descanso_min} min cada ~${p.sesion_min} min.${extra}`;
}
function pintarConfig() {
  const sel = $("#cPerfil");
  sel.innerHTML = Object.entries(PERFILES).map(([k, p]) => `<option value="${k}">${esc(p.nombre)}</option>`).join("");
  sel.value = CONFIG.perfil_seguridad || "seguro";
  $("#perfilTxt").textContent = textoPerfil(sel.value);
  $("#cGemini").value = CONFIG.gemini_key || "";
  $("#cNombre").value = CONFIG.mi_nombre || "";
  $("#cFono").value = CONFIG.mi_fono || "";
  $("#cRubro").value = CONFIG.mi_rubro || "";
  $("#cZona").value = CONFIG.mi_zona || "";
  $("#cPlantilla").value = CONFIG.plantilla || "";
  $("#cH1").value = CONFIG.horario?.[0] || "07:30";
  $("#cH2").value = CONFIG.horario?.[1] || "23:30";
  $("#cPausaH").value = CONFIG.pausa_bloqueo_horas || 24;
  $("#cRondas").checked = CONFIG.rondas_activa !== false;
  $("#cRecientes").checked = CONFIG.ver_recientes !== false;
  $("#cBuscar").checked = CONFIG.buscar_palabras !== false;
  $("#cCada").value = CONFIG.busqueda_cada || 3;
  $("#cBusqRec").checked = !!CONFIG.busqueda_reciente;
  $("#cFeed").checked = CONFIG.feed_activo !== false;
  $("#cDias").value = CONFIG.dias_antiguedad || 7;
  $("#cVentana").checked = !!CONFIG.ventana_aparte;
  $("#cNtfy").value = CONFIG.ntfy_tema || "";
  $("#cWebhook").value = CONFIG.webhook_url || "";
}
$("#cPerfil").onchange = () => { $("#perfilTxt").textContent = textoPerfil($("#cPerfil").value); };
function leerConfig() {
  return {
    gemini_key: $("#cGemini").value.trim(), mi_nombre: $("#cNombre").value.trim(), mi_fono: $("#cFono").value.trim(),
    mi_rubro: $("#cRubro").value.trim(), mi_zona: $("#cZona").value.trim(), plantilla: $("#cPlantilla").value.trim(),
    perfil_seguridad: $("#cPerfil").value, horario: [$("#cH1").value || "07:30", $("#cH2").value || "23:30"],
    pausa_bloqueo_horas: +$("#cPausaH").value || 24,
    rondas_activa: $("#cRondas").checked, ver_recientes: $("#cRecientes").checked, buscar_palabras: $("#cBuscar").checked,
    busqueda_cada: +$("#cCada").value || 3, busqueda_reciente: $("#cBusqRec").checked, feed_activo: $("#cFeed").checked,
    dias_antiguedad: +$("#cDias").value || 7, ventana_aparte: $("#cVentana").checked,
    ntfy_tema: $("#cNtfy").value.trim(), webhook_url: $("#cWebhook").value.trim()
  };
}
$("#btnConfig").onclick = async () => {
  await bg("set_config", { config: leerConfig() });
  $("#configMsg").textContent = "Guardado ✓"; setTimeout(() => $("#configMsg").textContent = "", 2200);
  setTimeout(pintarConfig, 300);
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
