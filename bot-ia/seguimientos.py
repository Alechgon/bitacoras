"""
seguimientos.py — lo que no lo resuelven los técnicos sino un proveedor: frío y trampas de grasa.

En el grupo:
  "el refrigerador del Teresa Prat no llega a temperatura"
      -> grupo: "gracias Carla, lo gestionaré. ¿me podrías mandar una foto de la placa del equipo? es una plaquita
                 metálica que casi siempre está por atrás."
      -> a ti:  el caso + TODOS los equipos de frío en seguimiento, numerados, y lo que dicen las bitácoras de ese colegio.
  "hay que limpiar la cámara / la trampa de grasa del Haití"
      -> grupo: "gracias Stephania, lo gestionaré."   (sin pedir foto)
      -> a ti:  la lista de trampas de grasa / cámaras en seguimiento.
  "¿para cuándo lo del refri?" / "¿cuándo vienen a limpiar la cámara?"
      -> si ya me dijiste algo: "va el proveedor el jueves 08-10" / "se vio el 03-10"
      -> si no: "confirmo con el proveedor y te comento en breve" (y te aviso que preguntó)
  La foto de la placa: la leo (marca, modelo, serie, gas) y te la paso.

Desde tu WhatsApp, con el número de la lista:
  1 se vio el 03/10        1 y 3 se vieron hoy       2 va el jueves       2 el proveedor va el 08/10
  4 cerrado                1: el técnico dice que es el termostato
Si alguien había preguntado, le aviso en el grupo con lo que me dijiste ("te comento en breve" cumplido).
"""
import json
import re
from datetime import datetime, timedelta

from nucleo import a_fecha, buscar, cfg, datos, en_texto, hoy, log, norm, sig_habil

FRIO_EQ = (r"\b(refrigerador\w*|refri|refris|congelador\w*|conservadora\w*|visicooler\w*|visi cooler|frigobar\w*|"
           r"freezer\w*|salad bar|camara de frio|camara frigorifica|camara de refrigeracion|equipos? de frio|"
           r"vitrina\w*|enfriador\w*|maquina de hielo|camara)\b")
FRIO_MAL = (r"\b(no (llega|llegan|alcanza|alcanzan|baja|bajan|mantiene|mantienen|logra|logran|agarra|toma)\w*\s+"
            r"(a\s+|la\s+|el\s+)*(temperatura|frio|la temperatura)|no enfria\w*|no esta enfriando|no estan enfriando|"
            r"no congela\w*|no hiela|temperatura (alta|mala|incorrecta|fuera de rango)|esta caliente|estan calientes|"
            r"se descongel\w*|perdio (el )?frio|sin frio|enfria poco|enfria mal|no enfrian bien|calienta)\b")
TEMP_SOLA = r"\bno (llega|llegan|alcanza|alcanzan) a (la )?temperatura\b"
GRASA = (r"\b((trampas?|tramas?) de grasas?|camaras? desgrasadoras?|desgrasadoras?|limpi\w+ (de |a )?(la |las )?camaras?|"
         r"camaras? (tapada|tapadas|llena|llenas|rebalsa\w*|colapsad\w*|con grasa|de grasa|sucia\w*|hedionda\w*)|"
         r"grasa (en|de) la camara|olor (a|de) (la )?camara)\b")
PARA_CUANDO = (r"\b(para cuando|cuando (vienen|van|viene|va|pasan|pasa|lo ven|la ven|lo arreglan|la arreglan|lo revisan|"
               r"la revisan|la limpian|limpian|vendran|van a venir|vendria|vendrian|seria|podrian|podria)|"
               r"que dia (vienen|van|viene|va)|hay fecha|tienen fecha|cuanto (se demora|falta|demora)|"
               r"fecha aproximada|aprox\w*|que paso con|que pasa con|novedades|alguna novedad|se sabe algo)\b")
ETIQUETA = {"frio": "equipo de frío", "grasa": "trampa de grasa / cámara"}


