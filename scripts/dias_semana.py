"""Extrai os dias da semana em que o voucher vale a partir do texto de validade do miolo.

Retorna lista ordenada com códigos: seg, ter, qua, qui, sex, sab, dom.
"""
import re, unicodedata

DIAS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
NOMES = {
    "seg": ["segunda", "seg"], "ter": ["terca", "ter"], "qua": ["quarta", "qua"],
    "qui": ["quinta", "qui"], "sex": ["sexta", "sex"], "sab": ["sabado", "sab"], "dom": ["domingo", "dom"],
}


def _norm(s):
    s = unicodedata.normalize("NFD", s or "").lower()
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _dia(tok):
    tok = re.sub(r"s?-?feiras?$|s$", "", tok)  # quartas-feiras -> quarta, sabados -> sabado
    for cod, nomes in NOMES.items():
        if tok in nomes:
            return cod
    return None


def dias_semana(texto):
    t = _norm(texto)
    if not t:
        return []
    if "todos os dias" in t or "todo dia" in t:
        return DIAS[:]
    dias = set()
    # intervalos "X a Y"
    for a, b in re.findall(r"\b([a-z]+(?:-feiras?)?)\s+a\s+([a-z]+(?:-feiras?)?)\b", t):
        da, db = _dia(a), _dia(b)
        if da and db:
            i, j = DIAS.index(da), DIAS.index(db)
            rng = DIAS[i:j + 1] if i <= j else DIAS[i:] + DIAS[:j + 1]
            dias.update(rng)
    # dias soltos (fora de "exceto ...")
    sem_excecao = re.split(r"\bexceto\b", t)[0]
    for tok in re.findall(r"[a-z]+(?:-feiras?)?", sem_excecao):
        d = _dia(tok)
        if d:
            dias.add(d)
    # exceções: "exceto sabados"
    for parte in re.split(r"\bexceto\b", t)[1:]:
        for tok in re.findall(r"[a-z]+(?:-feiras?)?", parte.split(":")[0]):
            d = _dia(tok)
            if d:
                dias.discard(d)
    return [d for d in DIAS if d in dias]


if __name__ == "__main__":
    import json, sys
    from collections import Counter
    data = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "data/parceiros.json"))
    c = Counter()
    for p in data:
        ds = dias_semana(p["horario_promo"])
        c.update(ds)
        print(f"{p['nome'][:28]:28} {','.join(ds) or '???':28} <- {p['horario_promo']}")
    print("\nPor dia:", dict(c))
    both = [p["nome"] for p in data if {"sab", "dom"} <= set(dias_semana(p["horario_promo"]))]
    print("Sab+Dom:", len(both), both)
