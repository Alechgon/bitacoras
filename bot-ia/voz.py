"""
voz.py — cómo habla el bot: como Manuel, no como un sistema.

  acentuar("REPUBLICA DE HAITI")      -> "República de Haití"
  nombre(946781)                      -> "Jardín Japón"   (los jardines se nombran como en el grupo)
  lista(["a", "b", "c"])              -> "a, b y c"
  comuna(8678)                        -> "Estación Central"
  hay_que("se cortó la luz", "ELEC")  -> "revisar el corte de luz"
  humanizar(texto, para, situacion)   -> el mismo mensaje reescrito con TU tono, aprendido de cada vez que
                                         le dijiste al bot "dile esto mejor: …" (decisiones 'reescribir').
                                         Nunca cambia datos: si Gemini mueve un número, un colegio o un
                                         nombre, se queda el texto original.
Todo se puede ajustar en config.json → "voz".
"""
import re

from nucleo import cfg, datos, norm

ACENTOS = {
    "confederacion": "Confederación", "jose": "José", "martin": "Martín", "dario": "Darío", "gonzalez": "González",
    "joaquin": "Joaquín", "republica": "República", "estacion": "Estación", "chiloe": "Chiloé",
    "benjamin": "Benjamín", "vicuna": "Vicuña", "haiti": "Haití", "rodriguez": "Rodríguez", "libano": "Líbano",
    "basica": "Básica", "victor": "Víctor", "mexico": "México", "catolicos": "Católicos", "union": "Unión",
    "capacitacion": "Capacitación", "politecnico": "Politécnico", "arriaran": "Arriarán", "feliu": "Feliú",
    "ramon": "Ramón", "rio": "Río", "ascencion": "Ascención", "maria": "María", "luciernagas": "Luciérnagas",
    "copiapo": "Copiapó", "apostol": "Apóstol", "antunez": "Antúnez", "japon": "Japón", "ayelen": "Ayelén",
    "alegria": "Alegría", "antilen": "Antilén", "amulen": "Amulén", "kimelu": "Kimelü", "fco": "Francisco",
    "asisis": "Asís", "jardin": "Jardín", "educandonos": "Educándonos", "borgono": "Borgoño",
    "insuco": "INSUCO", "dargoltz": "Dargoltz", "latinoamericana": "Latinoamericana",
}
MINUS = {"de", "del", "la", "las", "los", "el", "y", "e", "a", "al", "en", "que", "un", "una", "hacia", "con"}
JARDIN = {"Junji", "Integra"}


def _conf():
    return cfg().get("voz", {})


def acentuar(nombre):
    """'LICEO CONFEDERACION SUIZA' -> 'Liceo Confederación Suiza'. Códigos (E70, A22, SC) quedan en mayúscula."""
    extra = {norm(k): v for k, v in (_conf().get("acentos") or {}).items()}
    out = []
    for i, w in enumerate(str(nombre or "").split()):
        partes = []
        for p in w.split("-"):                         # "WILLI-MAPU" -> "Willi-Mapu"
            n = norm(p)
            if re.fullmatch(r"[A-Za-z]\d+|\d+|[IVX]{2,}|SC|JI", p):
                partes.append(p.upper())
            elif n in extra:
                partes.append(extra[n])
            elif n in ACENTOS:
                partes.append(ACENTOS[n])
            elif i > 0 and n in MINUS:
                partes.append(p.lower())
            else:
                partes.append(p[:1].upper() + p[1:].lower())
        out.append("-".join(partes))
    return " ".join(out)


def nombre(rbd_o_nombre):
    """Como lo diría una persona del grupo: 'Silvia Salas Edwards', 'Jardín Japón', 'Liceo Darío Salas'."""
    E = datos()["E"]
    if isinstance(rbd_o_nombre, int) and rbd_o_nombre in E:
        e = E[rbd_o_nombre]
        n = acentuar(e["nombre"])
        if e.get("inst") in JARDIN and _conf().get("jardin_antes", True) and \
                not re.match(r"(?i)(jard|sala cuna|ji\b)", norm(n)):
            n = "Jardín " + n
        return n
    return acentuar(rbd_o_nombre)


def lista(cosas, y="y"):
    cosas = [c for c in cosas if c]
    if not cosas:
        return ""
    if len(cosas) == 1:
        return cosas[0]
    return ", ".join(cosas[:-1]) + f" {y} " + cosas[-1]


