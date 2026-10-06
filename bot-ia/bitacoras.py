"""
bitacoras.py — archivo inteligente de bitácoras de Datácora.

Qué hace:
  - Lee el PDF de bitácora (formato Datácora), saca folio, RBD, establecimiento,
    fecha, institución, motivo, técnico y cada fila de cada cuadro con su observación.
  - Lo guarda ordenado en carpetas: archivo/<RBD>_<NOMBRE>/<fecha>_folio<n>.pdf
  - Indexa todo en la base para poder responder preguntas cruzando establecimiento,
    labores y observaciones.

No ejecuta nada de Datácora: solo lee el PDF que le llega por WhatsApp.
"""
import os, re, shutil, unicodedata
from datetime import datetime
from nucleo import BASE, a_fecha, buscar, cfg, datos, db, log, norm


def carpeta_archivo():
    return os.path.join(BASE, cfg().get("archivo_carpeta", "archivo"))
CATEGORIAS = ["Calor", "Electricidad", "Frio", "Frío", "Vectores", "Agua", "Infraestructura"]
UBIC = {"cocina", "bodega", "bano", "baño", "patio", "otro"}


def _slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "_", s).strip("_")[:40]


ACCIONES = r"(Mantenci[oó]n|Reparaci[oó]n|Cambio|Instalaci[oó]n|Retiro|Revisi[oó]n|Limpieza|Reemplazo|Ajuste)"


def leer_pdf(ruta):
    """
    Devuelve dict con cabecera (fecha en ISO aaaa-mm-dd) + lista de items. Lanza ValueError si no es una bitácora.
    Primero con pdfplumber (lee las tablas); si no está instalado o falla, con pypdf + el catálogo de ítems del panel.
    """
    errores = []
    for lector in (_leer_pdfplumber, _leer_pypdf):
        try:
            cab = lector(ruta)
        except ImportError as e:
            errores.append(f"{lector.__name__}: falta {e.name}")
            continue
        except ValueError:
            raise
        except Exception as e:
            errores.append(f"{lector.__name__}: {str(e)[:80]}")
            continue
        if not cab["items"] and lector is _leer_pdfplumber:
            try:                                   # tablas que pdfplumber no separó: el texto plano a veces sí
                alt = _leer_pypdf(ruta)
                if alt["items"]:
                    cab["items"] = alt["items"]
            except Exception:
                pass
        return cab
    raise ValueError("no pude leer el PDF (" + "; ".join(errores) + "). Corre de nuevo bot-ia/instalar.sh")


def _cabecera(texto):
    """Folio, fecha (ISO), hora, RBD, establecimiento, dirección, comuna, técnico y motivo desde el texto del PDF."""
    def buscar1(pat, d=""):
        m = re.search(pat, texto, re.I | re.M)
        return m.group(1).strip() if m else d
    cab = {}
    cab["folio"] = buscar1(r"FOLIO\s*\n?\s*(\d+)") or buscar1(r"FOLIO\s+(\d+)")
    cab["fecha_texto"] = buscar1(r"FECHA:\s*([\d/.-]+)")
    cab["fecha"] = _fecha_cl(cab["fecha_texto"]) or (a_fecha(cab["fecha_texto"]).isoformat()
                                                    if a_fecha(cab["fecha_texto"]) else "")
    cab["hora"] = buscar1(r"HORA:\s*([\d:]+)")
    cab["rbd"] = buscar1(r"RBD:\s*(\d+)")
    cab["establecimiento"] = buscar1(r"ESTABLECIMIENTO:\s*(.+?)\s*$")
    cab["direccion"] = buscar1(r"DIRECCION:\s*(.+?)\s+COMUNA")
    cab["comuna"] = buscar1(r"COMUNA:\s*(.+?)\s*$")
    cab["tecnico"] = buscar1(r"Nombre:\s*(.+?)\s*$").split(" Nombre:")[0].strip()
    cab["motivo"] = _detectar_motivo(texto)
    if not cab["rbd"] and not cab["folio"]:
        raise ValueError("No parece una bitácora de Datácora (sin folio ni RBD).")
    return cab