def _lo_de(que):
    return "lo d" + que[1:] if que.startswith("el ") else "lo de " + que


def _nota(n):
    return f": {n.strip().rstrip('.')}." if n and n.strip() else "."


def _que(s):
    """'el refrigerador del Teresa Prat' / 'la limpieza de la cámara del Haití'."""
    import voz
    if s["tipo"] == "grasa":
        base = "la limpieza de la cámara"
    else:
        eq = s["equipo"] or "equipo de frío"
        base = ("la " if eq.startswith(("cámara", "vitrina", "conservadora", "maquina", "máquina")) else "el ") + eq
    return base + (f" del {voz.nombre(s['rbd'])}" if s["rbd"] else "")


def conf():
    return cfg().get("seguimientos", {})


# ---------------------------------------------------------------- reconocer
def tipo_de(texto):
    t = norm(texto)
    if re.search(GRASA, t):
        return "grasa"
    if (re.search(FRIO_EQ, t) and re.search(FRIO_MAL, t)) or re.search(TEMP_SOLA, t):
        return "frio"
    return None


def _tema(texto):
    """¿Habla de frío o de cámara/grasa aunque no sea un reclamo nuevo? ('¿para cuándo lo del refri?')"""
    t = norm(texto)
    if re.search(GRASA, t) or re.search(r"\b(camara|grasa|desgrasador)", t):
        return "grasa" if not re.search(r"\bcamara de frio|frigorific", t) else "frio"
    if re.search(FRIO_EQ, t) or re.search(r"\b(frio|temperatura)\b", t):
        return "frio"
    return None


def es_para_cuando(texto):
    return bool(re.search(PARA_CUANDO, norm(texto)))


def detectar(con, texto, autor):
    """('reporte'|'para_cuando'|'colegio', dato) o (None, None)."""
    if not conf().get("activa", True):
        return None, None
    pend = _esperando_colegio(con, autor)
    if pend and (en_texto(texto) or _rbd_difuso(texto)):
        return "colegio", pend
    tipo = tipo_de(texto)
    if es_para_cuando(texto):
        import ia
        tema = _tema(texto) or tipo
        rbd = _rbd(con, texto, autor)
        otro_equipo = ia.tipo_por_palabras(texto) not in ("OTRO", "FRIO")
        if tema or (rbd and _abiertos(con, rbd=rbd) and not otro_equipo):
            return "para_cuando", {"tema": tema, "rbd": rbd}
    if tipo:
        return "reporte", tipo
    return None, None


# ---------------------------------------------------------------- datos
def _rbd_difuso(texto):
    limpio = re.sub(FRIO_EQ + "|" + FRIO_MAL + "|" + GRASA + "|" + PARA_CUANDO, " ", norm(texto))
    top = buscar(limpio) if limpio.strip() else []
    return top[0][1] if top and top[0][0] >= 85 and (len(top) == 1 or top[0][0] - top[1][0] >= 5) else None


def _rbd(con, texto, autor):
    hits = en_texto(texto)
    if hits:
        return hits[0]
    r = _rbd_difuso(texto)
    if r:
        return r
    try:
        import consultas
        return consultas._ultimo_rbd.get(autor)
    except Exception:
        return None


def _abiertos(con, rbd=None, tipo=None):
    q = "SELECT * FROM seguimientos WHERE estado='abierto'"
    p = []
    if rbd:
        q += " AND rbd=?"
        p.append(rbd)
    if tipo:
        q += " AND tipo=?"
        p.append(tipo)
    return con.execute(q + " ORDER BY id", p).fetchall()


def _esperando_colegio(con, autor):
    desde = (datetime.now() - timedelta(minutes=90)).strftime("%Y-%m-%d %H:%M:%S")
    return con.execute("SELECT * FROM seguimientos WHERE rbd IS NULL AND espera='colegio' AND estado='abierto' AND autor=? "
                       "AND creado>=? ORDER BY id DESC LIMIT 1", (autor, desde)).fetchone()


