"""
servidor.py — el "jefe de obra". Recibe cada mensaje del grupo (se lo pasa
bot.mjs), le pregunta a la IA qué dice, aplica tus reglas, guarda en la agenda
y devuelve la respuesta para el grupo. Corre en http://127.0.0.1:8765.

Uso: python servidor.py
"""
import base64, json, os, re, sys, threading, traceback, urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.modules.setdefault("servidor", sys.modules[__name__])   # un solo módulo (y un solo candado) aunque corra como main

import bitacoras
import consultas
import ia
import memoria
import planificador
import privado
import reportes
from nucleo import (a_fecha, agenda, agendar, bonita, buscar, cfg, datos, db, en_texto, es_habil, es_prioridad,
                    hora_bloque, hoy, log, metas, nombre_tec, norm, sumar_habiles)

LOCK = threading.RLock()   # reentrante: una función con el candado puede llamar a otra que también lo usa
PUERTO = 8765


def _umbrales():
    u = cfg().get("identificacion", {})
    return int(u.get("seguro", 82)), int(u.get("duda", 60))

EMOJI = {"GAS": "🔥", "FRIO": "❄️", "AGUA": "💧", "ELEC": "⚡", "EQUIPO": "🍳", "OTRO": "🔧"}


# ================================================================ resolver establecimiento
def resolver(h, texto, excluir=()):
    """Devuelve (rbd, candidatos). rbd=None si hay que preguntar."""
    E = datos()["E"]
    SEGURO, DUDA = _umbrales()
    r = h.get("rbd")
    try:
        r = int(r) if r not in (None, "", "null") else None
    except (TypeError, ValueError):
        r = None
    if r in E and h.get("seguro", True):
        return r, []
    alias = [a for a in en_texto(texto) if a not in excluir]
    nombre = h.get("nombre_mencionado") or ""
    if len(alias) == 1 and (not r or r == alias[0]):
        return alias[0], []
    cands = buscar(nombre) if nombre else []
    if r in E and r not in [x for _, x in cands]:
        cands.insert(0, (SEGURO, r))
    if alias:
        for a in alias:
            if a not in [x for _, x in cands]:
                cands.insert(0, (SEGURO, a))
    if cands:
        top, segundo = cands[0][0], (cands[1][0] if len(cands) > 1 else 0)
        if top >= SEGURO and top - segundo >= 5:
            return cands[0][1], []
    return None, [x for p, x in cands if p >= DUDA and x not in excluir][:3]


# ================================================================ mensajes del grupo
def texto_respuesta(e, problema, crit, res):
    lin = [f"📌 *{e['nombre']}* · RBD {e['rbd']}",
           f"{EMOJI.get(crit, '🔧')} {problema}",
           f"⚠️ Criticidad *{res['pts']}/20* ({crit}) · {e.get('inst', '').upper()} · {e.get('rac', '?')} raciones",
           f"👷 {nombre_tec(res['tec'])} · *{bonita(res['fecha'])}* · {hora_bloque(res['fecha'], res['bloque'])}"]
    if res["modo"] == "fusion":
        lin.append("✅ Se resuelve en la visita que ya estaba agendada")
    elif res["modo"].startswith("adelantada"):
        lin.append(f"⏩ Se adelantó su visita del {bonita(res['antes'])}")
    if "extra" in res["modo"] or res["modo"] == "sobrecupo":
        lin.append("❗ Agenda llena: va como bloque extra (emergencia), Manuel lo confirma")
    if res.get("postergadas"):
        for m in res["postergadas"]:
            lin.append(f"↪️ {m['nombre']} pasa del {bonita(m['de'])} al {bonita(m['a'])}")
    elif res.get("movida"):
        m = res["movida"]
        lin.append(f"↪️ {m['nombre']} pasa del {bonita(m['de'])} al {bonita(m['a'])}")
    return "\n".join(lin)


