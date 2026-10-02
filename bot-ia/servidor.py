"""
servidor.py — el "jefe de obra". Recibe cada mensaje del grupo (se lo pasa
bot.mjs), le pregunta a la IA qué dice, aplica tus reglas, guarda en la agenda
y devuelve la respuesta para el grupo. Corre en http://127.0.0.1:8765.

Uso: python servidor.py
"""
import base64, json, threading, traceback, urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ia
import reportes
from nucleo import (a_fecha, agenda, agendar, bonita, buscar, cfg, datos, db, en_texto, es_prioridad,
                    hora_bloque, hoy, log, metas, nombre_tec, sumar_habiles)

LOCK = threading.Lock()
PUERTO = 8765
SEGURO, DUDA = 82, 60
EMOJI = {"GAS": "🔥", "FRIO": "❄️", "AGUA": "💧", "ELEC": "⚡", "EQUIPO": "🍳", "OTRO": "🔧"}


# ================================================================ resolver establecimiento
def resolver(h, texto, excluir=()):
    """Devuelve (rbd, candidatos). rbd=None si hay que preguntar."""
    E = datos()["E"]
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
    if any(i.lower() in autor.lower() for i in cfg().get("ignorar", []) if i):
        return []
    analisis, motor = ia.analizar(texto, autor)
    if not analisis.get("es_reporte") or not analisis.get("hallazgos"):
        return []
    E = datos()["E"]
    salida = []
    with LOCK:
        con = db()
        vistos = set()
        for h in analisis["hallazgos"][:6]:
            problema = (h.get("problema") or texto[:90]).strip()
            crit = h.get("tipo") if h.get("tipo") in ia.PAL or h.get("tipo") == "OTRO" else ia.tipo_por_palabras(texto)
            rbd, cands = resolver(h, texto, vistos)
            if rbd:
                if rbd in vistos:
                    continue
                vistos.add(rbd)
                # ¿ya lo tenemos registrado esta semana con la misma falla? no duplicar
                dup = con.execute("SELECT respuesta FROM hallazgos WHERE rbd=? AND crit=? AND estado='agendado' "
                                  "AND recibido>=?", (rbd, crit,
                                                      (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"))).fetchone()
                if dup:
                    salida.append(f"🔁 Ya estaba registrado:\n{dup['respuesta']}")
                    continue
                salida.append(registrar_y_agendar(con, rbd, problema, crit, texto, autor, motor))
            else:
                con.execute("INSERT INTO hallazgos(recibido,autor,texto,problema,crit,prio,estado,candidatos,motor) "
                            "VALUES(?,?,?,?,?,?,'por_confirmar',?,?)",
                            (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, problema, crit,
                             int(es_prioridad(texto)), json.dumps(cands), motor))
                nom = h.get("nombre_mencionado") or "el establecimiento"
                if cands:
                    ops = "\n".join(f"  • {E[r]['nombre']} ({E[r]['comuna']}) → *!es {r}*" for r in cands)
                    salida.append(f"🤔 «{nom}»: ¿cuál es?\n{ops}\n{EMOJI.get(crit, '🔧')} {problema}")
                else:
                    salida.append(f"❓ No ubico «{nom}» en los 93 establecimientos.\n{EMOJI.get(crit, '🔧')} "
                                  f"{problema}\nRespondan *!es RBD* para agendarlo.")
        con.commit()
    threading.Thread(target=subir_github, daemon=True).start()
    return salida


# ================================================================ comandos
AYUDA = """🤖 *Comandos del bot*
!hoy — agenda de hoy
!mañana — agenda de mañana
!semana — próximos 5 días hábiles
!agenda camilo / !agenda rodrigo
!pendientes — hallazgos por confirmar o sin visita
!metas — avance JUNAEB y jardines
!hecho RBD — marcar visita realizada
!es RBD — confirmar el establecimiento del último mensaje dudoso
!ficha RBD — puntaje y próxima visita
!reporte — Excel completo
_admin:_ !mover RBD dd-mm [bloque] · !anular RBD"""


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


def procesar_comando(texto, autor, es_admin):
    D = datos()
    E = D["E"]
    partes = texto.strip().split()
    cmd = partes[0].lower().replace("ñ", "n")
    args = partes[1:]
    tecs = {t.lower(): t for t in D["META"]["tecnicos"]}
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
            return {"texto": "No entendí. Escribe !ayuda"}
        finally:
            con.commit()


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
            if self.path == "/mensaje":
                return self._json(200, {"respuestas": procesar_mensaje(data.get("texto", ""),
                                                                        data.get("autor", "supervisora"))})
            if self.path == "/comando":
                return self._json(200, procesar_comando(data.get("texto", ""), data.get("autor", ""),
                                                        bool(data.get("es_admin"))))
            self._json(404, {"error": "no existe"})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    con = db()
    n = con.execute("SELECT COUNT(*) FROM tarjetas WHERE estado='programada'").fetchone()[0]
    print(f"🧠 Servidor SOSER en http://127.0.0.1:{PUERTO} · datos.js {datos()['META']['version']} · "
          f"{len(datos()['ESTAB'])} establecimientos · {n} visitas programadas")
    con.close()
    ThreadingHTTPServer(("127.0.0.1", PUERTO), H).serve_forever()
