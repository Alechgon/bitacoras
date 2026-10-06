"""
conversacion.py — el bot conversa en el grupo como una persona antes de agendar.

Cuando una supervisora avisa un caso:
  1. Si no dice qué pasa      -> "Carla, ¿de qué se trata? Así vemos quién va y qué llevar."
  2. Si no se entiende dónde  -> "¿En cuál colegio es? ¿El Carolina Vergara Ayares?"
  3. Si es urgente (gas, frío, agua, o dice emergencia/urgente):
        "Ok Carla, lo del República de Austria (gas).
         Hoy tengo:
         Camilo
         - Liceo Confederación Suiza, 08:15 a 10:15
         - Arnaldo Falabella, 10:45 a 12:45
         Rodrigo
         - Santiago de Chile E70, 08:15 a 10:15
         - libre de 10:45 a 12:45
         Mañana ...
         Rodrigo tiene libre hoy de 10:45 a 12:45, ¿lo dejamos ahí? Si no, díganme cuál de estas
         visitas se puede cambiar y la muevo."
     Las supervisoras responden en el grupo ("la del Confederación Suiza se puede mover", "sí", "ninguna")
     y el bot mueve esa visita al siguiente hueco (respetando su meta) y pone la emergencia ahí.
  4. A ti te llega cada paso. Si no corresponde: "deshacer N".
  5. Si nadie responde en esperar_min: gas o prioridad -> se agenda solo con las reglas; lo demás queda
     registrado para tu plan del día.
"""
import json, re
from datetime import datetime, timedelta

import ia
import lenguaje
import memoria
from nucleo import (_limpio, _parecido, a_fecha, agenda, agendar, bloques, bonita, buscar, cfg, colocar_forzado,
                    datos, en_texto, es_habil, es_prioridad, hora_bloque, hoy, libres, log, motivo, nombre_tec, norm,
                    sig_habil, sumar_habiles)

DIAS_LARGO = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
ETIQUETA = {"GAS": "gas", "FRIO": "frío", "AGUA": "agua", "ELEC": "electricidad", "EQUIPO": "equipo de cocina",
            "OTRO": ""}
RELLENO = set("""tengo tenemos tiene tienen hay una uno un unos unas emergencia emergencias urgente urgencia urgentes
problema problemas falla fallas ayuda porfa favor por necesito necesitamos necesita en el la los las de del al
colegio escuela esc liceo jardin infantil sala cuna complejo educacional centro hola buenas buenos dias tardes
noches agendar agenden agendame que con se nos me mi y o a para esta estan hoy ahora rapido pronto altiro ya
chiquillos chicos equipo mantencion visita vengan venir alguien su sus le les lo es son muy mucho otra vez
rbd n numero""".split())
SI = r"^(si|sii+|ok|oka|okey|dale|ya|bueno|perfecto|de acuerdo|ahi|ahi esta bien|esta bien|me parece|listo|sale|va)\b"
NINGUNA = r"\b(ninguna|ninguno|no se puede|no podemos|no se pueden|nada|todas son importantes|imposible)\b"
CUALQUIERA = r"\b(cualquiera|la que sea|da lo mismo|como quieras|la que quieras|tu decide)\b"


def conf():
    return cfg().get("conversacion", {})


def _n(autor):
    return (autor or "").split()[0] if autor else ""


def nom(rbd_o_nombre):
    """Nombre del colegio como lo escribe una persona: 'Liceo Confederación Suiza', no 'LICEO CONFEDERACION SUIZA'."""
    import voz
    return voz.nombre(rbd_o_nombre)


def _hora(d, b):
    """'1ra visita', '2da visita'… (sin horarios: el número indica el orden)."""
    return hora_bloque(d, b)


def _inicio(d, b):
    from nucleo import inicio_bloque
    return inicio_bloque(d, b)


def _dia(d, d0=None):
    d0 = d0 or hoy()
    if d == d0:
        return "hoy"
    if d == d0 + timedelta(days=1):
        return "mañana"
    return f"el {DIAS_LARGO[d.weekday()]} {d.strftime('%d-%m')}"


def pasa_a(d):
    """'pasa al martes 06-10' / 'pasa a mañana'."""
    x = _dia(d)
    return "al " + x[3:] if x.startswith("el ") else "a " + x


