"""Agro: siembra y cosecha, ventas al exterior, exportaciones, divisas y precios.

Etapa 1: relevamiento automático de fuentes (diagnóstico en data/agro_status.json).
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
CKANS = ["https://datos.magyp.gob.ar/api/3/action", "https://datos.gob.ar/api/3/action"]


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def get(url, **kw):
    timeout = kw.pop("timeout", 90)
    for intento in range(4):
        r = requests.get(url, headers=UA, timeout=timeout, **kw)
        if r.status_code in (502, 503, 504) and intento < 3:
            time.sleep(4 * (intento + 1))
            continue
        r.raise_for_status()
        return r


def leer(url: str, max_bytes: int = 80_000_000) -> pd.DataFrame:
    crudo = get(url, timeout=300).content[:max_bytes]
    u = url.lower().split("?")[0]
    if u.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(crudo), dtype=str)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = crudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if texto[:3000].count(";") > texto[:3000].count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, low_memory=False, on_bad_lines="skip")


def catalogo(diag: dict) -> dict:
    out, vistos, errores = [], set(), []
    consultas = ["estimaciones agricolas", "djve", "declaraciones juradas ventas exterior", "exportaciones agroindustriales",
                 "precios fob", "faena bovina", "existencias ganaderas", "molienda", "trigo maiz soja", "retenciones derechos exportacion"]
    for base in CKANS:
        for q in consultas:
            try:
                res = get(f"{base}/package_search", params={"q": q, "rows": 15}).json()["result"]["results"]
            except Exception as e:
                errores.append(f"{base[:30]} {q}: {e}"[:150]); continue
            for p in res:
                if p["name"] in vistos:
                    continue
                vistos.add(p["name"])
                out.append({"base": base.split("/")[2], "name": p["name"], "title": p.get("title"), "modified": (p.get("metadata_modified") or "")[:10],
                            "resources": [{"name": r.get("name"), "format": (r.get("format") or "").lower(), "url": r.get("url"),
                                           "modified": (r.get("last_modified") or r.get("created") or "")[:10]} for r in p.get("resources", [])][:10]})
    diag["errors"] = errores
    diag["datasets"] = out
    muestras = {}
    claves = ("estimac", "djve", "declarac", "export", "fob", "faena", "existenc", "molienda")
    for d in out:
        if not any(k in norm(d["name"] + " " + (d["title"] or "")) for k in claves):
            continue
        for r in [r for r in d["resources"] if r["format"] in ("csv", "xlsx") or (r["url"] or "").lower().split("?")[0].endswith((".csv", ".xlsx"))][:3]:
            try:
                df = leer(r["url"], 6_000_000)
                muestras[f'{d["name"]} | {r["name"]}'[:120]] = {"url": r["url"], "rows": int(len(df)), "columns": list(df.columns)[:30],
                                                               "tail": df.tail(2).astype(str).to_dict(orient="records")}
            except Exception as e:
                muestras[f'{d["name"]} | {r["name"]}'[:120]] = {"url": r["url"], "error": f"{type(e).__name__}: {str(e)[:120]}"}
    diag["samples"] = muestras
    return {"n": len(out)}


def series(diag: dict) -> dict:
    out = []
    for q in ("bienes cobros oleaginosas cereales", "cobros exportaciones agro", "exportaciones productos primarios", "exportaciones manufacturas origen agropecuario",
              "liquidacion divisas agroexportadoras", "faena bovina", "precio novillo", "produccion soja", "exportaciones cereales"):
        try:
            for r in get(f"{SERIES_API}/search/", params={"q": q, "limit": 15}).json().get("data", []):
                f = r.get("field", {})
                out.append([q, f.get("id"), (f.get("description") or "")[:100], f.get("frequency"), f.get("time_index_end"), (r.get("dataset") or {}).get("title", "")[:60]])
        except Exception as e:
            out.append([q, "ERROR", str(e)[:100]])
    diag["series"] = out
    return {"n": len(out)}


MAGYP = {"name": "Secretaría de Agricultura, Ganadería y Pesca, estimaciones agrícolas", "url": "https://datos.magyp.gob.ar/dataset/estimaciones-agricolas", "license": "CC BY 4.0"}
CULTIVOS = {"soja total": "soy", "maíz": "corn", "trigo total": "wheat", "girasol": "sunflower", "cebada total": "barley", "sorgo": "sorghum", "maní": "peanut"}


def num(sr):
    return pd.to_numeric(sr.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def estimaciones(diag: dict) -> dict:
    pk = get("https://datos.magyp.gob.ar/api/3/action/package_show", params={"id": "estimaciones-agricolas"}).json()["result"]
    r = next(r for r in pk["resources"] if norm(r.get("name")) == "estimaciones agricolas" and (r.get("url") or "").lower().endswith(".csv"))
    diag["resource"] = r["url"]
    df = leer(r["url"])
    df = df[df["cultivo"].isin(CULTIVOS)].copy()
    for c in ("superficie_sembrada_ha", "superficie_cosechada_ha", "produccion_tm"):
        df[c] = num(df[c]).fillna(0)
    df["crop"] = df["cultivo"].map(CULTIVOS)
    df["camp"] = df["campania"].astype(str)
    df["dep_id"] = df["departamento_id"].astype(str).str.split(".").str[0].str.zfill(5)
    ult = df.groupby("crop")["camp"].max().to_dict()
    camp = max(ult.values())
    diag["latest"] = ult
    # Serie nacional por campaña y cultivo
    nat = df.groupby(["camp", "crop"])[["superficie_sembrada_ha", "superficie_cosechada_ha", "produccion_tm"]].sum().reset_index()
    camps = sorted(nat["camp"].unique())[-25:]
    serie = {c: [] for c in CULTIVOS.values()}
    for _, x in nat[nat["camp"].isin(camps)].iterrows():
        rend = x["produccion_tm"] / x["superficie_cosechada_ha"] * 1000 if x["superficie_cosechada_ha"] else None
        serie[x["crop"]].append({"campaign": x["camp"], "planted_ha": int(x["superficie_sembrada_ha"]), "production_t": int(x["produccion_tm"]),
                                 "yield_kg_ha": round(rend) if rend else None})
    # Provincias, última campaña
    d = df[df["camp"] == camp]
    prov = d.groupby("provincia")["produccion_tm"].sum().sort_values(ascending=False)
    prov_crop = d.pivot_table(index="provincia", columns="crop", values="produccion_tm", aggfunc="sum").fillna(0)
    total = float(prov.sum())
    provincias = [{"name": n, "production_t": int(v), "share_pct": round(v / total * 100, 1),
                   "by_crop": {c: int(prov_crop.loc[n, c]) for c in prov_crop.columns if prov_crop.loc[n, c] > 0}} for n, v in prov.items() if v > 0]
    # Departamentos, última campaña: producción por cultivo
    dep = d.groupby(["dep_id", "departamento", "provincia", "crop"])["produccion_tm"].sum().reset_index()
    deps = {}
    for _, x in dep.iterrows():
        k = x["dep_id"]
        e = deps.setdefault(k, {"id": k, "name": x["departamento"], "province": x["provincia"], "by_crop": {}})
        if x["produccion_tm"] > 0:
            e["by_crop"][x["crop"]] = int(x["produccion_tm"])
    lista = [dict(v, total_t=sum(v["by_crop"].values())) for v in deps.values()]
    lista = [x for x in lista if x["total_t"] > 0]
    # Centroides (Georef, API oficial de normalización geográfica)
    try:
        g = get("https://apis.datos.gob.ar/georef/api/departamentos", params={"max": 1000, "campos": "id,centroide"}).json()["departamentos"]
        cen = {x["id"]: x["centroide"] for x in g}
        for x in lista:
            c = cen.get(x["id"])
            if c:
                x["lat"], x["lon"] = round(c["lat"], 3), round(c["lon"], 3)
        diag["deps_with_coords"] = sum(1 for x in lista if "lat" in x)
    except Exception as e:
        diag["georef_error"] = str(e)[:200]
    lista.sort(key=lambda x: x["total_t"], reverse=True)
    cba = next((p for p in provincias if norm(p["name"]) == "cordoba"), None)
    return {"source": MAGYP, "campaign": camp, "latest_by_crop": ult, "national": serie, "provinces": provincias,
            "departments": lista, "total_t": int(total), "cordoba": cba}


def banco_mundial(diag: dict) -> dict:
    html = get("https://www.worldbank.org/en/research/commodity-markets").text
    links = sorted(set(re.findall(r'href="([^"]+CMO-Historical-Data-Monthly\.xlsx)"', html)))
    if not links:
        raise RuntimeError("No se encontró el archivo mensual del Banco Mundial")
    url = links[0] if links[0].startswith("http") else "https://www.worldbank.org" + links[0]
    m = pd.read_excel(io.BytesIO(get(url, timeout=180).content), sheet_name="Monthly Prices", header=None, dtype=object)
    fila = next(i for i in range(15) if any(isinstance(v, str) and "soybean" in v.lower() for v in m.iloc[i].tolist()))
    nombres = [str(v).strip() if pd.notna(v) else "" for v in m.iloc[fila].tolist()]
    unidades = [str(v).strip() if pd.notna(v) else "" for v in m.iloc[fila + 1].tolist()]
    quiero = [("soybeans", "soybeans"), ("soybean_oil", "soybean oil"), ("soybean_meal", "soybean meal"), ("maize", "maize"),
              ("wheat", "wheat, us hrw"), ("sunflower_oil", "sunflower oil"), ("beef", "beef")]
    cols = {}
    for clave, pal in quiero:
        j = next((j for j, n in enumerate(nombres) if norm(n).startswith(pal)), None)
        if j is not None:
            cols[clave] = j
    out = {}
    datos = m.iloc[fila + 2:]
    for clave, j in cols.items():
        pts = []
        for _, r in datos.iterrows():
            mm = re.match(r"^(\d{4})M(\d{2})$", str(r.iloc[0]))
            v = pd.to_numeric(r.iloc[j], errors="coerce")
            if mm and pd.notna(v) and mm.group(1) >= "2010":
                pts.append({"period": f"{mm.group(1)}-{mm.group(2)}", "v": round(float(v), 2)})
        out[clave] = {"name": nombres[j], "unit": unidades[j], "monthly": pts}
    diag["found"] = {k: [v["name"], v["unit"], len(v["monthly"])] for k, v in out.items()}
    return {"source": {"name": "World Bank, Commodity Price Data (Pink Sheet)", "url": "https://www.worldbank.org/en/research/commodity-markets", "license": "CC BY 4.0"}, "prices": out}


def serie_api(ids, desde="2005-01-01"):
    j = get(f"{SERIES_API}/series/", params={"ids": ",".join(ids), "format": "json", "limit": 1000, "start_date": desde}).json()
    return j.get("data", [])


def divisas(diag: dict) -> dict:
    """Liquidación de divisas de la agroexportación (CIARA-CEC), publicada en la API de Series de Tiempo."""
    filas = [x for x in serie_api(["349.2_ACUM_MENSUAL__13"], "2010-01-01") if x[1] is not None]
    if len(filas) < 24:
        raise RuntimeError(f"Serie corta: {len(filas)}")
    m = [{"period": x[0][:7], "usd_m": round(float(x[1]), 1)} for x in filas]
    diag["last"] = m[-1]
    # La serie viene en millones de USD; si viniera en USD se ajusta.
    if max(x["usd_m"] for x in m) > 1e6:
        for x in m:
            x["usd_m"] = round(x["usd_m"] / 1e6, 1)
    u12, p12 = m[-12:], m[-24:-12]
    return {"source": {"name": "CIARA-CEC, liquidación de divisas de la agroexportación (API de Series de Tiempo)", "url": "https://datos.gob.ar/series/api/series/?ids=349.2_ACUM_MENSUAL__13", "license": "CC BY 4.0"},
            "monthly": m, "last_12m": round(sum(x["usd_m"] for x in u12), 1), "prev_12m": round(sum(x["usd_m"] for x in p12), 1), "latest_period": m[-1]["period"]}


EXPO_IDS = {"primary": "75.2_IETPP_0_T_43", "moa": "75.2_ITMOA_0_T_13", "cereals": "75.2_IEC_0_T_26"}


def exportaciones(diag: dict) -> dict:
    out = {}
    for k, i in EXPO_IDS.items():
        d = {x[0][:7]: x[1] for x in serie_api([i], "2010-01-01") if x[1] is not None}
        diag[k] = [len(d), max(d) if d else None]
        out[k] = d
    # Años completos (4 trimestres) para primarios y manufacturas de origen agropecuario
    anios = {}
    for k in ("primary", "moa"):
        for p, v in out[k].items():
            anios.setdefault(p[:4], {}).setdefault(k, []).append(v)
    yearly = [{"year": int(y), "primary": round(sum(v["primary"]), 1), "moa": round(sum(v["moa"]), 1)}
              for y, v in sorted(anios.items()) if len(v.get("primary", [])) == 4 and len(v.get("moa", [])) == 4]
    ult = max(set(out["primary"]) & set(out["moa"])) if out["primary"] and out["moa"] else None
    return {"source": {"name": "INDEC, exportaciones por grandes rubros (API de Series de Tiempo)", "url": "https://datos.gob.ar/series", "license": "CC BY 4.0"},
            "yearly": yearly, "latest_quarter": {"period": ult, "primary": out["primary"].get(ult), "moa": out["moa"].get(ult)} if ult else None,
            "note_moa": "Manufacturas de origen agropecuario: harinas, aceites, carnes, lácteos y otros productos industrializados del agro."}


def main() -> None:
    status, salida = {}, {}
    previo = DATA / "agro.json"
    if previo.exists():
        try:
            salida = json.loads(previo.read_text(encoding="utf-8"))
        except Exception:
            salida = {}
    for nombre, fn in [("crops", estimaciones), ("prices", banco_mundial), ("fx_settlements", divisas), ("exports", exportaciones)]:
        diag: dict = {}
        try:
            salida[nombre] = fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diag": diag, "trace": traceback.format_exc()[-1000:]}
        print(nombre, status[nombre]["ok"], file=sys.stderr)
    import math
    def limpio(x):
        if isinstance(x, float):
            return None if math.isnan(x) or math.isinf(x) else x
        if isinstance(x, dict):
            return {str(k): limpio(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [limpio(v) for v in x]
        if hasattr(x, "item"):
            return limpio(x.item())
        return x
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    previo.write_text(json.dumps(limpio(salida), ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str) + "\n", encoding="utf-8")
    (DATA / "agro_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
