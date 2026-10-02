"""
memoria.py — lo que el bot aprende de ti.

1. Cada decisión tuya (ok, no, agendar, pedir info, reescribir, mover, plan) queda en la
   base local y se sube a tu planilla de Google, hoja "Decisiones del encargado".
2. Antes de redactar, el bot busca tus decisiones parecidas (mismo colegio, falla, tipo,
   supervisora) y se las muestra a Gemini como ejemplo de cómo decides tú.
3. Una vez al día revisa tus decisiones y te PROPONE reglas cuando ve un patrón
   ("en gas siempre pides fotos"). Solo se activan si dices "regla N si".
4. Las reglas viven en la hoja "Reglas del bot": puedes editarlas o escribir nuevas a mano
   (columna Activa = si/no). El bot las trae cada pocos minutos.

Tipos de regla que el bot APLICA:
  preguntar    · alcance falla:GAS / rbd:8678 / todas · valor = preguntas que se agregan al borrador
  tecnico      · alcance falla:X / rbd:N              · valor = CAMILO / RODRIGO (quién va primero)
  instruccion  · alcance todas / falla:X / rbd:N      · valor = indicación para redactar (tono, qué incluir)
"""
import json, re, secrets, threading, urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from nucleo import cfg, datos, db, log, norm

_lock = threading.Lock()
_estado = {"pendiente": False, "ultimo_sync": None, "ultimo_resultado": "todavía no sincroniza"}


# ---------------------------------------------------------------- configuración
def conf():
    return cfg().get("memoria", {})


def asegurar_clave():
    """La clave que protege tu planilla. Se crea sola la primera vez."""
    import ajustes
    raw = ajustes.leer()
    if not raw.get("memoria", {}).get("clave"):
        raw.setdefault("memoria", {})["clave"] = secrets.token_hex(16)     # directo: por chat no se puede cambiar
        ajustes.guardar(raw)


def _post(payload, timeout=25):
    url = conf().get("apps_script_url", "")
    if not url or not conf().get("activa", True):
        raise RuntimeError("memoria en Google desactivada o sin URL")
    payload = {**payload, "origen": "bot", "clave": conf().get("clave", "")}
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:      # Apps Script responde con 302 -> GET (urllib lo sigue)
        out = json.loads(r.read().decode("utf-8", "ignore"))
    if not out.get("ok"):
        raise RuntimeError(out.get("error", "respuesta sin ok"))
    return out