SEGUNDOS = {"carlos", "pablo", "jose", "antonio", "ignacio", "francisco", "luis", "andres", "manuel", "esteban",
            "alberto", "paz", "ignacia", "belen", "elena", "teresa", "fernanda", "jesus", "eugenia", "angelica",
            "ines", "isabel", "cristina", "soledad", "luisa", "victoria", "gabriela", "javiera", "jose"}


def vocativo(autor):
    """Cómo se le habla a alguien: 'Carla', 'Juan Carlos', 'María José' (nombres compuestos completos)."""
    p = [w for w in str(autor or "").split() if re.match(r"^[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+$", w)]
    if not p:
        return ""
    if len(p) >= 2 and norm(p[1]) in SEGUNDOS:
        return f"{p[0]} {p[1]}"
    return p[0]


def comuna(rbd):
    c = datos()["E"].get(rbd, {}).get("comuna", "")
    return acentuar(c)


def el(rbd):
    """'el Silvia Salas Edwards' / 'el Jardín Japón' (con artículo, como se habla)."""
    return "el " + nombre(rbd)


def al(rbd):
    """'al Silvia Salas Edwards' (contracción de 'a el')."""
    return "al " + nombre(rbd)


def del_(rbd):
    """'del Silvia Salas Edwards' (contracción de 'de el')."""
    return "del " + nombre(rbd)


def primera_min(t):
    """Estilo WhatsApp: primera letra en minúscula (salvo nombres propios conocidos)."""
    if not t or not _conf().get("minusculas", True):
        return t
    w = t.split()[0]
    if w[:1].isupper() and norm(w) not in _nombres_propios():
        return t[:1].lower() + t[1:]
    return t


def _nombres_propios():
    D = datos()
    s = {norm(i["nombre"]).split()[0] for i in D["META"]["tecnicos"].values()}
    s |= {norm(e.get("sup", "")).split()[0] for e in D["ESTAB"] if e.get("sup")}
    s |= {"manuel", "annahi", "juan", "ok"}
    return s


# ---------------------------------------------------------------- "hay que …"
INFINITIVO = r"^(revisar|reparar|cambiar|instalar|arreglar|ver|limpiar|destapar|reponer|retirar|sacar|poner|mover|" \
             r"regular|ajustar|soldar|sellar|pintar|correr|desatascar|reemplazar|conectar|cortar|mantener|chequear)\b"
POR_TIPO = {"GAS": "revisar el gas", "FRIO": "revisar el equipo de frío", "AGUA": "revisar lo del agua",
            "ELEC": "revisar la parte eléctrica", "EQUIPO": "revisar el equipo", "OTRO": "ir a revisar"}


def hay_que(problema, crit="OTRO"):
    """Convierte lo que contó la supervisora en lo que hay que hacer: 'se cortó la luz' -> 'revisar el corte de luz'."""
    p = re.sub(r"\s+", " ", (problema or "")).strip(" .,;:")
    if not p:
        return POR_TIPO.get(crit, "ir a revisar")
    pl = p[:1].lower() + p[1:]
    if re.match(INFINITIVO, norm(pl)):
        return pl
    t = norm(pl)
    def objeto(corte):
        o = re.split(corte, pl, flags=re.I)[0].strip(" ,.")
        o = re.sub(r"^(en el|en la|hay|tenemos|tengo|el|la|los|las)\s+", lambda m: m.group(0).lower(), o)
        if o and not re.match(r"(?i)(el|la|los|las|un|una)\b", o):
            o = "el " + o[:1].lower() + o[1:]
        return o if 0 < len(o.split()) <= 6 else ""
    reglas = [
        (r"\b(fuga|olor) (de|a) gas\b", lambda: "revisar la fuga de gas"),
        (r"\bse corto la luz|corte de luz|sin luz\b", lambda: "revisar el corte de luz"),
        (r"\bno (enfria|congela|llega a temperatura)|no alcanza (la )?temperatura",
         lambda: (f"revisar {o} que no enfría" if (o := objeto(r"\bno (enfr|congel|llega|alcanza)")) else
                  "revisar el equipo de frío que no enfría")),
        (r"\bgotea|gotera|filtracion|filtra\b", lambda: "revisar la filtración"),
        (r"\binundad|se inundo|rebalsa\b", lambda: "ver la inundación"),
        (r"\btapad|tapo|no corre el agua|no evacua\b",
         lambda: f"destapar {o}" if (o := objeto(r"\b(est[aá]n? )?tapad|se tap|no corre|no evac")) else "destapar el desagüe"),
        (r"\bsin agua caliente|calefont|califont\b", lambda: "revisar el calefont"),
        (r"\bno prende|no enciende|no funciona|se apag[oa]\b",
         lambda: f"revisar {o} que no funciona" if (o := objeto(r"\b(no prende|no enciende|no funciona|se apag)"))
         else POR_TIPO.get(crit, "ir a revisar")),
    ]
    for pat, frase in reglas:
        if re.search(pat, t):
            return frase()
    if re.match(r"^(el|la|los|las|un|una)\b", t):
        return f"revisar {pl}"
    if re.match(r"^(se|no|esta|estan|hay|tiene|tienen|sale|salen)\b", t):
        return f"ver lo de que {pl}" if len(pl) < 60 else POR_TIPO.get(crit, "ir a revisar")
    return f"revisar {pl}" if len(pl.split()) <= 6 else POR_TIPO.get(crit, "ir a revisar")


