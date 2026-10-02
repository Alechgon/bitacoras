"""
planificador.py — el plan del día que armas TÚ.

1. A las 07:15 (o con !plan) te llega:
     · hoy y mañana de cada técnico, bloque por bloque
     · los casos registrados que todavía no tienen hora, numerados
2. Respondes como hablas:  "1 hoy camilo b3, 2 mañana, 3 lunes, 4 no, 5 espera"
     1 hoy camilo b3 -> Camilo, hoy, bloque 3 (si estaba ocupado, lo que había se posterga)
     2 mañana        -> mañana, el técnico y bloque los elige el bot
     4 no            -> se descarta ·  5 espera -> queda sin hora
     "solo esos"     -> los que no nombraste NO se agendan solos
3. Te muestra la VISTA PREVIA (se simula en una copia de la base, nada cambia todavía).
4. "ok plan" -> se aplica, se avisa al grupo (con la supervisora) y a cada técnico.
"""
import json, re, sqlite3
from datetime import datetime, timedelta

import lenguaje
from nucleo import (DB_PATH, a_fecha, agendar, agenda, bloques, bonita, cfg, colocar_forzado, datos, db, es_prioridad,
                    hora_bloque, hoy, log, nombre_tec, norm, sig_habil, sumar_habiles)

EMOJI = {"GAS": "🔥", "FRIO": "❄️", "AGUA": "💧", "ELEC": "⚡", "EQUIPO": "🍳", "OTRO": "🔧"}
PALABRAS_ITEM = r"(hoy|manana|pasado|lunes|martes|miercoles|jueves|viernes|lun|mar|mie|jue|vie|b[1-4]|bloque|" \
                r"no|descartar|espera|esperar|despues|camilo|rodrigo|temprano|tarde|\d{1,2}[/-]\d{1,2})"


# ---------------------------------------------------------------- sesión (qué número es qué caso)
def _meta_get(con, k):
    f = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return json.loads(f["v"]) if f and f["v"] else None


def _meta_set(con, k, v):
    con.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False, default=str)))


def sesion_activa(con):
    s = _meta_get(con, "plan_sesion")
    if not s:
        return None
    horas = int(cfg().get("plan", {}).get("vigencia_horas", 12))
    if datetime.now() - datetime.fromisoformat(s["creado"]) > timedelta(hours=horas):
        return None
    return s


def parece_plan(con, texto):
    """¿El mensaje es una respuesta al plan? ('1 hoy camilo b3, 2 mañana' / 'ok plan')"""
    t = norm(texto)
    if re.fullmatch(r"(ok|dale|si|listo|confirmo|aplica|aplicar)\s+(el\s+)?plan", t) or t in ("cancelar plan", "no plan"):
        return True
    if not sesion_activa(con) or re.search(r"\bcaso\b", t):
        return False
    return bool(re.search(rf"(^|[,;\n]|\by\b)\s*\d{{1,2}}\s+(a\s+|para\s+|el\s+)?{PALABRAS_ITEM}\b", t))


# ---------------------------------------------------------------- vista
def _sin_hora(con):
    return con.execute("SELECT * FROM hallazgos WHERE estado='registrado' AND rbd IS NOT NULL ORDER BY "
                       "CASE crit WHEN 'GAS' THEN 0 WHEN 'FRIO' THEN 1 WHEN 'AGUA' THEN 2 WHEN 'ELEC' THEN 3 "
                       "WHEN 'EQUIPO' THEN 4 ELSE 5 END, prio DESC, id").fetchall()


def _dia_tec(con, d, tec):
    E = datos()["E"]
    filas = {t["bloque"]: t for t in agenda(con, d, d, tec)}
    out = []
    for b in sorted(set(bloques(d)) | set(filas)):
        t = filas.get(b)
        etiqueta = f"B{b}" if b <= 3 else "EXTRA"
        if not t:
            out.append(f"   {etiqueta} · libre")
            continue
        e = E.get(t["rbd"], {})
        icono = "🚨" if "CORRECTIVO" in t["clase"] else ("🛠️" if "PREV" in t["clase"] else "📋")
        crit = f" {EMOJI.get(t['crit'], '')}" if "CORRECTIVO" in t["clase"] and t["crit"] else ""
        out.append(f"   {etiqueta} {icono} {e.get('nombre', t['rbd'])} ({t['pts']}){crit}")
    return out