def _leer_pypdf(ruta):
    """Lector de respaldo: texto plano + catálogo de ítems (CATS de datos.js) para cortar fila por fila."""
    from pypdf import PdfReader
    texto = "\n".join((p.extract_text() or "") for p in PdfReader(ruta).pages)
    cab = _cabecera(texto)
    plano = re.sub(r"\s+", " ", texto)
    cats = datos().get("CATS") or {}
    cabeceras = [(m.start(), m.end(), m.group(1)) for m in
                 re.finditer(r"\b(Calor|Electricidad|Fr[ií]o|Vectores|Agua|Infraestructura)\s+Cocina\s+Bodega\s+"
                             r"Ba[nñ]o\s+Patio\s+Otro\s+Cantidad\s+Acci[oó]n\s+Observaci[oó]n", plano, re.I)]
    items = []
    for k, (ini, fin, nombre_cat) in enumerate(cabeceras):
        hasta = cabeceras[k + 1][0] if k + 1 < len(cabeceras) else len(plano)
        seccion = plano[fin:hasta]
        cat = "Frio" if norm(nombre_cat) == "frio" else nombre_cat.title()
        catalogo = cats.get(cat) or cats.get(nombre_cat) or []
        pos = []
        for it in catalogo:
            pat = r"\s*".join(re.escape(ch) for ch in it.replace(" ", ""))   # el PDF corta los nombres en líneas
            m = re.search(pat, seccion, re.I)
            if m:
                pos.append((m.start(), m.end(), it))
        pos.sort()
        for i, (a, b, it) in enumerate(pos):
            trozo = seccion[b:pos[i + 1][0] if i + 1 < len(pos) else len(seccion)]
            filas = list(re.finditer(rf"(?:(\d+)\s+)?(\d+)\s+{ACCIONES}\b", trozo, re.I))
            nombre_pat = r"\s*".join(re.escape(ch) for ch in it.replace(" ", ""))
            for j, m in enumerate(filas):           # el mismo ítem en cocina y en bodega = dos filas
                obs = trozo[m.end(): filas[j + 1].start() if j + 1 < len(filas) else len(trozo)]
                obs = re.sub(rf"{nombre_pat}\s*$", "", obs.strip(), flags=re.I)
                obs = re.sub(r"(Firma|Nombre:|Encargado|T[eé]cnico).*$", "", obs).strip()
                items.append({"categoria": cat, "item": it, "ubicacion": "", "cantidad": m.group(2),
                              "accion": m.group(3).capitalize(), "observacion": obs[:500]})
    cab["items"] = items
    return cab


def _leer_pdfplumber(ruta):
    import pdfplumber
    cab, items = {}, []
    with pdfplumber.open(ruta) as pdf:
        texto_total = []
        for pag in pdf.pages:
            texto_total.append(pag.extract_text() or "")
            categoria = None
            for tabla in pag.extract_tables():
                for fila in tabla:
                    celdas = [(" ".join((c or "").split())).strip() for c in fila]
                    if not any(celdas):
                        continue
                    primera = celdas[0]
                    # fila de encabezado de un cuadro: "Calor | Cocina | Bodega | ..."
                    if primera in CATEGORIAS and "Cantidad" in celdas:
                        categoria = "Frio" if primera.startswith("Frí") else primera
                        continue
                    if not categoria or not primera:
                        continue
                    # columnas: item, cocina, bodega, bano, patio, otro, cantidad, accion, observacion
                    cols = celdas + [""] * (9 - len(celdas))
                    item, c, b, ba, pa, ot, cant, accion, obs = cols[:9]
                    ubic = next((u for u, v in zip(["Cocina", "Bodega", "Baño", "Patio", "Otro"],
                                                   [c, b, ba, pa, ot]) if v), "")
                    if accion or obs or cant:          # solo filas con trabajo
                        items.append({"categoria": categoria, "item": item, "ubicacion": ubic,
                                      "cantidad": cant, "accion": accion, "observacion": obs})
        texto = "\n".join(texto_total)
    cab = _cabecera(texto)
    cab["items"] = items
    return cab


def _detectar_motivo(texto):
    """El motivo marcado no deja marca de texto; se infiere por el ítem si existe, si no 'desconocido'."""
    # En el PDF el check es visual; devolvemos los motivos posibles para que el usuario confirme.
    for m in ["Plan Preventivo Mantencion", "Emergencia", "Mutualidad", "DT", "Acta", "Seremi", "SEC"]:
        if re.search(re.escape(m), texto, re.I):
            # todos aparecen como etiqueta; no distingue el marcado. Se deja preventivo/emergencia como default.
            pass
    return "por confirmar"