# ---------------------------------------------------------------- tu tono (aprendido)
def _ejemplos_manuel(n=6):
    """Pares (lo que propuso el bot, cómo lo dejaste tú) de cada 'dile esto mejor'."""
    from nucleo import db
    try:
        filas = db().execute("SELECT propuesta, texto_final FROM decisiones WHERE decision='reescribir' AND "
                             "COALESCE(texto_final,'')<>'' ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    except Exception:
        return []
    return [(f["propuesta"], f["texto_final"]) for f in filas if f["propuesta"] != f["texto_final"]]


def _datos_duros(t):
    """Lo que nunca se puede perder al reescribir: números, fechas y palabras con mayúscula (colegios, personas)."""
    nums = set(re.findall(r"\d+", t))
    nombres = {norm(w) for w in re.findall(r"\b[A-ZÁÉÍÓÚÑ][\wáéíóúñü]{3,}", t)}
    return nums, nombres


def humanizar(texto, para="", situacion=""):
    """
    Reescribe en tu tono SOLO si hay de dónde aprender (tus correcciones o tus instrucciones de estilo).
    Valida que sobreviva cada número y cada nombre propio; si no, devuelve el texto original.
    """
    c = _conf()
    if not texto or not c.get("humanizar", True):
        return texto
    import memoria
    ejemplos = _ejemplos_manuel(int(c.get("ejemplos", 6)))
    instrucciones = memoria.instrucciones()
    if not ejemplos and not instrucciones:
        return texto                      # todavía no hay cómo saber tu tono: el texto ya viene natural
    import ia
    pares = "\n".join(f"- Bot: «{a[:200]}»\n  Manuel: «{b[:200]}»" for a, b in ejemplos)
    prompt = ("Reescribe el MENSAJE para que suene exactamente como lo escribiría Manuel, encargado de mantención, "
              "en un grupo de WhatsApp con supervisoras. Español de Chile, natural, breve, sin emojis, sin listas, "
              "sin negritas. NO agregues ni quites información: mismos colegios, técnicos, días, números y "
              "compromisos. Devuelve solo el mensaje.\n"
              + (f"Va dirigido a: {para}\n" if para else "") + (f"Situación: {situacion}\n" if situacion else "")
              + ("INSTRUCCIONES DE MANUEL:\n" + "\n".join(f"- {i}" for i in instrucciones) + "\n" if instrucciones else "")
              + (f"ASÍ CORRIGE MANUEL AL BOT:\n{pares}\n" if pares else "")
              + f"\nMENSAJE:\n{texto}")
    nuevo = ia.generar(prompt, max_seg=int(c.get("max_seg", 12)))
    if not nuevo:
        return texto
    nuevo = nuevo.strip().strip('"«»').strip()
    n0, p0 = _datos_duros(texto)
    n1, p1 = _datos_duros(nuevo)
    if not n0 <= n1 or not {p for p in p0 if p not in _palabras_comunes()} <= {norm(w) for w in re.findall(r"[\wáéíóúñü]+", nuevo)}:
        return texto
    if len(nuevo) > len(texto) * 1.6 + 40:
        return texto
    return nuevo


def _palabras_comunes():
    return {"listo", "ok", "hola", "buenas", "buenos", "gracias", "como", "esta", "estos", "esas", "esos", "para",
            "ojo", "por", "hoy", "manana", "lunes", "martes", "miercoles", "jueves", "viernes", "visita", "entonces",
            "ahi", "eso", "ese", "esa", "si", "no", "cuando", "donde", "dime", "dale", "perfecto", "tambien", "pero",
            "mientras", "cierren", "ventilen"}