def vista(con, desde=None):
    """Texto del plan: hoy/mañana por técnico + casos sin hora numerados. Guarda la sesión."""
    D = datos()
    E = D["E"]
    d1 = sig_habil(a_fecha(desde) or hoy())
    d2 = sumar_habiles(d1, 1)
    lin = [f"🗓️ *Plan del día* · {bonita(d1)} y {bonita(d2)}"]
    for d in (d1, d2):
        lin.append(f"\n*{bonita(d).upper()}*")
        for tec in D["META"]["tecnicos"]:
            lin.append(f"👷 {nombre_tec(tec)}")
            lin += _dia_tec(con, d, tec)
    casos = _sin_hora(con)
    ids = []
    if casos:
        lin.append("\n📋 *Casos sin hora* (registrados, esperando agenda)")
        for n, h in enumerate(casos, 1):
            e = E.get(h["rbd"], {})
            edad = ""
            try:
                horas = (datetime.now() - datetime.strptime(h["recibido"], "%Y-%m-%d %H:%M")).total_seconds() / 3600
                edad = f"hace {int(horas)} h" if horas < 48 else f"hace {int(horas // 24)} días"
            except Exception:
                pass
            from nucleo import puntaje
            pts, _ = puntaje(e, h["crit"] or "OTRO", h["prio"])
            plazo = min(10, cfg().get("plazo_habiles", {}).get(h["crit"] or "OTRO", 10))
            lin.append(f"{n}. {EMOJI.get(h['crit'], '🔧')} *{e.get('nombre', h['rbd'])}* · {h['problema'][:60]} "
                       f"· {pts} pts · plazo {plazo} días · {h['autor'].split()[0] if h['autor'] else ''} {edad}".rstrip())
            ids.append(h["id"])
        lin.append("\nResponde, por ejemplo:\n*1 hoy camilo b3, 2 mañana, 3 lunes, 4 no, 5 espera*\n"
                   "(lo que no nombres lo agendo yo después de lo tuyo; si no quieres, agrega *solo esos*)")
    else:
        lin.append("\n✅ No hay casos sin hora.")
    _meta_set(con, "plan_sesion", {"creado": datetime.now().isoformat(), "ids": ids, "d1": d1.isoformat()})
    con.commit()
    return "\n".join(lin)


# ---------------------------------------------------------------- entender tu respuesta
def interpretar(texto, ids):
    """'1 hoy camilo b3, 2 mañana, 3 lunes' -> [{n, hid, accion, fecha, tec, bloque}], solo_esos, errores"""
    t = texto.replace("\n", ",").replace(";", ",")
    t = re.sub(r"\s+y\s+(?=\d)", ",", t)
    solo = bool(re.search(r"\bsolo (esos|esas|eso|estos)\b", norm(texto)))
    items, errores = [], []
    for parte in [p.strip() for p in t.split(",") if p.strip()]:
        m = re.match(r"^(?:#|n[°º]?\s*)?(\d{1,2})\b(.*)$", parte.strip())
        if not m:
            continue
        n, resto = int(m.group(1)), m.group(2)
        if not (1 <= n <= len(ids)):
            errores.append(f"no hay caso {n} en la lista")
            continue
        r = norm(resto)
        if re.search(r"\b(no|descartar|descarta|borrar|anular)\b", r) and not lenguaje.fecha_de(resto):
            items.append({"n": n, "hid": ids[n - 1], "accion": "descartar"})
            continue
        if re.search(r"\b(espera|esperar|despues|luego|pendiente)\b", r) and not lenguaje.fecha_de(resto):
            items.append({"n": n, "hid": ids[n - 1], "accion": "esperar"})
            continue
        items.append({"n": n, "hid": ids[n - 1], "accion": "colocar", "fecha": lenguaje.fecha_de(resto),
                      "tec": lenguaje.tec_de(resto), "bloque": lenguaje.bloque_de(resto)})
    return items, solo, errores


