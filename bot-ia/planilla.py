"""
planilla.py — todo respaldado en tu Google Sheet (el mismo del panel), ordenado por hojas.

Manda a tu Apps Script el MISMO paquete que manda el panel cuando aprietas "Respaldar en Google",
pero con la agenda viva del bot. El script arma las hojas de siempre:
  Panel (KPIs y metas) · Programa (el cronograma completo) · Establecimientos · Correctivos ·
  Bitácoras · Datácora · Movimientos (cada cambio de agenda y por qué) · Reportes supervisoras ·
  Semanas · Histórico (avance de metas día a día)
y además hojas propias del bot:
  Cronograma (próximas 4 semanas, día × técnico × bloque) · Metas por establecimiento ·
  Hallazgos WhatsApp · Conversaciones · Consultas a supervisoras · Mensajes del grupo
(Decisiones del encargado, Reglas del bot y Bitácoras del bot las escribe memoria.py.)

Se sube sola cuando la agenda cambia (y al menos una vez por hora). A mano: !planilla
"""
import hashlib, json, threading
from datetime import datetime, timedelta

from nucleo import (a_fecha, agenda, bloques, bonita, cfg, datos, db, es_habil, habiles_entre, hora_bloque, hoy,
                    metas, nombre_tec, sumar_habiles)

_lock = threading.Lock()
_estado = {"hash": None, "hash_tablas": None, "ultimo": None, "resultado": "todavía no sube", "kpi": None}


def _conf():
    return cfg().get("planilla", {})


def _hora(fecha, bloque):
    try:
        return hora_bloque(fecha, bloque)
    except Exception:
        return ""


# ---------------------------------------------------------------- el paquete del panel, con la agenda viva
def construir_estado(con):
    D = datos()
    E = D["E"]
    tarjetas = {t["id"]: t for t in con.execute("SELECT * FROM tarjetas")}
    plan = []
    for p in D["PLAN"]:
        q = dict(p)
        t = tarjetas.get(p["id"])
        if t:
            q.update(fecha=t["fecha"], tec=t["tec"], bloque=t["bloque"], hora=_hora(t["fecha"], t["bloque"]),
                     estado=t["estado"], aplaz=t["aplaz"], clase=t["clase"], detalle=t["detalle"], pts=t["pts"],
                     crit=t["crit"] or q.get("crit", ""))
        plan.append(q)
    ids = {p["id"] for p in D["PLAN"]}
    for t in tarjetas.values():
        if t["id"] in ids:
            continue
        plan.append({"id": t["id"], "fase": "BOT", "fecha": t["fecha"], "tec": t["tec"], "bloque": t["bloque"],
                     "hora": _hora(t["fecha"], t["bloque"]), "rbd": t["rbd"], "clase": t["clase"],
                     "detalle": t["detalle"], "pts": t["pts"], "crit": t["crit"] or "", "estado": t["estado"],
                     "aplaz": t["aplaz"], "tipoReal": "Correctiva" if "CORRECTIVO" in (t["clase"] or "") else "",
                     "origen": "bot"})

    corr = list(D.get("CORR", []))
    for h in con.execute("SELECT h.*, t.fecha AS f_ag FROM hallazgos h LEFT JOIN tarjetas t ON t.id=h.tarjeta_id "
                         "WHERE h.rbd IS NOT NULL AND h.estado IN ('registrado','agendado','por_confirmar')"):
        try:
            dias = (datetime.now() - datetime.strptime(h["recibido"][:10], "%Y-%m-%d")).days
        except ValueError:
            dias = 0
        corr.append({"rbd": h["rbd"], "estado": "AGENDADO" if h["estado"] == "agendado" else "PENDIENTE",
                     "detalle": f"[WhatsApp · {h['autor']}] {h['problema']}", "crit": h["crit"] or "OTRO",
                     "freporte": h["recibido"][:10], "dias": dias, "prio": bool(h["prio"]), "pts": h["pts"] or 0,
                     "agendado": h["f_ag"] or ""})

    menc = list(D.get("MENC", []))
    for m in con.execute("SELECT * FROM mensajes WHERE origen='grupo' AND rbd IS NOT NULL ORDER BY id DESC LIMIT 400"):
        menc.append({"fecha": m["recibido"][:10], "rbd": m["rbd"], "autor": m["autor"], "texto": m["texto"]})

    bits = list(D.get("BITS", []))
    folios = {str(b.get("folio")) for b in bits}
    for b in con.execute("SELECT * FROM bitacoras"):
        if str(b["folio"]) in folios:
            continue
        its = [dict(r) for r in con.execute("SELECT categoria, item, ubicacion, cantidad, accion, observacion "
                                            "FROM bitacora_items WHERE folio=?", (b["folio"],))]
        bits.append({"folio": b["folio"], "fecha": b["fecha"], "rbd": b["rbd"], "estab": b["establecimiento"],
                     "tecnico": b["tecnico"], "items": its, "fuente": "bot"})

    log_ = []
    for m in con.execute("SELECT * FROM movimientos ORDER BY id"):
        if m["estado"] == "nueva":
            que = f"Nueva visita {m['a_fecha']} B{m['a_bloque']} {nombre_tec(m['a_tec'] or '')}"
        elif m["estado"] != m["estado_antes"]:
            que = f"{m['estado_antes']} → {m['estado']}"
        else:
            que = (f"{m['de_fecha']} B{m['de_bloque']} {nombre_tec(m['de_tec'] or '')} → "
                   f"{m['a_fecha']} B{m['a_bloque']} {nombre_tec(m['a_tec'] or '')}")
        log_.append({"ts": m["cuando"].replace(" ", "T"), "rbd": m["rbd"], "aplaz": m["aplaz"] or 0,
                     "nueva": m["a_fecha"] or "", "motivo": f"{m['motivo']} · {que}", "fuente": "bot"})

    return {"META": D["META"], "ESTAB": D["ESTAB"], "CORR": corr, "MENC": menc, "DC": D.get("DC", []),
            "CATS": D.get("CATS", []), "PLAN": plan, "BITS": bits, "LOG": log_}


