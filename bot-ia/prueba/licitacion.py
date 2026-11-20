"""
ASESOR DE LA LICITACIÓN 85-34-LR25 (IA de prueba).

Le preguntas en lenguaje normal ("necesito cambiar un vidrio de la cocina, ¿quién paga?") y:
  1) busca en TODOS los documentos de la licitación (texto por página) y en la guía de mantención,
  2) le pasa a la IA (Qwen en el celular) solo los trozos encontrados,
  3) la IA responde si corresponde a SOSER, al sostenedor o "depende de…", con plazo y qué hacer,
     citando [DOCUMENTO pág. N]; si los documentos no lo dicen, lo dice y pregunta lo que falta.
Siempre se agregan al final las fuentes consultadas (aunque la IA no las cite), para que nada quede sin respaldo.

Fuentes:
  documentos_texto/*.jsonl.gz    Bases (353 pág.), Manual SGC PAE, Manual de productos, Anexo 17 (ya incluidos)
  Descargas/SOSER-prueba/conocimiento/*.md   guía y conocimiento (el 08 es la guía completa)
  Descargas/SOSER-prueba/documentos/        cualquier PDF/TXT que agregues (se lee por página con pdftotext)

Uso:  python licitacion.py "necesito cambiar un vidrio"      |  python licitacion.py --buscar "malla mosquitera"
"""
import glob
import gzip
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
from collections import Counter

AQUI = os.path.dirname(os.path.abspath(__file__))
OLLAMA = "http://127.0.0.1:11434"
MODELO = "qwen2.5:1.5b"

STOP = set("""a al algo ante antes como con contra cual cuales cuando de del desde donde dos el ella ellas ellos en
entre era es esa ese eso esta este esto estos estas fue fueron ha han hasta hay la las le les lo los mas me mi muy
no nos o otra otro para pero por porque que se sea segun ser si sin sobre su sus tambien te tiene tienen todo todos
tu un una uno unos y ya yo debe deben debera deberan cada caso puede pueden sera seran asi aquella aquellos dicho
dicha mismo misma necesito quiero hay donde quien tengo tenemos hacer hago corresponde""".split())

SINONIMOS = {
    "vidrio": ["ventana", "cristal", "quebrazon", "trizadura", "lamina"],
    "ventana": ["vidrio", "malla", "marco"],
    "foco": ["luminaria", "ampolleta", "tubo", "fluorescente", "iluminacion"],
    "luz": ["electricidad", "electrica", "iluminacion"],
    "enchufe": ["electricidad", "electrica", "interruptor"],
    "gas": ["combustible", "cilindro", "bombona", "sec", "hermeticidad"],
    "agua": ["red", "grifo", "griferia", "filtracion", "llave"],
    "llave": ["griferia", "grifo", "llaves"],
    "desague": ["alcantarillado", "aguas", "servidas", "desgrasadora"],
    "techo": ["cielo", "estructural", "filtracion", "goteras"],
    "gotera": ["techo", "cielo", "filtracion", "estructural"],
    "muro": ["pared", "estructural", "grieta", "pintura"],
    "grieta": ["estructural", "muro"],
    "pintura": ["pintar", "moho", "descascaramiento", "hongos"],
    "puerta": ["infraestructura", "cerradura", "marco"],
    "piso": ["ceramica", "baldosa", "infraestructura"],
    "refrigerador": ["frio", "congeladora", "refrigeracion", "equipo"],
    "malla": ["mosquitera", "mosquiteras", "hermetica"],
    "extractor": ["campana", "ductos", "ventilacion"],
    "ratones": ["plagas", "roedores"], "cucarachas": ["plagas"], "palomas": ["plagas", "animales"],
    "plaga": ["plagas", "roedores", "sostenedor"],
    "paga": ["costo", "cargo", "responsable", "responsabilidad", "sostenedor", "prestador"],
    "responsable": ["sostenedor", "prestador", "responsabilidad", "cargo"],
    "multa": ["multas", "utm", "incumplimiento", "sancion"],
    "plazo": ["plazo", "dias", "habiles", "corridos"],
    "soser": ["prestador"], "colegio": ["establecimiento", "educacional", "junaeb"],
    "jardin": ["junji", "integra", "parvulos"],
}