# ---------------------------------------------------------------- aplicar (en copia o de verdad)
def _ejecutar(con, items, solo):
    """Aplica las órdenes sobre con. Devuelve resumen [(n, hallazgo, res|accion)] y los agendados solos."""
    from servidor import texto_respuesta        # import tardío (servidor importa este módulo)
    E = datos()["E"]
    hechos, ultimo = [], hoy()
    mencionados = set()
    for it in items:
        h = con.execute("SELECT * FROM hallazgos WHERE id=?", (it["hid"],)).fetchone()
        mencionados.add(it["hid"])
        if not h or h["estado"] != "registrado":
            hechos.append((it["n"], h, "ya no estaba pendiente"))
            continue
        if it["accion"] == "descartar":
            con.execute("UPDATE hallazgos SET estado='descartado' WHERE id=?", (h["id"],))
            hechos.append((it["n"], h, "descartado"))
            continue
        if it["accion"] == "esperar":
            hechos.append((it["n"], h, "sigue sin hora"))
            continue
        d = it.get("fecha") or hoy()
        res = colocar_forzado(con, h["rbd"], h["crit"], h["problema"], bool(h["prio"]), h["autor"], h["id"],
                              tec=it.get("tec"), d=d, b=it.get("bloque"))
        resp = texto_respuesta(E[h["rbd"]], h["problema"], h["crit"], res)
        con.execute("UPDATE hallazgos SET estado='agendado', pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                    (res["pts"], res["tarjeta"], resp, h["id"]))
        ultimo = max(ultimo, res["fecha"])
        hechos.append((it["n"], h, res))
    solos = []
    if not solo and cfg().get("plan", {}).get("agendar_resto", True):
        for h in _sin_hora(con):
            if h["id"] in mencionados:
                continue
            res = agendar(con, h["rbd"], h["crit"], h["problema"], bool(h["prio"]), h["autor"], h["id"],
                          desde=ultimo if ultimo > hoy() else None)
            resp = texto_respuesta(E[h["rbd"]], h["problema"], h["crit"], res)
            con.execute("UPDATE hallazgos SET estado='agendado', pts=?, tarjeta_id=?, respuesta=? WHERE id=?",
                        (res["pts"], res["tarjeta"], resp, h["id"]))
            solos.append((h, res))
    return hechos, solos


def _foto_agenda(con):
    return {t["id"]: dict(t) for t in con.execute("SELECT * FROM tarjetas WHERE estado='programada'")}


def _cambios(antes, despues):
    """Tarjetas que ya existían y cambiaron de día/bloque/técnico (las 'postergadas')."""
    out = []
    for tid, a in antes.items():
        b = despues.get(tid)
        if b and (a["fecha"], a["bloque"], a["tec"]) != (b["fecha"], b["bloque"], b["tec"]):
            out.append((a, b))
    return out


def _resumen(hechos, solos, cambios, previa=True):
    E = datos()["E"]
    lin = ["👀 *Vista previa del plan* (todavía no cambia nada)" if previa else "✅ *Plan aplicado*"]
    for n, h, r in hechos:
        nom = E.get(h["rbd"], {}).get("nombre", "?") if h else "?"
        if isinstance(r, dict):
            extra = " ⚠️ fuera de los bloques del día (va como extra)" if r["bloque"] not in bloques(r["fecha"]) else ""
            lin.append(f"{n}. {nom} → {nombre_tec(r['tec'])} *{bonita(r['fecha'])}* B{r['bloque']}{extra}")
        else:
            lin.append(f"{n}. {nom} → {r}")
    if solos:
        lin.append("\n🤖 *Los demás los agendé yo, después de lo tuyo:*")
        for h, r in solos:
            lin.append(f"• {E.get(h['rbd'], {}).get('nombre', '?')} → {nombre_tec(r['tec'])} {bonita(r['fecha'])} "
                       f"B{r['bloque']}")
    propios = {r["tarjeta"] for _, _, r in hechos if isinstance(r, dict)} | {r["tarjeta"] for _, r in solos}
    movs = [(a, b) for a, b in cambios if a["id"] not in propios]
    if movs:
        lin.append("\n↪️ *Se postergan:*")
        for a, b in movs:
            e = E.get(a["rbd"], {})
            tec = "" if a["tec"] == b["tec"] else f" ({nombre_tec(a['tec'])}→{nombre_tec(b['tec'])})"
            lin.append(f"• {e.get('nombre', a['rbd'])} ({a['clase'].lower()}): {bonita(a['fecha'])} B{a['bloque']} → "
                       f"*{bonita(b['fecha'])}* B{b['bloque']}{tec} · sup. {e.get('sup', '?').split()[0]}")
    if previa:
        lin.append("\nResponde *ok plan* para aplicarlo, o mándame el plan corregido.")
    return "\n".join(lin)


def responder(texto, autor="Manuel"):
    """Tu mensaje sobre el plan. Devuelve dict de salida para bot.mjs."""
    out = {"admin": [], "envios_grupo": [], "mensajes_tecnicos": []}
    con = db()
    t = norm(texto)
    if t in ("cancelar plan", "no plan"):
        _meta_set(con, "plan_previa", None)
        con.commit()
        out["admin"].append("🗑️ Plan cancelado, no cambié nada.")
        return out
    if re.fullmatch(r"(ok|dale|si|listo|confirmo|aplica|aplicar)\s+(el\s+)?plan", t):
        pv = _meta_get(con, "plan_previa")
        if not pv:
            out["admin"].append("No tengo un plan en vista previa. Escribe *!plan* para partir.")
            return out
        return aplicar(con, pv, autor)
    s = sesion_activa(con)
    if not s:
        out["admin"].append("El plan venció. Escribe *!plan* para verlo de nuevo.")
        return out
    items, solo, errores = interpretar(texto, s["ids"])
    if not items:
        out["admin"].append("No entendí el plan. Ejemplo: *1 hoy camilo b3, 2 mañana, 3 lunes*")
        return out
    # simulación en una copia de la base: nada real cambia
    copia = sqlite3.connect(":memory:")
    con.backup(copia)
    copia.row_factory = sqlite3.Row
    copia.create_function("REGEXP", 2, lambda p, v: 1 if (v and re.search(p, v, re.I)) else 0)
    antes = _foto_agenda(copia)
    hechos, solos = _ejecutar(copia, items, solo)
    texto_prev = _resumen(hechos, solos, _cambios(antes, _foto_agenda(copia)), previa=True)
    copia.close()
    if errores:
        texto_prev += "\n\n⚠️ " + " · ".join(errores)
    _meta_set(con, "plan_previa", {"texto": texto, "creado": datetime.now().isoformat(), "ids": s["ids"]})
    con.commit()
    out["admin"].append(texto_prev)
    return out


def aplicar(con, pv, autor):
    import memoria
    out = {"admin": [], "envios_grupo": [], "mensajes_tecnicos": []}
    E = datos()["E"]
    items, solo, _ = interpretar(pv["texto"], pv["ids"])
    antes = _foto_agenda(con)
    hechos, solos = _ejecutar(con, items, solo)
    cambios = _cambios(antes, _foto_agenda(con))
    c = cfg().get("plan", {})
    # memoria: cada elección tuya queda como decisión
    for n, h, r in hechos:
        if not h:
            continue
        if isinstance(r, dict):
            memoria.registrar(con, origen="plan", supervisora=h["autor"], rbd=h["rbd"], tipo="plan", crit=h["crit"],
                              original=h["texto"], propuesta="", decision="plan", detalle=f"orden: {pv['texto'][:200]}",
                              tec=r["tec"], fecha_visita=r["fecha"], bloque=r["bloque"])
        else:
            memoria.registrar(con, origen="plan", supervisora=h["autor"], rbd=h["rbd"], tipo="plan", crit=h["crit"],
                              original=h["texto"], decision=f"plan:{r}")
    # borradores 'requerimiento' pendientes de esos hallazgos: ya no hacen falta
    tocados = [h["id"] for _, h, r in hechos if h and isinstance(r, dict)] + [h["id"] for h, _ in solos]
    for hid in tocados:
        con.execute("UPDATE borradores SET estado='reemplazado' WHERE hallazgo_id=? AND estado='pendiente'", (hid,))
    for _, h, r in hechos:
        if h and r == "descartado":
            con.execute("UPDATE borradores SET estado='descartado' WHERE hallazgo_id=? AND estado='pendiente'", (h["id"],))
    log(con, f"Plan aplicado por {autor}: {pv['texto'][:120]}")
    _meta_set(con, "plan_previa", None)
    _meta_set(con, "plan_sesion", None)
    con.commit()
    out["admin"].append(_resumen(hechos, solos, cambios, previa=False))

    # ---- grupo: cada caso agendado (citando el mensaje original si se puede) + las postergaciones
    if c.get("publicar_grupo", True):
        for hid in tocados:
            h = con.execute("SELECT * FROM hallazgos WHERE id=?", (hid,)).fetchone()
            orig = con.execute("SELECT id FROM borradores WHERE hallazgo_id=? ORDER BY id LIMIT 1", (hid,)).fetchone()
            bid = con.execute("INSERT INTO borradores(origen,autor,texto_original,respuesta,rbd,crit,hallazgo_id,"
                              "tarjeta_id,estado,tipo) VALUES('plan',?,?,?,?,?,?,?,'enviado','agendar')",
                              (h["autor"], h["texto"], h["respuesta"], h["rbd"], h["crit"], hid, h["tarjeta_id"])).lastrowid
            out["envios_grupo"].append({"borrador_id": bid, "citar_borrador": orig["id"] if orig else None,
                                        "textos": [h["respuesta"]]})
        propios = {con.execute("SELECT tarjeta_id FROM hallazgos WHERE id=?", (x,)).fetchone()[0] for x in tocados}
        movs = [(a, b) for a, b in cambios if a["id"] not in propios]
        if movs:
            lin = ["↪️ *Cambios de agenda*"]
            for a, b in movs:
                e = E.get(a["rbd"], {})
                lin.append(f"• {e.get('nombre', a['rbd'])}: pasa del {bonita(a['fecha'])} al *{bonita(b['fecha'])}* "
                           f"({hora_bloque(b['fecha'], b['bloque'])}, {nombre_tec(b['tec'])}) · {e.get('sup', '')}")
            out["envios_grupo"].append({"borrador_id": None, "textos": ["\n".join(lin)]})
        con.commit()
    # ---- técnicos: su día
    if c.get("avisar_tecnicos", True):
        dias = sorted({r["fecha"] for _, _, r in hechos if isinstance(r, dict)} | {r["fecha"] for _, r in solos} |
                      {a_fecha(b["fecha"]) for _, b in cambios})
        for tec in datos()["META"]["tecnicos"]:
            partes = []
            for d in dias[:3]:
                filas = agenda(con, d, d, tec)
                if filas:
                    partes.append(f"*{bonita(d).upper()}*\n" + "\n".join(
                        f"B{t['bloque'] if t['bloque'] <= 3 else 'X'} {hora_bloque(t['fecha'], t['bloque'])} · "
                        f"{E.get(t['rbd'], {}).get('nombre', t['rbd'])} · {t['clase'].lower()}"
                        + (f" — {t['detalle'].split('||')[-1].strip()[:80]}" if 'CORRECTIVO' in t['clase'] else "")
                        for t in filas))
            if partes:
                out["mensajes_tecnicos"].append({"tec": tec, "texto": f"👷 Hola {nombre_tec(tec)}, así queda tu "
                                                                     f"agenda:\n\n" + "\n\n".join(partes)})
    return out
