"""
consultas.py — responde preguntas sobre lo hecho y lo que viene.

"Oye, el otro día en el Silvia Salas, ¿qué hicieron?"
  1. Establecimiento: RBD o alias en el texto (o el último que nombró esa persona).
  2. Tiempo: "hoy", "ayer", "el otro día", "el lunes", "la semana pasada", "hace 3 días",
     "en septiembre", "24/09"... se convierte en un rango de fechas a partir de la hora
     del mensaje. Sin referencia, toma lo más reciente.
  3. Tema: gas, agua, luz, frío, horno... filtra las visitas y los ítems de bitácora.
  4. Cruza 5 fuentes: plan histórico (datos.js), registros de Datácora, bitácoras PDF
     archivadas, bitácoras del panel y visitas que el bot marcó como hechas.
  5. Si preguntan por el futuro ("¿cuándo vienen?"), responde con la próxima visita.
Gemini solo redacta con esos datos; si no hay IA, responde con plantilla.
"""
import calendar
import re
from datetime import date, datetime, timedelta

from nucleo import a_fecha, agenda, bonita, buscar, cfg, datos, db, en_texto, hoy, metas, nombre_tec, norm

DIAS_SEM = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
MESES = {m: i for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"], start=1)}
TEMAS = {
    "gas": r"gas|calefont|flexible|regulador|hermeticidad|caseta|cilindro|granel",
    "agua": r"agua|griferia|sifon|filtracion|llave|desague|lavafondo|lavaplato|evacuacion",
    "luz": r"electr|enchufe|interruptor|luminaria|foco|tablero|corriente|luz",
    "frio": r"refriger|congelador|visicooler|frigobar|frio|salad bar",
    "campana": r"campana|extractor|ducto",
    "horno": r"horno|cocinilla|anafe|marmita|bano maria|fogon|cocina 4",
    "bano": r"\bbano|wc|lavamanos|inodoro",
    "infra": r"meson|mueble|estanteria|pintura|puerta|ventana|vidrio|malla|extintor|senaletica|basurero",
}


# ---------------------------------------------------------------- tiempo
def rango_tiempo(texto, ahora=None):
    """Devuelve (desde, hasta, etiqueta) o (None, None, '') si no hay referencia de tiempo."""
    ahora = ahora or datetime.now()
    d = ahora.date() if isinstance(ahora, datetime) else ahora
    t = norm(texto)
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", str(texto))
    if m:
        dd, mm, aa = int(m.group(1)), int(m.group(2)), m.group(3)
        a = int(aa) + (2000 if aa and len(aa) == 2 else 0) if aa else d.year
        try:
            f = date(a, mm, dd)
            return f - timedelta(days=1), f + timedelta(days=1), f"el {f.strftime('%d-%m')}"
        except ValueError:
            pass
    if re.search(r"\bhoy\b", t):
        return d, d, "hoy"
    if re.search(r"\b(anteayer|antes de ayer)\b", t):
        f = d - timedelta(days=2)
        return f, f, "anteayer"
    if re.search(r"\bayer\b", t):
        f = d - timedelta(days=1)
        return f, f, "ayer"
    m = re.search(r"\bhace (\d+|un|una|dos|tres) (dia|dias|semana|semanas)\b", t)
    if m:
        n = {"un": 1, "una": 1, "dos": 2, "tres": 3}.get(m.group(1)) or int(m.group(1))
        dias = n * (7 if m.group(2).startswith("semana") else 1)
        f = d - timedelta(days=dias)
        holgura = 3 if m.group(2).startswith("semana") else 1
        return f - timedelta(days=holgura), f + timedelta(days=holgura), m.group(0)
    if re.search(r"\b(semana pasada|la otra semana)\b", t):
        lunes = d - timedelta(days=d.weekday() + 7)
        return lunes, lunes + timedelta(days=6), "la semana pasada"
    if re.search(r"\besta semana\b", t):
        return d - timedelta(days=d.weekday()), d, "esta semana"
    m = re.search(r"\b(el )?(lunes|martes|miercoles|jueves|viernes|sabado|domingo)( pasado)?\b", t)
    if m:
        atras = (d.weekday() - DIAS_SEM[m.group(2)]) % 7 or 7
        f = d - timedelta(days=atras)
        return f, f, f"el {m.group(2)} {f.strftime('%d-%m')}"
    if re.search(r"\bmes pasado\b", t):
        primero = (d.replace(day=1) - timedelta(days=1)).replace(day=1)
        return primero, primero.replace(day=calendar.monthrange(primero.year, primero.month)[1]), "el mes pasado"
    m = re.search(r"\ben (" + "|".join(MESES) + r")\b", t)
    if m:
        mes = MESES[m.group(1)]
        a = d.year if mes <= d.month else d.year - 1
        return date(a, mes, 1), date(a, mes, calendar.monthrange(a, mes)[1]), f"en {m.group(1)}"
    if re.search(r"\b(otro dia|el otro dia|hace poco|hace unos dias|la otra vez|recien|ultimamente|la vez pasada)\b", t):
        return d - timedelta(days=21), d, "el otro día"
    return None, None, ""


# ---------------------------------------------------------------- historial de un establecimiento
def _num(folio):
    m = re.search(r"\d+", str(folio or ""))
    return m.group(0) if m else ""


def eventos(rbd):
    """Todas las visitas conocidas, de 5 fuentes, sin duplicados (por folio), más reciente primero."""
    D = datos()
    ev = {}

    def add(fecha, tipo, folio, tec, detalle, fuente, items=None):
        f = a_fecha(fecha)
        if not f:
            return
        k = (f.isoformat(), _num(folio)) if _num(folio) else (f.isoformat(), fuente, detalle[:30])
        e = ev.setdefault(k, {"fecha": f, "tipo": tipo or "", "folio": _num(folio), "tec": tec or "", "detalle": "",
                              "items": [], "fuentes": set()})
        if detalle and detalle not in e["detalle"]:
            e["detalle"] = (e["detalle"] + " · " if e["detalle"] else "") + detalle.replace("[Datácora]", "").strip()
        if items:
            e["items"] = e["items"] or items
        if tec and not e["tec"]:
            e["tec"] = tec
        e["fuentes"].add(fuente)

    for h in D.get("HIST", []):
        if h.get("rbd") == rbd and h.get("detalle") not in (None, "", "emergencia registrada en Datacora"):
            add(h["fecha"], h.get("tipo"), h.get("folio"), h.get("tec"), h.get("detalle", ""), "historial")
        elif h.get("rbd") == rbd:
            add(h["fecha"], h.get("tipo"), h.get("folio"), h.get("tec"), "", "historial")
    for x in D.get("DC", []):
        if x.get("rbd") == rbd:
            add(x["fecha"], x.get("tipo"), x.get("folio"), x.get("tec"), x.get("det", ""), "Datácora")
    con = db()
    for b in con.execute("SELECT * FROM bitacoras WHERE rbd=?", (rbd,)).fetchall():
        its = [dict(r) for r in con.execute("SELECT item, ubicacion, accion, observacion FROM bitacora_items "
                                            "WHERE folio=?", (b["folio"],))]
        add(b["fecha"], b["motivo"] if b["motivo"] != "por confirmar" else "Bitácora", b["folio"], b["tecnico"], "",
            "bitácora archivada", its)
    for b in D.get("BITS", []):
        if b.get("rbd") == rbd:
            its = [{"item": i.get("item"), "ubicacion": i.get("ubicacion"), "accion": i.get("accion"),
                    "observacion": i.get("observacion")} for i in b.get("items", [])]
            add(b["fecha"], "Bitácora", b.get("folio"), b.get("tecnico"), "", "bitácora panel", its)
    for t in db().execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='realizada'", (rbd,)).fetchall():
        add(t["fecha"], t["clase"].title(), "", nombre_tec(t["tec"]), t["detalle"][:120], "agenda del bot")
    return sorted(ev.values(), key=lambda e: e["fecha"], reverse=True)


def _filtrar_tema(evs, tema_txt):
    pat = None
    t = norm(tema_txt)
    for p in TEMAS.values():
        if t and re.search(p, t):
            pat = p
            break
    if not pat:
        return evs, None
    out = []
    for e in evs:
        its = [i for i in e["items"] if re.search(pat, norm(f"{i.get('item')} {i.get('observacion')}"))]
        if re.search(pat, norm(e["detalle"])) or its:
            out.append({**e, "items": its})
    return out, pat


# ---------------------------------------------------------------- responder
_ultimo_rbd = {}          # autor -> último establecimiento que nombró (para "¿y cuándo vuelven?")


def recordar_rbd(autor, rbd):
    if rbd:
        _ultimo_rbd[autor] = rbd


def _resolver_rbd(texto, pista, autor):
    D = datos()
    try:
        r = int(pista.get("rbd")) if pista.get("rbd") not in (None, "", "null") else None
    except (TypeError, ValueError):
        r = None
    if r in D["E"]:
        return r
    hits = en_texto(texto)
    if hits:
        return hits[0]
    nombre = pista.get("nombre_mencionado") or ""
    if nombre:
        c = buscar(nombre)
        if c and c[0][0] >= 75:
            return c[0][1]
    return _ultimo_rbd.get(autor)


def responder(texto, autor, pista=None, ahora=None):
    """Texto de respuesta a una pregunta. ahora = hora del mensaje (para 'ayer', 'el otro día')."""
    pista = pista or {}
    ahora = ahora or datetime.now()
    D = datos()
    t = norm(texto)
    explicito = bool(en_texto(texto)) or pista.get("rbd") not in (None, "", "null") or pista.get("nombre_mencionado")
    es_metas = re.search(r"\b(metas?|faltan|cuantos|avance|como vamos)\b", t)
    rbd = _resolver_rbd(texto, pista, autor) if (explicito or not es_metas) else None

    if not rbd:
        if es_metas:
            m = metas(db())
            j, jt, jf = m["junaeb"]
            g, gt, gf = m["jardines"]
            return (f"🎯 JUNAEB en Datácora: *{j}/{jt}* (meta {bonita(jf)})\n"
                    f"🎯 Jardines con preventiva: *{g}/{gt}* (meta {bonita(gf)})")
        return "🤔 ¿De qué establecimiento? Díganme el nombre o el RBD y les respondo."
    recordar_rbd(autor, rbd)
    e = D["E"][rbd]
    cab = f"🏫 *{e['nombre']}* · RBD {rbd}"

    # ---- preguntas sobre lo que viene
    futuro = pista.get("sobre") == "futuro" or re.search(
        r"\b(cuando (vienen|van|viene|va|vuelven|vuelve|regresan|pasan|pasa|llegan|llega|toca|le toca)|proxima|programad|agendad)", t)
    con = db()
    prox = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>=? ORDER BY fecha LIMIT 2",
                       (rbd, hoy().isoformat())).fetchall()
    linea_prox = ("📅 Próxima visita: " + " · ".join(
        f"{bonita(p['fecha'])} {nombre_tec(p['tec'])} ({p['clase'].lower()})" for p in prox)) if prox else \
        "📅 Sin visita programada todavía."
    if futuro:
        return f"{cab}\n{linea_prox}"

    # ---- preguntas sobre lo hecho
    evs = eventos(rbd)
    if not evs:
        return f"{cab}\n📭 No tengo visitas registradas de este establecimiento.\n{linea_prox}"
    tema = pista.get("tema") or texto
    evs_tema, pat = _filtrar_tema(evs, tema)
    base = evs_tema if pat and evs_tema else evs
    desde, hasta, etiqueta = rango_tiempo(pista.get("tiempo") or texto, ahora)
    if desde:
        en_rango = [x for x in base if desde <= x["fecha"] <= hasta]
        if en_rango:
            elegidos, intro = en_rango[:4], f"🗓️ {etiqueta.capitalize()}:"
        else:
            ancla = desde + (hasta - desde) / 2
            elegidos = sorted(base, key=lambda x: abs((x["fecha"] - ancla).days))[:2]
            elegidos.sort(key=lambda x: x["fecha"], reverse=True)
            intro = f"🗓️ No hay visita justo {etiqueta}; lo más cercano:"
    else:
        elegidos, intro = base[:3], "🗓️ Lo más reciente:"
    if pat and not evs_tema:
        intro = "🔎 No encontré trabajos de ese tema; esto es lo último:"

    hechos = [cab, intro]
    tecs = datos()["META"]["tecnicos"]
    for n, x in enumerate(elegidos):
        tec = nombre_tec(x["tec"].upper()) if x["tec"] and x["tec"].upper() in tecs else (x["tec"] or "s/técnico").title()
        lin = f"• {bonita(x['fecha'])} · {tec.split()[0]} · {x['tipo'] or 'visita'}" + \
              (f" folio {x['folio']}" if x["folio"] else "")
        if x["detalle"]:
            lin += f": {x['detalle'][:140]}"
        hechos.append(lin)
        for i in (x["items"][:3] if (pat or n == 0) else []):
            obs = (i.get("observacion") or "").replace("\n", " ")
            hechos.append(f"   ↳ {i.get('item')} ({i.get('ubicacion') or 's/u'}): {i.get('accion') or ''} — {obs[:90]}")
    hechos.append(linea_prox)
    plantilla = "\n".join(hechos)

    # Gemini solo redacta (no agrega datos); si falla, va la plantilla
    if cfg().get("redactar_con_ia", True):
        import ia
        prompt = ("Eres el asistente de mantención de SOSER. Responde la pregunta de una supervisora usando "
                  "SOLO los datos de abajo. Español de Chile, cordial y directo, máximo 7 líneas, con fechas y "
                  "técnico. Mantén los emojis de los datos. Si los datos no responden exactamente, dilo en una "
                  f"línea y muestra lo más cercano. No inventes nada.\n\nPREGUNTA de {autor}: {texto}\n\n"
                  f"DATOS:\n{plantilla}")
        txt = ia.generar(prompt, max_seg=25)
        if txt and len(txt) > 20:
            return txt
    return plantilla
