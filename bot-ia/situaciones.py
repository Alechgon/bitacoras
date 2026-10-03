"""
situaciones.py — reglas de acción sacadas de cómo escriben de verdad en el grupo (chat de ago–sep 2026).

Antes de pasarle un mensaje a la IA, el bot revisa si es una de estas situaciones y actúa como lo haría Manuel:

  horario      "cierra a las 4 hoy", "se puede entrar a las 14:00", "con extensión hasta las 5:30",
               "solo autorizaron de 7:30 a 9"         -> anota la ventana de acceso y avisa si choca con la agenda
  reclamo      "no llegaron a limpiar la cámara", "vino el gasfiter y se fue sin avisar",
               "no lo dejó funcionando"                -> disculpa corta, te alerta y deja el caso con prioridad
  insistencia  "recordar lo del Haití", "no se ha arreglado el calefont", "¿qué pasó con el gasfiter?",
               "por favooor"                           -> responde el estado real (agendado / sin hora) y sube prioridad
  supervision  "mañana recibe supervisión", "será objeto de auditoría", "hoy va Junaeb"
                                                       -> prioriza lo pendiente de ese colegio y te avisa
  pregunta     preguntas frecuentes de respuestas.json (técnicos, horarios, cómo pedir visita, qué nos corresponde…)

Lo que no calza con ninguna sigue el camino normal (caso, pregunta, observación).
"""
import json, os, re
from datetime import datetime, timedelta

import lenguaje
from nucleo import (BASE, agenda, bloques, bonita, buscar, cfg, datos, en_texto, hora_bloque, hoy, log, nombre_tec,
                    norm, sumar_habiles)

RUTA_FAQ = os.path.join(BASE, "respuestas.json")


def conf():
    return cfg().get("situaciones", {})


def _n(autor):
    return (autor or "").split()[0]


def _nom(rbd):
    from conversacion import nom
    return nom(rbd)


def _colegios(texto):
    hits = en_texto(texto)
    if hits:
        return hits
    top = buscar(texto)
    return [top[0][1]] if top and top[0][0] >= 85 else []


# ---------------------------------------------------------------- horas
def _hora(h, m=None, tarde_si_menor=8):
    h = int(h)
    m = int(m) if m else 0
    if h < tarde_si_menor:          # "cierra a las 4" = 16:00
        h += 12
    return f"{h:02d}:{m:02d}"


H = r"(\d{1,2})(?:h(\d{2}))?\s*(?:hrs?|horas)?"


def _ventana(texto):
    """Devuelve (desde, hasta, etiqueta) o None."""
    t = norm(re.sub(r"(\d{1,2})[:.](\d{2})", r"\1h\2", texto))      # "5:30" -> "5h30" (norm borra los dos puntos)
    m = re.search(rf"\b(?:desde|de)\s+(?:las\s+)?{H}\s*(?:hasta|a)\s+(?:las\s+)?{H}", t)
    if m:
        return _hora(m.group(1), m.group(2), 6), _hora(m.group(3), m.group(4)), "horario autorizado"
    m = re.search(rf"\b(cierra|cierran|cerramos|cierre|se van|salen)\s+(?:hoy\s+)?(?:a\s+las|a la)\s+{H}", t)
    if m:
        return None, _hora(m.group(2), m.group(3)), "cierra temprano"
    m = re.search(rf"\b(extension|horario extendido)\b.*?\bhasta\s+las\s+{H}", t)
    if m:
        return None, _hora(m.group(2), m.group(3)), "con extensión horaria"
    m = re.search(rf"\b(se puede entrar|pueden entrar|pueden venir|pueden ir|abren|abre|reciben)\s+(?:desde\s+)?"
                  rf"(?:a\s+)?(?:las\s+)?{H}", t)
    if m:
        return _hora(m.group(2), m.group(3), 6), None, "se puede entrar desde"
    m = re.search(rf"\b(?:esta\s+)?abierto\s+(?:de|desde)\s+(?:las\s+)?{H}\s*(?:a|hasta)\s+(?:las\s+)?{H}", t)
    if m:
        return _hora(m.group(1), m.group(2), 6), _hora(m.group(3), m.group(4)), "horario del colegio"
    return None


def ventanas_de(con, rbd, d):
    """Restricciones de horario vigentes para ese colegio ese día (las del día + las permanentes)."""
    return con.execute("SELECT * FROM ventanas WHERE rbd=? AND (fecha IS NULL OR fecha=?) ORDER BY id DESC",
                       (rbd, d.isoformat())).fetchall()