def registrar_y_agendar(con, rbd, problema, crit, texto, autor, motor, hid=None):
    e = datos()["E"][rbd]
    prio = es_prioridad(texto)
    if hid is None:
        hid = con.execute("INSERT INTO hallazgos(recibido,autor,texto,rbd,problema,crit,prio,estado,motor) "
                          "VALUES(?,?,?,?,?,?,?,'agendado',?)",
                          (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, rbd, problema, crit, int(prio),
                           motor)).lastrowid
    else:
        con.execute("UPDATE hallazgos SET rbd=?, estado='agendado' WHERE id=?", (rbd, hid))
    res = agendar(con, rbd, crit, problema, prio, autor, hid)
    resp = texto_respuesta(e, problema, crit, res)
    con.execute("UPDATE hallazgos SET pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                (res["pts"], res["tarjeta"], resp, hid))
    log(con, f"Hallazgo {hid} {e['nombre']} {crit} {res['pts']}pts ({res['detalle_pts']}) -> "
             f"{res['tec']} {res['fecha']} b{res['bloque']} [{res['modo']}]")
    return resp


def procesar_mensaje(texto, autor):
    """Compatibilidad: modo directo (sin borrador). Devuelve lista de respuestas al grupo."""
    r = entrada("grupo", texto, autor, forzar_directo=True)
    return r["grupo"]


def texto_registro(e, problema, crit, pedir_foto):
    lin = [f"📝 *Registrado* · {e['nombre']} · RBD {e['rbd']}",
           f"{EMOJI.get(crit, '🔧')} {problema}",
           "Para programar la visita respondan *agendar* (o citen este mensaje y escriban agendar)."]
    if pedir_foto:
        lin.append("📸 Si pueden, manden una foto de la falla: ayuda a llevar los materiales correctos.")
    return "\n".join(lin)


def _generar_respuestas(con, texto, autor, motor, analisis, agendar_ahora=True, foto=None):
    """
    Por cada hallazgo: si agendar_ahora, lo agenda con las reglas (criticidad, licitación, raciones,
    aplazamientos); si no, lo deja 'registrado' esperando la palabra agendar (salvo gas, si así se configuró).
    Devuelve [(texto_respuesta, rbd, crit, hallazgo_id, tarjeta_id, tipo)].
    """
    c = cfg()
    E = datos()["E"]
    salida, vistos = [], set()
    bcfg = c.get("borrador", {})
    for h in analisis["hallazgos"][:int(bcfg.get("max_hallazgos_por_mensaje", 6))]:
        problema = (h.get("problema") or texto[:90]).strip()
        crit = h.get("tipo") if h.get("tipo") in ia.PAL or h.get("tipo") == "OTRO" else ia.tipo_por_palabras(texto)
        rbd, cands = resolver(h, texto, vistos)
        if rbd:
            if rbd in vistos:
                continue
            vistos.add(rbd)
            consultas.recordar_rbd(autor, rbd)
            dup = con.execute("SELECT respuesta FROM hallazgos WHERE rbd=? AND crit=? AND estado='agendado' "
                              "AND recibido>=?", (rbd, crit,
                              (datetime.now() - timedelta(days=int(bcfg.get("dias_duplicado", 7)))).strftime("%Y-%m-%d"))).fetchone()
            if dup:
                salida.append((f"🔁 Ya estaba agendado:\n{dup['respuesta']}", rbd, crit, None, None, "aviso"))
                continue
            e = E[rbd]
            ahora_si = agendar_ahora or (crit == "GAS" and c.get("gas_agenda_siempre", True))
            hid = con.execute("INSERT INTO hallazgos(recibido,autor,texto,rbd,problema,crit,prio,estado,motor,foto) "
                              "VALUES(?,?,?,?,?,?,?,?,?,?)",
                              (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, rbd, problema, crit,
                               int(es_prioridad(texto)), "agendado" if ahora_si else "registrado", motor,
                               foto)).lastrowid
            if not ahora_si:
                resp = texto_registro(e, problema, crit, c.get("pedir_foto", True) and not foto)
                con.execute("UPDATE hallazgos SET respuesta=? WHERE id=?", (resp, hid))
                log(con, f"Hallazgo {hid} {e['nombre']} {crit} registrado (espera 'agendar')")
                salida.append((resp, rbd, crit, hid, None, "requerimiento"))
                continue
            res = agendar(con, rbd, crit, problema, es_prioridad(texto), autor, hid)
            resp = texto_respuesta(e, problema, crit, res)
            if crit == "GAS" and not agendar_ahora:
                resp += "\n🔥 Gas: se agenda de inmediato aunque no digan agendar."
            con.execute("UPDATE hallazgos SET pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                        (res["pts"], res["tarjeta"], resp, hid))
            log(con, f"Hallazgo {hid} {e['nombre']} {crit} {res['pts']}pts -> {res['tec']} {res['fecha']} [{res['modo']}]")
            salida.append((resp, rbd, crit, hid, res["tarjeta"], "agendar"))
        else:
            con.execute("INSERT INTO hallazgos(recibido,autor,texto,problema,crit,prio,estado,candidatos,motor) "
                        "VALUES(?,?,?,?,?,?,'por_confirmar',?,?)",
                        (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, problema, crit,
                         int(es_prioridad(texto)), json.dumps(cands), motor))
            nom = h.get("nombre_mencionado") or "el establecimiento"
            if cands:
                ops = "\n".join(f"  • {E[r]['nombre']} ({E[r]['comuna']}) → *!es {r}*" for r in cands)
                salida.append((f"🤔 «{nom}»: ¿cuál es?\n{ops}\n{EMOJI.get(crit, '🔧')} {problema}", None, crit, None, None, "aviso"))
            else:
                salida.append((f"❓ No ubico «{nom}» en los 93 establecimientos.\n{EMOJI.get(crit, '🔧')} "
                               f"{problema}\nRespondan *!es RBD* para agendarlo.", None, crit, None, None, "aviso"))
    return salida


def _registrados_para_agendar(con, texto, citado, autor):
    """'agendar' sin falla nueva: ¿qué requerimiento registrado se quiere agendar?"""
    horas = int(cfg().get("agendar_ventana_horas", 72))
    desde = (datetime.now() - timedelta(hours=horas)).strftime("%Y-%m-%d %H:%M")
    rbds = en_texto(f"{texto} {citado}")
    if rbds:
        marcas = ",".join("?" * len(rbds))
        filas = con.execute(f"SELECT * FROM hallazgos WHERE estado='registrado' AND rbd IN ({marcas}) "
                            f"ORDER BY id DESC", rbds).fetchall()
        vistos, out = set(), []
        for f in filas:
            if f["rbd"] not in vistos:
                vistos.add(f["rbd"])
                out.append(f)
        return out
    f = con.execute("SELECT * FROM hallazgos WHERE estado='registrado' AND autor=? AND recibido>=? ORDER BY id DESC "
                    "LIMIT 1", (autor, desde)).fetchone()
    return [f] if f else []


def _salida(con, origen, autor, texto, items, modo_borrador, archivos=None):
    """Convierte respuestas en borradores para el admin o en mensajes directos al grupo."""
    out = {"grupo": [], "admin": [], "borradores": [], "archivos_admin": [], "archivos_grupo": []}
    archivos = [a for a in (archivos or []) if a and os.path.exists(a)]
    for resp, rbd, crit, hid, tid, tipo in items:
        if tipo in ("agendar", "requerimiento") and rbd:
            qs = memoria.preguntas_para(crit, rbd, con)         # reglas "preguntar" que aprobaste
            if qs:
                resp += "\n❔ Para avanzar: " + " ".join(q if q.strip().endswith("?") else q + "." for q in qs)
        if origen == "admin" and tipo == "pregunta":
            out["admin"].append(resp)
            out["archivos_admin"] += archivos
        elif modo_borrador:
            bid = con.execute("INSERT INTO borradores(origen,autor,texto_original,respuesta,rbd,crit,"
                              "hallazgo_id,tarjeta_id,estado,tipo,adjuntos) VALUES(?,?,?,?,?,?,?,?,'pendiente',?,?)",
                              (origen, autor, texto, resp, rbd, crit, hid, tid, tipo,
                               json.dumps(archivos if tipo == "pregunta" else []))).lastrowid
            out["borradores"].append(bid)
            out["admin"].append(_texto_borrador(con, bid))
        else:
            out["grupo"].append(resp)
            if tipo == "pregunta":
                out["archivos_grupo"] += archivos
    return out


def _mismo_nombre(a, b):
    """'Carla Espinoza' (planilla) y 'Carla 🌸' (WhatsApp) son la misma persona: compara el primer nombre."""
    a, b = norm(a).split(), norm(b).split()
    return bool(a and b and a[0] == b[0])


def _pedido_abierto(con, autor):
    minutos = int(cfg().get("pedir_info", {}).get("esperar_respuesta_min", 180))
    desde = (datetime.now() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    for p in con.execute("SELECT * FROM pedidos_info WHERE estado='esperando' AND creado>=? ORDER BY id DESC",
                         (desde,)).fetchall():
        if _mismo_nombre(p["autor"], autor):
            return p
    return None


def _respuesta_a_pedido(con, texto, autor, citado):
    """¿Este mensaje del grupo responde a una pregunta que le hizo el bot (pedir info)? -> fila de pedidos_info."""
    m = re.search(r"caso #(\d+)", citado or "")
    if m:
        p = con.execute("SELECT * FROM pedidos_info WHERE borrador_id=? AND estado='esperando' ORDER BY id DESC",
                        (int(m.group(1)),)).fetchone()
        if p:
            return p
    p = _pedido_abierto(con, autor)
    if not p:
        return None
    otros = [r for r in en_texto(texto) if r != p["rbd"]]
    if otros or ia.pide_agendar(texto):          # habla de otro colegio o pide agendar: es un mensaje nuevo
        return None
    return p


def _pegar_respuesta(con, p, texto, autor):
    con.execute("UPDATE pedidos_info SET estado='respondido', respuesta=?, respondido=datetime('now','localtime') "
                "WHERE id=?", (texto[:1000], p["id"]))
    b = con.execute("SELECT * FROM borradores WHERE id=?", (p["borrador_id"],)).fetchone()
    con.execute("UPDATE borradores SET nota_interna=TRIM(nota_interna || ' [💬 ' || ? || ': ' || ? || ']'), "
                "estado=CASE WHEN estado IN ('enviado','descartado') THEN estado ELSE 'pendiente' END WHERE id=?",
                (autor.split()[0] if autor else "?", texto[:400], p["borrador_id"]))
    log(con, f"Caso #{p['borrador_id']}: {autor} respondió la consulta")
    con.commit()
    out = {"grupo": [], "admin": [f"💬 *{autor} respondió* (caso #{p['borrador_id']}):\n«{texto[:600]}»"],
           "borradores": [], "intencion": "respuesta_info"}
    if b and b["estado"] == "pendiente":
        out["admin"].append(_texto_borrador(con, b["id"]) +
                            "\n\nSi quieres contestarle con lo nuevo: *caso " + str(b["id"]) + " responde: …*")
    return out


def entrada(origen, texto, autor, forzar_directo=False, citado="", foto=None, foto_resumen="", ahora=None):
    """
    Punto de entrada de TODO mensaje. Estructura fija:
      1. Clasificar en 5 intenciones: agendar · requerimiento · pregunta · observacion · charla
      2. agendar        -> agenda con criticidad (licitación, raciones, metas) y aplaza lo de menor prioridad
         requerimiento  -> queda registrado y se sugiere "agendar" (gas se agenda igual, si está configurado)
         pregunta       -> se responde con historial, bitácoras y agenda
         observacion    -> se anota en el historial del establecimiento, sin responder
         charla         -> nada
      3. Lo que va al grupo pasa por ti (modo borrador) salvo lo que tengas liberado.
    """
    c = cfg()
    vacio = {"grupo": [], "admin": [], "borradores": [], "intencion": "charla", "archivos_admin": [],
             "archivos_grupo": []}
    if origen == "grupo" and any(i.lower() in autor.lower() for i in c.get("ignorar", []) if i):
        return vacio
    if origen == "grupo":
        with LOCK:
            con = db()
            p = _respuesta_a_pedido(con, texto, autor, citado)
            if p:
                r = _pegar_respuesta(con, p, texto, autor)
                con.execute("INSERT INTO mensajes(origen,autor,texto,intencion,rbd,resultado,motor) VALUES(?,?,?,?,?,?,?)",
                            (origen, autor, texto[:1000], "respuesta_info", p["rbd"], f"caso #{p['borrador_id']}", "regla"))
                con.commit()
                return {**vacio, **r}
    contexto = ""
    if citado:
        contexto += f"El mensaje responde a: «{citado[:400]}»\n"
    if foto_resumen:
        contexto += f"Adjunta una foto que muestra: {foto_resumen}\n"
    analisis, motor = ia.analizar(texto, autor, contexto)
    it = analisis.get("intencion", "charla")
    modo_borrador = c.get("modo_borrador", True) and not forzar_directo
    rbd_log = (analisis.get("hallazgos") or [{}])[0].get("rbd") if analisis.get("hallazgos") else \
        (analisis.get("pregunta") or analisis.get("observacion") or {}).get("rbd")
    out = dict(vacio)
    with LOCK:
        con = db()
        try:
            rbd_log = int(rbd_log) if rbd_log not in (None, "", "null") else None
        except (TypeError, ValueError):
            rbd_log = None
        if it == "pregunta":
            r = consultas.responder(texto + (f" {citado}" if citado else ""), autor,
                                    analisis.get("pregunta") or {}, ahora)
            resp, archivos = (r["texto"], r.get("archivos", [])) if isinstance(r, dict) else (r, [])
            rbd_log = rbd_log or (r.get("rbd") if isinstance(r, dict) else None)
            libre = c.get("preguntas_sin_aprobacion", False)
            out = _salida(con, origen, autor, texto, [(resp, rbd_log, None, None, None, "pregunta")],
                          modo_borrador and not libre, archivos)
            resultado = "respondida"
        elif it == "observacion":
            ob = analisis.get("observacion") or {}
            r_ob = rbd_log or (en_texto(texto) or [None])[0]
            con.execute("INSERT INTO observaciones(autor,rbd,texto,resumen) VALUES(?,?,?,?)",
                        (autor, r_ob, texto, ob.get("resumen") or texto[:120]))
            if origen == "admin":
                out["admin"].append("🗒️ Anotado como observación (no se agenda nada).")
            resultado = "anotada"
        elif it in ("agendar", "requerimiento"):
            agendar_ya = it == "agendar" or not c.get("agendar_requiere_palabra", True)
            sin_falla_nueva = ia.tipo_por_palabras(texto) == "OTRO" and not en_texto(texto)
            if it == "agendar" and sin_falla_nueva and _registrados_para_agendar(con, texto, citado, autor):
                analisis["hallazgos"] = []          # 'agendar' a secas o citando: va lo ya registrado
            if analisis.get("hallazgos"):
                items = _generar_respuestas(con, texto, autor, motor, analisis, agendar_ya, foto)
            else:
                filas = _registrados_para_agendar(con, texto, citado, autor) if it == "agendar" else []
                items = []
                for f in filas:
                    resp = registrar_y_agendar(con, f["rbd"], f["problema"], f["crit"], f["texto"], f["autor"],
                                               f["motor"], hid=f["id"])
                    con.execute("UPDATE borradores SET estado='reemplazado' WHERE hallazgo_id=? AND "
                                "estado='pendiente' AND tipo='requerimiento'", (f["id"],))
                    tid = con.execute("SELECT tarjeta_id FROM hallazgos WHERE id=?", (f["id"],)).fetchone()[0]
                    items.append((resp, f["rbd"], f["crit"], f["id"], tid, "agendar"))
                if not filas and it == "agendar":
                    items = [("🗓️ ¿Qué agendo? Citen el mensaje de la falla y escriban *agendar*, o escriban "
                              "*agendar* con el establecimiento y el problema.", None, None, None, None, "aviso")]
            out = _salida(con, origen, autor, texto, items, modo_borrador)
            resultado = f"{len(items)} caso(s)"
        else:
            if origen == "admin":
                out["admin"].append("🤖 Te leo. Escríbeme un caso, una pregunta o *!ayuda* para ver comandos.")
            resultado = "nada"
        out["intencion"] = it
        con.execute("INSERT INTO mensajes(origen,autor,texto,intencion,rbd,resultado,motor) VALUES(?,?,?,?,?,?,?)",
                    (origen, autor, texto[:1000], it, rbd_log, resultado, motor))
        con.commit()
    if it in ("agendar", "requerimiento"):
        threading.Thread(target=subir_github, daemon=True).start()
    return out


def foto(ruta, autor, origen, caption="", citado=""):
    """
    Foto recibida. Se analiza con Gemini (qué se ve, falla, tipo, gravedad, materiales).
    - Con texto: se procesa como mensaje normal, con lo que muestra la foto como contexto.
    - Sola: se pega al último caso de esa persona (si es reciente) y te avisa; si no hay caso, pregunta de dónde es.
    """
    c = cfg()
    if origen == "grupo" and any(i.lower() in autor.lower() for i in c.get("ignorar", []) if i):
        return {"grupo": [], "admin": [], "borradores": []}
    an = ia.analizar_foto(ruta, autor, caption) or {}
    resumen = "; ".join(x for x in [an.get("que_se_ve"), (f"falla: {an['falla']}" if an.get("falla") else ""),
                                     (f"gravedad {an['gravedad']}" if an.get("gravedad") else ""),
                                     (f"llevar: {an['materiales']}" if an.get("materiales") else "")] if x)
    with LOCK:
        con = db()
        fid = con.execute("INSERT INTO fotos(autor,ruta,caption,analisis) VALUES(?,?,?,?)",
                          (autor, ruta, caption, json.dumps(an, ensure_ascii=False))).lastrowid
        con.commit()
    if caption.strip():
        r = entrada(origen, caption, autor, citado=citado, foto=ruta, foto_resumen=resumen)
        with LOCK:
            con = db()
            for bid in r.get("borradores", []):
                con.execute("UPDATE borradores SET nota_interna=TRIM(nota_interna || ' [📸 ' || ? || ']') WHERE id=?",
                            (resumen or "foto sin analizar", bid))
            con.commit()
            r["admin"] = [_texto_borrador(con, bid) for bid in r.get("borradores", [])] + \
                [m for m in r.get("admin", []) if not m.startswith("🆕")]
        return r
    minutos = int(c.get("fotos", {}).get("vincular_min", 60))
    desde = (datetime.now() - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M")
    with LOCK:
        con = db()
        h = con.execute("SELECT * FROM hallazgos WHERE autor=? AND recibido>=? AND estado IN ('registrado','agendado') "
                        "ORDER BY id DESC LIMIT 1", (autor, desde)).fetchone()
        out = {"grupo": [], "admin": [], "borradores": []}
        p = _pedido_abierto(con, autor) if origen == "grupo" else None
        if p:
            con.execute("UPDATE fotos SET rbd=? WHERE id=?", (p["rbd"], fid))
            r = _pegar_respuesta(con, p, f"[📸 foto] {resumen or 'sin analizar'}", autor)
            r["archivos_admin"] = [ruta]
            return r
        if h:
            con.execute("UPDATE hallazgos SET foto=? WHERE id=?", (ruta, h["id"]))
            con.execute("UPDATE fotos SET rbd=?, hallazgo_id=? WHERE id=?", (h["rbd"], h["id"], fid))
            b = con.execute("SELECT id FROM borradores WHERE hallazgo_id=? AND estado='pendiente'", (h["id"],)).fetchone()
            nom = datos()["E"].get(h["rbd"], {}).get("nombre", "?")
            if b:
                con.execute("UPDATE borradores SET nota_interna=TRIM(nota_interna || ' [📸 ' || ? || ']') WHERE id=?",
                            (resumen or "foto sin analizar", b["id"]))
                out["admin"].append(_texto_borrador(con, b["id"]))
            else:
                out["admin"].append(f"📸 {autor} mandó foto de *{nom}* ({h['problema']}).\n"
                                    f"{('🔎 ' + resumen) if resumen else '(sin IA para analizarla)'}")
        elif an.get("falla"):
            out = _salida(con, origen, autor, "[foto]", [(f"📸 Veo: {resumen}.\n¿De qué establecimiento es? "
                                                        f"Respondan con el nombre o RBD.", None, an.get("tipo"),
                                                        None, None, "aviso")],
                          c.get("modo_borrador", True))
        else:
            out["admin"].append(f"📸 Foto de {autor} sin texto ni caso reciente. "
                                f"{('🔎 ' + resumen) if resumen else ''}".strip())
        con.commit()
    return out


# ================================================================ borradores (aprobación)
def _texto_borrador(con, bid):
    b = con.execute("SELECT * FROM borradores WHERE id=?", (bid,)).fetchone()
    orig = "supervisora" if b["origen"] == "grupo" else "ti"
    adj = json.loads(b["adjuntos"] or "[]")
    etiqueta = {"pregunta": "❓ pregunta", "requerimiento": "📝 requerimiento", "agendar": "🗓️ agendar",
                "aviso": "ℹ️ aviso"}.get(b["tipo"] or "agendar", "")
    e = datos()["E"].get(b["rbd"], {}) if b["rbd"] else {}
    lin = [f"🆕 *Caso #{bid}* · {etiqueta} · de {orig} ({b['autor']})",
           f"💬 «{b['texto_original'][:160]}»"]
    if e:
        lin.append(f"👩 Sup. {e.get('sup', '?')} · {e.get('inst', '')} · {e.get('rac', '?')} raciones")
    sug = memoria.sugerencia(b["rbd"], b["crit"], con)
    if sug:
        lin.append(sug)
    espera = con.execute("SELECT pregunta FROM pedidos_info WHERE borrador_id=? AND estado='esperando'", (bid,)).fetchone()
    if espera:
        lin.append(f"⏳ Esperando respuesta a: «{espera['pregunta'][:80]}»")
    lin += ["", "📝 *Borrador para el grupo:*", b["respuesta"]]
    if b["nota_interna"]:
        lin += ["", f"➕ Agregado: {b['nota_interna']}"]
    if adj:
        lin.append(f"📎 Adjuntos: {', '.join(os.path.basename(a) for a in adj)}")
    extra = " · *agendar* para programarlo ya" if (b["tipo"] or "") == "requerimiento" else ""
    lin += ["", f"*ok* envía · *no* descarta{extra} · *+texto* suma · *pregúntale …* · *responde: …* · "
                f"*camilo jueves b2* · o un PDF/foto citando"]
    return "\n".join(lin)


def _borrador_pendiente(con, bid=None):
    if bid:
        return con.execute("SELECT * FROM borradores WHERE id=? AND estado='pendiente'", (bid,)).fetchone()
    return con.execute("SELECT * FROM borradores WHERE estado='pendiente' ORDER BY id DESC LIMIT 1").fetchone()


def _nota_publica(nota):
    """Lo que tú sumaste va al grupo; el análisis de fotos [📸 ...] queda solo para ti."""
    import re as _re
    return _re.sub(r"\s*\[(📸|💬)[^\]]*\]", "", nota or "").strip(" |")


def salida_aprobar(r):
    """Pasa la salida de aprobar() al formato común que entiende bot.mjs."""
    out = {"admin": list(r.get("admin", [])), "envios_grupo": [], "pedidos": [], "mensajes_tecnicos": [],
           "borradores": [], "grupo": []}
    if r.get("enviar_borrador"):
        out["envios_grupo"].append({"borrador_id": r["enviar_borrador"], "textos": r.get("grupo", [])})
    elif r.get("grupo"):
        out["grupo"] += r["grupo"]
    return out


def aprobar(decision, autor, bid=None, memo=None):
    """
    decision: 'ok', 'no', 'agendar' o texto para sumar. Devuelve {'grupo':[], 'admin':[], 'enviar_borrador':id}.
    memo = (decision, detalle, propuesta_original) para registrar en la memoria algo distinto de 'ok' (ej. reescribir).
    """
    out = {"grupo": [], "admin": [], "enviar_borrador": None}
    with LOCK:
        con = db()
        b = _borrador_pendiente(con, bid)
        if not b:
            out["admin"].append("No hay ningún caso pendiente de aprobar.")
            return out
        d = decision.strip()
        dl = d.lower()
        c = cfg()
        si = [x.lower() for x in c.get("palabras_ok", ["ok"])]
        no = [x.lower() for x in c.get("palabras_no", ["no"])]
        if ia.pide_agendar(d) and b["hallazgo_id"] and (b["tipo"] or "") == "requerimiento":
            h = con.execute("SELECT * FROM hallazgos WHERE id=?", (b["hallazgo_id"],)).fetchone()
            if h and h["estado"] == "registrado":
                resp = registrar_y_agendar(con, h["rbd"], h["problema"], h["crit"], h["texto"], h["autor"],
                                           h["motor"], hid=h["id"])
                tid = con.execute("SELECT tarjeta_id FROM hallazgos WHERE id=?", (h["id"],)).fetchone()[0]
                con.execute("UPDATE borradores SET respuesta=?, tarjeta_id=?, tipo='agendar' WHERE id=?",
                            (resp, tid, b["id"]))
                log(con, f"Borrador #{b['id']} pasado a agenda por {autor}")
                t = con.execute("SELECT * FROM tarjetas WHERE id=?", (tid,)).fetchone()
                memoria.registrar_de_borrador(con, b, "agendar", tec=t["tec"] if t else "",
                                              fecha_visita=t["fecha"] if t else "", bloque=t["bloque"] if t else "")
                con.commit()
                out["admin"].append("🗓️ Agendado. Así queda el borrador:\n\n" + _texto_borrador(con, b["id"]))
                return out
        if dl in si:
            resp = b["respuesta"]
            if _nota_publica(b["nota_interna"]):
                resp += f"\nℹ️ {_nota_publica(b['nota_interna'])}"
            con.execute("UPDATE borradores SET estado='enviado' WHERE id=?", (b["id"],))
            log(con, f"Borrador #{b['id']} aprobado por {autor} -> grupo")
            t = con.execute("SELECT * FROM tarjetas WHERE id=?", (b["tarjeta_id"],)).fetchone() if b["tarjeta_id"] else None
            if memo:
                bb = dict(b)
                bb["respuesta"] = memo[2] or b["respuesta"]
                memoria.registrar_de_borrador(con, bb, memo[0], detalle=memo[1], texto_final=resp,
                                              tec=t["tec"] if t else "", fecha_visita=t["fecha"] if t else "",
                                              bloque=t["bloque"] if t else "")
            else:
                memoria.registrar_de_borrador(con, b, "ok", detalle=_nota_publica(b["nota_interna"]), texto_final=resp,
                                              tec=t["tec"] if t else "", fecha_visita=t["fecha"] if t else "",
                                              bloque=t["bloque"] if t else "")
            con.commit()
            out["grupo"].append(resp)
            out["enviar_borrador"] = b["id"]       # para que bot.mjs adjunte PDFs y cite el original
            out["admin"].append(f"✅ Enviado al grupo (caso #{b['id']}).")
        elif dl in no:
            if b["tarjeta_id"]:
                con.execute("UPDATE tarjetas SET estado='anulada', modificada=1 WHERE id=?", (b["tarjeta_id"],))
            if b["hallazgo_id"]:
                con.execute("UPDATE hallazgos SET estado='descartado' WHERE id=?", (b["hallazgo_id"],))
            con.execute("UPDATE borradores SET estado='descartado' WHERE id=?", (b["id"],))
            con.execute("UPDATE pedidos_info SET estado='cerrado' WHERE borrador_id=? AND estado='esperando'", (b["id"],))
            memoria.registrar_de_borrador(con, b, "no")
            log(con, f"Borrador #{b['id']} descartado por {autor}")
            con.commit()
            out["admin"].append(f"🗑️ Caso #{b['id']} descartado, liberé el bloque.")
        else:
            nota = (b["nota_interna"] + " | " if b["nota_interna"] else "") + d
            con.execute("UPDATE borradores SET nota_interna=? WHERE id=?", (nota, b["id"]))
            memoria.registrar_de_borrador(con, b, "nota", detalle=d)
            con.commit()
            out["admin"].append(_texto_borrador(con, b["id"]))
    return out


def adjuntar_a_borrador(ruta, autor, bid=None):
    with LOCK:
        con = db()
        b = _borrador_pendiente(con, bid)
        if not b:
            return {"admin": ["No hay caso pendiente al cual adjuntar el archivo."]}
        adj = json.loads(b["adjuntos"] or "[]")
        adj.append(ruta)
        con.execute("UPDATE borradores SET adjuntos=? WHERE id=?", (json.dumps(adj), b["id"]))
        con.commit()
        return {"admin": [f"📎 Adjunté {os.path.basename(ruta)} al caso #{b['id']}.", _texto_borrador(con, b["id"])]}


def adjuntos_de(bid):
    con = db()
    b = con.execute("SELECT adjuntos FROM borradores WHERE id=?", (bid,)).fetchone()
    return json.loads(b["adjuntos"] or "[]") if b else []



# ================================================================ comandos
AYUDA = """🤖 *Comandos del bot*

*📅 Agenda*
!hoy · !mañana · !semana — lo programado
!agenda camilo · !agenda rodrigo — por técnico
!ficha RBD — puntaje, cobertura y próxima visita
!metas — avance JUNAEB y jardines
!pendientes — por confirmar y sin visita
!hecho RBD — marcar visita realizada
!es RBD — confirmar establecimiento dudoso

*📚 Bitácoras*
📎 PDF con texto: Nombre, dd/mm/aaaa
!consulta <texto> — ej: !consulta gas silvia salas
!historial RBD — bitácoras de un establecimiento
!buscar <palabra> — en todas las observaciones

*💬 Cómo escribir en el grupo*
• Falla → queda registrada
• Falla + *agendar* (o citar y escribir agendar) → se programa
• Pregunta → el bot responde con historial y bitácoras
• 📸 Foto → se analiza y se pega al caso

*✅ Casos (tu privado, como hablas)*
Escríbeme un caso → te mando el borrador
ok · no · agendar · +texto (al último, o citando)
caso 6 no · ok 4 y 5 · ok todos
caso 6: pregúntale si tiene fotos → le pregunta en el grupo
caso 6 responde: mañana va Camilo → envía tu texto
el 3 pásalo a Camilo el jueves b2 → reprograma
!casos — pendientes · !caso N — ver uno

*🗓️ Plan del día*
!plan · !plan mañana → hoy/mañana por técnico + casos sin hora
1 hoy camilo b3, 2 mañana, 3 no → vista previa
ok plan → se aplica y avisa a grupo y técnicos

*👩 Supervisoras*
!supervisora carla → sus colegios, casos y visitas
!supervisoras → resumen de las tres

*🧠 Memoria*
!reglas — lo que aprendí · regla 5 si / regla 5 no
!regla nueva preguntar falla:GAS ¿tienen fotos?
!memoria — estado y sincronizar con tu planilla

*⚙️ Encargado*
!config — ver ajustes · !config clave valor — cambiar
!perfil prueba|produccion — cambiar instancia
!modo borrador|directo — con o sin tu ok
!diagnostico — revisa WhatsApp, IA, base y disco
!simular <texto> — prueba como si fuera supervisora
!mover RBD dd-mm [bloque] · !anular RBD
!reporte — Excel completo"""


def texto_agenda(con, desde, hasta, tec=None, titulo="Agenda"):
    E = datos()["E"]
    filas = agenda(con, desde, hasta, tec)
    if not filas:
        return f"📅 *{titulo}*: sin visitas programadas."
    out, dia = [f"📅 *{titulo}*"], None
    for t in filas:
        if t["fecha"] != dia:
            dia = t["fecha"]
            out.append(f"\n*{bonita(dia).upper()}*")
        e = E.get(t["rbd"], {})
        icono = "🚨" if "CORRECTIVO" in t["clase"] else ("🛠️" if "PREV" in t["clase"] else "📋")
        extra = f" {EMOJI.get(t['crit'], '')}" if "CORRECTIVO" in t["clase"] and t["crit"] else ""
        b = f"B{t['bloque']}" if t["bloque"] <= 3 else "EXTRA"
        out.append(f"{icono} {nombre_tec(t['tec'])} {b}: {e.get('nombre', t['rbd'])} ({t['pts']}){extra}")
    return "\n".join(out)


def procesar_comando(texto, autor, es_admin, privado=False, wa=None):
    D = datos()
    E = D["E"]
    partes = texto.strip().split()
    cmd = partes[0].lower().replace("ñ", "n")
    args = partes[1:]
    tecs = {t.lower(): t for t in D["META"]["tecnicos"]}
    # estos dos van FUERA del candado: llaman a internet o a entrada(), que maneja su propio candado
    if cmd in ("!diagnostico", "!diag", "!simular", "!memoria"):
        if not es_admin:
            return {"texto": "Ese comando es solo para el encargado."}
        if cmd == "!memoria":
            r = memoria.sincronizar()
            return {"texto": f"🧠 *Memoria*\n{memoria.estado_texto()}\n\nRecién: {r}"}
        if cmd == "!simular":
            if not args:
                return {"texto": "Uso: !simular <mensaje como si fuera una supervisora>"}
            r = entrada("grupo", texto.split(None, 1)[1], "Simulación")
            if not r["admin"] and not r["grupo"]:
                return {"texto": "🧪 La simulación no detectó establecimiento ni falla."}
            return {"texto": f"🧪 Simulación lista ({len(r['borradores'])} caso/s). Revisa el borrador.",
                    "admin": r["admin"], "borradores": r["borradores"]}
        return {"texto": diagnostico(wa or {})}
    with LOCK:
        con = db()
        try:
            if cmd in ("!ayuda", "!help", "!comandos"):
                return {"texto": AYUDA}
            if cmd == "!hoy":
                return {"texto": texto_agenda(con, hoy(), hoy(), None, f"Hoy {bonita(hoy())}")}
            if cmd in ("!manana", "!mañana"):
                d = sumar_habiles(hoy(), 1)
                return {"texto": texto_agenda(con, d, d, None, bonita(d))}
            if cmd == "!semana":
                return {"texto": texto_agenda(con, hoy(), sumar_habiles(hoy(), 4), None, "Próximos 5 días hábiles")}
            if cmd == "!agenda":
                tec = next((tecs[a.lower()] for a in args if a.lower() in tecs), None)
                if tec:
                    return {"texto": texto_agenda(con, hoy(), sumar_habiles(hoy(), 4), tec,
                                                  f"Agenda {nombre_tec(tec)}")}
                return {"texto": texto_agenda(con, hoy(), sumar_habiles(hoy(), 1), None, "Hoy y mañana")}
            if cmd == "!metas":
                m = metas(con)
                j, jt, jf = m["junaeb"]
                g, gt, gf = m["jardines"]
                return {"texto": f"🎯 *Metas*\nJUNAEB en Datácora: *{j}/{jt}* (al {bonita(jf)})\n"
                                 f"Jardines con preventiva: *{g}/{gt}* (al {bonita(gf)})"}
            if cmd == "!pendientes":
                pc = con.execute("SELECT * FROM hallazgos WHERE estado='por_confirmar' ORDER BY id DESC LIMIT 10"
                                 ).fetchall()
                sin = con.execute("SELECT DISTINCT rbd FROM tarjetas WHERE estado='programada'").fetchall()
                agendados = {r[0] for r in sin}
                falta = [e for e in D["ESTAB"] if e["rbd"] not in agendados and
                         (e["cobertura"] == "SIN VISITA" or (e["inst"] != "Junaeb" and not e.get("prevOK")))]
                txt = []
                if pc:
                    txt.append("🤔 *Por confirmar*\n" + "\n".join(f"• {h['problema']} ({h['autor']})" for h in pc))
                if falta:
                    txt.append("⏳ *Sin visita en agenda y les falta cobertura*\n" + "\n".join(
                        f"• {e['nombre']} ({e['inst']}, {e['pts']} pts)" for e in falta[:20]))
                return {"texto": "\n\n".join(txt) or "✅ Nada pendiente."}
            if cmd == "!ficha" and args:
                e = E.get(int(args[0])) if args[0].isdigit() else None
                if not e:
                    return {"texto": "RBD no encontrado."}
                prox = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' ORDER BY fecha LIMIT 2",
                                   (e["rbd"],)).fetchall()
                pv = "\n".join(f"📅 {bonita(t['fecha'])} {nombre_tec(t['tec'])} B{t['bloque']} · {t['clase']}"
                               for t in prox) or "📅 Sin visita programada"
                return {"texto": f"🏫 *{e['nombre']}* · {e['comuna']} · {e['inst']}\n👩 {e['sup']}\n"
                                 f"⚠️ {e['pts']}/20 — {e['why']}\n🍽️ {e['rac']} raciones · {e['gas']}\n"
                                 f"📊 {e['cobertura']} · última visita {e['ultima'] or '—'}\n{pv}"}
            if cmd == "!plan":
                if not es_admin:
                    return {"texto": "Ese comando es solo para el encargado."}
                desde = sumar_habiles(hoy(), 1) if args and norm(args[0]).startswith("man") else None
                return {"texto": planificador.vista(con, desde)}
            if cmd in ("!supervisora", "!sup") and args:
                return {"texto": texto_supervisora(con, " ".join(args))}
            if cmd == "!supervisoras":
                sups = sorted({e["sup"] for e in D["ESTAB"] if e.get("sup")})
                return {"texto": "\n\n".join(texto_supervisora(con, s_, corto=True) for s_ in sups)}
            if cmd == "!reglas":
                return {"texto": memoria.texto_reglas()}
            if cmd == "!regla" and es_admin:
                if len(args) >= 4 and args[0].lower() == "nueva" and args[1].lower() in ("preguntar", "tecnico", "instruccion"):
                    valor = texto.strip().split(None, 4)[4]
                    rid = memoria.nueva_manual(con, args[1].lower(), args[2], valor)
                    return {"texto": f"✅ Regla {rid} activa: {args[1]} · {args[2]} · {valor}"}
                if len(args) >= 2 and args[0].lstrip("rR").isdigit():
                    acepta = norm(args[1]) in ("si", "ok", "dale", "activa", "activar")
                    return {"texto": memoria.decidir_regla(con, args[0], acepta, autor)}
                return {"texto": "Uso: !regla nueva preguntar|tecnico|instruccion todas|falla:GAS|rbd:8678 <valor>\n"
                                 "o: regla 5 si / regla 5 no"}
            if cmd == "!reporte":
                return {"texto": "📊 Reporte actualizado", "archivo": reportes.generar()}
            # ---- bitácoras
            if cmd in ("!consulta", "!consultar") and args:
                return {"texto": bitacoras.consultar(" ".join(args))}
            if cmd == "!historial" and args and args[0].isdigit():
                return {"texto": bitacoras.historial(int(args[0]))}
            if cmd == "!buscar" and args:
                return {"texto": _buscar_observaciones(con, " ".join(args))}
            # ---- casos / borradores
            if cmd == "!casos":
                ps = con.execute("SELECT id,autor,rbd,texto_original FROM borradores WHERE estado='pendiente' "
                                 "ORDER BY id").fetchall()
                if not ps:
                    return {"texto": "✅ No hay casos pendientes."}
                return {"texto": "📋 *Casos pendientes*\n" + "\n".join(
                    f"#{b['id']} · {E.get(b['rbd'], {}).get('nombre', '¿?')} · «{b['texto_original'][:50]}»" for b in ps)}
            if cmd == "!caso" and args and args[0].isdigit():
                return {"texto": _texto_borrador(con, int(args[0]))}
            if cmd == "!hecho" and args and args[0].isdigit():
                t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' ORDER BY fecha LIMIT 1",
                                (int(args[0]),)).fetchone()
                if not t:
                    return {"texto": f"No hay visita programada para RBD {args[0]}."}
                con.execute("UPDATE tarjetas SET estado='realizada', fecha=?, modificada=1 WHERE id=?",
                            (hoy().isoformat(), t["id"]))
                con.execute("UPDATE hallazgos SET estado='resuelto' WHERE rbd=? AND estado='agendado'", (t["rbd"],))
                log(con, f"Realizada {t['id']} RBD {t['rbd']} por {autor}")
                return {"texto": f"✅ {E[t['rbd']]['nombre']} marcada como realizada. No olviden subir la bitácora "
                                 f"a Datácora."}
            if cmd == "!es" and args and args[0].isdigit():
                rbd = int(args[0])
                if rbd not in E:
                    return {"texto": f"RBD {rbd} no está entre los 93 establecimientos."}
                h = con.execute("SELECT * FROM hallazgos WHERE estado='por_confirmar' ORDER BY id DESC LIMIT 1"
                                ).fetchone()
                if not h:
                    return {"texto": "No hay mensajes pendientes de confirmar."}
                resp = registrar_y_agendar(con, rbd, h["problema"], h["crit"], h["texto"], h["autor"], h["motor"],
                                           hid=h["id"])
                threading.Thread(target=subir_github, daemon=True).start()
                return {"texto": resp}
            # ---- encargado: configuración, instancias, diagnóstico, simulación
            if cmd in ("!config", "!perfil", "!diagnostico", "!diag", "!simular") and not es_admin:
                return {"texto": "Ese comando es solo para el encargado."}
            if cmd == "!config":
                if not privado:
                    return {"texto": "🔒 !config solo funciona en tu chat privado con el bot."}
                import ajustes
                if not args:
                    return {"texto": ajustes.resumen()}
                if args[0].lower() == "ver" and len(args) > 1:
                    try:
                        v = ajustes.obtener(args[1])
                        return {"texto": f"🔎 {args[1]} = {json.dumps(ajustes.tapar(args[1], v), ensure_ascii=False)}"}
                    except KeyError:
                        return {"texto": f"No existe la clave «{args[1]}»."}
                if args[0].lower() in ("reset", "restablecer") and len(args) > 1:
                    try:
                        v = ajustes.restablecer(args[1])
                        log(con, f"Config {args[1]} restablecida por {autor}")
                        return {"texto": f"↩️ {args[1]} vuelve a {json.dumps(v, ensure_ascii=False)}"}
                    except KeyError:
                        return {"texto": f"No existe la clave «{args[1]}» en la plantilla."}
                if len(args) >= 2:
                    clave = args[0]
                    valor = texto.strip().split(None, 2)[2] if len(texto.strip().split(None, 2)) > 2 else ""
                    try:
                        ant, nuevo_v, donde = ajustes.fijar(clave, valor)
                        log(con, f"Config {clave}: {ajustes.tapar(clave, ant)} -> {ajustes.tapar(clave, nuevo_v)} por {autor}")
                        return {"texto": f"✅ *{clave}*: {json.dumps(ajustes.tapar(clave, ant), ensure_ascii=False)} → "
                                         f"{json.dumps(ajustes.tapar(clave, nuevo_v), ensure_ascii=False)} ({donde}). "
                                         f"Ya está aplicado."}
                    except KeyError:
                        return {"texto": f"No existe la clave «{clave}». Escribe *!config* para ver las principales."}
                    except (ValueError, json.JSONDecodeError) as e:
                        return {"texto": f"❌ Valor inválido para {clave}: {e}"}
                return {"texto": "Uso: !config · !config clave valor · !config ver clave · !config reset clave"}
            if cmd == "!perfil":
                import ajustes
                raw = ajustes.leer()
                if not args:
                    return {"texto": f"🧭 Perfil activo: *{raw.get('perfil_activo')}*\nDisponibles: "
                                     f"{', '.join(raw.get('perfiles', {}))}\nCambia con: !perfil produccion"}
                try:
                    ajustes.cambiar_perfil(args[0].lower())
                    c2 = ajustes.efectiva()
                    log(con, f"Perfil cambiado a {args[0]} por {autor}")
                    return {"texto": f"🧭 Ahora en perfil *{args[0].lower()}* · grupo «{c2.get('grupo_id') or c2.get('grupo_nombre')}». "
                                     f"El bot ya lee ese grupo."}
                except KeyError:
                    return {"texto": f"No existe el perfil «{args[0]}»."}
            # ---- solo admin
            if not es_admin:
                return {"texto": "Ese comando es solo para el encargado."} if cmd in ("!mover", "!anular") else \
                    {"texto": "No entendí. Escribe !ayuda"}
            if cmd == "!mover" and len(args) >= 2 and args[0].isdigit():
                d = a_fecha(f"{hoy().year}-{args[1][3:5]}-{args[1][0:2]}") if len(args[1]) == 5 else a_fecha(args[1])
                b = int(args[2]) if len(args) > 2 and args[2].isdigit() else 1
                if not d:
                    return {"texto": "Fecha inválida. Usa !mover RBD dd-mm [bloque]"}
                n = con.execute("UPDATE tarjetas SET fecha=?, bloque=?, aplaz=aplaz+1, modificada=1 WHERE id=("
                                "SELECT id FROM tarjetas WHERE rbd=? AND estado='programada' ORDER BY fecha LIMIT 1)",
                                (d.isoformat(), b, int(args[0]))).rowcount
                log(con, f"Movida manual RBD {args[0]} a {d} b{b} por {autor}")
                return {"texto": f"↪️ Movida al {bonita(d)} bloque {b} (autorizado por encargado)." if n
                        else "No encontré esa visita."}
            if cmd == "!anular" and args and args[0].isdigit():
                n = con.execute("UPDATE tarjetas SET estado='anulada', modificada=1 WHERE id=(SELECT id FROM tarjetas "
                                "WHERE rbd=? AND estado='programada' ORDER BY fecha LIMIT 1)", (int(args[0]),)).rowcount
                return {"texto": "🗑️ Anulada." if n else "No encontré esa visita."}
            if cmd == "!modo" and args:
                m = args[0].lower()
                if m in ("borrador", "directo"):
                    _set_modo(m == "borrador")
                    return {"texto": f"⚙️ Modo *{m}*: " + ("te mando el borrador a aprobar antes del grupo."
                            if m == "borrador" else "responde directo al grupo, sin tu aprobación.")}
                return {"texto": "Usa !modo borrador  o  !modo directo"}
            return {"texto": "No entendí. Escribe !ayuda"}
        finally:
            con.commit()


def texto_supervisora(con, nombre, corto=False):
    """Vista por supervisora: sus colegios, casos abiertos, próximas visitas y consultas pendientes."""
    D = datos()
    q = norm(nombre)
    sups = sorted({e["sup"] for e in D["ESTAB"] if e.get("sup")})
    sup = next((s_ for s_ in sups if q and (q in norm(s_) or norm(s_).split()[0] == q.split()[0])), None)
    if not sup:
        return f"No encuentro la supervisora «{nombre}». Hay: {', '.join(sups)}"
    mios = {e["rbd"]: e for e in D["ESTAB"] if e.get("sup") == sup}
    marcas = ",".join("?" * len(mios))
    abiertos = con.execute(f"SELECT h.*, t.fecha AS f, t.tec FROM hallazgos h LEFT JOIN tarjetas t ON t.id=h.tarjeta_id "
                           f"WHERE h.rbd IN ({marcas}) AND h.estado IN ('registrado','agendado') ORDER BY h.id DESC",
                           list(mios)).fetchall()
    prox = con.execute(f"SELECT * FROM tarjetas WHERE rbd IN ({marcas}) AND estado='programada' AND fecha BETWEEN ? AND ? "
                       f"ORDER BY fecha, bloque", list(mios) + [hoy().isoformat(), sumar_habiles(hoy(), 5).isoformat()]
                       ).fetchall()
    sin = [e for e in mios.values() if e.get("cobertura") == "SIN VISITA"]
    jun = sum(1 for e in mios.values() if e["inst"] == "Junaeb")
    lin = [f"👩 *{sup}* · {len(mios)} establecimientos ({jun} JUNAEB, {len(mios) - jun} jardines)",
           f"📋 Casos abiertos: {len(abiertos)} · 📅 visitas próximos 5 días: {len(prox)} · ⏳ sin visita: {len(sin)}"]
    if corto:
        return "\n".join(lin)
    if abiertos:
        lin.append("\n📋 *Casos abiertos*")
        for h in abiertos[:12]:
            cuando = f"{bonita(h['f'])} {nombre_tec(h['tec'])}" if h["f"] else "sin hora"
            lin.append(f"• {EMOJI.get(h['crit'], '🔧')} {mios[h['rbd']]['nombre']}: {h['problema'][:50]} → {cuando}")
    if prox:
        lin.append("\n📅 *Próximas visitas*")
        for t in prox[:15]:
            lin.append(f"• {bonita(t['fecha'])} B{t['bloque']} {nombre_tec(t['tec'])} · {mios[t['rbd']]['nombre']} "
                       f"({t['clase'].lower()})")
    esperando = [p for p in con.execute("SELECT * FROM pedidos_info WHERE estado='esperando'").fetchall()
                 if _mismo_nombre(p["autor"], sup)]
    if esperando:
        lin.append("\n💬 *Le preguntaste y no responde:* " + ", ".join(f"caso #{p['borrador_id']}" for p in esperando))
    if sin:
        lin.append("\n⏳ *Sin visita todavía:* " + ", ".join(e["nombre"] for e in sin[:10]))
    return "\n".join(lin)


def _buscar_observaciones(con, palabra):
    filas = con.execute("SELECT b.rbd, bi.item, bi.observacion, b.folio, b.fecha FROM bitacora_items bi "
                        "JOIN bitacoras b ON b.folio=bi.folio WHERE bi.observacion REGEXP ? OR bi.item REGEXP ? "
                        "ORDER BY b.fecha DESC LIMIT 15", (palabra, palabra)).fetchall()
    if not filas:
        return f"🔎 Nada con «{palabra}» en las bitácoras."
    E = datos()["E"]
    out = [f"🔎 *«{palabra}»* en bitácoras:"]
    for f in filas:
        obs = (f["observacion"] or "").replace("\n", " ")
        out.append(f"• {E.get(f['rbd'], {}).get('nombre', f['rbd'])} ({f['fecha']}, folio {f['folio']}): "
                   f"{f['item']} — {obs[:70]}")
    return "\n".join(out)


def _set_modo(borrador):
    import ajustes
    ajustes.fijar("modo_borrador", "si" if borrador else "no")


# ================================================================ diagnóstico
def diagnostico(wa):
    """Chequeo completo: WhatsApp, Gemini, datos, base, configuración, disco."""
    import shutil
    c = cfg()
    D = datos()
    con = db()
    v = lambda ok: "✅" if ok else "❌"
    lin = ["🩺 *Diagnóstico del bot*", ""]
    # WhatsApp (lo informa bot.mjs)
    lin.append(f"{v(wa.get('conectado'))} WhatsApp conectado como {wa.get('yo') or '—'}")
    lin.append(f"{v(wa.get('grupo'))} Grupo detectado: {wa.get('grupo_nombre') or wa.get('grupo') or 'NO ENCONTRADO'}")
    lin.append(f"{v(wa.get('admin_ok'))} Tu número verificado en WhatsApp: {wa.get('admin') or '—'}")
    # Gemini
    ok, det = ia.probar()
    lin.append(f"{v(ok)} Gemini: {det}")
    if not ok:
        lin.append("   ↳ Sin IA el bot igual funciona con alias y palabras clave del panel.")
    # datos y base
    lin.append(f"✅ datos.js {D['META']['version']} · {len(D['ESTAB'])} establecimientos")
    prog = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado='programada'").fetchone()[0]
    pend = con.execute("SELECT COUNT(*) FROM borradores WHERE estado='pendiente'").fetchone()[0]
    try:
        bits = con.execute("SELECT COUNT(*) FROM bitacoras").fetchone()[0]
    except Exception:
        bits = 0
    lin.append(f"✅ Agenda: {prog} visitas programadas · {pend} casos por aprobar · {bits} bitácoras archivadas")
    # configuración clave
    lin.append(f"✅ Perfil *{c.get('perfil_activo')}* · modo {'borrador' if c.get('modo_borrador') else 'directo'}")
    ign = c.get("ignorar", [])
    if c.get("perfil_activo") == "prueba" and ign:
        lin.append("⚠️ En prueba estás ignorando a: " + ", ".join(ign) + " (tus mensajes de prueba no se procesarán)")
    # memoria
    mem = c.get("memoria", {})
    lin.append(f"{v(mem.get('activa') and mem.get('apps_script_url'))} Memoria: {memoria.estado_texto()}")
    # disco
    libre = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__))).free / 1e9
    lin.append(f"{v(libre > 0.5)} Espacio libre: {libre:.1f} GB")
    # respaldo
    rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "respaldos")
    ult = sorted(os.listdir(rd))[-1] if os.path.isdir(rd) and os.listdir(rd) else None
    lin.append(f"{v(bool(ult))} Último respaldo: {ult or 'todavía ninguno (se hace a las ' + c.get('respaldo', {}).get('hora', '23:30') + ')'}")
    return "\n".join(lin)


