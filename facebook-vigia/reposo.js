// reposo.js — lo que muestra la pestaña del vigía entre una mirada y la siguiente.
let EST = {}, ACT = false;
const dos = (n) => String(n).padStart(2, "0");
const TXT = {
  pausado: "Pausado. Actívalo desde el panel.",
  fuera_horario: "Fuera de horario. Vuelve solo.",
  descanso: "Descansando, como una persona.",
  pausa_seguridad: "En pausa de seguridad.",
  limite_hora: "Llegó al tope de grupos de esta hora.",
  limite_dia: "Llegó al tope de grupos de hoy. Mañana sigue.",
  limite_busq: "Usó las búsquedas permitidas por ahora.",
  esperando: "Siguiente grupo en",
  entre_pasos: "Siguiente paso en",
  sin_internet: "Sin internet."
};
function pintar() {
  const a = EST.actual || {};
  const falta = a.hasta ? Math.max(0, Math.round((a.hasta - Date.now()) / 1000)) : 0;
  const reloj = falta >= 3600 ? `${Math.floor(falta / 3600)}h ${dos(Math.floor(falta % 3600 / 60))}m` : `${dos(Math.floor(falta / 60))}:${dos(falta % 60)}`;
  document.getElementById("cuenta").textContent = !ACT ? "Pausado" : (a.hasta ? reloj : "…");
  document.getElementById("que").textContent = ACT ? (TXT[a.accion] || "Trabajando…") + (a.motivo ? ` (${a.motivo})` : "") : TXT.pausado;
}
async function cargar() {
  const r = await chrome.storage.local.get(["estado", "config"]);
  EST = r.estado || {}; ACT = !!(r.config || {}).activo;
  pintar();
}
chrome.storage.onChanged.addListener((ch) => { if (ch.estado || ch.config) cargar(); });
document.getElementById("panel").onclick = () => chrome.tabs.create({ url: chrome.runtime.getURL("panel.html") });
setInterval(pintar, 1000);
cargar();