def choca(con, t):
    """¿La visita t cae fuera del horario que dijeron? Devuelve el texto del aviso o ''."""
    from nucleo import inicio_bloque
    d = datetime.strptime(t["fecha"], "%Y-%m-%d").date()
    i0 = inicio_bloque(d, t["bloque"])
    ini = i0.strftime("%H:%M")
    fin = (datetime.combine(d, i0) + timedelta(hours=2)).strftime("%H:%M")
    for v in ventanas_de(con, t["rbd"], d):
        if v["hasta"] and ini >= v["hasta"]:
            return f"cierra a las {v['hasta']} y la visita ({hora_bloque(d, t['bloque'])}) parte cerca de las {ini}"
        if v["hasta"] and fin > v["hasta"] and not v["desde"]:
            return f"cierra a las {v['hasta']} y la visita ({hora_bloque(d, t['bloque'])}) termina cerca de las {fin}"
        if v["desde"] and ini < v["desde"]:
            return f"se puede entrar desde las {v['desde']} y la visita ({hora_bloque(d, t['bloque'])}) parte cerca de las {ini}"
    return ""


# ---------------------------------------------------------------- reconocer
RECLAMO = (r"\b(no (llegaron|llego|vinieron|vino|han llegado|ha llegado|aparecieron|aparecio|hicieron|arreglaron|lo dejo "
           r"funcionando|dejo funcionando)|se fue sin avisar|se fue y|quedo igual|sigue igual|nunca llego|nunca vino|"
           r"no quedo funcionando|dejaron (todo )?(malo|igual|sucio))\b")
INSISTE = (r"\b(recordar|recuerde|recuerda|recordatorio|le recuerdo|les recuerdo|no se ha arreglado|aun no|todavia no|"
           r"sigue sin|siguen sin|que paso con|que pasara con|para cuando|hace rato|hace tiempo|"
           r"hace (\d+|un|una|dos|tres) (dias|semanas|meses)|nunca ha tenido|cuando vienen|cuando van a venir|"
           r"siguen esperando|seguimos esperando)\b")
RUEGO = r"^(por favo+r+|porfa+|porfis|plis+)\b"            # "por favooor" a secas, o con el colegio
SUPERVISION = (r"\b(auditoria|supervision|supervisan|fiscalizacion|fiscalizan|inspeccion|seremi|va junaeb|viene junaeb|"
               r"visita de junaeb|visita de la institucion|recibira supervision|recibe supervision)\b")


def detectar(texto):
    """('horario'|'reclamo'|'insistencia'|'supervision'|'faq', datos) o (None, None)."""
    if not conf().get("activa", True):
        return None, None
    t = norm(texto)
    v = _ventana(texto)
    if v and (_colegios(texto) or re.search(r"\b(jardin|colegio|escuela|liceo|ese colegio|todos)\b", t)):
        return "horario", v
    if re.search(SUPERVISION, t):
        return "supervision", None
    if re.search(RECLAMO, t):
        return "reclamo", None
    if (re.search(INSISTE, t) or (re.search(RUEGO, t) and len(t.split()) <= 6)) and _colegios(texto):
        return "insistencia", None
    f = faq(texto)
    if f:
        return "faq", f
    return None, None


# ---------------------------------------------------------------- actuar
def _estado_colegio(con, rbd):
    """Lo que hay abierto y lo que viene para ese colegio, en palabras."""
    from conversacion import _dia, _entre
    abiertos = con.execute("SELECT h.*, t.fecha AS f, t.tec, t.bloque FROM hallazgos h LEFT JOIN tarjetas t "
                           "ON t.id=h.tarjeta_id AND t.estado='programada' WHERE h.rbd=? AND "
                           "h.estado IN ('registrado','agendado') ORDER BY h.id DESC", (rbd,)).fetchall()
    prox = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>=? ORDER BY fecha, bloque "
                       "LIMIT 1", (rbd, hoy().isoformat())).fetchone()
    partes = []
    if prox:
        d = datetime.strptime(prox["fecha"], "%Y-%m-%d").date()
        partes.append(f"{nombre_tec(prox['tec'])} va {_dia(d)} {_entre(d, prox['bloque'])}")
    sin_hora = [h for h in abiertos if h["estado"] == "registrado"]
    if sin_hora:
        partes.append("tengo registrado " + "; ".join(h["problema"][:60] for h in sin_hora[:2]) + " todavía sin hora")
    return partes, abiertos, prox


