"""
personas.py — quién escribe en el grupo, el hilo de cada uno y que nadie quede sin respuesta.

Identificación (en este orden):
  1. Números que ya conoce (tabla personas, se llena sola o con !persona).
  2. config.json → "personas": {"569XXXXXXXX": {"nombre": "Carla", "rol": "supervisora"}}.
  3. Tu número (admins) = encargado · tecnicos_whatsapp = técnico.
  4. Por el nombre de WhatsApp contra las supervisoras de datos.js ("Carla 🌸" = Carla Espinoza).
     Lo que aprende queda guardado: la próxima vez la reconoce por el número aunque cambie el nombre.

Cada mensaje del grupo (de ellas, del bot y tuyo) queda en la tabla chat, agrupado en conversaciones
(sesiones) por persona, con inicio y cierre claros. La planilla tiene una hoja por persona.
Si alguien pide algo y en avisar_min nadie le responde (ni el bot ni tú), te aviso una vez.
"""
import re
from datetime import datetime, timedelta

from nucleo import cfg, datos, norm

ROLES = ("supervisora", "jefatura", "encargado", "tecnico", "integrante")
REQUIERE = {"agendar", "requerimiento", "pregunta", "verificador", "frio", "grasa", "seguimiento", "insistencia",
            "reclamo", "conversacion", "faq", "emergencia", "consulta_seguimiento", "respuesta_info"}
ALIAS_NOMBRE = {"annahi": "anahi", "nangii": "anahi", "steph": "stephania", "stefania": "stephania",
                "estefania": "stephania"}


def conf():
    return cfg().get("vigilancia", {})


def solo_digitos(x):
    return re.sub(r"\D", "", str(x or ""))


# ---------------------------------------------------------------- quién es
def _sup_por_nombre(push):
    """'Carla 🌸' -> 'Carla Espinoza' (supervisora de datos.js) o None."""
    p = norm(push).split()
    if not p:
        return None
    primero = ALIAS_NOMBRE.get(p[0], p[0])
    sups = sorted({e["sup"] for e in datos()["ESTAB"] if e.get("sup")})
    for s in sups:
        ns = norm(s).split()
        if ns and ALIAS_NOMBRE.get(ns[0], ns[0]) == primero:
            return s
    return None


def identificar(con, numero, push=""):
    """Devuelve {numero, nombre, rol, sup}. Aprende números nuevos."""
    n = solo_digitos(numero)
    c = cfg()
    if n:
        f = con.execute("SELECT * FROM personas WHERE numero=?", (n,)).fetchone()
        if f:
            return {"numero": n, "nombre": f["nombre"], "rol": f["rol"], "sup": f["sup"] or ""}
        p = (c.get("personas") or {}).get(n)
        if isinstance(p, dict) and p.get("nombre"):
            sup = p.get("sup") or (_sup_por_nombre(p["nombre"]) if p.get("rol", "supervisora") == "supervisora" else "")
            return _aprender(con, n, p["nombre"], p.get("rol", "supervisora"), sup or "", "config")
        if n in [solo_digitos(a) for a in c.get("admins", [])]:
            return _aprender(con, n, c.get("nombre_encargado", "Manuel"), "encargado", "", "admins")
        for tec, num in (c.get("tecnicos_whatsapp") or {}).items():
            if num and solo_digitos(num) == n:
                return _aprender(con, n, tec.title(), "tecnico", "", "tecnicos_whatsapp")
    sup = _sup_por_nombre(push)
    if sup:
        nombre = _primer_nombre(push) or sup.split()[0]
        return _aprender(con, n, nombre, "supervisora", sup, "nombre de WhatsApp") if n else \
            {"numero": "", "nombre": nombre, "rol": "supervisora", "sup": sup}
    if n and push:
        return _aprender(con, n, _limpiar_push(push), "integrante", "", "nombre de WhatsApp")
    return {"numero": n, "nombre": _limpiar_push(push) or "alguien", "rol": "integrante", "sup": ""}


def _limpiar_push(push):
    """'Stephania Fernandez Supp Soser 🌷' -> 'Stephania Fernandez'."""
    t = re.sub(r"[^\w\sáéíóúñüÁÉÍÓÚÑÜ'-]", " ", str(push or ""))
    t = re.sub(r"(?i)\b(supp?|soser|sec\d*|supervisora?|jefa|jefe)\b", " ", t)
    return " ".join(t.split()[:2])