def _equipo_de(texto):
    m = re.search(FRIO_EQ, norm(texto))
    if not m:
        return ""
    e = m.group(1)
    e = {"refri": "refrigerador", "refris": "refrigeradores", "camara": "cámara de frío"}.get(e, e)
    return e.replace("camara", "cámara").replace("frio", "frío").replace("frigorifica", "frigorífica")


def equipos_en_bitacoras(con, rbd, tipo="frio"):
    """Lo que dicen las bitácoras de ese colegio: 'refrigerador (24-09), congelador x2 (24-09)'."""
    pat = r"refriger|congel|visicooler|frigobar|salad|frio" if tipo == "frio" else r"camara|desgras|grasa|sifon|evacuac"
    vistos = {}
    for f in con.execute("SELECT bi.item, bi.cantidad, bi.observacion, b.fecha FROM bitacora_items bi JOIN bitacoras b "
                         "ON b.folio=bi.folio WHERE bi.rbd=? ORDER BY b.fecha DESC", (rbd,)).fetchall():
        if re.search(pat, norm(f"{f['item']} {f['observacion']}")):
            k = norm(f["item"])
            if k not in vistos:
                vistos[k] = (f["item"], f["cantidad"], f["fecha"], f["observacion"])
    for b in datos().get("BITS", []):
        if b.get("rbd") != rbd:
            continue
        for i in b.get("items", []):
            if re.search(pat, norm(f"{i.get('item')} {i.get('observacion')}")):
                k = norm(i.get("item"))
                if k not in vistos:
                    vistos[k] = (i.get("item"), i.get("cantidad"), b.get("fecha"), i.get("observacion"))
    out = []
    for item, cant, fecha, obs in vistos.values():
        f = a_fecha(fecha)
        out.append(f"{item.lower()}" + (f" x{cant}" if str(cant or "1") not in ("1", "", "None") else "")
                   + (f" ({f.strftime('%d-%m')}" + (f": {str(obs)[:60]}" if obs else "") + ")" if f else ""))
    return out


def _fecha_cl(iso):
    f = a_fecha(iso)
    return f.strftime("%d-%m") if f else ""


def _cuando_txt(iso):
    from conversacion import _dia
    f = a_fecha(iso)
    return _dia(f) if f else ""