def limpiar_problema(texto, rbd):
    """'Tengo una emergencia en el Teresa Prat, se cortó la luz' -> 'se cortó la luz'."""
    p = " " + re.sub(r"\s+", " ", texto or "") + " "
    nombres = [datos()["E"].get(rbd, {}).get("nombre", "")] + datos()["E"].get(rbd, {}).get("unidades", []) + \
              [k for k, r in datos()["ALIAS"].items() if r == rbd]
    tildes = {"a": "[aá]", "e": "[eé]", "i": "[ií]", "o": "[oó]", "u": "[uúü]", "n": "[nñ]"}
    flex = lambda w: "".join(tildes.get(ch, re.escape(ch)) for ch in norm(w))
    for n in sorted(filter(None, nombres), key=len, reverse=True):
        p = re.sub(r"(?i)\b(en|del|de)?\s*(el|la)?\s*" + r"\s+".join(flex(w) for w in norm(n).split()) + r"\b", " ", p)
    p = re.sub(r"(?i)\b(hola|buenas|buenos dias)\b|\b(tengo|tenemos|hay)\s+(una|un)?\s*(emergencia|urgencia|problema|"
               r"caso)\s*(en|de|con)?\s*(el|la)?\b|\brbd\s*\d+|\b\d{4,6}\b", " ", p)
    p = re.sub(r"\s+", " ", p).strip(" ,.;:-·")
    pals = "|".join(re.escape(x) for x in cfg().get("agendar_palabras", ["agendar"]))
    p = re.sub(rf"(?i)\b({pals})\b|\b(porfa|por favor|plis)\b", " ", p)
    p = re.sub(r"\s+", " ", p).strip(" ,.;:-·")
    p = re.sub(r"^(emergencia|urgencia|urgente)\b[\s,:.-]*", "", p, flags=re.I)
    p = re.sub(r"^(y|que|en|el|la|tiene|tienen|esta|está)\s+", "", p, flags=re.I).strip(" ,.;:-")
    return p[:1].lower() + p[1:] if len(p.split()) >= 2 else ""


def _cap(s):
    return s[:1].upper() + s[1:]


# ---------------------------------------------------------------- ¿hace falta conversar?
def es_vaga(texto, crit, rbd, nombre_mencionado=""):
    """True si el mensaje no dice qué pasa ('tengo una emergencia en el X')."""
    if crit and crit != "OTRO":
        return False
    quitar = set()
    if rbd:
        quitar |= set(norm(datos()["E"][rbd]["nombre"]).split())
    quitar |= set(norm(nombre_mencionado).split())
    for k, r in datos()["ALIAS"].items():
        if re.search(rf"\b{re.escape(k)}\b", norm(texto)):
            quitar |= set(k.split())
    utiles = [w for w in norm(texto).split() if w not in RELLENO and w not in quitar and not w.isdigit() and len(w) > 2]
    return len(utiles) < 2


def es_urgente(crit, texto):
    c = conf()
    return crit in c.get("ofrecer_agenda_para", ["GAS", "FRIO", "AGUA"]) or es_prioridad(texto)


# ---------------------------------------------------------------- hilos
def _hilo(con, hid):
    return con.execute("SELECT * FROM hilos WHERE id=?", (hid,)).fetchone()