# ---------------------------------------------------------------- hojas propias del bot
def _col(t, w=110, **kw):
    return {"t": t, "w": w, **kw}


def tablas(con):
    D = datos()
    E = D["E"]
    out = []

    # Cronograma: próximas 4 semanas, una fila por día y técnico
    filas, d = [], hoy()
    fin = sumar_habiles(d, 20)
    for dia in habiles_entre(d, fin):
        for tec in D["META"]["tecnicos"]:
            por_b = {t["bloque"]: t for t in agenda(con, dia, dia, tec)}
            celdas = []
            for b in (1, 2, 3):
                t = por_b.get(b)
                if b not in bloques(dia):
                    celdas.append("—")
                elif t:
                    celdas.append(f"{E.get(t['rbd'], {}).get('nombre', t['rbd'])} · {t['clase'].lower()} ({t['pts']})")
                else:
                    celdas.append("LIBRE")
            extra = "; ".join(f"{E.get(t['rbd'], {}).get('nombre', t['rbd'])}" for b, t in por_b.items() if b > 3)
            filas.append([dia.isoformat(), bonita(dia), nombre_tec(tec), *celdas, extra,
                          sum(1 for c in celdas if c == "LIBRE")])
    out.append({"hoja": "Cronograma", "titulo": "Cronograma · próximas 4 semanas (agenda viva del bot)",
                "sub": "Una fila por día y técnico. Cambia solo cuando el bot o tú mueven algo · " +
                       datetime.now().strftime("%d-%m-%Y %H:%M"),
                "cols": [_col("Fecha", 92, al="center"), _col("Día", 80, al="center"), _col("Técnico", 90),
                         _col("Bloque 1", 260, wrap=True), _col("Bloque 2", 260, wrap=True),
                         _col("Bloque 3", 260, wrap=True), _col("Extra", 200, wrap=True),
                         _col("Libres", 60, al="center")],
                "filas": filas})

    # Metas por establecimiento: qué falta y cuándo se cumple
    M = D["META"]
    hechas = {r[0] for r in con.execute("SELECT rbd FROM tarjetas WHERE estado='realizada'")}
    prev_hechas = {r[0] for r in con.execute("SELECT rbd FROM tarjetas WHERE estado='realizada' AND clase LIKE 'PREV%'")}
    prox = {}
    for t in con.execute("SELECT * FROM tarjetas WHERE estado='programada' ORDER BY fecha"):
        prox.setdefault(t["rbd"], t)
    filas = []
    for e in D["ESTAB"]:
        junaeb = e["inst"] == "Junaeb"
        meta_f = M["metaJunaeb"] if junaeb else M["metaJardines"]
        ok = (e.get("enDatacora") or e["rbd"] in hechas) if junaeb else (e.get("prevOK") or e["rbd"] in prev_hechas)
        t = prox.get(e["rbd"])
        if ok:
            estado, holgura = "CUMPLIDA", ""
        elif t:
            estado = "AGENDADA" if t["fecha"] <= meta_f else "AGENDADA DESPUÉS DE LA META"
            holgura = len(list(habiles_entre(a_fecha(t["fecha"]), a_fecha(meta_f)))) - 1 if t["fecha"] <= meta_f else \
                -len(list(habiles_entre(a_fecha(meta_f), a_fecha(t["fecha"]))))
        else:
            estado, holgura = "SIN AGENDAR", ""
        filas.append([e["rbd"], e["nombre"], e["inst"], e["sup"],
                      "Visita cargada en Datácora" if junaeb else "Preventiva completa", meta_f, estado,
                      t["fecha"] if t and not ok else "", nombre_tec(t["tec"]) if t and not ok else "",
                      (t["clase"] if t and not ok else ""), holgura, e["pts"]])
    orden = {"AGENDADA DESPUÉS DE LA META": 0, "SIN AGENDAR": 1, "AGENDADA": 2, "CUMPLIDA": 3}
    filas.sort(key=lambda f: (orden[f[6]], f[7] or "9999"))
    m = metas(con)
    j, jt, jf = m["junaeb"]
    g, gt, gf = m["jardines"]
    out.append({"hoja": "Metas por establecimiento",
                "titulo": f"Metas · JUNAEB {j}/{jt} al {jf} · Jardines {g}/{gt} al {gf}",
                "sub": "Primero lo que está en riesgo (agendado después de la meta o sin agendar) · " +
                       datetime.now().strftime("%d-%m-%Y %H:%M"),
                "cols": [_col("RBD", 70, al="center"), _col("Establecimiento", 230), _col("Inst.", 66, al="center"),
                         _col("Supervisora", 140), _col("Meta", 170), _col("Fecha meta", 92, al="center"),
                         _col("Estado", 190, al="center"), _col("Próxima visita", 100, al="center"),
                         _col("Técnico", 80), _col("Clase", 140), _col("Holgura (días háb.)", 90, al="center"),
                         _col("Pts", 48, al="center")],
                "filas": filas})

    # Hallazgos que llegaron por WhatsApp
    filas = []
    for h in con.execute("SELECT h.*, t.fecha AS f_ag, t.tec, t.bloque FROM hallazgos h LEFT JOIN tarjetas t "
                         "ON t.id=h.tarjeta_id ORDER BY h.id DESC LIMIT 500"):
        filas.append([h["recibido"], h["autor"], h["rbd"] or "", E.get(h["rbd"], {}).get("nombre", ""),
                      E.get(h["rbd"], {}).get("sup", ""), h["crit"], h["problema"], h["pts"] or "", h["estado"],
                      h["f_ag"] or "", nombre_tec(h["tec"]) if h["tec"] else "", h["bloque"] or "", h["texto"][:500]])
    out.append({"hoja": "Hallazgos WhatsApp", "titulo": "Fallas reportadas por WhatsApp",
                "sub": "Lo que el bot leyó del grupo y qué hizo · " + datetime.now().strftime("%d-%m-%Y %H:%M"),
                "cols": [_col("Recibido", 120), _col("Quién", 140), _col("RBD", 70, al="center"),
                         _col("Establecimiento", 220), _col("Supervisora", 140), _col("Falla", 70, al="center"),
                         _col("Problema", 260, wrap=True), _col("Pts", 48, al="center"), _col("Estado", 100),
                         _col("Agendado", 92, al="center"), _col("Técnico", 80), _col("Bloque", 56, al="center"),
                         _col("Mensaje", 360, wrap=True)],
                "filas": filas})

    # Conversaciones del bot con las supervisoras
    filas = [[h["creado"], h["id"], h["autor"], h["rbd"] or "", E.get(h["rbd"], {}).get("nombre", ""), h["crit"],
              h["texto"][:400], h["paso"], h["estado"], h["resultado"] or ""]
             for h in con.execute("SELECT * FROM hilos ORDER BY id DESC LIMIT 300")]
    out.append({"hoja": "Conversaciones", "titulo": "Conversaciones del bot en el grupo",
                "sub": "Preguntas de detalle/colegio y coordinación de agenda · " + datetime.now().strftime("%d-%m-%Y %H:%M"),
                "cols": [_col("Fecha", 120), _col("#", 40, al="center"), _col("Supervisora", 140),
                         _col("RBD", 70, al="center"), _col("Establecimiento", 220), _col("Falla", 70, al="center"),
                         _col("Lo que dijo", 340, wrap=True), _col("Paso", 80), _col("Estado", 80),
                         _col("Resultado", 260, wrap=True)],
                "filas": filas})

    # Consultas que pediste a las supervisoras
    filas = [[p["creado"], p["borrador_id"], p["autor"], p["rbd"] or "", E.get(p["rbd"], {}).get("nombre", ""),
              p["pregunta"], p["estado"], p["respuesta"] or "", p["respondido"] or ""]
             for p in con.execute("SELECT * FROM pedidos_info ORDER BY id DESC LIMIT 300")]
    out.append({"hoja": "Consultas a supervisoras", "titulo": "Lo que les preguntaste por el bot",
                "sub": datetime.now().strftime("%d-%m-%Y %H:%M"),
                "cols": [_col("Fecha", 120), _col("Caso", 50, al="center"), _col("Supervisora", 140),
                         _col("RBD", 70, al="center"), _col("Establecimiento", 220), _col("Pregunta", 300, wrap=True),
                         _col("Estado", 90), _col("Respuesta", 320, wrap=True), _col("Respondió", 120)],
                "filas": filas})

    # Mensajes del grupo (lo que leyó el bot y cómo lo entendió)
    filas = [[m["recibido"], m["origen"], m["autor"], m["intencion"], m["rbd"] or "",
              E.get(m["rbd"], {}).get("nombre", ""), m["texto"][:500], m["resultado"] or "", m["motor"] or ""]
             for m in con.execute("SELECT * FROM mensajes ORDER BY id DESC LIMIT 500")]
    out.append({"hoja": "Mensajes del grupo", "titulo": "Mensajes leídos por el bot",
                "sub": "Últimos 500 · " + datetime.now().strftime("%d-%m-%Y %H:%M"),
                "cols": [_col("Recibido", 120), _col("Origen", 60), _col("Autor", 140), _col("Intención", 100),
                         _col("RBD", 70, al="center"), _col("Establecimiento", 200), _col("Mensaje", 380, wrap=True),
                         _col("Resultado", 140), _col("Motor", 120)],
                "filas": filas})
    return out