# ---------------------------------------------------------------- en el grupo
def actuar(con, tipo, dato, texto, autor, origen="grupo"):
    import voz
    out = {"grupo": [], "admin": [], "borradores": [], "archivos_admin": []}
    n = voz.vocativo(autor)
    destino = "grupo" if origen == "grupo" else "admin"
    if tipo == "colegio":
        s = dato
        rbd = en_texto(texto)[0] if en_texto(texto) else _rbd_difuso(texto)
        con.execute("UPDATE seguimientos SET rbd=?, espera=NULL, actualizado=datetime('now','localtime') WHERE id=?",
                    (rbd, s["id"]))
        con.commit()
        out[destino].append(f"gracias {n}, anotado.")
        out["admin"].append(_aviso_manuel(con, con.execute("SELECT * FROM seguimientos WHERE id=?", (s["id"],)).fetchone(),
                                          nuevo=True))
        return out

    if tipo == "para_cuando":
        rbd, tema = dato.get("rbd"), dato.get("tema")
        cands = _abiertos(con, rbd=rbd, tipo=tema) if rbd else _abiertos(con, tipo=tema)
        cands = [s for s in cands if not rbd or s["rbd"] == rbd]
        if not rbd:
            mios = [s for s in cands if s["autor"] == autor]
            cands = mios or (cands if len(cands) == 1 else [])
        s = cands[-1] if cands else None
        if not s and tema and rbd:                     # preguntan por algo que nadie había reportado: queda en seguimiento
            sid = _crear(con, tema, rbd, autor, texto)
            s = con.execute("SELECT * FROM seguimientos WHERE id=?", (sid,)).fetchone()
        if not s:
            if not tema:
                return None
            out[destino].append(f"{n}, " + conf().get("respuesta_para_cuando", "confirmo con el proveedor y te comento "
                                                                                "en breve") + ".")
            out["admin"].append(f"{autor} pregunta para cuándo viene el proveedor ({ETIQUETA[tema]}), pero no sé de qué "
                                f"colegio. le dije que confirmas. «{texto[:200]}»")
            return out
        resp = _estado_para(s, n)
        out[destino].append(resp)
        if resp.endswith(conf().get("respuesta_para_cuando", "confirmo con el proveedor y te comento en breve") + "."):
            preg = json.loads(s["preguntas"] or "[]") + [{"autor": autor, "cuando": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                        "texto": texto[:200], "respondida": False}]
            con.execute("UPDATE seguimientos SET preguntas=?, actualizado=datetime('now','localtime') WHERE id=?",
                        (json.dumps(preg, ensure_ascii=False), s["id"]))
            out["admin"].append(f"{autor} pregunta para cuándo lo del {voz.nombre(s['rbd']) if s['rbd'] else '¿colegio?'} "
                                f"(#{s['id']}, {s['equipo'] or ETIQUETA[s['tipo']]}). le dije que confirmas con el proveedor.\n"
                                f"cuando sepas: «{s['id']} va el jueves» o «{s['id']} se vio el 05/10» y le aviso.")
        con.commit()
        return out

    # reporte nuevo (frío que no llega a temperatura / trampa de grasa / limpieza de cámara)
    tipo = dato
    rbd = _rbd(con, texto, autor) if (en_texto(texto) or _rbd_difuso(texto)) else None
    prev = _abiertos(con, rbd=rbd, tipo=tipo) if rbd else []
    if prev:
        s = prev[-1]
        con.execute("UPDATE seguimientos SET veces=veces+1, texto=?, actualizado=datetime('now','localtime') WHERE id=?",
                    (f"{s['texto']} · {texto}"[:1500], s["id"]))
        sid, nuevo = s["id"], False
    else:
        sid, nuevo = _crear(con, tipo, rbd, autor, texto), True
    s = con.execute("SELECT * FROM seguimientos WHERE id=?", (sid,)).fetchone()
    resp = conf().get("respuesta", "gracias {nombre}, lo gestionaré.").format(nombre=n).replace("gracias , ", "gracias, ")
    if not rbd:
        resp += " ¿me dices de qué colegio es?"
        con.execute("UPDATE seguimientos SET espera='colegio' WHERE id=?", (sid,))
    if tipo == "frio" and conf().get("pedir_placa", True) and not s["placa"] and (nuevo or not s["pide_placa"]):
        resp += " " + conf().get("texto_placa", "¿me podrías mandar una foto de la placa del equipo? es una plaquita "
                                               "metálica que casi siempre está por atrás.")
        con.execute("UPDATE seguimientos SET pide_placa=1 WHERE id=?", (sid,))
    out[destino].append(resp)
    if rbd:
        out["admin"].append(_aviso_manuel(con, s, nuevo=nuevo))
    con.commit()
    log(con, f"Seguimiento #{sid} {tipo} {rbd} de {autor}")
    return out


def _crear(con, tipo, rbd, autor, texto):
    return con.execute("INSERT INTO seguimientos(tipo,rbd,equipo,autor,texto) VALUES(?,?,?,?,?)",
                       (tipo, rbd, _equipo_de(texto) if tipo == "frio" else "", autor, texto[:1500])).lastrowid


def _estado_para(s, n):
    """Lo que se le contesta a quien pregunta 'para cuándo'."""
    que = _que(s)
    if s["proxima"] and a_fecha(s["proxima"]) and a_fecha(s["proxima"]) >= hoy():
        return f"{n}, {_lo_de(que)}: va el proveedor {_cuando_txt(s['proxima'])}" + _nota(s["nota"])
    if s["visto"]:
        return f"{n}, {_lo_de(que)} se vio el {_fecha_cl(s['visto'])}" + _nota(s["nota"])
    base = conf().get("respuesta_para_cuando", "confirmo con el proveedor y te comento en breve")
    return f"{n}, {base}."


