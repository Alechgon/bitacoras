// panel.js — la pantalla donde ves las solicitudes, apruebas palabras y configuras todo.
// Todo pasa por el background con mensajes {tipo:'panel', accion:...}.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const bg = (accion, extra = {}) => chrome.runtime.sendMessage({ tipo: "panel", accion, ...extra });

let CONFIG = {}, LEADS = [], ESTADO = {}, BITACORA = [], MIRADOS = [], filtro = "nuevo";

// ---------------- navegación de pestañas
$$(".tab").forEach(t => t.onclick = () => {
  $$(".tab").forEach(x => x.classList.remove("activo"));
  $$(".pag").forEach(x => x.classList.remove("activo"));
  t.classList.add("activo");
  $("#" + t.dataset.t).classList.add("activo");
  cargar();
});
$$(".filtro").forEach(f => f.onclick = () => {
  $$(".filtro").forEach(x => x.classList.remove("activo"));
  f.classList.add("activo"); filtro = f.dataset.f; pintarLeads();
});

// ---------------- cargar estado
async function cargar() {
  const r = await bg("estado");
  CONFIG = r.config; LEADS = r.leads || []; ESTADO = r.estado || {}; BITACORA = r.bitacora || []; MIRADOS = r.mirados || [];
  pintarEstado(r);
  pintarActividad();
  pintarLeads();
  pintarGrupos();
  pintarPalabras();
  pintarConfig();
}

function pintarEstado(r) {
  const chip = $("#estadoChip");
  chip.textContent = CONFIG.activo ? "Activo" : "Pausado";
  chip.className = "chip " + (CONFIG.activo ? "on" : "off");
  $("#btnActivo").textContent = CONFIG.activo ? "Pausar" : "Activar";
  const nuevas = LEADS.filter(l => l.estado === "nuevo").length;
  $("#cuentaNuevas").textContent = nuevas || "";
}

$("#btnActivo").onclick = async () => { await bg("set_config", { config: { activo: !CONFIG.activo } }); cargar(); };
$("#btnRonda").onclick = async () => { await bg("forzar_ronda"); $("#btnRonda").textContent = "Buscando…"; setTimeout(() => { $("#btnRonda").textContent = "Buscar ahora"; cargar(); }, 3000); };

