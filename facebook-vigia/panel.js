// panel.js — la pantalla donde ves las solicitudes, apruebas palabras y configuras todo.
// Todo pasa por el background con mensajes {tipo:'panel', accion:...}.

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const bg = (accion, extra = {}) => chrome.runtime.sendMessage({ tipo: "panel", accion, ...extra });

let CONFIG = {}, LEADS = [], filtro = "nuevo";

// ---------------- navegación de pestañas
$$(".tab").forEach(t => t.onclick = () => {
  $$(".tab").forEach(x => x.classList.remove("activo"));
  $$(".pag").forEach(x => x.classList.remove("activo"));
  t.classList.add("activo");
  $("#" + t.dataset.t).classList.add("activo");
});
$$(".filtro").forEach(f => f.onclick = () => {
  $$(".filtro").forEach(x => x.classList.remove("activo"));
  f.classList.add("activo"); filtro = f.dataset.f; pintarLeads();
});

// ---------------- cargar estado
async function cargar() {
  const r = await bg("estado");
  CONFIG = r.config; LEADS = r.leads || [];
  pintarEstado(r);
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
$("#btnRonda").onclick = async () => { await bg("forzar_ronda"); $("#btnRonda").textContent = "Buscando…"; setTimeout(() => $("#btnRonda").textContent = "Buscar ahora", 4000); };

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

// refresco suave de solicitudes
setInterval(async () => { const r = await bg("estado"); LEADS = r.leads || []; CONFIG = r.config; pintarEstado(r); if ($("#solicitudes").classList.contains("activo")) pintarLeads(); }, 15000);
cargar();