# ================================================================ tareas por minuto
_tick_estado = {"respaldo": None, "minar": None, "plan": None}
_buzon = []                       # mensajes para ti que se generan en segundo plano (reglas propuestas, etc.)
_buzon_lock = threading.Lock()


def al_buzon(textos):
    with _buzon_lock:
        _buzon.extend(t for t in textos if t)


def _minar_en_fondo():
    try:
        al_buzon(memoria.minar())
    except Exception as e:
        print("[memoria] no pude buscar reglas:", e)


def _en_ventana(hhmm, hora, minutos=90):
    """True si ahora está entre 'hora' y 'hora + minutos' (para no mandar el plan a las 22:00 tras un reinicio)."""
    try:
        h = datetime.strptime(hora, "%H:%M")
        a = datetime.strptime(hhmm, "%H:%M")
        return h <= a <= h + timedelta(minutes=minutos)
    except ValueError:
        return False


def tick():
    """
    Lo llama bot.mjs cada minuto. Devuelve lo que hay que enviar:
      {'admin': [textos], 'envios_grupo': [{'borrador_id', 'textos'}]}
    - Recordatorio de casos sin respuesta.
    - Casos de GAS que salen solos si no respondes (configurable, 0 = nunca).
    - Respaldo diario de la base.
    """
    c = cfg()
    b = c.get("borrador", {})
    rec = int(b.get("recordatorio_min", 0) or 0)
    gas = int(b.get("auto_enviar_gas_min", 0) or 0)
    out = {"admin": [], "envios_grupo": []}
    ahora = datetime.now()
    hhmm = ahora.strftime("%H:%M")
    hoy_s = ahora.strftime("%Y-%m-%d")
    with LOCK:
        con = db()
        # consultas a supervisoras que nadie respondió
        minutos = int(c.get("pedir_info", {}).get("esperar_respuesta_min", 180))
        limite = (ahora - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
        for p in con.execute("SELECT * FROM pedidos_info WHERE estado='esperando' AND creado<?", (limite,)).fetchall():
            con.execute("UPDATE pedidos_info SET estado='vencido' WHERE id=?", (p["id"],))
            out["admin"].append(f"⌛ {p['autor'] or 'La supervisora'} no respondió en {minutos // 60} h la consulta del "
                                f"caso #{p['borrador_id']} («{p['pregunta'][:60]}»). Responde *caso {p['borrador_id']} ok* "
                                f"para enviar igual, o pregúntale de nuevo.")
        # plan del día
        pl = c.get("plan", {})
        if pl.get("auto", True) and es_habil(ahora.date()) and _tick_estado["plan"] != hoy_s and \
                _en_ventana(hhmm, pl.get("hora", "07:15")):
            _tick_estado["plan"] = hoy_s
            out["admin"].append(planificador.vista(con))
        for br in con.execute("SELECT * FROM borradores WHERE estado='pendiente'").fetchall():
            edad = (ahora - datetime.strptime(br["creado"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
            if gas and br["crit"] == "GAS" and edad >= gas:
                resp = br["respuesta"] + (f"\nℹ️ {_nota_publica(br['nota_interna'])}" if _nota_publica(br["nota_interna"]) else "")
                con.execute("UPDATE borradores SET estado='enviado' WHERE id=?", (br["id"],))
                memoria.registrar_de_borrador(con, br, "auto_gas", detalle=f"{int(edad)} min sin respuesta",
                                              texto_final=resp)
                log(con, f"Borrador #{br['id']} (GAS) enviado solo tras {int(edad)} min sin respuesta")
                out["envios_grupo"].append({"borrador_id": br["id"], "textos": [resp]})
                out["admin"].append(f"⏱️ Caso #{br['id']} es de *gas* y llevaba {int(edad)} min sin respuesta: "
                                    f"lo envié al grupo. Si no correspondía, escribe !anular {br['rbd']}.")
            elif rec and edad >= rec and not br["recordado"]:
                con.execute("UPDATE borradores SET recordado=1 WHERE id=?", (br["id"],))
                out["admin"].append(f"⏰ El caso #{br['id']} lleva {int(edad)} min esperando tu ok.\n"
                                    f"Responde *ok*, *no* o escribe *!caso {br['id']}* para verlo.")
        con.commit()
    # memoria: subir decisiones / traer reglas, y una vez al día buscar patrones
    if memoria.toca_sincronizar():
        threading.Thread(target=memoria.sincronizar, daemon=True).start()
    mh = c.get("memoria", {}).get("minar_hora", "18:15")
    if _tick_estado["minar"] != hoy_s and _en_ventana(hhmm, mh, 180):
        _tick_estado["minar"] = hoy_s
        threading.Thread(target=_minar_en_fondo, daemon=True).start()
    with _buzon_lock:
        out["admin"] += _buzon
        _buzon.clear()
    # respaldo diario
    r = c.get("respaldo", {})
    if r.get("activo") and ahora.strftime("%H:%M") >= r.get("hora", "23:30") and _tick_estado["respaldo"] != hoy_s:
        _tick_estado["respaldo"] = hoy_s
        try:
            respaldar(int(r.get("conservar_dias", 14)))
        except Exception as e:
            out["admin"].append(f"⚠️ No pude hacer el respaldo diario: {e}")
    return out


def respaldar(conservar=14):
    import shutil, sqlite3 as _sq
    base = os.path.dirname(os.path.abspath(__file__))
    rd = os.path.join(base, "respaldos")
    os.makedirs(rd, exist_ok=True)
    destino = os.path.join(rd, f"agenda_{datetime.now().strftime('%Y-%m-%d')}.db")
    src = _sq.connect(os.path.join(base, "agenda.db"))
    dst = _sq.connect(destino)
    with dst:
        src.backup(dst)          # copia consistente aunque la base esté en uso
    src.close()
    dst.close()
    for f in sorted(os.listdir(rd))[:-conservar]:
        os.remove(os.path.join(rd, f))
    return destino


def agenda_del_dia():
    con = db()
    return texto_agenda(con, hoy(), hoy(), None, f"Agenda de hoy {bonita(hoy())}")


# ================================================================ panel (GitHub)
def subir_github():
    """Empuja bot-datos.json con el mismo formato que lee tu panel (pestaña WhatsApp)."""
    c = cfg()
    if not c.get("github_token"):
        return
    try:
        con = db()
        E = datos()["E"]
        corte = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        filas = con.execute("""SELECT h.*, t.fecha AS f_ag, t.tec, t.bloque FROM hallazgos h
                               LEFT JOIN tarjetas t ON t.id=h.tarjeta_id
                               WHERE h.rbd IS NOT NULL AND h.recibido>=? ORDER BY h.id""", (corte,)).fetchall()
        st = {"generado": datetime.now().strftime("%Y-%m-%d %H:%M"), "fuente": "bot-ia", "hallazgos": [
            {"fecha": h["recibido"][:10], "autor": h["autor"], "rbd": h["rbd"], "texto": h["texto"][:400],
             "crit": h["crit"], "estab": E[h["rbd"]]["nombre"], "sup": E[h["rbd"]]["sup"],
             "problema": h["problema"], "pts": h["pts"], "agendado": h["f_ag"], "tec": h["tec"],
             "bloque": h["bloque"], "estado": h["estado"]} for h in filas]}
        url = f"https://api.github.com/repos/{c['github_repo']}/contents/{c['github_archivo']}"
        cab = {"Authorization": f"Bearer {c['github_token']}", "Accept": "application/vnd.github+json",
               "Content-Type": "application/json", "User-Agent": "soser-bot-ia"}
        sha = None
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{url}?ref={c['github_rama']}", headers=cab),
                                        timeout=20) as r:
                sha = json.loads(r.read())["sha"]
        except Exception:
            pass
        cuerpo = {"message": f"bot-ia: {len(st['hallazgos'])} hallazgo(s) al {st['generado']}",
                  "content": base64.b64encode(json.dumps(st, ensure_ascii=False, indent=1).encode()).decode(),
                  "branch": c["github_rama"]}
        if sha:
            cuerpo["sha"] = sha
        urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(cuerpo).encode(), headers=cab,
                                                      method="PUT"), timeout=30)
        print("[github] bot-datos.json actualizado")
    except Exception as e:
        print("[github] no pude subir:", e)


# ================================================================ HTTP
class H(BaseHTTPRequestHandler):
    def _json(self, code, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/salud":
                return self._json(200, {"ok": True, "version_datos": datos()["META"]["version"]})
            if self.path == "/agenda_dia":
                return self._json(200, {"texto": agenda_del_dia()})
            if self.path == "/reporte":
                return self._json(200, {"archivo": reportes.generar()})
            self._json(404, {"error": "no existe"})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": str(e)})

    def do_POST(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/mensaje":        # compatibilidad modo directo
                return self._json(200, {"respuestas": procesar_mensaje(data.get("texto", ""),
                                                                        data.get("autor", "supervisora"))})
            if self.path == "/entrada":        # mensaje del grupo o caso del admin
                ts = data.get("ts")
                return self._json(200, entrada(data.get("origen", "grupo"), data.get("texto", ""),
                                               data.get("autor", "supervisora"), citado=data.get("citado", ""),
                                               ahora=datetime.fromtimestamp(ts) if ts else None))
            if self.path == "/foto":           # foto del grupo o de tu privado
                return self._json(200, foto(data.get("ruta", ""), data.get("autor", ""), data.get("origen", "grupo"),
                                            data.get("caption", ""), data.get("citado", "")))
            if self.path == "/privado":        # todo lo que escribes en tu chat privado (lenguaje natural)
                ts = data.get("ts")
                return self._json(200, privado.manejar(data.get("texto", ""), data.get("autor", "Manuel"),
                                                       data.get("borrador_id"), data.get("citado", ""), ts))
            if self.path == "/aprobar":        # ok / no / texto sobre un borrador
                return self._json(200, aprobar(data.get("decision", ""), data.get("autor", ""),
                                               data.get("borrador_id")))
            if self.path == "/adjuntar":       # PDF u otro archivo para el borrador pendiente
                return self._json(200, adjuntar_a_borrador(data.get("ruta", ""), data.get("autor", ""),
                                                           data.get("borrador_id")))
            if self.path == "/bitacora":       # archivar un PDF de bitácora
                try:
                    r = bitacoras.archivar(data.get("ruta", ""), data.get("nombre", ""), data.get("fecha", ""))
                    memoria.subir_bitacora(r)
                    txt = (f"📥 Bitácora archivada\n🏫 {r['nombre']} · RBD {r['rbd']}\n"
                           f"📄 Folio {r['folio']} · {bonita(r['fecha'])} · {r['tecnico'] or 's/téc'}\n"
                           f"🔧 {r['n_items']} ítems con trabajo")
                    if r["avisos"]:
                        txt += "\n⚠️ " + "\n⚠️ ".join(r["avisos"])
                    return self._json(200, {"texto": txt})
                except Exception as e:
                    return self._json(200, {"texto": f"❌ No pude leer el PDF como bitácora: {e}"})
            if self.path == "/adjuntos":       # bot.mjs pide los PDFs de un borrador aprobado
                return self._json(200, {"archivos": adjuntos_de(data.get("borrador_id"))})
            if self.path == "/comando":
                return self._json(200, procesar_comando(data.get("texto", ""), data.get("autor", ""),
                                                        bool(data.get("es_admin")), bool(data.get("privado")),
                                                        data.get("wa") or {}))
            if self.path == "/tick":
                return self._json(200, tick())
            self._json(404, {"error": "no existe"})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    import ajustes
    nuevas = ajustes.migrar()
    if nuevas:
        print("⚙️ config.json actualizado con claves nuevas:", ", ".join(nuevas))
    try:
        memoria.asegurar_clave()
    except Exception as e:
        print("⚠️ memoria: no pude crear la clave de la planilla:", e)
    con = db()
    n = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado='programada'").fetchone()[0]
    print(f"🧠 Servidor SOSER en http://127.0.0.1:{PUERTO} · datos.js {datos()['META']['version']} · "
          f"{len(datos()['ESTAB'])} establecimientos · {n} visitas programadas")
    con.close()
    ThreadingHTTPServer(("127.0.0.1", PUERTO), H).serve_forever()