def actuar(con, tipo, datos_, texto, autor, origen="grupo"):
    out = {"grupo": [], "admin": [], "borradores": []}
    n = _n(autor)
    rbds = _colegios(texto)
    E = datos()["E"]
    directo = conf().get("directo", True)
    destino = "grupo" if origen == "grupo" else "admin"

    if tipo == "horario":
        desde, hasta, etiqueta = datos_
        d = lenguaje.fecha_de(texto) if re.search(r"\b(hoy|manana|lunes|martes|miercoles|jueves|viernes|\d{1,2}[/-]\d)",
                                                    norm(texto)) else None
        if not rbds:
            return None
        for r in rbds:
            con.execute("INSERT INTO ventanas(autor,rbd,fecha,desde,hasta,texto) VALUES(?,?,?,?,?,?)",
                        (autor, r, d.isoformat() if d else None, desde, hasta, texto[:300]))
        log(con, f"Horario de {autor}: {', '.join(str(r) for r in rbds)} {etiqueta} {desde or ''}-{hasta or ''}")
        cuando = (f"{'hoy' if d == hoy() else bonita(d)}" if d else "desde ahora")
        rango = (f"de {desde} a {hasta}" if desde and hasta else f"hasta las {hasta}" if hasta else f"desde las {desde}")
        nombres = ", ".join(_nom(r) for r in rbds)
        out[destino].append(f"Anotado, {n}: {nombres} {rango} ({cuando}). Lo tengo en cuenta para las visitas.")
        # ¿choca con algo ya agendado?
        choques = []
        for r in rbds:
            q = "SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>=?" + (" AND fecha=?" if d else "")
            for t in con.execute(q, (r, hoy().isoformat(), *( [d.isoformat()] if d else []))).fetchall():
                c = choca(con, t)
                if c:
                    choques.append(f"{_nom(r)} el {bonita(t['fecha'])} con {nombre_tec(t['tec'])}: {c}")
        if choques:
            out["admin"].append("Ojo con el horario que avisó " + autor + ":\n- " + "\n- ".join(choques) +
                                "\nPara moverla: *!mover RBD dd-mm bloque* o dile al bot por privado.")
        elif origen == "grupo":
            out["admin"].append(f"Horario anotado ({autor}): {nombres} {rango} ({cuando}).")
        con.commit()
        return out

    if tipo == "reclamo":
        nombres = ", ".join(_nom(r) for r in rbds) if rbds else "eso"
        out[destino].append(f"Disculpa, {n}. Le aviso altiro a Manuel para reprogramar lo del {nombres}." if rbds else
                            f"Disculpa, {n}. ¿De qué colegio es? Le aviso altiro a Manuel.")
        for r in rbds:
            hid = con.execute("INSERT INTO hallazgos(recibido,autor,texto,rbd,problema,crit,prio,estado,motor) "
                              "VALUES(?,?,?,?,?,?,1,'registrado','regla')",
                              (datetime.now().strftime("%Y-%m-%d %H:%M"), autor, texto, r,
                               f"Reclamo: {texto[:100]}", _crit(texto))).lastrowid
            con.execute("UPDATE hallazgos SET prio=1 WHERE rbd=? AND estado IN ('registrado','agendado')", (r,))
            ult = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND fecha<=? ORDER BY fecha DESC LIMIT 1",
                              (r, hoy().isoformat())).fetchone()
            extra = (f" Última visita en agenda: {bonita(ult['fecha'])} con {nombre_tec(ult['tec'])} "
                     f"({ult['estado']}).") if ult else ""
            log(con, f"Reclamo de {autor} sobre {E.get(r, {}).get('nombre', r)} (hallazgo {hid})")
            out["admin"].append(f"⚠️ Reclamo de {autor} sobre {_nom(r)}: «{texto[:300]}».{extra}\n"
                                f"Quedó con prioridad y sin hora: lo ves en *!plan* o escribe *caso … camilo mañana b1*.")
        if not rbds:
            out["admin"].append(f"⚠️ Reclamo de {autor} (no reconocí el colegio): «{texto[:300]}»")
        con.commit()
        return out

    if tipo == "insistencia":
        r = rbds[0]
        partes, abiertos, prox = _estado_colegio(con, r)
        if not abiertos and not prox:
            return None                   # no hay nada abierto: probablemente es un caso nuevo, flujo normal
        crit = _crit(texto)
        if crit != "OTRO" and not any(h["crit"] == crit for h in abiertos):
            return None                   # "nuevamente la cocina inundada": es una falla nueva, flujo normal
        con.execute("UPDATE hallazgos SET prio=1, insistencias=COALESCE(insistencias,0)+1 WHERE rbd=? AND "
                    "estado IN ('registrado','agendado')", (r,))
        veces = con.execute("SELECT MAX(COALESCE(insistencias,0)) FROM hallazgos WHERE rbd=?", (r,)).fetchone()[0] or 1
        txt = f"{n}, lo del {_nom(r)}: " + (", y ".join(partes) if partes else "lo tengo anotado") + "."
        if any(h["estado"] == "registrado" for h in abiertos):
            txt += " Se lo paso a Manuel para darle prioridad."
        out[destino].append(txt)
        out["admin"].append(f"{'⚠️ ' if veces >= 2 else ''}Insisten por {_nom(r)} ({autor}, vez {veces}): «{texto[:200]}»\n"
                            f"Le respondí: «{txt}»")
        log(con, f"Insistencia {veces} de {autor} por {r}")
        con.commit()
        return out

    if tipo == "supervision":
        d = lenguaje.fecha_de(texto)
        if not rbds:
            return None
        for r in rbds:
            con.execute("UPDATE hallazgos SET prio=1 WHERE rbd=? AND estado IN ('registrado','agendado')", (r,))
            partes, abiertos, prox = _estado_colegio(con, r)
            cuando = f" el {bonita(d)}" if d and d != hoy() else (" hoy" if d == hoy() else "")
            pend = [h for h in abiertos]
            out["admin"].append(f"⚠️ {_nom(r)} tiene supervisión/auditoría{cuando} (avisó {autor}). "
                                f"Pendientes: {len(pend)}" + (": " + "; ".join(h['problema'][:50] for h in pend[:3]) if pend else "") +
                                (f". Próxima visita: {bonita(prox['fecha'])}." if prox else ". No tiene visita agendada."))
        log(con, f"Supervisión avisada por {autor}: {rbds}")
        con.commit()
        if _crit(texto) != "OTRO":                  # "hoy va Junaeb, hay dos sifones malos": además es un caso
            out["_seguir"] = True
            return out
        out[destino].append(f"Gracias, {n}. Lo dejo priorizado para que quede todo en orden antes de la supervisión.")
        return out

    if tipo == "faq":
        f = datos_
        txt = _rellenar(con, f, texto, autor)
        if not txt:
            return None
        if f.get("aprobar") and cfg().get("modo_borrador", True) and origen == "grupo":
            bid = con.execute("INSERT INTO borradores(origen,autor,texto_original,respuesta,estado,tipo) "
                              "VALUES('grupo',?,?,?,'pendiente','pregunta')", (autor, texto, txt)).lastrowid
            con.commit()
            import servidor as S
            out["borradores"].append(bid)
            out["admin"].append(S._texto_borrador(con, bid))
        else:
            out[destino].append(txt)
            if origen == "grupo" and conf().get("copiar_faq", False):
                out["admin"].append(f"Respondí a {autor}: «{txt[:200]}»")
        return out
    return None