def archivar(ruta_origen, nombre_texto="", fecha_texto=""):
    """
    Guarda el PDF y lo indexa. nombre_texto y fecha_texto vienen del caption del
    WhatsApp ('Silvia Salas, 24/09/2026'); sirven de confirmación, el PDF manda.
    Devuelve dict con resultado y avisos.
    """
    cab = leer_pdf(ruta_origen)
    D = datos()
    rbd = int(cab["rbd"]) if cab["rbd"] and cab["rbd"].isdigit() else None
    avisos = []

    # cruce con el caption
    if nombre_texto and rbd and rbd in D["E"]:
        cands = buscar(nombre_texto)
        if cands and cands[0][1] != rbd and cands[0][0] >= 82:
            avisos.append(f"Escribiste «{nombre_texto}» pero el PDF dice RBD {rbd} "
                          f"({D['E'][rbd]['nombre']}). Archivo según el PDF.")
    nombre = D["E"].get(rbd, {}).get("nombre") or cab["establecimiento"] or f"RBD_{rbd}"
    fecha = a_fecha(cab["fecha"]) or a_fecha(_fecha_cl(fecha_texto)) or datetime.now().date()

    carpeta = os.path.join(carpeta_archivo(), f"{rbd or 'SR'}_{_slug(nombre)}")
    os.makedirs(carpeta, exist_ok=True)
    folio = cab["folio"] or "SF"
    destino = os.path.join(carpeta, f"{fecha.isoformat()}_folio{folio}.pdf")
    shutil.copy(ruta_origen, destino)

    con = db()
    cab["fecha"] = fecha.isoformat()
    cab["folio"] = folio
    indexar_cab(con, cab, destino, nombre)
    log(con, f"Bitácora folio {folio} archivada: {nombre} RBD {rbd}, {len(cab['items'])} ítems")
    con.commit()
    try:                                      # si esa visita estaba en la agenda, queda hecha con la fecha de la bitácora
        import realizados
        realizados.desde_bitacora(con, rbd, fecha, cab.get("tecnico"))
    except Exception as e:
        print("[bitacoras] no pude marcar la visita:", e)
    return {"folio": folio, "rbd": rbd, "nombre": nombre, "fecha": fecha, "n_items": len(cab["items"]),
            "archivo": destino, "tecnico": cab["tecnico"], "avisos": avisos, "items": cab["items"]}


def indexar_cab(con, cab, archivo, nombre=None):
    """Guarda (o actualiza) una bitácora leída y sus ítems en la base. No hace commit: lo hace quien llama."""
    rbd = int(cab["rbd"]) if str(cab.get("rbd") or "").isdigit() else None
    folio = str(cab.get("folio") or "SF")
    nombre = nombre or datos()["E"].get(rbd, {}).get("nombre") or cab.get("establecimiento") or f"RBD_{rbd}"
    fecha = a_fecha(cab.get("fecha")) or a_fecha(_fecha_cl(cab.get("fecha_texto", "")))
    previo = con.execute("SELECT archivo FROM bitacoras WHERE folio=?", (folio,)).fetchone()
    if previo and previo["archivo"] and os.path.exists(previo["archivo"]) and \
            os.sep + "archivo" + os.sep in previo["archivo"] and os.sep + "archivo" + os.sep not in archivo:
        archivo = previo["archivo"]           # la copia ordenada en archivo/ manda sobre la de la carpeta
    con.execute("DELETE FROM bitacora_items WHERE folio=?", (folio,))
    con.execute("INSERT OR REPLACE INTO bitacoras(folio,rbd,establecimiento,fecha,hora,comuna,motivo,tecnico,"
                "archivo,n_items) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (folio, rbd, nombre, fecha.isoformat() if fecha else "", cab.get("hora", ""), cab.get("comuna", ""),
                 cab.get("motivo", ""), cab.get("tecnico", ""), archivo, len(cab.get("items", []))))
    for it in cab.get("items", []):
        con.execute("INSERT INTO bitacora_items(folio,rbd,categoria,item,ubicacion,cantidad,accion,observacion) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (folio, rbd, it.get("categoria"), it.get("item"), it.get("ubicacion"), str(it.get("cantidad") or ""),
                     it.get("accion"), it.get("observacion")))
    return folio