# ---------------------------------------------------------------- decisiones
def registrar(con, caso=None, origen="", supervisora="", rbd=None, tipo="", crit="", original="", propuesta="",
              decision="", detalle="", texto_final="", tec="", fecha_visita="", bloque=""):
    E = datos()["E"]
    con.execute("""INSERT INTO decisiones(fecha,caso,origen,supervisora,rbd,estab,tipo,crit,original,propuesta,
                   decision,detalle,texto_final,tec,fecha_visita,bloque,sync)
                   VALUES(datetime('now','localtime'),?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (caso, origen, supervisora, rbd, E.get(rbd, {}).get("nombre", ""), tipo or "", crit or "",
                 (original or "")[:1500], (propuesta or "")[:1500], decision, (detalle or "")[:800],
                 (texto_final or "")[:1500], tec or "", str(fecha_visita or ""), str(bloque or "")))
    _estado["pendiente"] = True          # el tick la sube al minuto siguiente (ya con la base guardada)


def registrar_de_borrador(con, b, decision, detalle="", texto_final="", tec="", fecha_visita="", bloque=""):
    """Atajo: arma la decisión con los datos del borrador (caso) y su hallazgo."""
    h = con.execute("SELECT * FROM hallazgos WHERE id=?", (b["hallazgo_id"],)).fetchone() if b["hallazgo_id"] else None
    sup = datos()["E"].get(b["rbd"], {}).get("sup", "") if b["rbd"] else ""
    registrar(con, caso=b["id"], origen=b["origen"], supervisora=(b["autor"] if b["origen"] == "grupo" else sup),
              rbd=b["rbd"], tipo=b["tipo"] or "", crit=b["crit"] or (h["crit"] if h else ""),
              original=b["texto_original"], propuesta=b["respuesta"], decision=decision, detalle=detalle,
              texto_final=texto_final, tec=tec, fecha_visita=fecha_visita, bloque=bloque)


# ---------------------------------------------------------------- sincronización con Google Sheets
def sincronizar():
    """Sube decisiones pendientes y trae las reglas (las editadas por ti en la planilla mandan)."""
    if not _lock.acquire(blocking=False):
        return "ocupado"
    try:
        con = db()
        pend = con.execute("SELECT * FROM decisiones WHERE sync=0 ORDER BY id LIMIT 60").fetchall()
        if pend:
            filas = [[d["fecha"], d["caso"] or "", d["origen"], d["supervisora"], d["rbd"] or "", d["estab"], d["tipo"],
                      d["crit"], d["original"], d["propuesta"], d["decision"], d["detalle"], d["texto_final"],
                      d["tec"], d["fecha_visita"], d["bloque"]] for d in pend]
            _post({"accion": "decisiones", "filas": filas})
            con.execute(f"UPDATE decisiones SET sync=1 WHERE id IN ({','.join(str(d['id']) for d in pend)})")
            con.commit()
        out = _post({"accion": "leer", "n": 50})
        for r in out.get("reglas", []):
            con.execute("""INSERT INTO reglas(id,activa,tipo,alcance,valor,descripcion,origen,creada,evidencia,estado)
                           VALUES(?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(id) DO UPDATE SET activa=excluded.activa, tipo=excluded.tipo,
                           alcance=excluded.alcance, valor=excluded.valor, descripcion=excluded.descripcion,
                           estado=CASE WHEN excluded.activa=1 THEN 'activa'
                                       WHEN reglas.estado IN ('propuesta','rechazada') THEN reglas.estado
                                       ELSE 'inactiva' END""",
                        (r["id"], int(bool(r["activa"])), r["tipo"], r["alcance"], str(r["valor"]), r["descripcion"],
                         r.get("origen", "planilla"), r.get("creada", ""), int(r.get("evidencia") or 0),
                         "activa" if r["activa"] else "inactiva"))
        con.commit()
        _estado["pendiente"] = False
        _estado["ultimo_resultado"] = f"ok: {len(pend)} decisiones subidas, {len(out.get('reglas', []))} reglas leídas"
    except Exception as e:
        _estado["ultimo_resultado"] = f"sin sincronizar ({str(e)[:120]})"
    finally:
        _estado["ultimo_sync"] = datetime.now()
        _lock.release()
    return _estado["ultimo_resultado"]


def toca_sincronizar():
    """True si hay decisiones nuevas o pasaron sync_min minutos desde la última vez."""
    if not conf().get("activa", True) or not conf().get("apps_script_url"):
        return False
    u = _estado["ultimo_sync"]
    cada = int(conf().get("sync_min", 10) or 10)
    return _estado["pendiente"] or u is None or (datetime.now() - u).total_seconds() >= cada * 60


def estado_texto():
    con = db()
    n = con.execute("SELECT COUNT(*) FROM decisiones").fetchone()[0]
    p = con.execute("SELECT COUNT(*) FROM decisiones WHERE sync=0").fetchone()[0]
    a = con.execute("SELECT COUNT(*) FROM reglas WHERE estado='activa'").fetchone()[0]
    pr = con.execute("SELECT COUNT(*) FROM reglas WHERE estado='propuesta'").fetchone()[0]
    u = _estado["ultimo_sync"]
    return (f"{n} decisiones ({p} sin subir) · {a} reglas activas, {pr} propuestas · "
            f"planilla: {_estado['ultimo_resultado']}" + (f" ({u.strftime('%H:%M')})" if u else ""))


def subir_regla(r):
    try:
        _post({"accion": "regla", "regla": {"id": r["id"], "activa": r["estado"] == "activa", "tipo": r["tipo"],
                                            "alcance": r["alcance"], "valor": r["valor"],
                                            "descripcion": r["descripcion"], "origen": r["origen"],
                                            "creada": r["creada"], "evidencia": r["evidencia"]}})
    except Exception as e:
        print("[memoria] no pude subir la regla:", e)


# ---------------------------------------------------------------- reglas: aplicar
def _aplica(alcance, crit, rbd):
    a = re.sub(r"\s+", "", str(alcance or "todas")).lower()
    if a in ("todas", "todo", "siempre", ""):
        return True
    valor = re.split(r"[:=]", a, 1)[-1]
    if a.startswith("falla") and crit:
        return norm(valor).upper() == str(crit).upper()
    if a.startswith("rbd") and rbd:
        return valor == str(rbd)
    return False


def activas(tipo=None, con=None):
    q = "SELECT * FROM reglas WHERE estado='activa'"
    return [r for r in (con or db()).execute(q).fetchall() if not tipo or r["tipo"] == tipo]


def preguntas_para(crit, rbd, con=None):
    return [r["valor"] for r in activas("preguntar", con) if _aplica(r["alcance"], crit, rbd)]


def tecnico_para(crit, rbd, con=None):
    rs = [r for r in activas("tecnico", con) if _aplica(r["alcance"], crit, rbd)]
    rs.sort(key=lambda r: 0 if str(r["alcance"]).startswith("rbd") else 1)      # la regla del colegio manda
    return str(rs[0]["valor"]).strip().upper() if rs else None


def instrucciones(crit=None, rbd=None, con=None):
    return [r["valor"] for r in activas("instruccion", con) if _aplica(r["alcance"], crit, rbd)]


def contexto_ia(rbd=None, crit=None, tipo=None, supervisora=None):
    """Bloque de texto para pegar en cualquier prompt de Gemini: tus reglas de estilo + tus decisiones parecidas."""
    out = []
    ins = instrucciones(crit, rbd)
    if ins:
        out.append("INSTRUCCIONES DE MANUEL (obligatorias):\n" + "\n".join(f"- {i}" for i in ins))
    ej = ejemplos(rbd, crit, tipo, supervisora)
    if ej:
        out.append("ASÍ HA DECIDIDO Y ESCRITO MANUEL EN CASOS PARECIDOS (imita su criterio y tono):\n" + "\n".join(ej))
    return "\n\n".join(out)


# ---------------------------------------------------------------- ejemplos para Gemini
def ejemplos(rbd=None, crit=None, tipo=None, supervisora=None, n=None):
    """Tus decisiones más parecidas, en texto, para que Gemini imite cómo decides y escribes."""
    n = n or int(conf().get("ejemplos", 4))
    filas = db().execute("SELECT * FROM decisiones ORDER BY id DESC LIMIT 400").fetchall()

    def puntaje(d):
        return (3 if rbd and d["rbd"] == rbd else 0) + (2 if crit and d["crit"] == crit else 0) + \
               (2 if tipo and d["tipo"] == tipo else 0) + (1 if supervisora and d["supervisora"] == supervisora else 0) + \
               (2 if d["decision"] in ("reescribir", "pedir_info", "nota") else 0)
    mejores = sorted(filas, key=puntaje, reverse=True)[:n]
    out = []
    for d in mejores:
        if puntaje(d) == 0:
            continue
        lin = f"- Mensaje: «{d['original'][:160]}» → bot propuso: «{d['propuesta'][:160]}» → Manuel decidió: {d['decision']}"
        if d["detalle"]:
            lin += f" ({d['detalle'][:120]})"
        if d["texto_final"] and d["texto_final"] != d["propuesta"]:
            lin += f" → texto final: «{d['texto_final'][:200]}»"
        out.append(lin)
    return out


# ---------------------------------------------------------------- reglas: aprender
def _nuevo_id(con):
    n = con.execute("SELECT COUNT(*) FROM reglas").fetchone()[0] + 1
    while con.execute("SELECT 1 FROM reglas WHERE id=?", (f"R{n}",)).fetchone():
        n += 1
    return f"R{n}"


def _ya_existe(con, tipo, alcance, valor):
    for r in con.execute("SELECT * FROM reglas WHERE tipo=? AND alcance=?", (tipo, alcance)).fetchall():
        if norm(r["valor"]) == norm(valor) or r["estado"] in ("rechazada",) and tipo != "instruccion":
            return True
    return False


def proponer(con, tipo, alcance, valor, descripcion, evidencia, origen="aprendida"):
    if _ya_existe(con, tipo, alcance, valor):
        return None
    rid = _nuevo_id(con)
    con.execute("INSERT INTO reglas(id,activa,tipo,alcance,valor,descripcion,origen,creada,evidencia,estado) "
                "VALUES(?,0,?,?,?,?,?,datetime('now','localtime'),?,'propuesta')",
                (rid, tipo, alcance, valor, descripcion, origen, evidencia))
    return rid


def minar():
    """Busca patrones en tus decisiones de los últimos 60 días. Devuelve mensajes de propuesta."""
    m = int(conf().get("min_evidencia", 3))
    con = db()
    desde = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    decs = con.execute("SELECT * FROM decisiones WHERE fecha>=?", (desde,)).fetchall()
    nuevas = []

    # 1) siempre pides la misma información en cierto tipo de falla
    por_falla = defaultdict(list)
    for d in decs:
        if d["decision"] == "pedir_info" and d["crit"]:
            por_falla[d["crit"]].append(d["detalle"])
    for crit, textos in por_falla.items():
        if len(textos) >= m:
            frase = Counter(norm(t) for t in textos).most_common(1)[0][0]
            original = next(t for t in textos if norm(t) == frase)
            rid = proponer(con, "preguntar", f"falla:{crit}", original,
                           f"En fallas de {crit}, preguntar siempre: «{original}»", len(textos))
            if rid:
                nuevas.append((rid, f"En fallas de *{crit}* pediste información {len(textos)} veces. "
                                    f"¿Agrego siempre al borrador: «{original}»?"))

    # 2) siempre cambias al mismo técnico para cierta falla
    tec_falla = defaultdict(list)
    for d in decs:
        if d["decision"] in ("reprogramar", "plan") and d["tec"] and d["crit"]:
            tec_falla[d["crit"]].append(d["tec"].upper())
    pref = cfg().get("preferencia_tecnico", {})
    for crit, tecs in tec_falla.items():
        tec, veces = Counter(tecs).most_common(1)[0]
        if veces >= m and veces / len(tecs) >= 0.7 and pref.get(crit) != tec:
            rid = proponer(con, "tecnico", f"falla:{crit}", tec,
                           f"En fallas de {crit}, mandar primero a {tec.title()}", veces)
            if rid:
                nuevas.append((rid, f"En *{crit}* elegiste a *{tec.title()}* {veces} de {len(tecs)} veces. "
                                    f"¿Lo dejo como primera opción?"))

    # 3) tu estilo: cuando reescribes respuestas, Gemini resume qué cambias
    reescritas = [d for d in decs if d["decision"] == "reescribir" and d["texto_final"]][-12:]
    if len(reescritas) >= m:
        import ia
        pares = "\n".join(f"- Bot: «{d['propuesta'][:220]}»\n  Manuel: «{d['texto_final'][:220]}»" for d in reescritas)
        txt = ia.generar("Compara cómo escribía un bot y cómo corrigió Manuel (encargado de mantención). "
                         "Devuelve SOLO un JSON lista de 1 a 3 instrucciones cortas y concretas (máx 20 palabras c/u) "
                         "para que el bot escriba como Manuel. Ej: [\"Saludar a la supervisora por su nombre\"]\n\n"
                         + pares, max_seg=30)
        try:
            for inst in json.loads(re.sub(r"^```(?:json)?|```$", "", (txt or "").strip()))[:3]:
                rid = proponer(con, "instruccion", "todas", inst, f"Estilo: {inst}", len(reescritas))
                if rid:
                    nuevas.append((rid, f"Viendo cómo corriges mis respuestas: «{inst}». ¿Lo aplico siempre?"))
        except Exception:
            pass
    con.commit()
    for rid, _ in nuevas:
        subir_regla(con.execute("SELECT * FROM reglas WHERE id=?", (rid,)).fetchone())
    return [f"📐 *Regla propuesta {rid}*\n{txt}\nResponde *regla {rid[1:]} si* o *regla {rid[1:]} no*."
            for rid, txt in nuevas]


def decidir_regla(con, rid, acepta, autor="Manuel"):
    rid = rid if str(rid).upper().startswith("R") else f"R{rid}"
    r = con.execute("SELECT * FROM reglas WHERE id=?", (rid.upper(),)).fetchone()
    if not r:
        return f"No existe la regla {rid}."
    estado = "activa" if acepta else "rechazada"
    con.execute("UPDATE reglas SET estado=?, activa=? WHERE id=?", (estado, int(acepta), r["id"]))
    log(con, f"Regla {r['id']} {estado} por {autor}")
    con.commit()
    subir_regla(con.execute("SELECT * FROM reglas WHERE id=?", (r["id"],)).fetchone())
    return f"{'✅ Activada' if acepta else '🗑️ Rechazada'}: {r['id']} · {r['descripcion']}"


def nueva_manual(con, tipo, alcance, valor):
    rid = _nuevo_id(con)
    con.execute("INSERT INTO reglas(id,activa,tipo,alcance,valor,descripcion,origen,creada,evidencia,estado) "
                "VALUES(?,1,?,?,?,?,'manual',datetime('now','localtime'),0,'activa')",
                (rid, tipo, alcance, valor, f"{tipo}: {valor}"))
    con.commit()
    subir_regla(con.execute("SELECT * FROM reglas WHERE id=?", (rid,)).fetchone())
    return rid


def texto_reglas():
    filas = db().execute("SELECT * FROM reglas WHERE estado IN ('activa','propuesta') ORDER BY estado, id").fetchall()
    if not filas:
        return ("📐 Todavía no hay reglas. Las propongo yo cuando vea patrones en tus decisiones, o créalas:\n"
                "*!regla nueva preguntar falla:GAS ¿tienen fotos? ¿cocina abierta?*\n"
                "*!regla nueva instruccion todas saludar a la supervisora por su nombre*")
    out = ["📐 *Reglas del bot*"]
    for r in filas:
        icono = "✅" if r["estado"] == "activa" else "🟡"
        out.append(f"{icono} {r['id']} · {r['tipo']} · {r['alcance']}: {r['valor'][:90]}")
    out.append("\n🟡 = propuesta. *regla N si* / *regla N no* · editables en la hoja «Reglas del bot».")
    return "\n".join(out)


def sugerencia(rbd, crit, con=None):
    """Una línea para el borrador: qué hiciste tú antes en casos parecidos (el bot 'te conoce')."""
    con = con or db()
    desde = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    filas = con.execute("SELECT decision, detalle, rbd FROM decisiones WHERE fecha>=? AND (rbd=? OR crit=?) "
                        "AND decision NOT LIKE 'plan%'", (desde, rbd or -1, crit or "-")).fetchall()
    if len(filas) < 2:
        return ""
    cuenta = Counter(f["decision"] for f in filas)
    nombres = {"ok": "aprobaste", "no": "descartaste", "agendar": "agendaste", "pedir_info": "pediste info",
               "reescribir": "reescribiste", "reprogramar": "reprogramaste", "nota": "sumaste nota",
               "auto_gas": "salió solo"}
    partes = [f"{n} {nombres.get(d, d)}" for d, n in cuenta.most_common(3)]
    pedidos = [f["detalle"] for f in filas if f["decision"] == "pedir_info" and f["detalle"]]
    extra = f" (ej: «{pedidos[-1][:60]}»)" if pedidos else ""
    return "🧠 Antes, en casos parecidos (mismo colegio o falla): " + ", ".join(partes) + extra


def subir_bitacora(r):
    """Copia los ítems de una bitácora archivada a la hoja 'Bitácoras del bot' de tu planilla (en segundo plano)."""
    def tarea():
        try:
            filas = [[r["folio"], str(r["fecha"]), r["rbd"] or "", r["nombre"], r.get("tecnico") or "",
                      it.get("categoria", ""), it.get("item", ""), it.get("ubicacion", ""), it.get("accion", ""),
                      it.get("observacion", "")] for it in r.get("items", [])] or \
                    [[r["folio"], str(r["fecha"]), r["rbd"] or "", r["nombre"], r.get("tecnico") or "", "", "", "", "", ""]]
            _post({"accion": "bitacoras", "filas": filas})
        except Exception as e:
            print("[memoria] bitácora no subida a la planilla:", e)
    if conf().get("activa", True) and conf().get("apps_script_url"):
        threading.Thread(target=tarea, daemon=True).start()
