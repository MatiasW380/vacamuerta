"""Industria: producción manufacturera, capacidad instalada, construcción, autos, empleo y parques industriales.

Etapa 1: relevamiento (data/industry_status.json).
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ArgentinaInvestMonitor/1.0; +https://github.com/MatiasW380/vacamuerta)"}
SERIES_API = "https://apis.datos.gob.ar/series/api"
CKAN = "https://datos.gob.ar/api/3/action"


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def get(url, **kw):
    timeout = kw.pop("timeout", 90)
    for intento in range(4):
        r = requests.get(url, headers=UA, timeout=timeout, **kw)
        if r.status_code in (429, 502, 503, 504) and intento < 3:
            time.sleep(4 * (intento + 1))
            continue
        r.raise_for_status()
        return r


def leer(url: str, max_bytes: int = 30_000_000) -> pd.DataFrame:
    crudo = get(url, timeout=300).content[:max_bytes]
    if url.lower().split("?")[0].endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(crudo), dtype=str)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = crudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if texto[:3000].count(";") > texto[:3000].count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, low_memory=False, on_bad_lines="skip")


def series_buscar(diag: dict) -> dict:
    out = []
    for q in ("ipi manufacturero nivel general", "indice produccion industrial manufacturero", "ipi manufacturero desestacionalizado", "ipi manufacturero divisiones",
              "utilizacion capacidad instalada industria", "isac indicador sintetico actividad construccion", "despacho cemento", "produccion automotores",
              "empleo registrado industria", "salario industria", "exportaciones manufacturas origen industrial", "demanda energia electrica industrial", "acero crudo produccion"):
        try:
            for r in get(f"{SERIES_API}/search/", params={"q": q, "limit": 12}).json().get("data", []):
                f = r.get("field", {})
                if (f.get("time_index_end") or "") >= "2026":
                    out.append([q, f.get("id"), (f.get("description") or "")[:100], f.get("frequency"), f.get("time_index_end"), f.get("units"), (r.get("dataset") or {}).get("title", "")[:60]])
        except Exception as e:
            out.append([q, "ERROR", str(e)[:100]])
    diag["series"] = out
    return {}


def catalogo(diag: dict) -> dict:
    out = []
    for q in ("parques industriales", "registro nacional parques industriales", "establecimientos industriales", "empresas industriales"):
        try:
            for p in get(f"{CKAN}/package_search", params={"q": q, "rows": 10}).json()["result"]["results"]:
                out.append({"name": p["name"], "title": p.get("title"), "modified": (p.get("metadata_modified") or "")[:10],
                            "resources": [{"name": r.get("name"), "format": (r.get("format") or "").lower(), "url": r.get("url"), "modified": (r.get("last_modified") or "")[:10]} for r in p.get("resources", [])][:6]})
        except Exception as e:
            out.append({"error": f"{q}: {e}"[:150]})
    diag["datasets"] = out
    muestras = {}
    for d in out:
        if "parque" not in norm(d.get("name", "")):
            continue
        for r in [r for r in d.get("resources", []) if r["format"] in ("csv", "xlsx", "geojson", "json")][:2]:
            try:
                df = leer(r["url"], 5_000_000)
                muestras[f'{d["name"]} | {r["name"]}'[:110]] = {"url": r["url"], "rows": int(len(df)), "columns": list(df.columns)[:30], "tail": df.tail(2).astype(str).to_dict(orient="records")}
            except Exception as e:
                muestras[f'{d["name"]} | {r["name"]}'[:110]] = {"url": r["url"], "error": f"{type(e).__name__}: {str(e)[:120]}"}
    diag["samples"] = muestras
    return {}


INDEC = {"name": "INDEC (API de Series de Tiempo)", "url": "https://datos.gob.ar/series", "license": "CC BY 4.0"}


def serie_api(ids, desde="2016-01-01"):
    j = get(f"{SERIES_API}/series/", params={"ids": ",".join(ids), "format": "json", "limit": 1000, "start_date": desde}).json()
    return [x for x in j.get("data", []) if all(v is not None for v in x[1:])]


def buscar(q, debe, prefijo, diag, clave, freq="R/P1M"):
    res = get(f"{SERIES_API}/search/", params={"q": q, "limit": 40}).json().get("data", [])
    c = []
    for r in res:
        f = r.get("field", {})
        txt = norm(f.get("description"))
        if all(d in txt for d in debe) and (f.get("id") or "").startswith(prefijo) and f.get("frequency") == freq:
            c.append({"id": f["id"], "desc": f.get("description"), "end": f.get("time_index_end"), "units": f.get("units")})
    c.sort(key=lambda x: x["end"] or "", reverse=True)
    diag.setdefault("cand", {})[clave] = c[:3]
    return c[0] if c else None


def mensual(id_, diag, clave, desde="2016-01-01"):
    d = serie_api([id_], desde)
    diag.setdefault("points", {})[clave] = [len(d), d[-1] if d else None]
    return [{"period": x[0][:7], "v": round(float(x[1]), 2)} for x in d]


def yoy(serie):
    m = {x["period"]: x["v"] for x in serie}
    if not serie:
        return None
    u = serie[-1]["period"]; p = f"{int(u[:4]) - 1}{u[4:]}"
    return round((m[u] / m[p] - 1) * 100, 1) if p in m and m[p] else None


def acumulado(serie):
    """Variación del acumulado del año contra el mismo período del año anterior."""
    if not serie:
        return None
    u = serie[-1]["period"]; y = u[:4]; meses = [x["period"][5:] for x in serie if x["period"][:4] == y]
    m = {x["period"]: x["v"] for x in serie}
    prev = [m.get(f"{int(y) - 1}-{mm}") for mm in meses]
    if None in prev or not prev:
        return None
    return round((sum(m[f"{y}-{mm}"] for mm in meses) / sum(prev) - 1) * 100, 1)


DIVISIONES = [("Alimentos y bebidas", "food"), ("Productos de tabaco", "tobacco"), ("Productos textiles", "textiles"), ("Prendas de vestir, cuero y calzado", "apparel"),
              ("Madera, papel, edición e impresión", "paper"), ("Refinación del petróleo, coque y combustible nuclear", "refining"), ("Sustancias y productos químicos", "chemicals"),
              ("Productos de caucho y plástico", "plastics"), ("Productos minerales no metálicos", "minerals"), ("Industrias metálicas básicas", "basic_metals"),
              ("Productos de metal", "metal_products"), ("Maquinaria y equipo", "machinery"), ("Otros equipos, aparatos e instrumentos", "equipment"),
              ("Vehículos automotores, carrocerías, remolques y autopartes", "autos"), ("Otro equipo de transporte", "transport"), ("Muebles y colchones, y otras industrias manufactureras", "furniture")]


def ipi(diag: dict) -> dict:
    gen = buscar("ipi nivel general serie desestacionalizada", ["nivel general", "desestacionalizada"], "453.1", diag, "sa")
    ori = buscar("ipi nivel general serie original", ["nivel general", "original"], "453.1", diag, "orig")
    if not ori:
        raise RuntimeError("Sin IPI manufacturero")
    so = mensual(ori["id"], diag, "orig")
    ss = mensual(gen["id"], diag, "sa") if gen else []
    divs = []
    for nombre, clave in DIVISIONES:
        c = buscar(f"ipi divisiones {nombre}", [norm(nombre).split(",")[0]], "453.2", diag, clave)
        if not c:
            continue
        s = mensual(c["id"], diag, clave, "2023-01-01")
        if len(s) > 13:
            divs.append({"key": clave, "name": c["desc"].replace("IPI Divisiones y Subclases ", ""), "yoy": yoy(s), "ytd": acumulado(s), "latest": s[-1]["period"]})
    divs.sort(key=lambda d: (d["yoy"] is None, -(d["yoy"] or 0)))
    return {"source": INDEC, "original": so, "sa": ss, "yoy": yoy(so), "ytd": acumulado(so), "divisions": divs}


def otras(diag: dict) -> dict:
    out = {}
    ucii = buscar("utilizacion capacidad instalada industria nivel general", ["capacidad instalada", "como porcentaje del total"], "31.3", diag, "ucii")
    if ucii:
        out["capacity"] = {"desc": ucii["desc"], "monthly": mensual(ucii["id"], diag, "ucii")}
    isac = buscar("isac sin estacionalidad", ["construccion", "sin estacionalidad"], "33.2", diag, "isac") or {"id": "33.2_ISAC_SIN_EDAD_0_M_23_56", "desc": "ISAC sin estacionalidad"}
    out["construction"] = {"monthly": mensual(isac["id"], diag, "isac")}
    for clave, i in (("cement_kt", "41.3_CP_0_A_16"), ("cars_units", "41.3_AA_0_A_23"), ("steel_kt", "359.3_ACERO_CRUDUDO__11")):
        try:
            s = mensual(i, diag, clave, "2016-01-01")
            out[clave] = {"monthly": s, "yoy": yoy(s), "ytd": acumulado(s)}
        except Exception as e:
            diag.setdefault("errors", []).append(f"{clave}: {e}"[:150])
    for k in ("capacity", "construction"):
        if k in out:
            out[k]["yoy"] = yoy(out[k]["monthly"])
    try:
        emp = serie_api(["155.1_ISTRIARIA_C_0_0_9"], "2012-01-01")
        out["jobs_quarterly"] = [{"period": x[0][:7], "v": round(float(x[1]))} for x in emp]
    except Exception as e:
        diag.setdefault("errors", []).append(f"jobs: {e}"[:150])
    out["source"] = INDEC
    return out


def parques(diag: dict) -> dict:
    p = get(f"{CKAN}/package_show", params={"id": "registro-nacional-de-parques-industriales-renpi"}).json()["result"]
    r = p["resources"][0]
    diag["resource"] = [r.get("name"), r.get("url")]
    crudo = get(r["url"], timeout=120).content
    hojas = pd.read_excel(io.BytesIO(crudo), engine="odf", sheet_name=None, dtype=str)
    diag["sheets"] = {k: [len(v), list(v.columns)[:20]] for k, v in hojas.items()}
    df = max(hojas.values(), key=len)
    diag["sample"] = df.head(3).astype(str).to_dict(orient="records")
    cols = {norm(c): c for c in df.columns}
    c_prov = next((cols[c] for c in cols if "provincia" in c), None)
    c_nom = next((cols[c] for c in cols if "nombre" in c or "parque" in c), None)
    c_tipo = next((cols[c] for c in cols if "tipo" in c or "caracter" in c), None)
    c_lat = next((cols[c] for c in cols if "lat" in c), None)
    c_lon = next((cols[c] for c in cols if "lon" in c), None)
    c_loc = next((cols[c] for c in cols if "localidad" in c or "municipio" in c or "partido" in c), None)
    items = []
    for _, x in df.iterrows():
        nombre = str(x.get(c_nom, "")).strip() if c_nom else ""
        if not nombre or nombre.lower() == "nan":
            continue
        it = {"name": nombre, "province": str(x.get(c_prov, "")).strip() if c_prov else None, "locality": str(x.get(c_loc, "")).strip() if c_loc else None,
              "type": str(x.get(c_tipo, "")).strip() if c_tipo else None}
        if c_lat and c_lon:
            la, lo = pd.to_numeric(str(x[c_lat]).replace(",", "."), errors="coerce"), pd.to_numeric(str(x[c_lon]).replace(",", "."), errors="coerce")
            if pd.notna(la) and pd.notna(lo) and -56 < la < -21 and -74 < lo < -53:
                it["lat"], it["lon"] = round(float(la), 4), round(float(lo), 4)
        items.append(it)
    por_prov = pd.Series([i["province"] for i in items]).value_counts().to_dict()
    diag["mapped"] = {"prov": c_prov, "name": c_nom, "type": c_tipo, "lat": c_lat, "lon": c_lon, "loc": c_loc, "with_coords": sum(1 for i in items if "lat" in i)}
    return {"source": {"name": "Ministerio de Economía, Registro Nacional de Parques Industriales (RENPI)", "url": "https://datos.gob.ar/dataset/registro-nacional-de-parques-industriales-renpi", "license": "CC BY 4.0"},
            "items": items, "by_province": por_prov, "updated": r.get("last_modified") or r.get("created")}


def main() -> None:
    status, salida = {}, {}
    destino = DATA / "industry.json"
    if destino.exists():
        try:
            salida = json.loads(destino.read_text(encoding="utf-8"))
        except Exception:
            salida = {}
    for nombre, fn in [("ipi", ipi), ("other", otras), ("parks", parques)]:
        diag: dict = {}
        try:
            salida[nombre] = fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diag": diag, "trace": traceback.format_exc()[-1000:]}
        print(nombre, status[nombre]["ok"], file=sys.stderr)
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    destino.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":"), default=str) + "\n", encoding="utf-8")
    (DATA / "industry_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