def _primer_nombre(push):
    t = _limpiar_push(push)
    return t.split()[0] if t else ""


def _aprender(con, numero, nombre, rol, sup, fuente):
    if numero:
        con.execute("INSERT OR IGNORE INTO personas(numero,nombre,rol,sup,fuente) VALUES(?,?,?,?,?)",
                    (numero, nombre, rol, sup, fuente))
    return {"numero": numero, "nombre": nombre, "rol": rol, "sup": sup}


def guardar_persona(con, numero, nombre, rol="supervisora"):
    """!persona 56912345678 Carla supervisora — fija (o corrige) a alguien."""
    n = solo_digitos(numero)
    if not (8 <= len(n) <= 15):
        raise ValueError("número con código de país, ej 56912345678")
    rol = rol if rol in ROLES else "supervisora"
    sup = _sup_por_nombre(nombre) if rol == "supervisora" else ""
    con.execute("INSERT INTO personas(numero,nombre,rol,sup,fuente) VALUES(?,?,?,?,'manual') "
                "ON CONFLICT(numero) DO UPDATE SET nombre=excluded.nombre, rol=excluded.rol, sup=excluded.sup, "
                "fuente='manual'", (n, nombre, rol, sup or ""))
    con.execute("UPDATE chat SET nombre=?, rol=?, sup=? WHERE numero=?", (nombre, rol, sup or "", n))
    con.execute("UPDATE sesiones SET nombre=? WHERE numero=?", (nombre, n))
    con.commit()
    return {"numero": n, "nombre": nombre, "rol": rol, "sup": sup or ""}


def texto_personas(con):
    filas = con.execute("SELECT p.*, (SELECT COUNT(*) FROM chat c WHERE c.numero=p.numero) AS n FROM personas p "
                        "ORDER BY CASE rol WHEN 'encargado' THEN 0 WHEN 'supervisora' THEN 1 ELSE 2 END, nombre"
                        ).fetchall()
    if not filas:
        return "Todavía no conozco a nadie del grupo. Apenas escriban, las reconozco por el nombre de WhatsApp."
    lin = ["Gente del grupo que tengo identificada:"]
    for f in filas:
        lin.append(f"- {f['nombre']} · {f['rol']}" + (f" ({f['sup']})" if f["sup"] and f["sup"] != f["nombre"] else "")
                   + f" · …{f['numero'][-4:]} · {f['n']} mensajes")
    lin.append("\nPara corregir: *!persona 569XXXXXXXX Nombre supervisora|jefatura|tecnico|integrante*")
    return "\n".join(lin)


def sup_de(persona):
    return (persona or {}).get("sup") or ""


def colegios_de(persona):
    s = sup_de(persona)
    return {e["rbd"] for e in datos()["ESTAB"] if s and e.get("sup") == s}


# ---------------------------------------------------------------- conversaciones (sesiones)
def _ahora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _sesion(con, persona):
    """La conversación abierta con esa persona, o una nueva (y cierra la vieja si pasó cerrar_min)."""
    clave = persona.get("numero") or persona.get("nombre")
    minutos = int(conf().get("cerrar_min", 90))
    s = con.execute("SELECT * FROM sesiones WHERE numero=? AND estado='abierta' ORDER BY id DESC LIMIT 1",
                    (clave,)).fetchone()
    if s:
        if datetime.strptime(s["ultimo"], "%Y-%m-%d %H:%M:%S") >= datetime.now() - timedelta(minutes=minutos):
            return s["id"]
        _cerrar(con, s, "inactividad")
    return con.execute("INSERT INTO sesiones(numero,nombre,inicio,ultimo) VALUES(?,?,?,?)",
                       (clave, persona.get("nombre"), _ahora(), _ahora())).lastrowid


def _cerrar(con, s, motivo_):
    con.execute("UPDATE sesiones SET estado='cerrada', fin=ultimo, cierre=? WHERE id=?", (motivo_, s["id"]))