def _fecha_cl(s):
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s or "")
    if not m:
        return None
    d, mes, a = m.groups()
    a = "20" + a if len(a) == 2 else a
    return f"{a}-{int(mes):02d}-{int(d):02d}"


# ---------------------------------------------------------------- consultas
def consultar(pregunta):
    """
    Responde preguntas tipo '¿qué se hizo con el gas en Silvia Salas?'.
    Cruza: establecimiento (difuso) + palabras de la observación/ítem.
    Devuelve texto listo para enviar.
    """
    con = db()
    D = datos()
    t = norm(pregunta)
    # establecimiento mencionado
    rbd = None
    for x in re.findall(r"\b\d{4,6}\b", pregunta):
        if int(x) in D["E"]:
            rbd = int(x)
    if not rbd:
        # buscar nombre dentro de la pregunta
        cands = buscar(pregunta)
        if cands and cands[0][0] >= 70:
            rbd = cands[0][1]
    if not rbd:
        return "¿De qué establecimiento? Dime el nombre o el RBD."

    bits = con.execute("SELECT * FROM bitacoras WHERE rbd=? ORDER BY fecha DESC", (rbd,)).fetchall()
    if not bits:
        nom = D["E"].get(rbd, {}).get("nombre", rbd)
        return f"📭 No tengo bitácoras archivadas de *{nom}* (RBD {rbd})."

    # filtro por tema: palabras clave de la pregunta sobre item/observacion/categoria
    temas = {"gas": "gas|calefont|flexible|regulador|hermeticidad",
             "electr": "electr|enchufe|interruptor|luminaria|foco|tablero|corriente",
             "agua": "agua|griferia|sifon|filtracion|llave|desague|camara",
             "frio": "refriger|congelador|visicooler|frigobar|cadena de frio",
             "campana": "campana|extractor|ducto", "horno": "horno|cocinilla|anafe|marmita|bano maria",
             "sanitario": "bano|wc|lavamanos|lavaplatos|inodoro",
             "infra": "meson|mueble|estanteria|pintura|puerta|ventana|vidrio|malla|extintor|senaletica|basurero"}
    patron = None
    for pat in temas.values():
        if re.search(pat, t):
            patron = pat
            break

    nom = D["E"].get(rbd, {}).get("nombre", rbd)
    out = [f"🏫 *{nom}* · RBD {rbd}"]
    for b in bits[:4]:
        q = "SELECT * FROM bitacora_items WHERE folio=?"
        p = [b["folio"]]
        if patron:
            q += " AND (observacion REGEXP ? OR item REGEXP ? OR categoria REGEXP ?)"
            p += [patron, patron, patron]
        its = con.execute(q, p).fetchall() if not patron else _regex_items(con, b["folio"], patron)
        if patron and not its:
            continue
        out.append(f"\n📄 *Folio {b['folio']}* · {b['fecha']} · {b['tecnico'] or 's/téc'}")
        for it in its[:8]:
            obs = (it["observacion"] or "").replace("\n", " ")
            out.append(f"  • {it['item']} ({it['ubicacion'] or 's/u'}): {it['accion']} — {obs[:90]}")
        out.append(f"  📎 {os.path.basename(b['archivo'])}")
    if len(out) == 1:
        out.append("No encontré ese trabajo en las bitácoras archivadas.")
    return "\n".join(out)


def _regex_items(con, folio, patron):
    pat = re.compile(patron, re.I)
    filas = con.execute("SELECT * FROM bitacora_items WHERE folio=?", (folio,)).fetchall()
    return [f for f in filas if pat.search(f["observacion"] or "") or pat.search(f["item"] or "")
            or pat.search(f["categoria"] or "")]


def historial(rbd):
    con = db()
    bits = con.execute("SELECT * FROM bitacoras WHERE rbd=? ORDER BY fecha DESC", (rbd,)).fetchall()
    if not bits:
        return f"📭 Sin bitácoras archivadas para RBD {rbd}."
    nom = datos()["E"].get(rbd, {}).get("nombre", rbd)
    out = [f"📚 *Historial {nom}* (RBD {rbd})"]
    for b in bits:
        out.append(f"• {b['fecha']} · folio {b['folio']} · {b['motivo']} · {b['n_items']} ítems · {b['tecnico'] or ''}")
    return "\n".join(out)
