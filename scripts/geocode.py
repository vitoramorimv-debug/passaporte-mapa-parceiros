#!/usr/bin/env python3
"""Geocodifica os parceiros de data/parceiros_raw.json e gera data/parceiros.json + data/parceiros.js.

Fontes: ViaCEP (resolve CEP -> logradouro/bairro), Google Geocoding API (endereco com numero,
precisa da variavel de ambiente GOOGLE_MAPS_API_KEY ou de um arquivo .env na raiz do projeto)
e Nominatim/OpenStreetMap + Photon (fallback: rua, bairro, cidade).
Resultados ficam em cache em data/geocode_cache.json para reexecucoes rapidas.
"""
import json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "parceiros_raw.json"
OUT_JSON = ROOT / "data" / "parceiros.json"
OUT_JS = ROOT / "data" / "parceiros.js"
CACHE = ROOT / "data" / "geocode_cache.json"
OVERRIDES = ROOT / "data" / "overrides.json"  # {"id": {"lat":..,"lon":..}} para correcao manual
ENV_FILE = ROOT / ".env"  # opcional: GOOGLE_MAPS_API_KEY=...

UA = "PassaporteGastronomicoMarilia/0.1 (mapa de parceiros; contato: vitoramorimv@gmail.com)"
CITY_CENTER = (-22.2139, -49.9458)
# viewbox: lon_min, lat_max, lon_max, lat_min  (Marilia e arredores)
VIEWBOX = "-50.05,-22.10,-49.85,-22.35"
cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
_last_nominatim = 0.0