def registrar_entrante(con, persona, texto, wa_id="", intencion=None, rbd=None):
    """Mensaje de alguien en el grupo. Devuelve el id de la fila de chat."""
    sid = _sesion(con, persona)
    cid = con.execute("INSERT INTO chat(numero,nombre,rol,sup,direccion,texto,intencion,rbd,sesion_id,wa_id) "
                      "VALUES(?,?,?,?,'entra',?,?,?,?,?)",
                      (persona.get("numero") or persona.get("nombre"), persona.get("nombre"), persona.get("rol"),
                       persona.get("sup"), (texto or "")[:2000], intencion, rbd, sid, wa_id or "")).lastrowid
    con.execute("UPDATE sesiones SET ultimo=?, entrantes=entrantes+1 WHERE id=?", (_ahora(), sid))
    return cid


def completar(con, chat_id, intencion, rbd=None, respondido=False, borrador_id=None):
    """Después de procesar: qué era, si pedía respuesta y si ya se le respondió en el grupo."""
    if not chat_id:
        return
    req = 1 if intencion in REQUIERE else 0
    con.execute("UPDATE chat SET intencion=?, rbd=COALESCE(?,rbd), requiere=?, borrador_id=?, "
                "respondido=CASE WHEN ? THEN ? ELSE respondido END WHERE id=?",
                (intencion, rbd, req, borrador_id, int(bool(respondido)), _ahora(), chat_id))
    s = con.execute("SELECT sesion_id FROM chat WHERE id=?", (chat_id,)).fetchone()
    if s and intencion and intencion not in ("charla",):
        ses = con.execute("SELECT temas FROM sesiones WHERE id=?", (s["sesion_id"],)).fetchone()
        temas = [x for x in (ses["temas"] or "").split(", ") if x]
        etiqueta = intencion + (f" {datos()['E'].get(rbd, {}).get('nombre', '')[:25]}" if rbd else "")
        if etiqueta.strip() and etiqueta not in temas:
            temas.append(etiqueta.strip())
        con.execute("UPDATE sesiones SET temas=? WHERE id=?", (", ".join(temas[-8:]), s["sesion_id"]))


def registrar_saliente(con, texto, para_numero="", cita_id="", quien="Bot"):
    """Lo que el bot (o tú) publica en el grupo. Lo cuelga de la conversación de esa persona y la marca respondida."""
    para = solo_digitos(para_numero)
    destino = None
    reciente = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    if cita_id:
        destino = con.execute("SELECT * FROM chat WHERE wa_id=? AND direccion='entra' ORDER BY id DESC LIMIT 1",
                              (cita_id,)).fetchone()
    if not destino and para:                          # última cosa que dijo esa persona (respondida o no)
        destino = con.execute("SELECT * FROM chat WHERE numero=? AND direccion='entra' ORDER BY id DESC LIMIT 1",
                              (para,)).fetchone()
    if not destino:                       # sin pista: si hay UNA sola persona esperando, es para ella
        esperando = con.execute("SELECT * FROM chat WHERE direccion='entra' AND requiere=1 AND respondido IS NULL "
                                "AND cuando>=? ORDER BY id DESC", (reciente,)).fetchall()
        if len({e["numero"] for e in esperando}) == 1:
            destino = esperando[0]
    sid = destino["sesion_id"] if destino else None
    con.execute("INSERT INTO chat(numero,nombre,rol,direccion,texto,sesion_id,para) VALUES(?,?,?,?,?,?,?)",
                ("bot" if quien == "Bot" else "encargado", quien, "bot" if quien == "Bot" else "encargado", "sale",
                 (texto or "")[:2000], sid, destino["numero"] if destino else para))
    if destino:
        con.execute("UPDATE chat SET respondido=? WHERE numero=? AND direccion='entra' AND respondido IS NULL "
                    "AND id<=?", (_ahora(), destino["numero"], destino["id"]))
        con.execute("UPDATE sesiones SET ultimo=?, salientes=salientes+1 WHERE id=?", (_ahora(), sid))
    con.commit()


def humano_responde(con, persona_admin, texto, para_numero="", cita_id=""):
    """Escribiste tú en el grupo (sin !): no te respondo, pero cuenta como respuesta a quien citaste."""
    registrar_saliente(con, texto, para_numero, cita_id, quien=persona_admin.get("nombre") or "Manuel")


# ---------------------------------------------------------------- vigilancia
def _en_horario(ahora):
    h = conf().get("horario", ["08:00", "18:30"])
    from nucleo import es_habil
    return es_habil(ahora.date()) and h[0] <= ahora.strftime("%H:%M") <= h[1]


