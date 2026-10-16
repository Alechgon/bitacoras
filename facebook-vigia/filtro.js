// filtro.js — reglas locales, sin IA.
//  - prefiltro(): decide si vale la pena gastar la IA en una publicación (oficio + alguien pidiendo). Amplio.
//  - clasificarLocal(): si no hay IA (sin llave o Gemini caído), decide con reglas ESTRICTAS
//    (mejor dejar pasar una que llenarte de ventas y trueques).
//  - plantilla(): mensaje base para escribirle a la persona.

export const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
const rx = (lista) => new RegExp("\\b(" + lista.join("|") + ")\\b");

// palabras de oficio (amplio, para el prefiltro)
const OFICIO = rx([
  "electric\\w*", "luz", "luces", "enchufe\\w*", "tablero\\w*", "automatico\\w*", "disyuntor\\w*", "diferencial\\w*",
  "corto ?circuito\\w*", "cable\\w*", "cableado", "foco\\w*", "lampara\\w*", "ampolleta\\w*", "interruptor\\w*", "medidor\\w*",
  "empalme", "gasfit\\w*", "gasfiter\\w*", "plomer\\w*", "caneria\\w*", "filtracion\\w*", "fuga\\w*", "gotera\\w*", "llave\\w*",
  "grifo\\w*", "wc", "inodoro\\w*", "desague\\w*", "destap\\w*", "alcantarill\\w*", "calefon\\w*", "califon\\w*", "termo\\w*",
  "calefactor\\w*", "gas", "cilindro\\w*", "regulador\\w*", "estanque\\w*", "ducha\\w*", "lavaplato\\w*", "lavamano\\w*", "sifon\\w*",
  "agua caliente", "bomba de agua", "sin agua", "maestro\\w*", "tecnico\\w*",
  "albanil\\w*", "construccion\\w*", "remodelac\\w*", "ampliac\\w*", "ceramic\\w*", "porcelanato", "pintor\\w*", "pintura",
  "techumbre", "techo", "radier", "tabique\\w*", "carpinter\\w*", "soldador\\w*", "yeso\\w*", "volcanita", "muro", "reja\\w*"
]);
// oficio claro (para decidir sin IA)
const OFICIO_FUERTE = rx([
  "electricista\\w*", "un electrico", "maestro electrico", "tablero electrico", "instalacion electrica", "enchufes?", "cortocircuito",
  "corto circuito", "salta el automatico", "se salta el automatico", "automatico", "sin luz", "se corto la luz", "empalme", "cableado",
  "gasfiter\\w*", "gasfitero\\w*", "gasfiteria", "plomero\\w*", "filtracion\\w*", "fuga de (agua|gas)", "caneria\\w*", "destape",
  "destapar", "desague\\w*", "alcantarillado", "calefont", "califont", "calefon", "califon", "termo electrico", "llave de paso",
  "wc", "inodoro", "estanque del bano", "lavaplatos tapado", "sifon",
  "albanil\\w*", "maestro de construccion", "maestro chasquilla", "ceramica", "ceramico", "porcelanato", "pintor", "techumbre",
  "gotera\\w*", "radier", "tabique\\w*", "remodelacion", "ampliacion", "carpintero", "soldador", "volcanita"
]);
const PIDE = rx([
  "necesito", "necesitamos", "necesita", "se necesita", "se busca", "requiero", "requerimos",
  "busco (un |una |a un |a una |algun |alguien )?(maestro|electricista|gasfiter\\w*|plomero|tecnico|persona|albanil|pintor|ceramista|carpintero|soldador|especialista)",
  "alguien (que )?(sepa|haga|pueda|conozca|me ayude|arregle|repare|instale|vea|venga|trabaje)",
  "recomiend\\w*", "recomendacion\\w*", "datos? de (un|una|algun)", "un dato", "quien (me )?(puede|podria|pueda|sabe|haga|arregle|repare|instale)",
  "cotiz\\w*", "presupuesto para", "cuanto (cobran|cobra|sale|cuesta)", "me pueden ayudar", "me ayudan", "conocen (a )?(alg|un)",
  "algun maestro", "un maestro", "maestro que", "un gasfiter", "un electricista", "urgente", "se me (corto|echo|rompio|quemo|tapo)",
  "me quede sin", "nos quedamos sin"
]);
// amplio: solo para decidir si se le pregunta a la IA
const PIDE_AMPLIO = rx([
  "busco", "buscamos", "buscando", "alguien", "ayuda", "ayudenme", "consulta", "por favor", "favor", "que (puedo|hago|me recomiendan)",
  "como (lo )?(arreglo|reparo|soluciono|cambio)", "donde (encuentro|consigo)", "valor", "precio",
  "se (corto|echo|rompio|quemo|tapo|salta|cae|gotea)", "no (prende|enciende|funciona|calienta|sale)",
  "tengo (una|un) (fuga|filtracion|problema|corto)", "olor a gas", "salta el automatico"
]);
// ventas, trueques, ofertas de servicio, gente buscando trabajo
const NO_ES = rx([
  "vendo", "se vende", "venta", "vendemos", "trueque", "permuto", "permuta", "regalo", "regalamos", "se regala", "arriendo", "se arrienda",
  "liquido", "liquidacion", "busco trabajo", "busco pega", "busco empleo", "me ofrezco", "ofrezco", "ofrecemos", "estoy disponible",
  "disponible para trabajar", "realizo", "realizamos", "hacemos", "hago trabajos", "atendemos", "nuestros servicios"
]);
const OFRECE = /\b(ofrezco|ofrecemos|realizo|realizamos|hago trabajos|hacemos trabajos|sin costo|contactame|contactanos|nuestra empresa|garantia|instalamos|reparamos|atendemos|servicios? de|disponible para|a domicilio|precios? (convenientes?|economicos?|justos?)|anos de experiencia|experiencia comprobada|presupuestos? gratis|llamar al|agenda tu|agendar hora|certificad[oa]s?|sec clase)\b/g;