def _guardar(con, hid, **campos):
    campos["actualizado"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sets = ", ".join(f"{k}=?" for k in campos)
    con.execute(f"UPDATE hilos SET {sets} WHERE id=?", (*campos.values(), hid))


def _anotar_msg(con, h, texto):
    msgs = json.loads(h["msgs"] or "[]") + [texto]
    _guardar(con, h["id"], msgs=json.dumps(msgs[-6:], ensure_ascii=False))


def _mismo(a, b):
    a, b = norm(a).split(), norm(b).split()
    return bool(a and b and a[0] == b[0])


def buscar_hilo(con, texto, autor, citado=""):
    """¿Este mensaje del grupo sigue una conversación abierta? Devuelve la fila del hilo o None."""
    minutos = int(conf().get("esperar_min", 45))
    desde = (datetime.now() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    abiertos = con.execute("SELECT * FROM hilos WHERE estado='abierto' AND actualizado>=? ORDER BY id DESC",
                           (desde,)).fetchall()
    if not abiertos:
        return None
    c = (citado or "").strip()
    if c:
        for h in abiertos:
            if any(c[:60] in m or m[:60] in c for m in json.loads(h["msgs"] or "[]")):
                return h
    otro_colegio = lambda h: any(r != h["rbd"] for r in en_texto(texto)) and ia.tipo_por_palabras(texto) != "OTRO"
    # una pregunta, un reclamo o un pedido de verificador de la misma persona NO es la respuesta a la conversación
    import situaciones, verificadores
    if "?" in texto or situaciones.detectar(texto)[0] in ("faq", "reclamo", "supervision", "horario") or \
            verificadores.es_pedido(texto):
        return None
    for h in abiertos:
        if _mismo(h["autor"], autor) and not (h["paso"] != "lugar" and otro_colegio(h)):
            return h
    habla_de_aplazar = re.search(r"\b(aplaz|mover|muev|cambi|corr|se puede|pueden|esa|ese|bloque|visita)", norm(texto))
    for h in abiertos:                       # en la oferta de agenda puede responder cualquier supervisora
        if h["paso"] == "agenda" and habla_de_aplazar and ia.tipo_por_palabras(texto) == "OTRO" and \
                _elegir(texto, json.loads(h["opciones"] or "[]"), h["rbd"])[0]:
            return h
    # oferta de emergencia ("¿lo coordino?"): cualquier supervisora puede decir sí o no
    acepta_o_no = re.search(SI, norm(texto)) or re.search(NINGUNA, norm(texto)) or re.match(NO_RX, norm(texto)) or \
        re.search(r"\b(ya les digo|avisa|avisale|coordina|coordinalo|hazlo|dale|porfa)\b", norm(texto))
    for h in abiertos:
        if h["paso"] == "emergencia" and acepta_o_no and ia.tipo_por_palabras(texto) in ("OTRO", h["crit"]):
            return h
    return None


# ---------------------------------------------------------------- empezar
def _rbd_escrito(texto, rbd):
    return bool(rbd) and re.search(rf"\b{rbd}\b", texto or "") is not None


def iniciar(con, texto, autor, h, intencion, motor):
    """
    Primer mensaje de un caso en el grupo. Devuelve la salida si el bot va a conversar,
    o None para seguir el flujo normal (borrador para ti).
    Orden: 1) confirmar el colegio  2) de qué se trata  3) si es urgente, la agenda para ver qué se aplaza.
    """
    import servidor as S
    c = conf()
    if not c.get("activa", True):
        return None
    rbd, cands = S.resolver(h, texto)
    crit = h.get("tipo") if h.get("tipo") in ia.PAL or h.get("tipo") == "OTRO" else ia.tipo_por_palabras(texto)
    if rbd:
        dias = int(cfg().get("borrador", {}).get("dias_duplicado", 7))
        desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
        if con.execute("SELECT 1 FROM hallazgos WHERE rbd=? AND crit=? AND estado='agendado' AND recibido>=?",
                       (rbd, crit, desde)).fetchone() or \
           con.execute("SELECT 1 FROM hilos WHERE rbd=? AND estado='abierto'", (rbd,)).fetchone():
            return None                      # ya está agendado o ya se está conversando: flujo normal
    confirmado = 1 if (_rbd_escrito(texto, rbd) or not c.get("confirmar_colegio", True)) else 0
    hid = con.execute("INSERT INTO hilos(autor,texto,problema,crit,rbd,cands,paso,intencion,motor,confirmado) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (autor, texto, (h.get("problema") or texto)[:120], crit, rbd, json.dumps(cands),
                       "nuevo", intencion, motor, confirmado)).lastrowid
    log(con, f"Conversación #{hid} con {autor}: {texto[:80]}")
    return _avanzar(con, _hilo(con, hid))


def _que(h):
    return "la emergencia" if re.search(r"emergencia", norm(h["texto"])) else "el problema"


def _comuna(rbd):
    return datos()["E"].get(rbd, {}).get("comuna", "").title()


def _vaga(h):
    return conf().get("preguntar_detalle", True) and not h["detallado"] and es_vaga(h["texto"], h["crit"], h["rbd"])


def _avanzar(con, h):
    """Decide el siguiente paso del hilo: colegio -> confirmación -> detalle -> agenda (o flujo normal)."""
    out = {"grupo": [], "admin": []}
    n = _n(h["autor"])
    vaga = _vaga(h)
    if not h["rbd"]:
        cands = json.loads(h["cands"] or "[]")
        if len(cands) == 1:
            txt = f"{n}, ¿es el {nom(cands[0])} de {_comuna(cands[0])}?"
        elif cands:
            txt = f"{n}, ¿en qué colegio es? ¿El " + ", el ".join(nom(r) for r in cands[:-1]) + f" o el {nom(cands[-1])}?"
        else:
            txt = f"{n}, ¿en qué colegio es? No me queda claro el nombre, ¿me lo dices o el RBD?"
        if vaga:
            txt += f" ¿Y de qué se trata {_que(h)}?"
        _guardar(con, h["id"], paso="lugar")
        return _salida(con, _hilo(con, h["id"]), txt, out, "le pregunté en qué colegio es")
    if not h["confirmado"]:
        txt = f"{n}, ¿es el {nom(h['rbd'])} de {_comuna(h['rbd'])}?"
        if vaga:
            txt += f" ¿Y de qué se trata {_que(h)}? Así vemos quién va y qué tiene que llevar."
        _guardar(con, h["id"], paso="confirmar")
        return _salida(con, _hilo(con, h["id"]), txt, out, "le pedí confirmar el colegio")
    if vaga:
        txt = f"{n}, ¿de qué se trata {_que(h)} en el {nom(h['rbd'])}? Así vemos quién va y qué tiene que llevar."
        _guardar(con, h["id"], paso="detalle")
        return _salida(con, _hilo(con, h["id"]), txt, out, "le pregunté de qué se trata")
    if conf().get("ofrecer_agenda", True) and es_urgente(h["crit"], h["texto"]):
        return _ofrecer(con, h, out)
    # no es urgente: pasa al flujo normal (te llega el borrador del requerimiento)
    _guardar(con, h["id"], estado="cerrado", paso="normal", resultado="flujo normal")
    return _a_flujo_normal(con, _hilo(con, h["id"]), out)


def _salida(con, h, texto, out, resumen):
    out["grupo"].append(texto)
    _anotar_msg(con, h, texto)
    if conf().get("copiar_encargado", True):
        out["admin"].append(f"Conversación #{h['id']} con {h['autor']}: {resumen}.\n«{texto[:300]}»")
    con.commit()
    return out


def _a_flujo_normal(con, h, out):
    import servidor as S
    analisis = {"hallazgos": [{"rbd": h["rbd"], "seguro": True, "problema": h["problema"], "tipo": h["crit"]}]}
    agendar_ya = h["intencion"] == "agendar" or not cfg().get("agendar_requiere_palabra", True)
    items = S._generar_respuestas(con, h["texto"], h["autor"], h["motor"] or "conversación", analisis, agendar_ya)
    r = S._salida(con, "grupo", h["autor"], h["texto"], items, cfg().get("modo_borrador", True))
    for k, v in r.items():
        if isinstance(v, list):
            out.setdefault(k, [])
            out[k] += v
    if out.get("borradores"):
        out["admin"].insert(0, f"Conversación #{h['id']}: ya tengo los datos, te paso el borrador.")
    con.commit()
    return out


# ---------------------------------------------------------------- la oferta de agenda
def _dias_oferta():
    ahora = datetime.now()
    d1 = hoy()
    if es_habil(d1):
        ini = _inicio(d1, max(bloques(d1)))
        if ini and ahora.time() >= ini:
            d1 = sumar_habiles(d1, 1)
    else:
        d1 = sig_habil(d1)
    return d1, sumar_habiles(d1, 1)


def _entre(d, b):
    """'como 1ra visita' / 'como visita extra'."""
    return f"como {hora_bloque(d, b)}"


def _armar_oferta(con, h):
    """Texto de la agenda de los dos días + lista de opciones (visitas y bloques libres) para elegir."""
    D = datos()
    tecs = list(D["META"]["tecnicos"])
    pref = memoria.tecnico_para(h["crit"], h["rbd"], con) or cfg().get("preferencia_tecnico", {}).get(h["crit"])
    d1, d2 = _dias_oferta()
    ahora = datetime.now()
    lineas, opciones, libre = [], [], None
    for n_dia, d in enumerate((d1, d2), 1):
        lineas.append(f"\n{_cap(_dia(d))}{'' if _dia(d).startswith('el ') else ' ' + DIAS_LARGO[d.weekday()]} "
                      f"{d.strftime('%d-%m') if not _dia(d).startswith('el ') else ''}".rstrip() + ":")
        for tec in sorted(tecs, key=lambda t: t != pref):
            lineas.append(nombre_tec(tec))
            filas = {t["bloque"]: t for t in agenda(con, d, d, tec)}
            for b in sorted(set(bloques(d)) | set(filas)):
                t = filas.get(b)
                pasado = d == hoy() and (_inicio(d, b) or ahora.time()) <= ahora.time()
                hora = f"Bloque {b}" if b in bloques(d) else "Extra"
                if t:
                    movible = not pasado and ((t["crit"] or "") != "GAS" or t["rbd"] == h["rbd"])
                    lineas.append(f"- {hora}: {nom(t['rbd'])}")
                    opciones.append({"id": t["id"], "rbd": t["rbd"], "nombre": nom(t["rbd"]), "tec": tec,
                                     "fecha": d.isoformat(), "dia": n_dia, "bloque": b, "movible": movible,
                                     "por_que": "ya pasó ese bloque" if pasado else
                                     ("es de gas" if (t["crit"] or "") == "GAS" else "")})
                elif b in bloques(d) and not pasado:
                    lineas.append(f"- {hora}: libre")
                    opciones.append({"id": None, "rbd": None, "nombre": "bloque libre", "tec": tec,
                                     "fecha": d.isoformat(), "dia": n_dia, "bloque": b, "movible": True, "por_que": ""})
                    if libre is None and (h["crit"] != "GAS" or tec == pref or pref not in tecs):
                        libre = {"tec": tec, "fecha": d.isoformat(), "bloque": b}
    return lineas, opciones, libre, (d1, d2)


def _ofrecer(con, h, out):
    lineas, opciones, libre, _ = _armar_oferta(con, h)
    # el caso queda registrado desde ya (si nadie responde, igual aparece en tu plan del día)
    if not h["hallazgo_id"]:
        hid = con.execute("INSERT INTO hallazgos(recibido,autor,texto,rbd,problema,crit,prio,estado,motor) "
                          "VALUES(?,?,?,?,?,?,?,'registrado',?)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), h["autor"], h["texto"], h["rbd"],
                           h["problema"], h["crit"], int(es_prioridad(h["texto"])), h["motor"] or "conversación")
                          ).lastrowid
        _guardar(con, h["id"], hallazgo_id=hid)
    problema = limpiar_problema(h["problema"], h["rbd"]) or limpiar_problema(h["texto"].split(" · ")[-1], h["rbd"])
    cab = (f"Ok {_n(h['autor'])}, {problema} en el {nom(h['rbd'])}." if problema else
           f"Ok {_n(h['autor'])}, lo del {nom(h['rbd'])}.")
    cab += " Esta es la programación que tengo:"
    propia = next((o for o in opciones if o["rbd"] == h["rbd"]), None)
    if propia:                       # ya tiene visita en esos días: lo natural es resolverlo ahí
        dp = a_fecha(propia["fecha"])
        libre = {"tec": propia["tec"], "fecha": propia["fecha"], "bloque": propia["bloque"], "propia": True}
        cierre = (f"\nEl {nom(h['rbd'])} ya tiene visita {_dia(dp)} con {nombre_tec(propia['tec'])} "
                  f"(bloque {propia['bloque']}); si les sirve, lo ven ahí mismo. Si es más urgente, díganme "
                  f"qué visita se podría aplazar; esa pasa al día hábil siguiente.")
    elif libre:
        cierre = (f"\n{nombre_tec(libre['tec'])} tiene libre el bloque {libre['bloque']} {_dia(a_fecha(libre['fecha']))}, "
                  f"si les sirve lo dejo ahí. Si no, díganme qué visita se podría aplazar; esa pasa al día hábil siguiente.")
    else:
        cierre = ("\nLo puedo sumar, pero habría que aplazar algún establecimiento. ¿Cuál podría ser? "
                  "(Por ejemplo: el del segundo bloque del segundo día.) El que se aplace pasa al día hábil siguiente.")
    if h["crit"] == "GAS":
        cierre += f" El gas lo ve {nombre_tec(cfg().get('preferencia_tecnico', {}).get('GAS', 'CAMILO'))}."
    texto = cab + "\n" + "\n".join(lineas).strip("\n") + "\n" + cierre
    _guardar(con, h["id"], paso="agenda", opciones=json.dumps(opciones, ensure_ascii=False),
             libre=json.dumps(libre) if libre else None)
    return _salida(con, _hilo(con, h["id"]), texto, out, "le mostré la agenda para ver qué se puede aplazar")