// ---------------- actividad (en vivo)
function dos(n) { return String(n).padStart(2, "0"); }
function pintarActividad() {
  const a = ESTADO.actual || {};
  const pulso = $("#pulso"); const txt = $("#ahoraTxt"); const sub = $("#ahoraSub");
  pulso.className = "pulso";
  if (!CONFIG.activo || a.accion === "pausado") { txt.textContent = "Pausado"; sub.textContent = "Dale a Activar arriba para que empiece a revisar."; }
  else if (a.accion === "buscando") { pulso.classList.add("busca"); txt.textContent = `Buscando “${a.palabra}”`; sub.textContent = `en ${a.grupo}`; }
  else if (a.accion === "recientes") { pulso.classList.add("busca"); txt.textContent = `Mirando lo reciente`; sub.textContent = `en ${a.grupo}`; }
  else if (a.accion === "fuera_horario") { txt.textContent = "En pausa por horario"; sub.textContent = `Trabaja de ${(CONFIG.horario || [])[0]} a ${(CONFIG.horario || [])[1]}.`; }
  else if (a.accion === "sin_datos") { txt.textContent = "Falta configurar"; sub.textContent = "Agrega grupos y palabras para que empiece."; }
  else {  // esperando
    pulso.classList.add("on");
    const falta = Math.max(0, Math.round(((ESTADO.ultima || 0) + (CONFIG.minutos_entre || 2) * 60000 - Date.now()) / 1000));
    const prox = ESTADO.proximo || {};
    txt.textContent = "Atento";
    sub.textContent = (falta > 0 ? `Próxima búsqueda en ${dos(Math.floor(falta / 60))}:${dos(falta % 60)}` : "Buscando en instantes") +
      (prox.grupo ? ` · sigue: ${prox.grupo}${prox.palabra ? " (" + prox.palabra + ")" : ""}` : "") +
      (ESTADO.ultimo_feed ? ` · inicio leído ${hace(ESTADO.ultimo_feed)}` : "");
  }
  $("#sRevisados").textContent = ESTADO.revisados || 0;
  $("#sVistos").textContent = ESTADO.posts_vistos || 0;
  $("#sPegas").textContent = ESTADO.solicitudes || 0;
  $("#sVuelta").textContent = ESTADO.vuelta || 0;

  const icon = { ronda: "🔎", resultado: "✓", inicio: "🏠", error: "⚠️" };
  $("#bitacora").innerHTML = BITACORA.length ? BITACORA.map(b =>
    `<div class="bl ${b.tipo}"><span class="h">${hora(b.t)}</span><span class="x">${icon[b.tipo] || "·"} ${esc(b.texto)}</span></div>`).join("")
    : '<div class="dim" style="padding:6px">Todavía no hace nada. Actívalo arriba.</div>';

  $("#mirados").innerHTML = MIRADOS.length ? MIRADOS.map(m =>
    `<div class="mir"><span class="v ${m.veredicto}">${m.veredicto === "pega" ? "PEGA" : "no"}</span>
      <div><b>${esc(m.autor || "—")}</b> <span class="dim">· ${esc(m.grupo)} · ${esc(m.via)} · ${hora(m.t)}</span>
      <div>${esc(m.snippet || "")}</div></div></div>`).join("")
    : '<div class="dim">Nada todavía.</div>';
}
function hora(t) { try { return new Date(t).toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return ""; } }
function hace(t) { const s = Math.round((Date.now() - t) / 1000); return s < 60 ? `hace ${s}s` : `hace ${Math.round(s / 60)} min`; }
function esc(s) { return String(s || "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
$("#btnLimpiarBita").onclick = async () => { await bg("limpiar_bitacora"); cargar(); };

// ---------------- solicitudes (leads)
function pintarLeads() {
  const cont = $("#listaLeads");
  cont.innerHTML = "";
  const lista = LEADS.filter(l => filtro === "todos" ? true : l.estado === filtro);
  $("#vacioLeads").style.display = lista.length ? "none" : "block";
  for (const l of lista) {
    const n = $("#tplLead").content.cloneNode(true);
    $(".tipo", n).textContent = l.tipo || "pega";
    if (l.urgencia) { const u = $(".urg", n); u.textContent = l.urgencia; u.classList.add(l.urgencia); }
    $(".meta", n).textContent = [l.grupo, l.comuna, l.via, fecha(l.creado)].filter(Boolean).join(" · ");
    $(".autor", n).textContent = l.autor || "(sin nombre)";
    $(".texto", n).textContent = l.resumen ? (l.resumen + "\n\n" + l.texto) : l.texto;
    $(".msg", n).value = l.mensaje || "";
    const abrir = $(".abrir", n); abrir.href = l.url || "#"; if (!l.url) abrir.style.display = "none";
    $(".copiar", n).onclick = (e) => { navigator.clipboard.writeText($(".msg", e.target.closest(".lead")).value); e.target.textContent = "¡Copiado!"; setTimeout(() => e.target.textContent = "Copiar mensaje", 1500); };
    $(".ok", n).onclick = () => cambiarLead(l.id, "contactado");
    $(".desc", n).onclick = () => cambiarLead(l.id, "descartado");
    cont.appendChild(n);
  }
}
async function cambiarLead(id, estado) {
  await bg("lead_estado", { id, estado });
  const l = LEADS.find(x => x.id === id); if (l) l.estado = estado;
  pintarEstado({}); pintarLeads();
}
$("#btnLimpiar").onclick = async () => { await bg("borrar_leads", { cuales: "descartado" }); cargar(); };

function fecha(iso) { try { return new Date(iso).toLocaleString("es-CL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return ""; } }

// ---------------- grupos
function pintarGrupos() {
  $("#txtGrupos").value = (CONFIG.grupos || []).map(g => g.url + (g.nombre && g.nombre !== g.id ? " | " + g.nombre : "")).join("\n");
  $("#nGrupos").textContent = (CONFIG.grupos || []).length + " grupos cargados";
}
$("#btnGrupos").onclick = async () => {
  const r = await bg("grupos_set", { texto: $("#txtGrupos").value });
  $("#nGrupos").textContent = r.n + " grupos cargados ✓"; cargar();
};

// ---------------- palabras
function pintarPalabras() {
  const cont = $("#chipsKw"); cont.innerHTML = "";
  for (const k of (CONFIG.keywords || [])) {
    const el = document.createElement("span"); el.className = "kw"; el.textContent = k;
    el.onclick = async () => { await bg("kw_del", { texto: k }); cargar(); };
    cont.appendChild(el);
  }
  const ap = $("#aprendidas"); ap.innerHTML = "";
  const props = (CONFIG.keywords_aprendidas || []).filter(x => x.estado !== "descartada");
  if (!props.length) ap.innerHTML = '<p class="dim">Nada aprendido todavía.</p>';
  for (const a of props) {
    const row = document.createElement("div"); row.className = "apr";
    row.innerHTML = `<span class="f">${a.frase}</span><span class="v">visto ${a.veces}× · ${a.estado}</span>`;
    const ok = document.createElement("button"); ok.className = "btn chico"; ok.textContent = a.estado === "activa" ? "✓ activa" : "Activar";
    ok.onclick = async () => { await bg("kw_aprendida", { frase: a.frase, estado: "activa" }); cargar(); };
    const no = document.createElement("button"); no.className = "btn chico fantasma"; no.textContent = "No";
    no.onclick = async () => { await bg("kw_aprendida", { frase: a.frase, estado: "descartada" }); cargar(); };
    row.append(ok, no); ap.appendChild(row);
  }
}
$("#btnKw").onclick = async () => { await bg("kw_add", { texto: $("#inpKw").value }); $("#inpKw").value = ""; cargar(); };
$("#inpKw").addEventListener("keydown", e => { if (e.key === "Enter") $("#btnKw").click(); });

// ---------------- config
function pintarConfig() {
  $("#cGemini").value = CONFIG.gemini_key || "";
  $("#cNombre").value = CONFIG.mi_nombre || "";
  $("#cFono").value = CONFIG.mi_fono || "";
  $("#cRubro").value = CONFIG.mi_rubro || "";
  $("#cZona").value = CONFIG.mi_zona || "";
  $("#cPlantilla").value = CONFIG.plantilla || "";
  $("#cMin").value = CONFIG.minutos_entre || 4;
  $("#cH1").value = (CONFIG.horario || [])[0] || "08:00";
  $("#cH2").value = (CONFIG.horario || [])[1] || "23:00";
  $("#cFeed").checked = CONFIG.feed_activo !== false;
  $("#cRondas").checked = CONFIG.rondas_activa !== false;
  $("#cRecientes").checked = CONFIG.ver_recientes !== false;
  $("#cWebhook").value = CONFIG.webhook_url || "";
}
$("#btnConfig").onclick = async () => {
  const config = {
    gemini_key: $("#cGemini").value.trim(), mi_nombre: $("#cNombre").value.trim(),
    mi_fono: $("#cFono").value.trim(), mi_rubro: $("#cRubro").value.trim(), mi_zona: $("#cZona").value.trim(),
    plantilla: $("#cPlantilla").value.trim(), minutos_entre: Math.max(2, +$("#cMin").value || 4),
    horario: [$("#cH1").value || "08:00", $("#cH2").value || "23:00"],
    feed_activo: $("#cFeed").checked, rondas_activa: $("#cRondas").checked,
    ver_recientes: $("#cRecientes").checked, webhook_url: $("#cWebhook").value.trim()
  };
  await bg("set_config", { config });
  $("#configMsg").textContent = "Guardado ✓"; setTimeout(() => $("#configMsg").textContent = "", 2000);
  cargar();
};
$("#btnProbar").onclick = async () => {
  $("#probarMsg").textContent = "Probando…";
  await bg("set_config", { config: { gemini_key: $("#cGemini").value.trim(), gemini_endpoint: CONFIG.gemini_endpoint || "auto" } });
  const r = await bg("probar");
  $("#probarMsg").textContent = (r.ok ? "✓ " : "✗ ") + r.detalle;
};

// refresco en vivo: rápido si estás mirando la Actividad; más lento en otras pestañas
setInterval(async () => {
  const enActividad = $("#actividad").classList.contains("activo");
  const enSolic = $("#solicitudes").classList.contains("activo");
  if (!enActividad && !enSolic) return;
  const r = await bg("estado");
  CONFIG = r.config; LEADS = r.leads || []; ESTADO = r.estado || {}; BITACORA = r.bitacora || []; MIRADOS = r.mirados || [];
  pintarEstado(r);
  if (enActividad) pintarActividad();
  if (enSolic) pintarLeads();
}, 1300);
cargar();
