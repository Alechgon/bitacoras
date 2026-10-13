// filtro.js — reglas locales, sin IA.
//  - prefiltro(): decide si vale la pena gastar la IA en una publicación (oficio + alguien pidiendo).
//  - clasificarLocal(): si no hay llave de Gemini (o la IA está en límite), decide con reglas.
//  - plantilla(): mensaje base para escribirle a la persona.

export const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

const OFICIO = new RegExp("\\b(" + [
  "electric\\w*", "electricist\\w*", "luz", "luces", "enchufe\\w*", "tablero\\w*", "automatico\\w*", "disyuntor\\w*",
  "diferencial\\w*", "corto ?circuito\\w*", "cable\\w*", "cableado", "instalacion(es)? electric\\w*", "foco\\w*",
  "lampara\\w*", "ampolleta\\w*", "interruptor\\w*", "medidor\\w*", "empalme", "gasfit\\w*", "plomer\\w*",
  "caneria\\w*", "filtracion\\w*", "fuga\\w*", "gotera\\w*", "llave\\w*", "grifo\\w*", "wc", "inodoro\\w*",
  "desague\\w*", "destap\\w*", "alcantarill\\w*", "calefon\\w*", "califon\\w*", "termo\\w*", "calefactor\\w*",
  "gas", "cilindro\\w*", "regulador\\w*", "estanque\\w*", "ducha\\w*", "lavaplato\\w*", "lavamano\\w*", "sifon\\w*",
  "agua caliente", "bomba de agua", "presion del agua", "sin agua", "cocina a gas", "maestro\\w*", "tecnico\\w*"
].join("|") + ")\\b");

const PIDE = new RegExp("\\b(" + [
  "busco", "buscamos", "buscando", "necesito", "necesitamos", "necesita", "se necesita", "se busca", "requiero",
  "requerimos", "alguien (que )?(sepa|haga|pueda|conozca|me ayude|arregle|repare|instale|vea)", "recomiend\\w*",
  "recomendacion\\w*", "datos? de", "dato de", "un dato", "urgente", "urgencia",
  "quien (me )?(puede|podria|pueda|sabe|haga|arregle|repare|instale)", "cotiz\\w*", "presupuesto", "ayuda con",
  "me pueden ayudar", "me ayudan", "cuanto (cobran|cobra|sale|cuesta)", "conocen (a )?(alg|un)", "algun maestro", "un maestro", "maestro que",
  "un gasfiter", "un electricista", "un tecnico", "necesito que", "alguien sabe", "alguien conoce", "alguien tiene",
  "se me (corto|echo|rompio|quemo|tapo)", "me quede sin", "nos quedamos sin"
].join("|") + ")\\b");

// Más amplio: solo decide si vale la pena preguntarle a la IA (ella separa lo que no es pega).
const PIDE_AMPLIO = new RegExp("\\b(" + [
  "alguien", "ayuda", "ayudenme", "consulta", "por favor", "favor", "que (puedo|hago|me recomiendan)",
  "como (lo )?(arreglo|reparo|soluciono|cambio)", "donde (encuentro|consigo)",
  "valor", "precio", "se (corto|echo|rompio|quemo|tapo|salta|cae|gotea)", "no (prende|enciende|funciona|calienta|sale)",
  "tengo (una|un) (fuga|filtracion|problema|corto)", "hay olor a gas", "olor a gas", "salta el automatico"
].join("|") + ")\\b");

const OFRECE =/\b(ofrezco|ofrecemos|realizo|realizamos|hago trabajos|hacemos trabajos|sin costo|contactame|contactanos|nuestra empresa|garantia|instalamos|reparamos|atendemos|servicios? de|disponible para|a domicilio|precios? (convenientes?|economicos?|justos?)|anos de experiencia|experiencia comprobada|presupuestos? gratis|llamar al|agenda tu|agendar hora|certificad[oa]s?|sec clase)\b/g;

export function prefiltro(texto, cfg = {}) {
  const n = norm(texto);
  if (n.length < 12) return false;
  const oficio = OFICIO.test(n);
  if (oficio && (PIDE.test(n) || PIDE_AMPLIO.test(n))) return true;
  // frases que tú agregaste o que el vigía aprendió (si traen algo del oficio)
  const propias = [...(cfg.keywords || []), ...((cfg.keywords_aprendidas || []).filter(x => x.estado === "activa").map(x => x.frase))]
    .map(norm).filter(k => k.length >= 6 && k.includes(" "));
  return oficio && propias.some(k => n.includes(k));
}

export function puntajeOferta(texto) {
  return (norm(texto).match(OFRECE) || []).length;
}

export function plantilla(cfg = {}) {
  const nom = cfg.mi_nombre ? `soy ${cfg.mi_nombre}, ` : "";
  const zona = cfg.mi_zona ? ` en ${cfg.mi_zona}` : "";
  const fono = cfg.mi_fono ? ` Si prefieres, mi fono es ${cfg.mi_fono}.` : "";
  return `Hola! ${nom}vi tu publicación. Me dedico a ${cfg.mi_rubro || "electricidad y gasfitería"}${zona}. ` +
         `¿Me cuentas un poco más qué necesitas y de qué comuna eres?${fono}`;
}

export function clasificarLocal(texto, cfg = {}) {
  const n = norm(texto);
  const es = OFICIO.test(n) && PIDE.test(n) && puntajeOferta(texto) < 2;
  const gasf = /(gas\b|gasfit|plomer|caneria|filtrac|fuga|gotera|llave|wc|inodoro|desague|destap|calefon|califon|ducha|lavaplato|lavamano|sifon|agua)/.test(n);
  const elec = /(electric|luz|luces|enchufe|tablero|automatic|disyuntor|cable|foco|ampolleta|interruptor|medidor|empalme|corto ?circuito)/.test(n);
  return {
    es_solicitud: es,
    tipo: gasf && elec ? "ambos" : gasf ? "gasfiteria" : elec ? "electricidad" : "otro",
    resumen: String(texto || "").replace(/\s+/g, " ").slice(0, 80),
    comuna: "",
    urgencia: /(urgente|urgencia|emergencia|hoy mismo|lo antes posible|ahora ya|cuanto antes)/.test(n) ? "alta" : "media",
    mensaje: plantilla(cfg),
    frases_clave: [],
    sin_ia: true
  };
}