# ---------------------------------------------------------------- seguir la conversación
ORD_DIA = {"primer": 1, "primero": 1, "1er": 1, "segundo": 2, "2do": 2, "otro": 2}


def _elegir(texto, opciones, rbd_caso=None):
    """
    ¿Qué visita o bloque nombró? Entiende el colegio ('la del Confederación Suiza'), o día + bloque
    ('el segundo bloque del segundo día', 'mañana en la tarde', 'el de Camilo de las 11').
    Devuelve (opcion, motivo_si_no_se_puede, ambiguas).
    """
    if not opciones:
        return None, "", []
    visitas = [o for o in opciones if o["rbd"]]
    rbds = [r for r in en_texto(texto) if r != rbd_caso]
    cand = [o for o in visitas if o["rbd"] in rbds]
    if not cand:
        q = _limpio(texto)
        puntajes = sorted(((_parecido(_limpio(o["nombre"]), q), i) for i, o in enumerate(visitas)), reverse=True)
        if puntajes and puntajes[0][0] >= 0.82:
            cand = [visitas[puntajes[0][1]]]
    if not cand:
        t = norm(texto)
        dia = None
        m = re.search(r"\b(primer|primero|1er|segundo|2do|otro)\s+dia\b|\bdia\s+([12])\b", t)
        if m:
            dia = ORD_DIA.get(m.group(1)) if m.group(1) else int(m.group(2))
        else:
            f = lenguaje.fecha_de(texto)
            if f:
                dia = next((o["dia"] for o in opciones if o["fecha"] == f.isoformat()), None)
        bl = lenguaje.bloque_de(re.sub(r"\b(primer|primero|segundo|otro)\s+dia\b", " ", t))
        if not bl:
            m = re.search(r"\b(?:las|a las)\s*(\d{1,2})(?:[:.](\d{2}))?\b", t)
            if m:
                hh = int(m.group(1))
                for o in opciones:
                    ini = _inicio(a_fecha(o["fecha"]), o["bloque"])
                    if ini and ini.hour == hh:
                        bl = o["bloque"]
                        break
        tec = lenguaje.tec_de(texto)
        if bl or (dia and tec):
            cand = [o for o in opciones if (not dia or o["dia"] == dia) and (not bl or o["bloque"] == bl)
                    and (not tec or o["tec"] == tec)]
            if not dia and len({o["dia"] for o in cand}) > 1:
                cand = [o for o in cand if o["dia"] == 1] or cand
    if not cand:
        return None, "", []
    if len(cand) > 1:
        return None, "", cand
    o = cand[0]
    return o, ("" if o["movible"] else o["por_que"] or "no se puede mover"), []