def vigilar(con):
    """Para el tick: mensajes que piden algo y nadie respondió; cierra conversaciones inactivas."""
    out = []
    ahora = datetime.now()
    if conf().get("activa", True) and _en_horario(ahora):
        limite = (ahora - timedelta(minutes=int(conf().get("avisar_min", 20)))).strftime("%Y-%m-%d %H:%M:%S")
        desde = (ahora - timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
        for m in con.execute("SELECT * FROM chat WHERE direccion='entra' AND requiere=1 AND respondido IS NULL "
                             "AND alertado=0 AND cuando<=? AND cuando>=? ORDER BY id", (limite, desde)).fetchall():
            minutos = int((ahora - datetime.strptime(m["cuando"], "%Y-%m-%d %H:%M:%S")).total_seconds() // 60)
            extra = ""
            if m["borrador_id"]:
                b = con.execute("SELECT estado FROM borradores WHERE id=?", (m["borrador_id"],)).fetchone()
                if b and b["estado"] == "pendiente":
                    extra = f" Tienes su caso #{m['borrador_id']} esperando tu ok."
            out.append(f"{m['nombre']} escribió hace {minutos} min y nadie le ha respondido: «{m['texto'][:200]}».{extra}")
            con.execute("UPDATE chat SET alertado=1 WHERE id=?", (m["id"],))
    minutos = int(conf().get("cerrar_min", 90))
    viejo = (ahora - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")
    for s in con.execute("SELECT * FROM sesiones WHERE estado='abierta' AND ultimo<?", (viejo,)).fetchall():
        sin = con.execute("SELECT COUNT(*) FROM chat WHERE sesion_id=? AND direccion='entra' AND requiere=1 AND "
                          "respondido IS NULL", (s["id"],)).fetchone()[0]
        _cerrar(con, s, "quedó algo sin responder" if sin else "inactividad")
    con.commit()
    return out


# ---------------------------------------------------------------- para la planilla
def personas_vistas(con):
    return con.execute("SELECT numero, MAX(nombre) AS nombre, MAX(rol) AS rol, MAX(sup) AS sup, COUNT(*) AS n "
                       "FROM chat WHERE direccion='entra' GROUP BY numero ORDER BY n DESC").fetchall()


def filas_chat(con, numero, limite=600):
    """Conversación con una persona, con separadores de inicio y cierre de cada conversación."""
    filas, sesion_act = [], None
    msgs = con.execute("SELECT * FROM chat WHERE (numero=? AND direccion='entra') OR "
                       "(direccion='sale' AND sesion_id IN (SELECT id FROM sesiones WHERE numero=?)) "
                       "ORDER BY id DESC LIMIT ?", (numero, numero, limite)).fetchall()[::-1]
    sesiones = {s["id"]: s for s in con.execute("SELECT * FROM sesiones WHERE numero=?", (numero,))}
    for m in msgs:
        if m["sesion_id"] != sesion_act:
            if sesion_act in sesiones and sesiones[sesion_act]["estado"] == "cerrada":
                s = sesiones[sesion_act]
                filas.append([s["fin"] or "", "", f"── fin de la conversación #{s['id']} ({s['cierre']}) ──",
                              "", "", ""])
            sesion_act = m["sesion_id"]
            s = sesiones.get(sesion_act)
            if s:
                filas.append([s["inicio"], "", f"── inicio de la conversación #{s['id']} ──", "", "", ""])
        quien = m["nombre"] if m["direccion"] == "entra" else ("Bot" if m["rol"] == "bot" else m["nombre"])
        estado = ""
        if m["direccion"] == "entra" and m["requiere"]:
            estado = "respondido" if m["respondido"] else "SIN RESPUESTA"
        filas.append([m["cuando"], quien, m["texto"], m["intencion"] or "",
                      datos()["E"].get(m["rbd"], {}).get("nombre", "") if m["rbd"] else "", estado])
    if sesion_act in sesiones and sesiones[sesion_act]["estado"] == "cerrada":
        s = sesiones[sesion_act]
        filas.append([s["fin"] or "", "", f"── fin de la conversación #{s['id']} ({s['cierre']}) ──", "", "", ""])
    return filas                            # en orden, del primero al último