GUIA_PESO = 1.6        # lo curado pesa más que el texto suelto


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def raiz(w):
    for suf in ("aciones", "acion", "ciones", "cion", "mente", "ados", "adas", "ado", "ada", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(s):
    return [raiz(w) for w in re.findall(r"[a-z0-9]{2,}", norm(s)) if w not in STOP]


# ------------------------------------------------------------------ corpus
def _base():
    for b in (os.path.expanduser("~/storage/downloads"), os.path.expanduser("~/storage/shared/Download")):
        if os.path.isdir(b):
            return os.path.join(b, "SOSER-prueba")
    return os.path.expanduser("~/SOSER-prueba")


def _md_trozos(ruta, codigo):
    out, titulo, buf = [], "", []
    for ln in open(ruta, encoding="utf-8"):
        if ln.startswith("## ") or ln.startswith("### "):
            if "".join(buf).strip():
                out.append((titulo, "".join(buf)))
            titulo, buf = ln.strip("# \n"), [ln]
        else:
            buf.append(ln)
    if "".join(buf).strip():
        out.append((titulo, "".join(buf)))
    # secciones largas (tablas de casos) se parten por líneas, repitiendo el título, para encontrar la fila exacta
    trozos = []
    for t, x in out:
        if len(x) <= 1400:
            trozos.append((t, x))
            continue
        cur = ""
        for ln in x.splitlines(keepends=True):
            if len(cur) + len(ln) > 900 and cur.strip():
                trozos.append((t, f"[{t}]\n" + cur))
                cur = ""
            cur += ln
        if cur.strip():
            trozos.append((t, f"[{t}]\n" + cur))
    return [{"doc": codigo, "archivo": os.path.basename(ruta), "pagina": t or "inicio", "texto": x} for t, x in trozos]


def _pdf_paginas(ruta):
    """Texto por página de un PDF que agregaste al celular (con caché por fecha de modificación)."""
    cache_d = os.path.join(_base(), ".docs_cache")
    os.makedirs(cache_d, exist_ok=True)
    clave = os.path.join(cache_d, re.sub(r"[^\w]+", "_", os.path.basename(ruta)) + f"_{int(os.path.getmtime(ruta))}.json")
    if os.path.exists(clave):
        return json.load(open(clave, encoding="utf-8"))
    info = subprocess.run(["pdfinfo", ruta], capture_output=True, text=True).stdout
    m = re.search(r"Pages:\s+(\d+)", info)
    n = int(m.group(1)) if m else 0
    pags = []
    for p in range(1, n + 1):
        t = subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-layout", ruta, "-"],
                           capture_output=True, text=True).stdout
        if t.strip():
            pags.append([p, re.sub(r"[ \t]+", " ", t)])
    json.dump(pags, open(clave, "w", encoding="utf-8"), ensure_ascii=False)
    return pags


