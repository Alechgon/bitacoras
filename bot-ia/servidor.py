"""
servidor.py — el "jefe de obra". Recibe cada mensaje del grupo (se lo pasa
bot.mjs), le pregunta a la IA qué dice, aplica tus reglas, guarda en la agenda
y devuelve la respuesta para el grupo. Corre en http://127.0.0.1:8765.

Uso: python servidor.py
"""
import base64, json, os, threading, traceback, urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bitacoras
import ia
import reportes
from nucleo import (a_fecha, agenda, agendar, bonita, buscar, cfg, datos, db, en_texto, es_prioridad,
                    hora_bloque, hoy, log, metas, nombre_tec, sumar_habiles)

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
           f"⚠️ Criticidad *{res['pts']}/20* ({crit})",
           f"👷 {nombre_tec(res['tec'])} · *{bonita(res['fecha'])}* · {hora_bloque(res['fecha'], res['bloque'])}"]
    if res["modo"] == "fusion":
        lin.append("✅ Se resuelve en la visita que ya estaba agendada")
    elif res["modo"].startswith("adelantada"):
        lin.append(f"⏩ Se adelantó su visita del {bonita(res['antes'])}")
    if "extra" in res["modo"] or res["modo"] == "sobrecupo":
        lin.append("❗ Agenda llena: va como bloque extra (emergencia), Manuel lo confirma")
    if res.get("movida"):
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