NO_RX = r"^(no|nop|noo+|negativo|no es|es otro|es otra|otro|otra)\b"


def _resto_tras_si(texto):
    return re.sub(r"^\s*(s[ií]+|ok|ya|exacto|correcto|ese|esa|ese mismo|esa misma|as[ií] es|eso|efectivamente)"
                  r"[\s,.!:;-]*", "", texto, flags=re.I).strip()


def continuar(con, h, texto, autor):
    out = {"grupo": [], "admin": []}
    t = norm(texto)
    if h["paso"] in ("verificador", "verif_lugar"):
        import verificadores
        return verificadores.continuar(con, h, texto, autor)
    if h["paso"] == "emergencia":
        import emergencias
        opcion = json.loads(h["opciones"] or "{}")
        if re.search(NINGUNA, t) or re.match(NO_RX, t):
            _guardar(con, h["id"], estado="cerrado", paso="hecho", resultado="no se coordinó")
            con.commit()
            out["grupo"].append(f"ok {_n(autor)}, lo dejo en la agenda y cuando se pueda lo vemos.")
            out["admin"].append(f"Urgencia {nom(h['rbd'])}: {autor} dijo que no coordinemos. Queda en *!plan*.")
            return out
        if re.search(SI, t) or re.search(r"\b(ya les digo|avisa|avisale|coordina|coordinalo|hazlo|dale|porfa)\b", t):
            resp, res = emergencias.aceptar(con, opcion, autor)
            _guardar(con, h["id"], estado="cerrado", paso="hecho",
                     resultado=f"coordinada → {res['tec']} {res['fecha']} b{res['bloque']}")
            con.commit()
            out["grupo"].append(resp)
            out["admin"].append(f"*Urgencia {nom(h['rbd'])}*: {autor} aceptó. {nombre_tec(res['tec'])} "
                                f"{bonita(res['fecha'])} B{res['bloque']}.\n«{resp}»")
            return out
        return None
    if h["paso"] == "confirmar":
        otros = [r for r in en_texto(texto) if r != h["rbd"]]
        if not otros and re.match(NO_RX, t):
            top = [x for _, x in buscar(re.sub(NO_RX, "", t)) [:3]] if len(t.split()) > 2 else []
            top = [x for x in top if x != h["rbd"]]
            _guardar(con, h["id"], rbd=None, cands=json.dumps(top[:2]), paso="nuevo")
            return _avanzar(con, _hilo(con, h["id"]))
        rbd = otros[0] if otros else h["rbd"]
        resto = limpiar_problema(re.sub(NO_RX, "", _resto_tras_si(texto), flags=re.I), rbd)
        campos = {"rbd": rbd, "confirmado": 1, "paso": "nuevo"}
        if resto and not es_vaga(resto, ia.tipo_por_palabras(resto), rbd):   # "sí, hay que instalar el cable…"
            crit = ia.tipo_por_palabras(resto)
            campos.update(texto=f"{h['texto']} · {resto}"[:1500], problema=resto[:120],
                          crit=crit if crit != "OTRO" else h["crit"], detallado=1)
        _guardar(con, h["id"], **campos)
        return _avanzar(con, _hilo(con, h["id"]))
    if h["paso"] == "detalle":
        crit = ia.tipo_por_palabras(texto)
        _guardar(con, h["id"], texto=f"{h['texto']} · {texto}"[:1500], problema=texto[:120],
                 crit=crit if crit != "OTRO" else h["crit"], paso="nuevo", detallado=1)   # se pregunta una sola vez
        return _avanzar(con, _hilo(con, h["id"]))
    if h["paso"] == "lugar":
        cands = json.loads(h["cands"] or "[]")
        rbd = next(iter(en_texto(texto)), None)
        if not rbd and cands and re.search(SI, t):
            rbd = cands[0]
        if not rbd and cands:
            m = re.search(r"\b(primero|1|segundo|2|tercero|3)\b", t)
            if m:
                idx = {"primero": 0, "1": 0, "segundo": 1, "2": 1, "tercero": 2, "3": 2}[m.group(1)]
                rbd = cands[idx] if idx < len(cands) else None
        if not rbd:
            top = buscar(texto)
            rbd = top[0][1] if top and top[0][0] >= 75 else None
        if not rbd:
            if h["intentos"] >= 1:
                _guardar(con, h["id"], estado="vencido", resultado="no se identificó el colegio")
                con.commit()
                out["admin"].append(f"Conversación #{h['id']}: no logré saber el colegio con {h['autor']}. "
                                    f"Mensaje: «{h['texto'][:200]}». Escríbeme el caso con el RBD si corresponde.")
                return out
            _guardar(con, h["id"], intentos=h["intentos"] + 1)
            return _salida(con, _hilo(con, h["id"]), f"No lo encuentro, {_n(autor)}. ¿Me das el RBD o el nombre "
                                                      f"completo?", out, "no ubiqué el colegio, le pedí el RBD")
        # si lo eligió de la lista o lo nombró, ya está confirmado; si fue búsqueda difusa, se confirma
        exacto = bool(en_texto(texto)) or (cands and rbd in cands)
        resto = re.sub(rf"\b{re.escape(norm(datos()['E'][rbd]['nombre']))}\b", "", t).strip()
        crit = ia.tipo_por_palabras(texto)
        campos = {"rbd": rbd, "confirmado": 1 if exacto else 0, "paso": "nuevo",
                  "crit": crit if crit != "OTRO" else h["crit"], "texto": f"{h['texto']} · {texto}"[:1500]}
        if crit != "OTRO" or len(resto.split()) >= 4:
            campos["problema"] = texto[:120]
        _guardar(con, h["id"], **campos)
        return _avanzar(con, _hilo(con, h["id"]))
    if h["paso"] == "agenda":
        opciones = json.loads(h["opciones"] or "[]")
        libre = json.loads(h["libre"]) if h["libre"] else None
        if re.search(NINGUNA, t):
            return _sin_cambio(con, h, autor, out, "nadie puede aplazar")
        o, por_que, ambiguas = _elegir(texto, opciones, h["rbd"])
        if ambiguas:
            txt = (f"{_n(autor)}, ¿cuál? ¿" + " o ".join(
                f"la de {nombre_tec(x['tec'])} ({x['nombre']})" for x in ambiguas[:3]) + "?")
            txt = txt.replace("¿la de", "¿La de", 1)
            return _salida(con, h, txt, out, "la respuesta calzaba con más de una visita")
        if o and por_que:
            return _salida(con, h, f"Esa no la puedo aplazar, {_n(autor)} ({por_que}). ¿Otra?", out,
                           f"pidieron aplazar {o['nombre']} pero {por_que}")
        if not o and re.search(CUALQUIERA, t):
            movibles = [x for x in opciones if x["movible"] and x["rbd"]]
            if movibles:
                pts = {r["id"]: r["pts"] for r in con.execute("SELECT id, pts FROM tarjetas")}
                o = sorted(movibles, key=lambda x: pts.get(x["id"], 99))[0]
        if o and o["rbd"] == h["rbd"]:
            return aplicar(con, h, autor, libre={**o, "propia": True})
        if o and not o["rbd"]:
            return aplicar(con, h, autor, libre=o)
        if o:
            return aplicar(con, h, autor, opcion=o)
        if libre and re.search(SI, t):
            return aplicar(con, h, autor, libre=libre)
        if _mismo(h["autor"], autor) and re.search(r"\b(aplaz|mover|muev|cambi|bloque|visita|dia|hoy|manana|esa|ese)", t):
            return _salida(con, h, f"{_n(autor)}, ¿qué visita se podría aplazar? Dime el colegio o el día y el "
                                   f"bloque (o *ninguna*).", out, "no entendí la respuesta")
        return None                          # otra cosa ("gracias", un caso nuevo…): sigue el camino normal
    return None