def corpus():
    docs = []
    for f in sorted(glob.glob(os.path.join(AQUI, "documentos_texto", "*.jsonl.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            docs += [json.loads(x) for x in fh]
    cdir = os.path.join(_base(), "conocimiento")
    fuentes_md = sorted(glob.glob(os.path.join(cdir, "*.md"))) or sorted(glob.glob(os.path.join(AQUI, "conocimiento_base", "*.md")))
    for f in fuentes_md:
        codigo = "GUÍA" if os.path.basename(f).startswith("08") else "CONOCIMIENTO"
        docs += _md_trozos(f, codigo)
    ddir = os.path.join(_base(), "documentos")
    if os.path.isdir(ddir):
        for f in sorted(os.listdir(ddir)):
            r = os.path.join(ddir, f)
            try:
                if f.lower().endswith(".pdf"):
                    for p, t in _pdf_paginas(r):
                        for i in range(0, len(t), 1600):
                            docs.append({"doc": os.path.splitext(f)[0][:40], "archivo": f, "pagina": p, "texto": t[i:i + 1600]})
                elif f.lower().endswith((".txt", ".md")):
                    docs += _md_trozos(r, os.path.splitext(f)[0][:40])
            except Exception:
                pass
    return docs


# ------------------------------------------------------------------ búsqueda (BM25)
class Indice:
    def __init__(self, docs):
        self.docs = docs
        self.toks = [tokens(d["texto"]) for d in docs]
        self.tf = [Counter(t) for t in self.toks]
        self.N = len(docs)
        self.avg = sum(len(t) for t in self.toks) / max(self.N, 1)
        df = Counter()
        for t in self.toks:
            df.update(set(t))
        self.idf = {w: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for w, n in df.items()}

    def buscar(self, consulta, k=6):
        q = tokens(consulta)
        extra = []
        for w in re.findall(r"[a-z]+", norm(consulta)):
            extra += [raiz(x) for x in SINONIMOS.get(w, []) + SINONIMOS.get(w.rstrip("s"), [])]
        pesos = Counter({w: 1.0 for w in q})
        for w in extra:
            pesos[w] = max(pesos[w], 0.5)
        res = []
        for i, tf in enumerate(self.tf):
            s, L = 0.0, len(self.toks[i])
            for w, pw in pesos.items():
                f = tf.get(w)
                if f:
                    s += pw * self.idf.get(w, 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * L / self.avg))
            if s:
                if self.docs[i]["doc"] == "GUÍA":
                    s *= GUIA_PESO
                res.append((s, i))
        res.sort(reverse=True)
        out, vistos = [], set()
        for s, i in res:
            d = self.docs[i]
            clave = (d["doc"], d["pagina"], d["texto"][:60] if d["doc"] in ("GUÍA", "CONOCIMIENTO") else "")
            if clave in vistos:
                continue
            vistos.add(clave)
            out.append(dict(d, score=round(s, 2)))
            if len(out) >= k:
                break
        return out


_IDX = {"t": 0, "idx": None}


def indice():
    if not _IDX["idx"] or time.time() - _IDX["t"] > 600:
        _IDX.update(t=time.time(), idx=Indice(corpus()))
    return _IDX["idx"]


def cita(d):
    p = d["pagina"]
    if d["doc"] == "GUÍA":
        return f"[Guía · {p}]"
    if d["doc"] == "CONOCIMIENTO":
        return f"[{d['archivo']} · {p}]"
    if d["doc"] == "ANEXO17":
        return f"[ANEXO 17 · {p}]"
    return f"[{d['doc']} pág. {p}]"


# ------------------------------------------------------------------ conversación
def _hist_p():
    return os.path.join(_base(), ".conversacion.json")


def historial():
    try:
        h = json.load(open(_hist_p(), encoding="utf-8"))
        return [x for x in h if time.time() - x["t"] < 1800][-3:]
    except Exception:
        return []


def _guardar_hist(p, r):
    h = historial() + [{"t": time.time(), "p": p, "r": r[:800]}]
    os.makedirs(_base(), exist_ok=True)
    json.dump(h[-6:], open(_hist_p(), "w", encoding="utf-8"), ensure_ascii=False)


REGLAS = """Eres el asesor de la licitación PAE 85-34-LR25 (JUNAEB, JUNJI, INTEGRA) para el encargado de mantención de
SOSER, que es el PRESTADOR del servicio de alimentación. El "sostenedor" es el dueño/administrador del colegio o jardín.
Reglas:
- Responde SOLO con lo que dicen los EXTRACTOS. No inventes artículos, plazos ni montos.
- Después de cada afirmación pon la cita tal como aparece al inicio del extracto, por ejemplo [BASES pág. 216].
- Si los extractos no alcanzan para decidir, dilo y haz UNA pregunta para aclarar (por ejemplo: ¿es colegio JUNAEB
  o jardín JUNJI/INTEGRA?, ¿lo dañó personal de SOSER?, ¿es estructural?).
- Formato, en español de Chile y breve:
  *Corresponde a:* SOSER / sostenedor / depende de … (una línea)
  *Por qué:* 2 a 4 viñetas con cita
  *Plazo:* si los extractos lo dicen (hábiles o corridos)
  *Qué hacer:* 1 o 2 pasos concretos"""


def responder(pregunta, k=5):
    idx = indice()
    hist = historial()
    consulta = pregunta + " " + " ".join(x["p"] for x in hist[-1:])     # seguimiento: "¿y si fue el técnico?"
    trozos = idx.buscar(consulta, k=k)
    if not trozos:
        return "📚 No encuentro nada sobre eso en los documentos de la licitación. ¿Me lo dices con otras palabras?"
    extractos = "\n\n".join(f"{cita(d)} {re.sub(r'\s+', ' ', d['texto'])[:1300]}" for d in trozos)
    previa = "\n".join(f"Pregunta anterior: {x['p']}\nRespuesta anterior: {x['r'][:400]}" for x in hist)
    prompt = (REGLAS + ("\n\nConversación previa:\n" + previa if previa else "")
              + f"\n\nEXTRACTOS:\n{extractos}\n\nPREGUNTA: {pregunta}\nRESPUESTA:")
    try:
        req = urllib.request.Request(OLLAMA + "/api/generate", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"model": MODELO, "prompt": prompt, "stream": False,
                                                      "keep_alive": "10m",
                                                      "options": {"temperature": 0.1, "num_ctx": 8192,
                                                                  "num_predict": 450}}).encode())
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.loads(r.read()).get("response", "").strip()
    except Exception as e:
        resp = f"(La IA no respondió: {e}. Te dejo lo que encontré en los documentos.)"
    fuentes = "\n".join(f"• {cita(d)} {re.sub(r'\s+', ' ', d['texto'])[:140]}…" for d in trozos)
    texto = f"📚 *Licitación* — {pregunta}\n\n{resp}\n\n_Fuentes consultadas:_\n{fuentes}"
    _guardar_hist(pregunta, resp)
    return texto


def buscar_texto(consulta, k=6):
    trozos = indice().buscar(consulta, k=k)
    if not trozos:
        return "No encontré nada sobre eso."
    return f"🔎 *{consulta}*\n" + "\n\n".join(
        f"{cita(d)}\n{re.sub(r'\s+', ' ', d['texto'])[:350]}…" for d in trozos)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--buscar":
        print(buscar_texto(" ".join(a[1:])))
    elif a:
        print(responder(" ".join(a)))
    else:
        print(__doc__)