def _aviso_manuel(con, s, nuevo=True):
    """El caso + la lista numerada de todo lo que está en seguimiento de ese tipo."""
    import voz
    tit = "frío que no llega a temperatura" if s["tipo"] == "frio" else "trampa de grasa / limpieza de cámara"
    lin = [f"{'nuevo' if nuevo else 'otra vez'}: {tit} · {s['autor']}, {voz.nombre(s['rbd']) if s['rbd'] else '¿colegio?'}"
           f" (#{s['id']})", f"«{s['texto'][-300:]}»"]
    if s["rbd"]:
        eqs = equipos_en_bitacoras(con, s["rbd"], s["tipo"])
        if eqs:
            lin.append(f"en las bitácoras del {voz.nombre(s['rbd'])} aparece: " + "; ".join(eqs[:5]))
    lin.append("")
    lin.append(texto_lista(con, s["tipo"]))
    if s["tipo"] == "frio" and s["pide_placa"] and not s["placa"]:
        lin.append("le pedí foto de la placa; si la manda, te paso marca y modelo.")
    lin.append(f"cuando sepas algo: «{s['id']} se vio el 05/10», «{s['id']} va el jueves», «{s['id']} cerrado» o "
               f"«{s['id']}: nota».")
    return "\n".join(lin)


def texto_lista(con, tipo=None):
    import voz
    tipos = [tipo] if tipo else ["frio", "grasa"]
    lin = []
    for tp in tipos:
        filas = _abiertos(con, tipo=tp)
        titulo = "equipos de frío en seguimiento" if tp == "frio" else "trampas de grasa / cámaras en seguimiento"
        if not filas:
            lin.append(f"{titulo}: ninguno.")
            continue
        lin.append(f"{titulo}:")
        for s in filas:
            partes = [f"{s['id']}. {voz.nombre(s['rbd']) if s['rbd'] else '¿colegio?'}"]
            if s["equipo"]:
                partes.append(s["equipo"])
            partes.append(f"desde {_fecha_cl(s['creado'])} ({(s['autor'] or '').split()[0]})")
            if s["veces"] > 1:
                partes.append(f"avisado {s['veces']} veces")
            if s["visto"]:
                partes.append(f"visto {_fecha_cl(s['visto'])}")
            if s["proxima"]:
                partes.append(f"va {_fecha_cl(s['proxima'])}")
            if s["placa"]:
                try:
                    p = json.loads(s["placa"])
                    partes.append("placa: " + " ".join(str(p.get(k)) for k in ("marca", "modelo") if p.get(k)))
                except ValueError:
                    pass
            if s["nota"]:
                partes.append(s["nota"][:80])
            lin.append(" · ".join(partes))
    return "\n".join(lin)


# ---------------------------------------------------------------- fotos de la placa
def foto(con, ruta, autor, caption=""):
    """¿Esta foto es la placa que le pedí a esa persona? Devuelve la salida o None (no era para esto)."""
    if not conf().get("activa", True):
        return None
    desde = (datetime.now() - timedelta(hours=int(conf().get("placa_horas", 24)))).strftime("%Y-%m-%d %H:%M:%S")
    s = con.execute("SELECT * FROM seguimientos WHERE pide_placa=1 AND placa IS NULL AND autor=? AND actualizado>=? "
                    "AND estado='abierto' ORDER BY id DESC LIMIT 1", (autor, desde)).fetchone()
    rbd_cap = en_texto(caption)[0] if caption and en_texto(caption) else None
    if not s and rbd_cap:
        s = con.execute("SELECT * FROM seguimientos WHERE pide_placa=1 AND placa IS NULL AND rbd=? AND estado='abierto' "
                        "ORDER BY id DESC LIMIT 1", (rbd_cap,)).fetchone()
    if not s:
        return None
    import ia
    import voz
    p = ia.leer_placa(ruta) or {}
    if not p.get("es_placa", True) and not re.search(r"placa|modelo|serie", norm(caption)):
        return None                                     # era otra foto (la falla, la cocina): sigue el camino normal
    con.execute("UPDATE seguimientos SET placa=?, foto=?, actualizado=datetime('now','localtime') WHERE id=?",
                (json.dumps(p, ensure_ascii=False), ruta, s["id"]))
    con.commit()
    datos_p = ", ".join(f"{k} {p[k]}" for k in ("marca", "modelo", "serie", "refrigerante", "voltaje", "potencia")
                        if p.get(k)) or "no se alcanza a leer bien; te la paso igual"
    n = voz.vocativo(autor)
    return {"grupo": [f"gracias {n}, con eso lo gestiono."], "admin": [
        f"placa del {s['equipo'] or 'equipo de frío'} del {voz.nombre(s['rbd']) if s['rbd'] else '¿colegio?'} "
        f"(#{s['id']}): {datos_p}."], "archivos_admin": [ruta], "borradores": []}


