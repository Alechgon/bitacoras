"""
privado.py — tu chat privado con el bot, en lenguaje natural.

Entiende (con o sin la palabra "caso", con o sin #):
  ok · no · agendar                     -> el último caso pendiente (o el que cites)
  caso 6 no · 6 ok · ok 4 y 5 · ok todos
  caso 3 agendar
  caso 6: pregúntale si tiene fotos     -> le pregunta a la supervisora EN EL GRUPO, citando su mensaje
  pregúntale si la cocina funciona      -> lo mismo, al último caso
  caso 6 responde: mañana va Camilo     -> ese texto reemplaza el borrador y se envía
  el 3 pásalo a Camilo el jueves b2     -> lo reprograma (lo que había ahí se posterga)
  caso 2 + llevar flexible de 1/2       -> suma una nota
  regla 5 si · regla 5 no               -> acepta o rechaza una regla que te propuse
  1 hoy camilo b3, 2 mañana · ok plan   -> plan del día (ver planificador.py)
Si nombra un caso pero no calza con nada, Gemini lo interpreta con tus casos pendientes a la vista.
Si no nombra ningún caso, es un caso nuevo o una pregunta: va al flujo normal.
"""
import json, re
from datetime import datetime, timedelta

import ia
import lenguaje
import memoria
import planificador
from nucleo import buscar, cfg, colocar_forzado, datos, db, en_texto, log, motivo, norm

VERBO_PEDIR = r"(preguntale|preguntales|pregunta|preguntar|pidele|pideles|pide|pedir|consultale|consulta|solicitale|" \
              r"solicita|averigua|que (me )?(mande|manden|envie|envien))"
VERBO_RESP = r"(responde|respondele|responder|respuesta|dile|diles|decirle|contesta|contestale|contestar|manda esto|" \
             r"envia esto|escribele)"
VERBO_NOTA = r"(agrega|agregale|agregar|suma|sumale|sumar|anota|nota|anade)"
VERBO_MOVER = r"(pasalo|pasala|pasa|muevelo|muevela|mueve|mover|cambialo|cambiala|cambia|reprograma|reprogramalo|" \
              r"reprogramala|dejalo|dejala|ponlo|ponla|asignalo|asignala|asigna|mandalo|mandala|que vaya|agendalo para)"


def _vacio():
    return {"admin": [], "envios_grupo": [], "pedidos": [], "mensajes_tecnicos": [], "borradores": [], "grupo": []}


def _palabras(clave, defecto):
    return {norm(x) for x in cfg().get(clave, defecto)}