def _generar_respuestas(con, texto, autor, motor, analisis):
    """Agenda cada hallazgo y devuelve [(texto_respuesta, rbd, crit, hallazgo_id, tarjeta_id)]."""
    E = datos()["E"]
    salida, vistos = [], set()
    bcfg = cfg().get("borrador", {})
    for h in analisis["hallazgos"][:int(bcfg.get("max_hallazgos_por_mensaje", 6))]:
        problema = (h.get("problema") or texto[:90]).strip()
        crit = h.get("tipo") if h.get("tipo") in ia.PAL or h.get("tipo") == "OTRO" else ia.tipo_por_palabras(texto)
        rbd, cands = resolver(h, texto, vistos)
        if rbd:
            if rbd in vistos:
                continue
            vistos.add(rbd)
            dup = con.execute("SELECT respuesta FROM hallazgos WHERE rbd=? AND crit=? AND estado='agendado' "
                              "AND recibido>=?", (rbd, crit,
                              (datetime.now() - timedelta(days=int(bcfg.get("dias_duplicado", 7)))).strftime("%Y-%m-%d"))).fetchone()
            if dup:
                salida.append((f"🔁 Ya estaba registrado:\n{dup['respuesta']}", rbd, crit, None, None))
                continue
            hid = con.execute("INSERT INTO hallazgos(recibido,autor,texto,rbd,problema,crit,prio,estado,motor) "
                              "VALUES(?,?,?,?,?,?,?,'agendado',?)",
                              (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, rbd, problema, crit,
                               int(es_prioridad(texto)), motor)).lastrowid
            e = E[rbd]
            res = agendar(con, rbd, crit, problema, es_prioridad(texto), autor, hid)
            resp = texto_respuesta(e, problema, crit, res)
            con.execute("UPDATE hallazgos SET pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                        (res["pts"], res["tarjeta"], resp, hid))
            log(con, f"Hallazgo {hid} {e['nombre']} {crit} {res['pts']}pts -> {res['tec']} {res['fecha']} [{res['modo']}]")
            salida.append((resp, rbd, crit, hid, res["tarjeta"]))
        else:
            con.execute("INSERT INTO hallazgos(recibido,autor,texto,problema,crit,prio,estado,candidatos,motor) "
                        "VALUES(?,?,?,?,?,?,'por_confirmar',?,?)",
                        (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, problema, crit,
                         int(es_prioridad(texto)), json.dumps(cands), motor))
            nom = h.get("nombre_mencionado") or "el establecimiento"
            if cands:
                ops = "\n".join(f"  • {E[r]['nombre']} ({E[r]['comuna']}) → *!es {r}*" for r in cands)
                salida.append((f"🤔 «{nom}»: ¿cuál es?\n{ops}\n{EMOJI.get(crit, '🔧')} {problema}", None, crit, None, None))
            else:
                salida.append((f"❓ No ubico «{nom}» en los 93 establecimientos.\n{EMOJI.get(crit, '🔧')} "
                               f"{problema}\nRespondan *!es RBD* para agendarlo.", None, crit, None, None))
    return salida


def entrada(origen, texto, autor, forzar_directo=False):
    """
    Punto de entrada de un mensaje. origen: 'grupo' (supervisora) o 'admin' (Manuel sube un caso).
    Devuelve {'grupo':[...], 'admin':[...], 'borradores':[ids]}.
    En modo borrador (config.modo_borrador), el grupo no recibe nada hasta que Manuel aprueba.
    """
    c = cfg()
    vacio = {"grupo": [], "admin": [], "borradores": []}
    if origen == "grupo" and any(i.lower() in autor.lower() for i in c.get("ignorar", []) if i):
        return vacio
    analisis, motor = ia.analizar(texto, autor)
    if not analisis.get("es_reporte") or not analisis.get("hallazgos"):
        return vacio
    modo_borrador = c.get("modo_borrador", True) and not forzar_directo
    out = {"grupo": [], "admin": [], "borradores": []}
    with LOCK:
        con = db()
        for resp, rbd, crit, hid, tid in _generar_respuestas(con, texto, autor, motor, analisis):
            if modo_borrador:
                bid = con.execute("INSERT INTO borradores(origen,autor,texto_original,respuesta,rbd,crit,"
                                  "hallazgo_id,tarjeta_id,estado) VALUES(?,?,?,?,?,?,?,?,'pendiente')",
                                  (origen, autor, texto, resp, rbd, crit, hid, tid)).lastrowid
                out["borradores"].append(bid)
                out["admin"].append(_texto_borrador(con, bid))
            else:
                out["grupo"].append(resp)
        con.commit()
    threading.Thread(target=subir_github, daemon=True).start()
    return out


# ================================================================ borradores (aprobación)
def _texto_borrador(con, bid):
    b = con.execute("SELECT * FROM borradores WHERE id=?", (bid,)).fetchone()
    orig = "supervisora" if b["origen"] == "grupo" else "ti"
    adj = json.loads(b["adjuntos"] or "[]")
    lin = [f"🆕 *Caso #{bid}* · de {orig} ({b['autor']})",
           f"💬 «{b['texto_original'][:160]}»", "",
           "📝 *Borrador para el grupo:*", b["respuesta"]]
    if b["nota_interna"]:
        lin += ["", f"➕ Agregado: {b['nota_interna']}"]
    if adj:
        lin.append(f"📎 Adjuntos: {', '.join(os.path.basename(a) for a in adj)}")
    lin += ["", "Responde *ok* para enviar · *no* para descartar · escribe texto para sumar · o envía un PDF"]
    return "\n".join(lin)


def _borrador_pendiente(con, bid=None):
    if bid:
        return con.execute("SELECT * FROM borradores WHERE id=? AND estado='pendiente'", (bid,)).fetchone()
    return con.execute("SELECT * FROM borradores WHERE estado='pendiente' ORDER BY id DESC LIMIT 1").fetchone()


def aprobar(decision, autor, bid=None):
    """decision: 'ok', 'no' o texto para sumar. Devuelve {'grupo':[], 'admin':[], 'enviar_borrador':id}."""
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
        if dl in si:
            resp = b["respuesta"]
            if b["nota_interna"]:
                resp += f"\nℹ️ {b['nota_interna']}"
            con.execute("UPDATE borradores SET estado='enviado' WHERE id=?", (b["id"],))
            log(con, f"Borrador #{b['id']} aprobado por {autor} -> grupo")
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
            log(con, f"Borrador #{b['id']} descartado por {autor}")
            con.commit()
            out["admin"].append(f"🗑️ Caso #{b['id']} descartado, liberé el bloque.")
        else:
            nota = (b["nota_interna"] + " | " if b["nota_interna"] else "") + d
            con.execute("UPDATE borradores SET nota_interna=? WHERE id=?", (nota, b["id"]))
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

*✅ Casos (tu privado)*
Escríbeme un caso → te mando el borrador
ok · no · +texto para sumar · PDF para adjuntar
!casos — pendientes · !caso N — ver uno

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
    if cmd in ("!diagnostico", "!diag", "!simular"):
        if not es_admin:
            return {"texto": "Ese comando es solo para el encargado."}
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
    # disco
    libre = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__))).free / 1e9
    lin.append(f"{v(libre > 0.5)} Espacio libre: {libre:.1f} GB")
    # respaldo
    rd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "respaldos")
    ult = sorted(os.listdir(rd))[-1] if os.path.isdir(rd) and os.listdir(rd) else None
    lin.append(f"{v(bool(ult))} Último respaldo: {ult or 'todavía ninguno (se hace a las ' + c.get('respaldo', {}).get('hora', '23:30') + ')'}")
    return "\n".join(lin)