# ---------------------------------------------------------------- tus respuestas desde el main
VERBOS_TU = (r"(se vio|se vieron|lo vio|la vio|los vio|lo vieron|la vieron|los vieron|vist[oa]s?|revisad[oa]s?|"
             r"se reviso|se revisaron|se limpio|se limpiaron|limpiad[oa]s?|va|van|ira|iran|vendra|vendran|"
             r"el proveedor|proveedor|queda para|quedo para|programad[oa]s?|agendad[oa]s?|cerrad[oa]s?|cerrar|"
             r"resuelt[oa]s?|solucionad[oa]s?|nota|fecha)")


def es_tuyo(con, texto, citado=""):
    """'1 se vio el 03/10', '2 va el jueves', '4 cerrado', '1: …' (números = ids de seguimiento abiertos)."""
    t = norm(texto)
    m = re.match(r"^\s*#?(\d{1,3}(?:\s*(?:,|y|e)\s*#?\d{1,3})*)\s*(?::|\s)\s*(.+)$", texto.strip())
    if not m:
        return None
    ids = [int(x) for x in re.findall(r"\d{1,3}", m.group(1))]
    resto = m.group(2).strip()
    existen = [i for i in ids if con.execute("SELECT 1 FROM seguimientos WHERE id=? AND (estado='abierto' OR "
                                             "actualizado>=datetime('now','-7 days'))", (i,)).fetchone()]
    if not ids or len(existen) != len(ids):
        return None
    citando = bool(re.search(r"seguimiento|placa del|frío que no|trampa de grasa", citado or "", re.I))
    con_dos_puntos = ":" in texto.split()[0] or re.match(r"^\s*#?[\d\sye]+:", texto)
    if citando or con_dos_puntos or re.match(rf"^{VERBOS_TU}\b", norm(resto)):
        return {"ids": ids, "resto": resto, "nota": bool(con_dos_puntos) and not re.match(rf"^{VERBOS_TU}\b", norm(resto))}
    return None


def _fecha_dicha(resto, futuro):
    """'el 03/10', 'hoy', 'ayer', 'el jueves', 'mañana'. Para 'va el jueves' busca hacia adelante; para 'se vio', atrás."""
    import lenguaje
    import realizados
    t = norm(resto)
    if not re.search(r"\b(hoy|ayer|anteayer|manana|pasado manana|lunes|martes|miercoles|jueves|viernes|sabado|"
                     r"\d{1,2}[/-]\d{1,2})\b", t + " " + resto):
        return hoy() if not futuro else None
    if futuro:
        return lenguaje.fecha_de(resto)
    return realizados.fecha_reporte(resto)