export function prefiltro(texto, cfg = {}) {
  const n = norm(texto);
  if (n.length < 12) return false;
  const oficio = OFICIO.test(n);
  if (oficio && (PIDE.test(n) || PIDE_AMPLIO.test(n))) return true;
  const propias = [...(cfg.keywords || []), ...((cfg.keywords_aprendidas || []).filter(x => x.estado === "activa").map(x => x.frase))]
    .map(norm).filter(k => k.length >= 6 && k.includes(" "));
  return oficio && propias.some(k => n.includes(k));
}

export function puntajeOferta(texto) {
  return (norm(texto).match(OFRECE) || []).length;
}

export function tipoDe(texto) {
  const n = norm(texto);
  const gasf = /(gas\b|gasfit|plomer|caneria|filtrac|fuga|gotera|llave de paso|\bwc\b|inodoro|desague|destap|alcantarill|calefon|califon|ducha|lavaplato|lavamano|sifon|agua caliente|termo)/.test(n);
  const elec = /(electric|\bluz\b|luces|enchufe|tablero|automatic|disyuntor|cable|ampolleta|interruptor|medidor|empalme|corto ?circuito)/.test(n);
  const cons = /(albanil|construcc|remodelac|ampliac|ceramic|porcelanato|pintor|pintura|techumbre|techo|radier|tabique|carpinter|soldador|yeso|volcanita|muro|reja)/.test(n);
  const n2 = [gasf, elec, cons].filter(Boolean).length;
  return n2 > 1 ? "varios" : gasf ? "gasfiteria" : elec ? "electricidad" : cons ? "construccion" : "otro";
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
  const es = OFICIO_FUERTE.test(n) && PIDE.test(n) && !NO_ES.test(n) && puntajeOferta(texto) < 2;
  const t = tipoDe(texto);
  const rubros = cfg.rubros?.length ? cfg.rubros : ["electricidad", "gasfiteria", "construccion"];
  const ok = es && (t === "varios" || t === "otro" || rubros.includes(t));
  const oracion = String(texto || "").replace(/\s+/g, " ").split(/(?<=[.!?])\s/)[0];
  return {
    es_solicitud: ok,
    tipo: t,
    resumen: oracion.slice(0, 80),
    necesita: oracion.slice(0, 160),
    comuna: "",
    urgencia: /(urgente|urgencia|emergencia|hoy mismo|lo antes posible|ahora ya|cuanto antes)/.test(n) ? "alta" : "media",
    mensaje: plantilla(cfg),
    frases_clave: [],
    sin_ia: true
  };
}