# ================================================================ tareas por minuto
_tick_estado = {"respaldo": None}


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
    with LOCK:
        con = db()
        for br in con.execute("SELECT * FROM borradores WHERE estado='pendiente'").fetchall():
            edad = (ahora - datetime.strptime(br["creado"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
            if gas and br["crit"] == "GAS" and edad >= gas:
                resp = br["respuesta"] + (f"\nℹ️ {br['nota_interna']}" if br["nota_interna"] else "")
                con.execute("UPDATE borradores SET estado='enviado' WHERE id=?", (br["id"],))
                log(con, f"Borrador #{br['id']} (GAS) enviado solo tras {int(edad)} min sin respuesta")
                out["envios_grupo"].append({"borrador_id": br["id"], "textos": [resp]})
                out["admin"].append(f"⏱️ Caso #{br['id']} es de *gas* y llevaba {int(edad)} min sin respuesta: "
                                    f"lo envié al grupo. Si no correspondía, escribe !anular {br['rbd']}.")
            elif rec and edad >= rec and not br["recordado"]:
                con.execute("UPDATE borradores SET recordado=1 WHERE id=?", (br["id"],))
                out["admin"].append(f"⏰ El caso #{br['id']} lleva {int(edad)} min esperando tu ok.\n"
                                    f"Responde *ok*, *no* o escribe *!caso {br['id']}* para verlo.")
        con.commit()
    # respaldo diario
    r = c.get("respaldo", {})
    hoy_s = ahora.strftime("%Y-%m-%d")
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
                return self._json(200, entrada(data.get("origen", "grupo"), data.get("texto", ""),
                                               data.get("autor", "supervisora")))
            if self.path == "/aprobar":        # ok / no / texto sobre un borrador
                return self._json(200, aprobar(data.get("decision", ""), data.get("autor", ""),
                                               data.get("borrador_id")))
            if self.path == "/adjuntar":       # PDF u otro archivo para el borrador pendiente
                return self._json(200, adjuntar_a_borrador(data.get("ruta", ""), data.get("autor", ""),
                                                           data.get("borrador_id")))
            if self.path == "/bitacora":       # archivar un PDF de bitácora
                try:
                    r = bitacoras.archivar(data.get("ruta", ""), data.get("nombre", ""), data.get("fecha", ""))
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
    con = db()
    n = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado='programada'").fetchone()[0]
    print(f"🧠 Servidor SOSER en http://127.0.0.1:{PUERTO} · datos.js {datos()['META']['version']} · "
          f"{len(datos()['ESTAB'])} establecimientos · {n} visitas programadas")
    con.close()
    ThreadingHTTPServer(("127.0.0.1", PUERTO), H).serve_forever()
