"""
lenguaje.py — entiende cómo escribes tú: días, técnicos y bloques.

  fecha_de("el jueves")        -> próximo jueves
  fecha_de("mañana")           -> mañana (si cae fin de semana o feriado, el siguiente hábil)
  fecha_de("15/10")            -> 15 de octubre
  tec_de("pásalo a camilo")    -> "CAMILO"
  bloque_de("b2"), bloque_de("en la tarde") -> 2, 3
"""
import re
from datetime import date, timedelta

from nucleo import datos, es_habil, hoy, norm, sig_habil

DIAS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
        "lun": 0, "mar": 1, "mie": 2, "jue": 3, "vie": 4}


def fecha_de(texto, base=None):
    base = base or hoy()
    t = norm(texto)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", str(texto))
    if m:
        dd, mm, aa = int(m.group(1)), int(m.group(2)), m.group(3)
        a = (int(aa) + (2000 if len(aa) == 2 else 0)) if aa else base.year
        try:
            f = date(a, mm, dd)
            if not aa and f < base - timedelta(days=60):
                f = date(a + 1, mm, dd)
            return f
        except ValueError:
            pass
    if re.search(r"\bpasado manana\b", t):
        return sig_habil(sig_habil(base + timedelta(days=1)) + timedelta(days=1))
    if re.search(r"\bhoy\b|\bahora\b|\bahora ya\b", t):
        return base
    if re.search(r"\bmanana\b", t) and not re.search(r"\b(en|por|de) la manana\b", t):
        return sig_habil(base + timedelta(days=1))
    m = re.search(r"\ben (\d+) dias?\b", t)
    if m:
        return sig_habil(base + timedelta(days=int(m.group(1))))
    m = re.search(r"\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo|lun|mar|mie|jue|vie)\b", t)
    if m:
        if re.search(r"\b(semana que viene|proxima semana|otra semana)\b", t):
            lunes = base + timedelta(days=7 - base.weekday())
            return lunes + timedelta(days=DIAS[m.group(1)])
        dif = (DIAS[m.group(1)] - base.weekday()) % 7
        return base + timedelta(days=dif or 7)    # "el jueves" dicho un jueves = el de la otra semana
    if re.search(r"\b(semana que viene|proxima semana)\b", t):
        return base + timedelta(days=(7 - base.weekday()))
    return None


def tec_de(texto):
    t = norm(texto)
    for clave, info in datos()["META"]["tecnicos"].items():
        nombres = {norm(clave)}
        if info.get("nombre"):
            nombres.add(norm(info["nombre"]).split()[0])
        if any(re.search(rf"\b{re.escape(n)}\b", t) for n in nombres if n):
            return clave
    return None


def bloque_de(texto):
    t = norm(texto)
    m = re.search(r"\b(?:b|bloque|bloq)\s*([1-4])\b", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(primer|segundo|tercer|cuarto)\s+bloque\b", t)
    if m:
        return {"primer": 1, "segundo": 2, "tercer": 3, "cuarto": 4}[m.group(1)]
    if re.search(r"\b(temprano|primera hora|a primera|en la manana|por la manana|de la manana)\b", t):
        return 1
    if re.search(r"\b(mediodia|medio dia|antes de almuerzo)\b", t):
        return 2
    if re.search(r"\b(tarde|despues de almuerzo)\b", t):
        return 3
    if re.search(r"\b(extra|sobrecupo)\b", t):
        return 4
    return None


def habil_o_siguiente(d):
    return d if es_habil(d) else sig_habil(d)