def aplicar_tuyo(con, r, autor="Manuel"):
    """Aplica tu respuesta. Devuelve {'admin': [...], 'envios_grupo': [...]}."""
    import voz
    out = {"admin": [], "envios_grupo": []}
    resto = r["resto"]
    t = norm(resto)
    hechos = []
    for sid in r["ids"]:
        s = con.execute("SELECT * FROM seguimientos WHERE id=?", (sid,)).fetchone()
        que = f"#{sid} {voz.nombre(s['rbd']) if s['rbd'] else '¿colegio?'}"
        if r["nota"]:
            con.execute("UPDATE seguimientos SET nota=?, actualizado=datetime('now','localtime') WHERE id=?",
                        (resto[:400], sid))
            hechos.append(f"{que}: anoté la nota")
        elif re.search(r"\b(cerrad[oa]s?|cerrar|resuelt[oa]s?|solucionad[oa]s?)\b", t):
            con.execute("UPDATE seguimientos SET estado='cerrado', actualizado=datetime('now','localtime') WHERE id=?",
                        (sid,))
            hechos.append(f"{que}: cerrado")
        elif re.search(r"\b(va|van|ira|iran|vendra|vendran|queda para|quedo para|programad|agendad)\b", t) and \
                not re.search(r"\b(se vio|se vieron|vist|revisad|se reviso|limpi)", t):
            f = _fecha_dicha(resto.split(",")[0], futuro=True)
            if not f:
                hechos.append(f"{que}: ¿qué día va? ej «{sid} va el jueves»")
                continue
            nota = re.sub(r"^(el proveedor\s+)?(va|van|ira|iran|vendra|vendran|queda para|quedo para)\s+", "", resto,
                          flags=re.I)
            con.execute("UPDATE seguimientos SET proxima=?, actualizado=datetime('now','localtime') WHERE id=?",
                        (f.isoformat(), sid))
            hechos.append(f"{que}: va {_cuando_txt(f.isoformat())}")
        else:
            f = _fecha_dicha(resto, futuro=False) or hoy()
            extra = resto.split(",", 1)[1].strip() if "," in resto else ""
            con.execute("UPDATE seguimientos SET visto=?, proxima=NULL, nota=CASE WHEN ?<>'' THEN ? ELSE nota END, "
                        "actualizado=datetime('now','localtime') WHERE id=?", (f.isoformat(), extra, extra, sid))
            hechos.append(f"{que}: visto el {f.strftime('%d-%m')}")
        s = con.execute("SELECT * FROM seguimientos WHERE id=?", (sid,)).fetchone()
        aviso = _cumplir_promesa(con, s)
        if aviso:
            out["envios_grupo"].append({"borrador_id": None, "textos": [aviso]})
            hechos[-1] += " (le avisé en el grupo a quien preguntó)"
    log(con, f"Seguimientos {r['ids']} actualizados por {autor}: {resto[:80]}")
    con.commit()
    out["admin"].append("listo. " + "; ".join(hechos) + ".")
    return out


def _cumplir_promesa(con, s):
    """Si alguien preguntó 'para cuándo' y le dijimos 'te comento en breve', ahora se le comenta."""
    if not conf().get("avisar_al_saber", True):
        return None
    preg = json.loads(s["preguntas"] or "[]")
    pend = [p for p in preg if not p.get("respondida")]
    if not pend:
        return None
    for p in preg:
        p["respondida"] = True
    con.execute("UPDATE seguimientos SET preguntas=? WHERE id=?", (json.dumps(preg, ensure_ascii=False), s["id"]))
    import voz
    nombres = sorted({voz.vocativo(p["autor"]) for p in pend if p.get("autor")})
    quien = voz.lista(nombres)
    te = "les" if len(nombres) > 1 else "te"
    que = _que(s)
    if s["estado"] == "cerrado":
        return f"{quien}, {_lo_de(que)} quedó resuelto" + _nota(s["nota"])
    if s["proxima"]:
        return f"{quien}, {te} comento: {_lo_de(que)}, va el proveedor {_cuando_txt(s['proxima'])}."
    if s["visto"]:
        return f"{quien}, {te} comento: {_lo_de(que)} se vio el {_fecha_cl(s['visto'])}" + _nota(s["nota"])
    if s["nota"]:
        return f"{quien}, {te} comento sobre {_lo_de(que)}: {s['nota']}"
    return None