# ---------------------------------------------------------------- aplicar
def _foto(con):
    cols = "id, fecha, tec, bloque, estado, aplaz, pts, clase, detalle, crit, hallazgo_id, modificada, limite"
    return {r["id"]: dict(r) for r in con.execute(f"SELECT {cols} FROM tarjetas")}


def aplicar(con, h, autor, opcion=None, libre=None, automatico=False, intro=None):
    import servidor as S
    out = {"grupo": [], "admin": []}
    E = datos()["E"]
    hal = con.execute("SELECT * FROM hallazgos WHERE id=?", (h["hallazgo_id"],)).fetchone()
    antes = _foto(con)
    motivo(con, f"Conversación #{h['id']} en el grupo ({autor}): {nom(h['rbd'])}")
    if automatico:
        res = agendar(con, h["rbd"], h["crit"], h["problema"], bool(hal["prio"]), h["autor"], hal["id"])
    else:
        dest = opcion or libre
        res = colocar_forzado(con, h["rbd"], h["crit"], h["problema"], bool(hal["prio"]), h["autor"], hal["id"],
                              tec=dest["tec"], d=a_fecha(dest["fecha"]),
                              b=None if dest.get("propia") else dest["bloque"])     # su propia visita: se junta
    resp = S.texto_respuesta(E[h["rbd"]], h["problema"], h["crit"], res)
    con.execute("UPDATE hallazgos SET estado='agendado', pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                (res["pts"], res["tarjeta"], resp, hal["id"]))
    despues = _foto(con)
    cambios = {k: v for k, v in antes.items() if despues.get(k) != v}
    nuevas = [k for k in despues if k not in antes]
    d = res["fecha"]
    quien = nombre_tec(res["tec"])
    intro = intro or (f"Listo {_n(autor)}." if not automatico else "Como no alcanzamos a coordinar, lo dejé así:")
    partes = [intro, f"{quien} va {_dia(d)} {_entre(d, res['bloque'])} al {nom(h['rbd'])}."]
    if res["modo"] == "fusion":
        partes[-1] = f"El {nom(h['rbd'])} ya tenía visita {_dia(d)} con {quien}, así que lo ven ahí mismo."
    for p in res.get("postergadas") or ([res["movida"]] if res.get("movida") else []):
        a = a_fecha(p["a"])
        bl = p.get("bloque")
        mismo_tec = not p.get("tec_antes") or p.get("tec") == p.get("tec_antes")
        if bl and bl in bloques(a):
            cuando = f"{_dia(a)} {_entre(a, bl)}"
        else:
            cuando = f"{_dia(a)} como visita extra"
        cuando = (pasa_a(a) + cuando[len(_dia(a)):]) if cuando.startswith(_dia(a)) else cuando
        partes.append(f"El {nom(p['nombre'])} pasa {cuando}" + ("" if mismo_tec else f", con {nombre_tec(p['tec'])}") + ".")
        if p.get("paso_limite"):
            partes.append("Ojo que esa queda después de su fecha meta; Manuel la revisa.")
    texto = " ".join(partes)
    bid = con.execute("INSERT INTO borradores(origen,autor,texto_original,respuesta,rbd,crit,hallazgo_id,tarjeta_id,"
                      "estado,tipo) VALUES('conversacion',?,?,?,?,?,?,?,'enviado','agendar')",
                      (h["autor"], h["texto"], texto, h["rbd"], h["crit"], hal["id"], res["tarjeta"])).lastrowid
    elegido = (f"movió {opcion['nombre']}" if opcion else "bloque libre" if libre else "automático")
    _guardar(con, h["id"], estado="cerrado", paso="hecho", resultado=f"{elegido} → {res['tec']} {d} b{res['bloque']}",
             deshacer=json.dumps({"antes": cambios, "nuevas": nuevas, "hallazgo": hal["id"], "borrador": bid},
                                 ensure_ascii=False, default=str))
    memoria.registrar(con, caso=bid, origen="conversacion", supervisora=autor, rbd=h["rbd"], tipo="conversacion",
                      crit=h["crit"], original=h["texto"], propuesta="", decision="conversacion", detalle=elegido,
                      texto_final=texto, tec=res["tec"], fecha_visita=d, bloque=res["bloque"])
    log(con, f"Conversación #{h['id']} cerrada: {elegido}")
    con.commit()
    out["grupo"].append(texto)
    out["admin"].append(f"*Conversación #{h['id']}* con {h['autor']}: {nom(h['rbd'])} → {quien} "
                        f"{bonita(d)} B{res['bloque']} ({elegido}).\n«{texto}»\nSi no corresponde: *deshacer {h['id']}*")
    return out


def _sin_cambio(con, h, autor, out, por_que):
    """Nadie puede mover nada: se agenda con las reglas normales (puede quedar en bloque extra)."""
    r = aplicar(con, h, autor, automatico=True, intro=f"Ok {_n(autor)}, entonces lo dejo así:")
    r["admin"].insert(0, f"Conversación #{h['id']}: {por_que}; lo agendé con las reglas normales.")
    return r


def deshacer(con, hid, autor="Manuel"):
    h = _hilo(con, hid)
    if not h or not h["deshacer"]:
        return f"No tengo nada que deshacer en la conversación #{hid}."
    d = json.loads(h["deshacer"])
    motivo(con, f"Deshecho por {autor} (conversación #{hid})")
    for tid, v in d["antes"].items():
        con.execute("UPDATE tarjetas SET fecha=?, tec=?, bloque=?, estado=?, aplaz=?, pts=?, clase=?, detalle=?, "
                    "crit=?, hallazgo_id=?, limite=? WHERE id=?",
                    (v["fecha"], v["tec"], v["bloque"], v["estado"], v["aplaz"], v["pts"], v["clase"], v["detalle"],
                     v["crit"], v["hallazgo_id"], v["limite"], tid))
    for tid in d["nuevas"]:
        con.execute("UPDATE tarjetas SET estado='anulada' WHERE id=?", (tid,))
    con.execute("UPDATE hallazgos SET estado='registrado', tarjeta_id=NULL WHERE id=?", (d["hallazgo"],))
    con.execute("UPDATE borradores SET estado='deshecho' WHERE id=?", (d.get("borrador"),))
    _guardar(con, hid, estado="deshecho", deshacer=None)
    log(con, f"Conversación #{hid} deshecha por {autor}")
    con.commit()
    return (f"↩️ Deshice la conversación #{hid}: la agenda vuelve a como estaba y el caso queda sin hora "
            f"(sale en *!plan*). Avísale al grupo si hace falta.")


def vencidos(con):
    """Conversaciones sin respuesta: gas/prioridad se agendan solas; lo demás te queda a ti."""
    out = {"admin": [], "envios_grupo": []}
    minutos = int(conf().get("esperar_min", 45))
    limite = (datetime.now() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    for h in con.execute("SELECT * FROM hilos WHERE estado='abierto' AND actualizado<?", (limite,)).fetchall():
        if h["paso"] == "agenda" and h["hallazgo_id"] and (h["crit"] == "GAS" or es_prioridad(h["texto"])):
            r = aplicar(con, h, h["autor"], automatico=True)
            out["envios_grupo"].append({"borrador_id": None, "textos": r["grupo"]})
            out["admin"] += [f"Conversación #{h['id']} sin respuesta en {minutos} min y es "
                             f"{'gas' if h['crit'] == 'GAS' else 'prioridad'}: la agendé sola."] + r["admin"]
        else:
            _guardar(con, h["id"], estado="vencido", resultado="sin respuesta")
            que = {"detalle": "de qué se trataba", "lugar": "en qué colegio era",
                   "agenda": "qué visita se podía mover"}.get(h["paso"], "")
            out["admin"].append(f"Conversación #{h['id']}: {h['autor']} no respondió {que} en {minutos} min. "
                                f"«{h['texto'][:150]}»" + (" · Queda sin hora en tu *!plan*." if h["hallazgo_id"] else ""))
    con.commit()
    return out


def texto_hilos(con):
    filas = con.execute("SELECT * FROM hilos ORDER BY id DESC LIMIT 12").fetchall()
    if not filas:
        return "💬 No hay conversaciones todavía."
    icono = {"abierto": "🟢", "cerrado": "✅", "vencido": "⌛", "deshecho": "↩️"}
    paso = {"detalle": "esperando de qué se trata", "lugar": "esperando el colegio", "agenda": "esperando qué aplazar",
            "confirmar": "esperando que confirme el colegio", "verificador": "esperando qué bitácora quiere"}
    return "💬 *Conversaciones del grupo*\n" + "\n".join(
        f"{icono.get(h['estado'], '•')} #{h['id']} {h['autor']} · {nom(h['rbd']) if h['rbd'] else '¿colegio?'} · "
        f"{paso.get(h['paso'], h['resultado'] or h['estado'])}" for h in filas) + \
        "\n\n*deshacer N* revierte un cambio · *!cerrar N* corta una conversación abierta"