def load_env_file():
    """Carrega variaveis de um .env simples (CHAVE=valor) sem sobrescrever o ambiente."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


load_env_file()
GOOGLE_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
GOOGLE_OK_TYPES = {"ROOFTOP", "RANGE_INTERPOLATED"}


def http_json(url):
    # usa curl: o Python deste Mac nao tem a cadeia de certificados instalada
    import subprocess
    r = subprocess.run(["curl", "-sS", "-m", "20", "-A", UA, "-H", "Accept: application/json", url],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # nao inclui a URL na mensagem (pode conter a chave da API)
        raise RuntimeError(f"curl falhou (codigo {r.returncode}): {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def google_geocode(street, numero, bairro):
    """Google Geocoding API. Retorna (lat, lon, display) so para resultado com numero
    (ROOFTOP / RANGE_INTERPOLATED) dentro de Marilia; None caso contrario.
    Erros da API nao sao gravados no cache."""
    if not GOOGLE_KEY or not numero:
        return None
    parts = [street, str(numero)] + ([bairro] if bairro else []) + ["Marília", "SP", "Brasil"]
    address = ", ".join(parts)
    key = "google:" + address
    if key in cache:
        results = cache[key]
    else:
        url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode({
            "address": address, "components": "country:BR", "region": "br", "language": "pt-BR", "key": GOOGLE_KEY})
        try:
            data = http_json(url)
        except Exception as e:
            print(f"  google erro ({address}): {e}", file=sys.stderr)
            return None
        status = data.get("status")
        if status == "OK":
            results = data.get("results", [])
        elif status == "ZERO_RESULTS":
            results = []
        else:  # OVER_QUERY_LIMIT, REQUEST_DENIED, INVALID_REQUEST, UNKNOWN_ERROR...
            print(f"  google {status} ({address}): {data.get('error_message', '')}", file=sys.stderr)
            return None
        cache[key] = results
    for r in results:
        geo = r.get("geometry", {})
        if geo.get("location_type") not in GOOGLE_OK_TYPES:
            continue
        comps = r.get("address_components", [])
        cities = {strip_accents(c["long_name"]).lower() for c in comps
                  if {"locality", "administrative_area_level_2", "sublocality", "postal_town"} & set(c.get("types", []))}
        if "marilia" not in cities:
            continue
        loc = geo["location"]
        if km_from_center({"lat": loc["lat"], "lon": loc["lng"]}) > 12:
            continue
        tag = f"Google {geo['location_type']}" + (", partial_match" if r.get("partial_match") else "")
        return float(loc["lat"]), float(loc["lng"]), f"{r.get('formatted_address', '')} ({tag})"
    return None


def viacep(cep):
    key = "viacep:" + cep
    if key in cache:
        return cache[key]
    try:
        data = http_json(f"https://viacep.com.br/ws/{cep}/json/")
        if data.get("erro"):
            data = None
    except Exception as e:
        print("  viacep erro", cep, e, file=sys.stderr)
        data = None
    cache[key] = data
    return data


def nominatim(params):
    global _last_nominatim
    key = "nominatim:" + json.dumps(params, sort_keys=True, ensure_ascii=False)
    if key in cache:
        return cache[key]
    wait = 1.1 - (time.time() - _last_nominatim)
    if wait > 0:
        time.sleep(wait)
    q = dict(params, format="jsonv2", limit=1, countrycodes="br", viewbox=VIEWBOX, bounded=1, addressdetails=1)
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(q)
    try:
        data = http_json(url)
    except Exception as e:
        print("  nominatim erro", params, e, file=sys.stderr)
        data = []
    _last_nominatim = time.time()
    cache[key] = data
    return data


def photon(q):
    key = "photon:" + q
    if key in cache:
        hit = cache[key]
    else:
        try:
            url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": q, "limit": 5, "lat": CITY_CENTER[0], "lon": CITY_CENTER[1]})
            feats = http_json(url).get("features", [])
        except Exception as e:
            print("  photon erro", q, e, file=sys.stderr)
            feats = []
        hit = None
        for f in feats:
            pr = f["properties"]; lon, lat = f["geometry"]["coordinates"]
            if strip_accents(pr.get("city") or pr.get("county") or "").lower() != "marilia":
                continue
            if km_from_center({"lat": lat, "lon": lon}) > 9:
                continue
            hit = [lat, lon, (pr.get("name") or pr.get("street") or "") + ", " + (pr.get("district") or "") + " (Photon)"]
            break
        cache[key] = hit
    return hit


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


CEP_RE = re.compile(r"(\d{2})\.?(\d{3})[-\s]?(\d{3})")
ABBREV = [(r"^r\.?\s", "Rua "), (r"^av\.?\s", "Avenida "), (r"^al\.?\s", "Alameda "), (r"^pç\.?\s", "Praça ")]


def parse_address(text):
    text = text or ""
    cep = None
    m = CEP_RE.search(text)
    if m:
        cep = "".join(m.groups())
        text = text[: m.start()] + " " + text[m.end():]
    text = re.sub(r"\bcep\b\s*:?", " ", text, flags=re.I)
    text = re.sub(r"\bn\s*[º°]\s*|\bno?\.\s*", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    numero = None
    street = text
    # numero do imovel: primeiro numero isolado que nao faz parte do nome da rua ("21 de abril")
    # nem e complemento ("loja 89", "box 10")
    for m in re.finditer(r"(^|[\s,])(\d{1,5})(?![\d:])", text):
        after = text[m.end():]
        before = text[: m.start()].strip().lower()
        if re.match(r"\s+de\s", after, re.I):
            continue
        if re.search(r"(loja|box|sala|apto|apt|bloco|lote|km)\s*$", before):
            continue
        numero = m.group(2)
        street = text[: m.start()].strip(" ,.-")
        if not street:  # ex: "17504081 av santo Antonio 325" -> rua vem depois do numero
            street = re.sub(r"(^|[\s,])\d{1,5}(?![\d:]).*$", "", after.strip(" ,.-")).strip(" ,.-")
        break
    street = street.strip(" ,.-")
    for pat, rep in ABBREV:
        street = re.sub(pat, rep, street, flags=re.I)
    return cep, street, numero


def has_type_prefix(street):
    return bool(re.match(r"^(rua|avenida|av|alameda|praça|praca|travessa|estrada|rodovia)\b", street, re.I))


import math


def km_from_center(r):
    lat, lon = float(r["lat"]), float(r["lon"])
    dlat = math.radians(lat - CITY_CENTER[0]); dlon = math.radians(lon - CITY_CENTER[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(CITY_CENTER[0])) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def pick(results, kinds, max_km=9):
    for r in results:
        if (r.get("addresstype") in kinds or r.get("type") in kinds) and km_from_center(r) <= max_km:
            return r
    return None


ROAD_KINDS = {"road", "residential", "secondary", "tertiary", "primary", "unclassified", "pedestrian", "living_street", "trunk"}
AREA_KINDS = {"suburb", "neighbourhood", "quarter", "city_district", "residential", "hamlet", "village"}


def geocode(street, numero, bairro):
    """Retorna (lat, lon, precisao, display)."""
    variants = [street] if has_type_prefix(street) else [street, "Rua " + street, "Avenida " + street]
    variants = [v for v in variants if v.strip() and v.strip() not in ("Rua", "Avenida")]
    # 0) Google Geocoding API: unica fonte com numeracao de imovel confiavel em Marilia
    if numero:
        g = google_geocode(street, numero, bairro)
        if g:
            return g[0], g[1], "endereco", g[2]
    # 1) endereco com numero (Nominatim/OSM; raramente tem numeracao em Marilia)
    if numero:
        for v in variants:
            r = nominatim({"street": f"{numero} {v}", "city": "Marília", "state": "São Paulo", "country": "Brasil"})
            hit = pick(r, {"house", "building", "place", "shop", "amenity"})
            if hit:
                return float(hit["lat"]), float(hit["lon"]), "endereco", hit["display_name"]
        for v in variants:
            r = nominatim({"q": f"{v}, {numero}, Marília, SP, Brasil"})
            hit = pick(r, {"house", "building", "place", "shop", "amenity"})
            if hit:
                return float(hit["lat"]), float(hit["lon"]), "endereco", hit["display_name"]
    # 2) rua
    for v in variants:
        r = nominatim({"street": v, "city": "Marília", "state": "São Paulo", "country": "Brasil"})
        hit = pick(r, ROAD_KINDS)
        if hit:
            return float(hit["lat"]), float(hit["lon"]), "rua", hit["display_name"]
    # 2b) so o nome proprio da rua (ex: "Cabrini" acha "Rua Sperêndio Cabrini")
    core = re.sub(r"^(rua|avenida|av|alameda|praça|praca|travessa)\b\.?\s*", "", street, flags=re.I)
    core = re.sub(r"^(dr|dra|doutor|doutora|cel|coronel|presidente|pres|prof|professor|dom|são|santo|santa)\b\.?\s*", "", core, flags=re.I)
    words = core.split()
    if words:
        r = nominatim({"q": f"{words[-1]}, Marília, SP, Brasil"})
        hit = pick(r, ROAD_KINDS)
        if hit and strip_accents(words[-1]).lower() in strip_accents(hit["display_name"]).lower():
            return float(hit["lat"]), float(hit["lon"]), "rua", hit["display_name"]
    # 2c) Photon (busca fuzzy sobre o OSM; acha grafias erradas como "Roosvelt")
    for v in variants[:1]:
        r = photon(f"{v} Marília")
        if r:
            return r[0], r[1], "rua", r[2]
    # 3) bairro
    if bairro:
        r = nominatim({"q": f"{bairro}, Marília, SP, Brasil"})
        hit = pick(r, AREA_KINDS, max_km=7)
        if hit:
            return float(hit["lat"]), float(hit["lon"]), "bairro", hit["display_name"]
    return CITY_CENTER[0], CITY_CENTER[1], "cidade", "Marília (centro aproximado)"


def clean_name(n):
    return re.sub(r"\s*-\s*(Horário|Produto)\s+(Alterado|Ajustado)\s*$", "", n, flags=re.I).strip()


def clean_instagram(s):
    if not s:
        return None
    s = s.strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9_.]+)", s)
    if m:
        return m.group(1)
    s = s.lstrip("@#").split()[0] if " " not in s.strip("@") else None
    if s and re.fullmatch(r"[A-Za-z0-9_.]+", s):
        return s.lower()
    return None


def main():
    raw = json.loads(RAW.read_text())
    overrides = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    if GOOGLE_KEY:
        print("Google Geocoding API: chave encontrada, enderecos com numero serao resolvidos pelo Google.\n")
    else:
        print("AVISO: GOOGLE_MAPS_API_KEY nao definida (ambiente ou .env). Pulando a etapa Google;\n"
              "       a maioria dos parceiros ficara com precisao 'rua'. Veja o README.\n", file=sys.stderr)
    out = []
    for p in raw:
        if p.get("status") != "Página Aprovada":
            continue
        nome = clean_name(p["nome"])
        cep, street, numero = parse_address(p.get("endereco"))
        bairro = None
        typed_street = street
        via = viacep(cep) if cep else None
        if via:
            bairro = via.get("bairro") or None
            if via.get("logradouro"):
                # prefere o logradouro oficial do CEP; mantém o numero digitado
                street = via["logradouro"]
        print(f"{nome}: street={street!r} num={numero} bairro={bairro} cep={cep}")
        if p["id"] in overrides:
            o = overrides[p["id"]]
            lat, lon, prec, disp = o["lat"], o["lon"], o.get("precisao", "manual"), "ajuste manual: " + o.get("obs", "")
        else:
            lat, lon, prec, disp = geocode(street, numero, bairro)
            if prec != "endereco" and typed_street and typed_street != street:
                # CEP pode estar errado ou o logradouro oficial nao bate: tenta a rua que a pessoa digitou,
                # mas so troca se o resultado for melhor (endereco) ou se antes caiu no centro da cidade
                lat2, lon2, prec2, disp2 = geocode(typed_street, numero, bairro)
                if prec2 == "endereco" or (prec == "cidade" and prec2 != "cidade"):
                    lat, lon, prec, disp = lat2, lon2, prec2, disp2 + " [rua digitada, CEP divergente]"
                    street = typed_street
        print(f"   -> {prec}: {lat:.5f}, {lon:.5f}  ({disp[:70]})")
        endereco_fmt = street + (f", {numero}" if numero else "")
        if bairro:
            endereco_fmt += f" - {bairro}"
        if p["id"] in overrides and overrides[p["id"]].get("endereco"):
            endereco_fmt = overrides[p["id"]]["endereco"]  # rotulo manual (ex.: alameda interna que o CEP nao conhece)
        so_delivery = (p.get("so_delivery") or []) == ["Sim"]
        out.append({
            "id": p["id"],
            "nome": nome,
            "endereco": endereco_fmt,
            "endereco_original": p.get("endereco"),
            "bairro": bairro,
            "cep": cep,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "precisao": prec,
            "segmento": p.get("segmento") or [],
            "instagram": clean_instagram(p.get("instagram")),
            "produto": p.get("produto"),
            "descricao": p.get("descricao"),
            "horario_promo": p.get("horario_promo"),
            "funcionamento": p.get("funcionamento"),
            "so_delivery": so_delivery,
            "ponto_retirada": "Sim" in (p.get("ponto_retirada") or []),
            "notion_url": f"https://app.notion.com/{p['id']}",
        })
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    out.sort(key=lambda x: strip_accents(x["nome"]).lower())
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    OUT_JS.write_text("window.PARCEIROS = " + json.dumps(out, ensure_ascii=False) + ";\n")
    from collections import Counter
    print("\nResumo precisao:", dict(Counter(x["precisao"] for x in out)), f"({len(out)} parceiros)")
    approx = [x for x in out if x["precisao"] not in ("endereco", "manual")]
    if approx:
        print(f"\nParceiros com posicao aproximada ({len(approx)}) - conferir e, se preciso, ajustar em data/overrides.json:")
        for x in approx:
            print(f"  [{x['precisao']:>7}] {x['nome']}: {x['endereco']}  (original: {x['endereco_original']!r})")
    else:
        print("\nTodos os parceiros com posicao exata (endereco ou ajuste manual).")


if __name__ == "__main__":
    main()