# ---------------------------------------------------------------- subir
def _hash(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def toca():
    c = _conf()
    if not c.get("activa", True):
        return False
    u = _estado["ultimo"]
    return u is None or (datetime.now() - u).total_seconds() >= int(c.get("revisar_min", 10)) * 60


def sincronizar(forzar=False):
    """Sube a la planilla solo si algo cambió (o si pasó más de una hora). Devuelve un texto de resultado."""
    import memoria
    if not _lock.acquire(blocking=False):
        return "ya estaba subiendo"
    try:
        con = db()
        est = construir_estado(con)
        tbs = tablas(con)
        h1 = _hash({k: est[k] for k in ("PLAN", "CORR", "LOG", "BITS")})
        h2 = _hash([{**t, "sub": "", "titulo": ""} for t in tbs])
        viejo = _estado["ultimo"] and (datetime.now() - _estado["ultimo"]).total_seconds() > \
            int(_conf().get("refrescar_min", 60)) * 60
        hecho = []
        if forzar or viejo or h1 != _estado["hash"]:
            r = memoria._post({"accion": "estado", "estado": est}, timeout=300)
            _estado["hash"] = h1
            _estado["kpi"] = r.get("kpi")
            hecho.append(f"{len(est['PLAN'])} visitas")
        if forzar or viejo or h2 != _estado["hash_tablas"]:
            memoria._post({"accion": "tablas", "tablas": tbs}, timeout=300)
            _estado["hash_tablas"] = h2
            hecho.append(f"{len(tbs)} hojas del bot")
        _estado["resultado"] = ("ok: " + ", ".join(hecho)) if hecho else "sin cambios"
    except Exception as e:
        _estado["resultado"] = f"no se pudo subir ({str(e)[:150]})"
    finally:
        _estado["ultimo"] = datetime.now()
        _lock.release()
    return _estado["resultado"]


def estado_texto():
    u = _estado["ultimo"]
    k = _estado.get("kpi") or {}
    extra = ""
    if k.get("meta1"):
        extra = (f" · planilla dice: JUNAEB {k['meta1']['hecho']}/{k['meta1']['total']}, "
                 f"jardines {k['meta2']['hecho']}/{k['meta2']['total']}")
    return f"{_estado['resultado']}" + (f" ({u.strftime('%H:%M')})" if u else "") + extra