def _crit(texto):
    import ia
    return ia.tipo_por_palabras(texto)


# ---------------------------------------------------------------- preguntas frecuentes
def faqs():
    try:
        with open(RUTA_FAQ, encoding="utf-8") as f:
            return json.load(f).get("preguntas", [])
    except Exception:
        return []


def faq(texto):
    t = norm(texto)
    for f in faqs():
        if any(re.search(p, t) for p in f.get("patrones", [])):
            return f
    return None


def _rellenar(con, f, texto, autor):
    """Completa la respuesta con datos vivos: técnicos, jornada, agenda de hoy, próxima visita…"""
    from conversacion import _dia, _entre
    D = datos()
    M = D["META"]
    tecs = M["tecnicos"]
    gas = cfg().get("preferencia_tecnico", {}).get("GAS", "CAMILO")
    v = {
        "nombre": _n(autor),
        "tecnicos": " y ".join(f"{i['nombre']} ({i.get('cred', '')})".replace(" ()", "") for i in tecs.values()),
        "tec_gas": tecs.get(gas, {}).get("nombre", gas),
        "jornada_lj": M.get("jornadaLJ", "08:30 a 17:30"),
        "jornada_v": M.get("jornadaV", "08:15 a 13:00"),
        "bloques": ", ".join(f"{v_}" for v_ in M.get("bloquesLJ", {}).values()),
        "hora_aviso": cfg().get("aviso_previo", {}).get("hora", "16:30"),
    }
    din = f.get("dinamica")
    if din == "agenda_hoy":
        d = hoy()
        filas = agenda(con, d, d)
        if not filas:
            return f"{v['nombre']}, hoy no hay visitas programadas."
        mias = _colegios_de(autor)
        filas = [t for t in filas if not mias or t["rbd"] in mias] or filas
        return f"{v['nombre']}, hoy vamos a: " + "; ".join(
            f"{_nom(t['rbd'])} ({nombre_tec(t['tec'])}, {hora_bloque(t['fecha'], t['bloque'])})"
            for t in filas) + "."
    if din == "proxima_visita":
        rbds = _colegios(texto)
        if not rbds:
            return None
        t = con.execute("SELECT * FROM tarjetas WHERE rbd=? AND estado='programada' AND fecha>=? ORDER BY fecha, bloque "
                        "LIMIT 1", (rbds[0], hoy().isoformat())).fetchone()
        if not t:
            return f"{v['nombre']}, el {_nom(rbds[0])} todavía no tiene visita agendada. Se lo paso a Manuel."
        d = datetime.strptime(t["fecha"], "%Y-%m-%d").date()
        return f"{v['nombre']}, al {_nom(rbds[0])} va {nombre_tec(t['tec'])} {_dia(d)} {_entre(d, t['bloque'])}."
    try:
        return f["respuesta"].format(**v)
    except (KeyError, IndexError):
        return f["respuesta"]