# ---------------------------------------------------------------- entender
def _sin_fechas(s):
    s = re.sub(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", " ", s)
    s = re.sub(r"\b(?:b|bloque)\s*[1-4]\b", " ", s, flags=re.I)
    return re.sub(r"\ben \d+ dias?\b", " ", s, flags=re.I)


def interpretar(texto, pendientes):
    """Devuelve dict(refs, accion, contenido, todos)."""
    raw = texto.strip()
    cab, cuerpo = raw, ""
    if ":" in raw:
        a, b = raw.split(":", 1)
        if len(a.split()) <= 8:
            cab, cuerpo = a, b.strip()
    cab_limpia = _sin_fechas(cab)
    h = norm(cab_limpia.replace("#", " caso "))
    OK = _palabras("palabras_ok", ["ok"])
    NO = _palabras("palabras_no", ["no"])
    AG = _palabras("agendar_palabras", ["agendar"])
    refs, todos = [], bool(re.search(r"\b(todos|todas|todo)\b", h))

    m = re.search(r"\bcasos?\s+((?:\d{1,4}\s*(?:y|e|,)?\s*)+)", h)
    if m:
        refs = [int(x) for x in re.findall(r"\d{1,4}", m.group(1))]
        h = (h[:m.start()] + " " + h[m.end():]).strip()
    else:
        resto = re.sub(r"\b(\d{1,3}|y|e|el|la|al|del|los|las|caso|casos|todos|todas|todo|a)\b", " ", h).split()
        if re.search(r"\b\d{1,3}\b", h) and resto and all(w in OK | NO | AG for w in resto):
            refs = [int(x) for x in re.findall(r"\b\d{1,3}\b", h)]          # "ok 4 y 5" / "6 no"
            h = " ".join(resto)
        else:
            m = re.match(r"^(?:el|la|al|del)?\s*(\d{1,3})\b\s*(.*)$", h)      # "el 3 pásalo a camilo..."
            if m and re.match(rf"^(y\s+)?({VERBO_MOVER}|{VERBO_PEDIR}|{VERBO_RESP}|{VERBO_NOTA})\b", m.group(2)):
                refs, h = [int(m.group(1))], m.group(2)
    h = re.sub(r"^(y|que|el|la|al)\s+", "", h.strip())
    orden_txt = (cab + " " + cuerpo).strip()
    if not h and cuerpo:                     # "caso 6: pregúntale si tiene fotos"
        h, cuerpo = norm(_sin_fechas(cuerpo)), ""
    cont_completo = (h + (": " + cuerpo if cuerpo else "")).strip()

    def despues(verbo):
        """Lo que va después del verbo, tomado del texto ORIGINAL (con tildes, mayúsculas y fechas)."""
        if cuerpo:
            return cuerpo
        toks = raw.split()
        for k in range(len(toks)):
            for n in (1, 2, 3):
                if re.fullmatch(verbo, norm(" ".join(toks[k:k + n]))):
                    return " ".join(toks[k + n:]).strip(" ,.")
        return ""

    accion, contenido = None, ""
    if todos:
        h = re.sub(r"\b(todos|todas|todo|los|las|a)\b", " ", h).strip()
    palabras = h.split()
    mas = re.search(r"\+\s*(.+)$", raw, re.S)
    if mas and (refs or raw.startswith("+")):          # "caso 2 + llevar flexible"
        accion, contenido = "nota", mas.group(1).strip()
    elif re.match(rf"^{VERBO_PEDIR}\b", h):
        accion, contenido = "pedir_info", despues(VERBO_PEDIR)
    elif re.match(rf"^{VERBO_RESP}\b", h):
        accion, contenido = "reescribir", despues(VERBO_RESP)
    elif re.match(rf"^{VERBO_NOTA}\b", h):
        accion, contenido = "nota", despues(VERBO_NOTA)
    elif palabras and all(w in OK for w in palabras):
        accion = "ok"
    elif palabras and all(w in NO for w in palabras):
        accion = "no"
    elif palabras and all(w in AG | {"ya", "porfa"} for w in palabras):
        accion = "agendar"
    elif lenguaje.tec_de(orden_txt) or lenguaje.bloque_de(orden_txt) or lenguaje.fecha_de(orden_txt) or \
            re.match(rf"^{VERBO_MOVER}\b", h):
        if refs or re.match(rf"^{VERBO_MOVER}\b", h):
            accion, contenido = "reprogramar", orden_txt
    if not refs and not accion:
        accion = None
    return {"refs": refs, "accion": accion, "contenido": contenido, "todos": todos and accion in ("ok", "no", "agendar"),
            "texto": cont_completo}


def _con_ia(texto, pendientes):
    """Gemini interpreta una orden que nombra un caso pero no calza con nada conocido."""
    if not cfg().get("privado", {}).get("entender_con_ia", True) or not pendientes:
        return None
    E = datos()["E"]
    lista = "\n".join(f"#{b['id']} · {E.get(b['rbd'], {}).get('nombre', '?')} · de {b['autor']} · "
                      f"«{b['texto_original'][:120]}»" for b in pendientes[:15])
    prompt = (
        "Eres el asistente de Manuel, encargado de mantención. Él te da órdenes cortas sobre casos pendientes. "
        "Devuelve SOLO JSON: {\"acciones\":[{\"caso\":N,\"accion\":\"ok|no|agendar|pedir_info|reescribir|"
        "reprogramar|nota|nuevo_caso\",\"texto\":\"\",\"tecnico\":\"CAMILO|RODRIGO|\",\"dia\":\"hoy|mañana|lunes|dd/mm|\","
        "\"bloque\":0}]}\n"
        "- pedir_info: texto = lo que hay que preguntarle a la supervisora.\n"
        "- reescribir: texto = la respuesta exacta que Manuel quiere enviar.\n"
        "- nota: texto = lo que hay que agregar.\n- nuevo_caso: el mensaje no es una orden sino un caso nuevo.\n"
        f"CASOS PENDIENTES:\n{lista}\n\nMENSAJE DE MANUEL: {texto}")
    txt = ia.generar(prompt, max_seg=25)
    try:
        return json.loads(re.sub(r"^```(?:json)?|```$", "", (txt or "").strip()))["acciones"]
    except Exception:
        return None


# ---------------------------------------------------------------- hacer
def _pedir_info(con, b, pregunta, autor):
    import servidor as S
    E = datos()["E"]
    c = cfg().get("pedir_info", {})
    sup = b["autor"] if b["origen"] == "grupo" else E.get(b["rbd"], {}).get("sup", "")
    nombre = (sup or "").split()[0] if sup else ""
    texto = ""
    if c.get("redactar_con_ia", True):
        ctx = memoria.contexto_ia(b["rbd"], b["crit"], "pedir_info", sup)
        txt = ia.generar(
            "Convierte la instrucción de Manuel (encargado de mantención) en un mensaje breve para la supervisora "
            f"{nombre or ''} en un grupo de WhatsApp. Español de Chile, cordial, tuteo, 1 o 2 líneas, sin firmar, sin "
            "comillas. Si son varias cosas, enuméralas en la misma línea.\n"
            + (ctx + "\n" if ctx else "")
            + (f"Mensaje original de ella: «{b['texto_original'][:300]}»\n" if b["origen"] == "grupo" else
               f"Es sobre el establecimiento {datos()['E'].get(b['rbd'], {}).get('nombre', '')}.\n")
            + f"Instrucción de Manuel: {pregunta}", max_seg=20)
        if txt and 5 < len(txt) < 400:
            texto = txt.strip().strip('"«»')
    if not texto:
        p = pregunta.strip().rstrip("?.")
        p = re.sub(r"^(si|que)\s+", "", p, flags=re.I)
        p = re.sub(r"^tiene\b", "tienes", p, flags=re.I)
        p = re.sub(r"^puede\b", "puedes", p, flags=re.I)
        p = re.sub(r"\s+y\s+(si|que)\s+", "? ¿", p, flags=re.I)
        if re.match(r"^(fotos?|videos?|registros?|una foto|un video|el|la|los|las|un|una)\b", p, re.I):
            p = f"me puedes mandar {p}"
        sobre = "tu mensaje" if b["origen"] == "grupo" else f"el {__import__('conversacion').nom(b['rbd'])}"
        texto = f"{nombre + ', ' if nombre else ''}una consulta sobre {sobre}: ¿{p}?"
    texto += f"\n_(caso #{b['id']})_"
    con.execute("INSERT INTO pedidos_info(borrador_id, rbd, autor, pregunta) VALUES(?,?,?,?)",
                (b["id"], b["rbd"], b["autor"] if b["origen"] == "grupo" else sup, pregunta))
    memoria.registrar_de_borrador(con, b, "pedir_info", detalle=pregunta, texto_final=texto)
    log(con, f"Caso #{b['id']}: pedida info a {sup}: {pregunta}")
    con.commit()
    minutos = int(c.get("esperar_respuesta_min", 180))
    return ({"borrador_id": b["id"], "texto": texto, "mencionar": bool(c.get("mencionar", True)) and b["origen"] == "grupo"},
            f"❔ Le pregunté a *{sup or 'la supervisora'}* en el grupo (caso #{b['id']}):\n«{texto.splitlines()[0]}»\n"
            f"Lo que responda en las próximas {minutos // 60 if minutos >= 60 else minutos} "
            f"{'horas' if minutos >= 60 else 'min'} lo pego al caso y te aviso.")


def _reprogramar(con, b, orden, autor):
    import servidor as S
    E = datos()["E"]
    if not b["hallazgo_id"] or not b["rbd"]:
        return f"El caso #{b['id']} no tiene una falla con establecimiento para agendar."
    h = con.execute("SELECT * FROM hallazgos WHERE id=?", (b["hallazgo_id"],)).fetchone()
    tec, d, bl = lenguaje.tec_de(orden), lenguaje.fecha_de(orden), lenguaje.bloque_de(orden)
    actual = con.execute("SELECT * FROM tarjetas WHERE id=?", (h["tarjeta_id"],)).fetchone() if h["tarjeta_id"] else None
    if not d:
        d = datetime.strptime(actual["fecha"], "%Y-%m-%d").date() if actual and actual["estado"] == "programada" else None
    if not (tec or d or bl):
        return "¿Para cuándo o con quién? Ej: *caso 3 camilo jueves b2*"
    motivo(con, f"Orden de {autor} por privado (caso #{b['id']}): {orden[:80]}")
    res = colocar_forzado(con, h["rbd"], h["crit"], h["problema"], bool(h["prio"]), h["autor"], h["id"], tec=tec, d=d,
                          b=bl, tarjeta_id=actual["id"] if actual and actual["estado"] == "programada" else None)
    resp = S.texto_respuesta(E[h["rbd"]], h["problema"], h["crit"], res)
    con.execute("UPDATE hallazgos SET estado='agendado', pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                (res["pts"], res["tarjeta"], resp, h["id"]))
    ya_enviado = b["estado"] != "pendiente"
    con.execute("UPDATE borradores SET respuesta=?, tarjeta_id=?, tipo='agendar', estado='pendiente', recordado=0 "
                "WHERE id=?", (("🔁 *Cambio de agenda*\n" if ya_enviado else "") + resp, res["tarjeta"], b["id"]))
    memoria.registrar_de_borrador(con, b, "reprogramar", detalle=orden, tec=res["tec"], fecha_visita=res["fecha"],
                                  bloque=res["bloque"])
    log(con, f"Caso #{b['id']} reprogramado por {autor}: {orden}")
    con.commit()
    extra = ""
    if len(res.get("postergadas", [])) > 1:
        extra = "\n↪️ También se postergan: " + ", ".join(p["nombre"] for p in res["postergadas"][1:])
    return "🔁 Reprogramado. Así queda el borrador:\n\n" + S._texto_borrador(con, b["id"]) + extra


def _reescribir(con, b, texto, autor):
    import servidor as S
    if not texto.strip():
        return None, "¿Qué le respondo? Ej: *caso 6 responde: mañana pasa Camilo*"
    con.execute("UPDATE borradores SET respuesta=? WHERE id=?", (texto.strip(), b["id"]))
    con.commit()
    return S.aprobar("ok", autor, b["id"], memo=("reescribir", "", b["respuesta"])), None


def _consulta_suelta(con, rbd, texto):
    """Pregunta sobre un colegio sin caso abierto: se crea un caso 'consulta' para poder seguir la respuesta."""
    sup = datos()["E"].get(rbd, {}).get("sup", "")
    bid = con.execute("INSERT INTO borradores(origen,autor,texto_original,respuesta,rbd,estado,tipo) "
                      "VALUES('admin',?,?,'',?,'consulta','consulta')", (sup, texto, rbd)).lastrowid
    con.commit()
    return bid


def ejecutar(con, bid, accion, contenido, autor):
    """Una acción sobre un caso. Devuelve una salida parcial."""
    import servidor as S
    out = _vacio()
    b = con.execute("SELECT * FROM borradores WHERE id=?", (bid,)).fetchone()
    if not b:
        out["admin"].append(f"No encuentro el caso #{bid}.")
        return out
    if accion in ("ok", "no", "agendar", "nota") and b["estado"] != "pendiente":
        out["admin"].append(f"El caso #{bid} ya está {b['estado']}.")
        return out
    if accion == "pedir_info":
        if not contenido.strip():
            out["admin"].append("¿Qué le pregunto? Ej: *caso 6: pregúntale si tiene fotos*")
            return out
        ped, aviso = _pedir_info(con, b, contenido, autor)
        out["pedidos"].append(ped)
        out["admin"].append(aviso)
        return out
    if accion == "reprogramar":
        out["admin"].append(_reprogramar(con, b, contenido, autor))
        return out
    if accion == "reescribir":
        r, err = _reescribir(con, b, contenido, autor)
        if err:
            out["admin"].append(err)
            return out
        return S.salida_aprobar(r)
    decision = {"ok": "ok", "no": "no", "agendar": "agendar"}.get(accion, contenido)
    return S.salida_aprobar(S.aprobar(decision, autor, bid))


def _mezclar(a, b):
    for k, v in b.items():
        if isinstance(v, list):
            a.setdefault(k, [])
            a[k] += v
        elif k not in a:
            a[k] = v
    return a


def manejar(texto, autor, citado_bid=None, citado="", ts=None):
    import servidor as S
    con = db()
    raw = (texto or "").strip()
    out = _vacio()
    ahora = datetime.fromtimestamp(ts) if ts else None
    # reporte en vivo desde tu main: "Camilo 1", "rodrigo 2 silvia salas", "camilo salió"
    import en_vivo
    rep = en_vivo.es_reporte(raw)
    if rep:
        out["admin"].append(en_vivo.registrar(con, rep, autor, ahora))
        return out
    # lo que se hizo: "rodrigo hizo hoy japón, suiza", "hoy se hicieron X, Y", "el 03/10 camilo hizo..."
    import realizados
    if realizados.es_deshacer(raw):
        out["admin"].append(realizados.deshacer(con, autor))
        return out
    if realizados.es_pasalas(raw):
        out["admin"].append(realizados.pasalas(con, autor))
        return out
    if realizados.es_reporte(raw):
        out["admin"].append(realizados.aplicar(con, raw, autor))
        return out
    # tus respuestas a seguimientos de frío/cámara: "1 se vio el 03/10", "2 va el jueves", "4 cerrado"
    import seguimientos
    st = seguimientos.es_tuyo(con, raw, citado)
    if st:
        return _mezclar(out, seguimientos.aplicar_tuyo(con, st, autor))
    # reglas que te propuse
    m = re.match(r"^\s*regla\s*r?(\d+)\s*(si|sí|ok|dale|activa|activar|acepto|no|nop|rechaza|rechazar)\b", raw, re.I)
    if m:
        acepta = norm(m.group(2)) not in ("no", "nop", "rechaza", "rechazar")
        out["admin"].append(memoria.decidir_regla(con, m.group(1), acepta, autor))
        return out
    # deshacer un cambio que hizo el bot conversando en el grupo
    m = re.match(r"^\s*deshacer\s*#?\s*(\d+)\s*$", raw, re.I)
    if m:
        import conversacion
        out["admin"].append(conversacion.deshacer(con, int(m.group(1)), autor))
        return out
    # plan del día
    if planificador.parece_plan(con, raw):
        return _mezclar(out, planificador.responder(raw, autor))
    pendientes = con.execute("SELECT * FROM borradores WHERE estado='pendiente' ORDER BY id DESC").fetchall()
    it = interpretar(raw, pendientes)
    refs = it["refs"]
    if it["todos"]:
        refs = [b["id"] for b in reversed(pendientes)]
    if not refs and citado_bid:
        refs = [citado_bid]
    if not refs and it["accion"] and (pendientes or it["accion"] == "pedir_info"):
        if it["accion"] in ("ok", "no", "agendar", "nota", "pedir_info") or re.match(
                rf"^({VERBO_RESP}|{VERBO_MOVER})\b", norm(raw)):
            # sin número: el caso del colegio que nombras ("…la emergencia del República de Austria"), o el último
            nombrados = en_texto(raw)
            if not nombrados:
                top = buscar(raw)
                nombrados = [top[0][1]] if top and top[0][0] >= 85 else []
            pool = list(pendientes)
            if it["accion"] == "pedir_info":       # también se puede preguntar por casos ya enviados o conversados
                desde = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
                pool += con.execute("SELECT * FROM borradores WHERE estado<>'pendiente' AND creado>=? ORDER BY id DESC",
                                    (desde,)).fetchall()
            del_colegio = [b["id"] for b in pool if b["rbd"] in nombrados]
            if del_colegio:
                refs = [del_colegio[0]]
            elif it["accion"] == "pedir_info" and nombrados:
                refs = [_consulta_suelta(con, nombrados[0], raw)]
            elif pendientes and not nombrados:
                refs = [pendientes[0]["id"]]
            elif it["accion"] == "pedir_info":
                out["admin"].append("¿A quién le pregunto? Dime el colegio o el número del caso. "
                                    "Ej: *caso 6: pregúntale si tiene fotos*")
                return out
    if refs and it["accion"]:
        for bid in refs:
            _mezclar(out, ejecutar(con, bid, it["accion"], it["contenido"], autor))
        return out
    if refs:                                           # nombró un caso pero no sé qué quiere: Gemini
        acciones = _con_ia(raw, pendientes)
        if acciones:
            for a in acciones:
                acc = a.get("accion")
                if acc == "nuevo_caso":
                    break
                if acc not in ("ok", "no", "agendar", "pedir_info", "reescribir", "reprogramar", "nota"):
                    continue
                cont = a.get("texto") or ""
                if acc == "reprogramar":
                    cont = " ".join(str(x) for x in (a.get("tecnico"), a.get("dia"),
                                                      f"b{a['bloque']}" if a.get("bloque") else "") if x)
                _mezclar(out, ejecutar(con, int(a.get("caso") or refs[0]), acc, cont, autor))
            else:
                if any(out.values()):
                    out["admin"].insert(0, "🧠 (Lo interpreté con IA)")
                    return out
        if not any(out.values()):
            out["admin"].append(
                f"No entendí qué hacer con el caso #{refs[0]}. Puedes decir:\n*caso {refs[0]} ok* · *caso {refs[0]} no* · "
                f"*caso {refs[0]}: pregúntale …* · *caso {refs[0]} responde: …* · *caso {refs[0]} camilo jueves b2*")
            return out
    # nada que ver con casos pendientes: es un caso nuevo o una pregunta tuya
    r = S.entrada("admin", raw, autor, citado=citado, ahora=datetime.fromtimestamp(ts) if ts else None)
    return _mezclar(out, r)