def _colegios_de(autor):
    """Colegios de la supervisora que escribe (por su primer nombre)."""
    a = norm(autor).split()
    if not a:
        return set()
    alias = {"annahi": "anahi"}
    p = alias.get(a[0], a[0])
    return {e["rbd"] for e in datos()["ESTAB"] if norm(e.get("sup", "")).split()[:1] == [p]}


# ---------------------------------------------------------------- aviso del día siguiente
def aviso_manana(con):
    """Texto para el grupo: a qué colegios vamos el próximo día hábil, por supervisora (para avisar a las PAE)."""
    from conversacion import _entre
    d = sumar_habiles(hoy(), 1)
    filas = agenda(con, d, d)
    if not filas:
        return None, []
    E = datos()["E"]
    por_sup = {}
    for t in filas:
        por_sup.setdefault(E.get(t["rbd"], {}).get("sup", "Otros"), []).append(t)
    from conversacion import _dia
    lin = [f"Buenas tardes. {_dia(d).capitalize()} vamos a:"]
    for sup, ts in sorted(por_sup.items()):
        lin.append(f"\n{sup.split()[0]}:")
        for t in ts:
            lin.append(f"- {_nom(t['rbd'])}, {hora_bloque(d, t['bloque'])} ({nombre_tec(t['tec'])})")
    lin.append("\nSi algún colegio tiene restricción de horario o necesita autorización, avísenme por acá.")
    choques = [f"{_nom(t['rbd'])}: {choca(con, t)}" for t in filas if choca(con, t)]
    return "\n".join(lin), choques


def texto_reglas():
    return ("📋 *Reglas de acción en el grupo*\n"
            "• Horario («cierra a las 4», «se puede entrar a las 14:00») → lo anoto y te aviso si choca con la agenda\n"
            "• Reclamo («no llegaron», «se fue sin avisar») → disculpa, te alerto y queda con prioridad\n"
            "• Insistencia («recordar…», «¿qué pasó con…?») → respondo el estado real y subo prioridad\n"
            "• Supervisión/auditoría → priorizo lo pendiente de ese colegio y te aviso\n"
            f"• Preguntas frecuentes: {len(faqs())} respuestas en respuestas.json (*!faq* para verlas)\n"
            f"• Aviso del día siguiente al grupo a las {cfg().get('aviso_previo', {}).get('hora', '16:30')}")


def texto_faq():
    return "❓ *Preguntas frecuentes que respondo*\n" + "\n".join(
        f"• {f.get('titulo', f.get('id'))}" + (" (pasa por ti)" if f.get("aprobar") else "") for f in faqs()) + \
        "\n\nSe editan en bot-ia/respuestas.json."
