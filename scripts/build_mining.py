"""Minería: proyectos, comercio exterior, precios de los metales y RIGI.

Fuentes públicas (todas sin clave):
    - SIACAM, Secretaría de Minería, en datos.gob.ar (CKAN): proyectos, comercio, empleo, impuestos.
    - API de Series de Tiempo (INDEC): exportaciones mineras.
    - Banco Mundial, "Pink Sheet": precios mensuales de cobre, oro, plata (CC BY 4.0).
    - SEGEMAR / SIGAM: capas geográficas.

Salida:
    data/mining.json          datos para el tablero /mineria/
    data/mining_status.json   diagnóstico por fuente
"""

from __future__ import annotations

import io
import json
import re
import sys
import traceback
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DATA = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ArgentinaInvestMonitor/1.0; +https://github.com/MatiasW380/vacamuerta)"}
CKAN = "https://datos.gob.ar/api/3/action"
SERIES_API = "https://apis.datos.gob.ar/series/api"


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def get(url, **kw):
    import time
    timeout = kw.pop("timeout", 90)
    for intento in range(4):
        r = requests.get(url, headers=UA, timeout=timeout, **kw)
        if r.status_code in (502, 503, 504) and intento < 3:
            time.sleep(4 * (intento + 1))
            continue
        r.raise_for_status()
        return r


def leer(url: str, max_bytes: int = 60_000_000) -> pd.DataFrame:
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
    return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, low_memory=False)


URLS = {
    "expo": "https://www.mecon.gob.ar/dataset/Comercio/expominerales-siacam.csv",
    "expo_sector": "https://www.mecon.gob.ar/dataset/Comercio/expo-mineria-por-sector.csv",
    "expo_prov": "https://www.mecon.gob.ar/dataset/Comercio/expo-mineria-por-provincia.csv",
    "expo_prod": "https://www.mecon.gob.ar/dataset/Comercio/principales-productos-mineros-exportados.csv",
    "balanza": "https://www.mecon.gob.ar/dataset/Comercio/balanza-comercial-mineria.csv",
    "litio": "https://www.mecon.gob.ar/dataset/Tablero-Litio/Exportaciones-litio.csv",
    "litio_dest": "https://www.mecon.gob.ar/dataset/Tablero-Litio/Exportaciones-por-destino-litio.csv",
    "empleo": "https://www.mecon.gob.ar/dataset/Empleo-rubro-prov.csv",
    "ipi": "https://www.mecon.gob.ar/dataset/ipi-minero/ipi-minero-series.csv",
    "ipi_ramas": "https://www.mecon.gob.ar/dataset/ipi-minero/ipi-minero-ramas-actividad.csv",
    "ipi_litio": "https://www.mecon.gob.ar/dataset/ipi-minero/ipi-minero-produccion-litio.csv",
    "precios": "https://www.mecon.gob.ar/dataset/precios-internacionales-minerales.xlsx",
    "cartera": "https://www.mecon.gob.ar/dataset/Cartera-de-Proyectos-Mineros-Metaliferos-y-Litio-del-SIACAM.xlsx",
    "anuncios": None,
}


def estructura(diag: dict) -> dict:
    """Columnas, últimas filas y valores distintos de las columnas de texto de cada archivo."""
    out = {}
    for k, u in URLS.items():
        if not u:
            continue
        try:
            df = leer(u)
            info = {"rows": int(len(df)), "columns": list(df.columns)[:30], "tail": df.tail(2).astype(str).to_dict(orient="records")}
            cats = {}
            for c in df.columns[:30]:
                vals = df[c].dropna().unique()
                if 1 < len(vals) <= 40 and not pd.to_numeric(pd.Series(vals), errors="coerce").notna().all():
                    cats[c] = [str(v)[:40] for v in vals[:40]]
            info["categories"] = cats
            out[k] = info
        except Exception as e:
            out[k] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    diag["files"] = out
    return {"n": len(out)}


# ---------------------------------------------------------------------------
# Datos del tablero
# ---------------------------------------------------------------------------
SIACAM = {"name": "Secretaría de Minería, SIACAM", "url": "https://www.argentina.gob.ar/economia/mineria/siacam", "license": "CC BY 4.0"}


def num(sr: pd.Series) -> pd.Series:
    t = sr.astype(str).str.strip().str.replace("\u00a0", "", regex=False)
    t = t.where(~t.str.contains(r"\d\.\d{3},"), t.str.replace(".", "", regex=False))
    return pd.to_numeric(t.str.replace(",", ".", regex=False), errors="coerce")


def fecha_dmy(sr: pd.Series) -> pd.Series:
    """'1/7/2026' (día/mes/año) o '2026-03-01' → '2026-07'."""
    def f(v):
        v = str(v).strip()
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", v)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}"
        m = re.match(r"^(\d{4})-(\d{2})", v)
        return f"{m.group(1)}-{m.group(2)}" if m else None
    return sr.map(f)


def exportaciones(diag: dict) -> dict:
    df = leer(URLS["expo"])
    df["v"] = num(df["FOB"]) / 1e6
    df["period"] = df["ANYO"].str.strip() + "-" + num(df["MES"]).astype("Int64").astype(str).str.zfill(2)
    df = df[df["v"].notna() & df["period"].str.match(r"^\d{4}-\d{2}$")]
    meses = sorted(df["period"].unique())
    ult = meses[-1]
    u12 = meses[-12:]; p12 = meses[-24:-12]
    tot = df.groupby("period")["v"].sum()
    sect = df.pivot_table(index="period", columns="SECTOR", values="v", aggfunc="sum").fillna(0)
    anual = df.assign(y=df["period"].str[:4]).pivot_table(index="y", columns="SECTOR", values="v", aggfunc="sum").fillna(0)
    meses_ult_anio = sum(1 for m in meses if m[:4] == ult[:4])
    grupos12 = df[df["period"].isin(u12)].groupby(["GRUPO", "SECTOR"])["v"].sum().sort_values(ascending=False)
    grupos_prev = df[df["period"].isin(p12)].groupby("GRUPO")["v"].sum()
    roll = tot.rolling(12).sum().dropna()
    diag["latest"] = ult
    return {
        "source": SIACAM, "latest_period": ult, "units": "USD million",
        "last_12m": round(float(tot.loc[u12].sum()), 1), "prev_12m": round(float(tot.loc[p12].sum()), 1),
        "rolling_12m": [{"period": p, "v": round(float(v), 1)} for p, v in roll.items() if p >= "2008-01"],
        "yearly_by_sector": {"years": list(anual.index), "partial_last": meses_ult_anio < 12, "months_last": meses_ult_anio,
                              "sectors": {c: [round(float(x), 1) for x in anual[c]] for c in anual.columns}},
        "groups_12m": [{"name": g, "sector": sc, "v": round(float(v), 1), "prev": round(float(grupos_prev.get(g, 0)), 1)} for (g, sc), v in grupos12.head(14).items()],
        "monthly_by_sector_last": {c: round(float(sect.loc[ult, c]), 1) for c in sect.columns},
    }


def anual_simple(url: str, cat: str, val: str) -> pd.DataFrame:
    df = leer(url)
    df["v"] = num(df[val])
    return df


def provincias_y_productos(diag: dict) -> dict:
    pv = anual_simple(URLS["expo_prov"], "PROVINCIA", "USD_FOB")
    y = pv["ANYO"].max()
    top = pv[pv["ANYO"] == y].sort_values("v", ascending=False)
    pr = anual_simple(URLS["expo_prod"], "PRODUCTO", "USD_FOB")
    yp = pr["ANYO"].max()
    prod = pr[pr["ANYO"] == yp].sort_values("v", ascending=False)
    bz = leer(URLS["balanza"]); bz["v"] = num(bz["USD_BALANZA_COMERCIAL_MINERA"])
    return {"year": y, "provinces": [{"name": r["PROVINCIA"].title().replace(" Del ", " del "), "v": round(float(r["v"]), 1)} for _, r in top.iterrows() if r["v"] > 0.5][:12],
            "products_year": yp, "products": [{"name": r["PRODUCTO"], "v": round(float(r["v"]), 1)} for _, r in prod.iterrows()][:12],
            "trade_balance": [{"year": int(r["ANYO"]), "v": round(float(r["v"]), 1)} for _, r in bz.iterrows() if pd.notna(r["v"])]}


def litio(diag: dict) -> dict:
    ex = leer(URLS["litio"]); ex["v"] = num(ex["Exportaciones_FOB"]); ex["share"] = num(ex["Participación_sobre_total_exportado"])
    de = leer(URLS["litio_dest"]); de["v"] = num(de["Suma_de_FOB"])
    yd = de["Año"].max()
    pr = leer(URLS["ipi_litio"]); pr["period"] = fecha_dmy(pr["Periodo"]); pr["t"] = num(pr["Carbonato_de_Litio_TN"])
    pr = pr.dropna(subset=["period", "t"]).sort_values("period")
    return {"exports_yearly": [{"year": int(r["Año"]), "v": round(float(r["v"]), 1), "share_pct": round(float(r["share"]) * 100, 1) if pd.notna(r["share"]) else None} for _, r in ex.iterrows() if pd.notna(r["v"])],
            "destinations_year": int(yd), "destinations": [{"name": r["Destino"], "v": round(float(r["v"]), 1)} for _, r in de[de["Año"] == yd].sort_values("v", ascending=False).iterrows()],
            "carbonate_t_monthly": [{"period": r["period"], "t": round(float(r["t"]), 1)} for _, r in pr.iterrows()]}


def ipi(diag: dict) -> dict:
    df = leer(URLS["ipi"]); df["period"] = fecha_dmy(df["Fecha"]); df["v"] = num(df["Indice"])
    out = {}
    for serie, clave in (("Serie Original", "original"), ("Serie Desestacionalizada", "sa"), ("Tendencia - Ciclo", "trend")):
        d = df[df["Serie"] == serie].dropna(subset=["period", "v"]).sort_values("period")
        out[clave] = [{"period": p, "v": round(float(v), 1)} for p, v in zip(d["period"], d["v"])]
    o = {x["period"]: x["v"] for x in out["original"]}
    ult = max(o) if o else None
    prev = f"{int(ult[:4]) - 1}{ult[4:]}" if ult else None
    ra = leer(URLS["ipi_ramas"]); ra["period"] = fecha_dmy(ra["Fecha"]); ra["v"] = num(ra["Indice"])
    ramas = {}
    for serie, g in ra.dropna(subset=["period", "v"]).groupby("Serie"):
        g = g.sort_values("period"); m = dict(zip(g["period"], g["v"]))
        if ult in m and prev in m and m[prev]:
            ramas[serie] = round((m[ult] / m[prev] - 1) * 100, 1)
    return {"source": SIACAM, "latest_period": ult, "yoy_pct": round((o[ult] / o[prev] - 1) * 100, 1) if ult and prev in o else None,
            "series": out, "branches_yoy": ramas}


def empleo(diag: dict) -> dict:
    df = leer(URLS["empleo"]); df["period"] = fecha_dmy(df["año_mes"]); df["v"] = num(df["Cantidad"])
    pv = df.pivot_table(index="period", columns="rubro", values="v", aggfunc="sum").fillna(0).sort_index()
    tot = pv.sum(axis=1)
    ult = pv.index[-1]; prev = f"{int(ult[:4]) - 1}{ult[4:]}"
    return {"source": SIACAM, "latest_period": ult, "total": int(tot.loc[ult]), "total_prev_year": int(tot.loc[prev]) if prev in tot.index else None,
            "monthly_total": [{"period": p, "v": int(v)} for p, v in tot.items()],
            "by_branch": [{"name": c, "v": int(pv.loc[ult, c]), "prev": int(pv.loc[prev, c]) if prev in pv.index else None} for c in pv.loc[ult].sort_values(ascending=False).index]}


def precios(diag: dict) -> dict:
    df = leer(URLS["precios"]); df["v"] = num(df["Precio"])
    df["period"] = df["Fecha"].astype(str).str.replace("M", "-", regex=False).str[:7]
    claves = {"Oro (Au)": "gold", "Plata (Ag)": "silver", "Cobre (Cu)": "copper", "Carbonato de Litio 99,5% (Li2CO3)": "lithium_carbonate"}
    out = {}
    for m, k in claves.items():
        d = df[df["Mineral"].str.strip() == m].dropna(subset=["v"]).sort_values("period")
        if len(d):
            out[k] = {"name": m, "unit": d["Unidad de medida"].iloc[-1], "monthly": [{"period": p, "v": round(float(v), 2)} for p, v in zip(d["period"], d["v"]) if p >= "2015-01"]}
    diag["minerals"] = sorted(df["Mineral"].dropna().unique().tolist())
    return {"source": SIACAM, "prices": out}


def proyectos(diag: dict) -> dict:
    df = leer(URLS["cartera"])
    df.columns = [str(c).strip() for c in df.columns]
    lim = lambda v: None if pd.isna(v) or str(v).strip() in ("", "-", "nan") else str(v).strip()
    out = []
    for _, r in df.iterrows():
        lat, lon = pd.to_numeric(r.get("LATITUD"), errors="coerce"), pd.to_numeric(r.get("LONGITUD"), errors="coerce")
        if pd.isna(lat) or pd.isna(lon) or not lim(r.get("NOMBRE")):
            continue
        duenos = []
        for i in ("1°", "2°", "3°"):
            n = lim(r.get(f"CONTROLANTE ({i})"))
            if n:
                pct = pd.to_numeric(r.get(f"PORCENTAJE ({i})"), errors="coerce")
                duenos.append({"name": n, "pct": round(float(pct) * 100) if pd.notna(pct) and pct <= 1 else (round(float(pct)) if pd.notna(pct) else None), "origin": lim(r.get(f"ORIGEN ({i})"))})
        out.append({"name": lim(r["NOMBRE"]), "lat": round(float(lat), 4), "lon": round(float(lon), 4),
                    "mineral": (lim(r.get("MINERAL PRINCIPAL")) or "").strip(), "province": lim(r.get("PROVINCIA")),
                    "stage": lim(r.get("ESTADO")), "owners": duenos})
    etapas = pd.Series([p["stage"] for p in out]).value_counts().to_dict()
    minerales = pd.Series([p["mineral"] for p in out]).value_counts().to_dict()
    diag["stages"] = etapas
    return {"source": {**SIACAM, "name": "Secretaría de Minería, SIACAM: cartera de proyectos metalíferos y de litio"}, "items": out,
            "by_stage": etapas, "by_mineral": minerales}


# ---------------------------------------------------------------------------
# Relevamiento: qué publica el SIACAM y con qué columnas
# ---------------------------------------------------------------------------
def catalogo(diag: dict) -> dict:
    vistos, out = set(), []
    errores = []
    for q in ("siacam", "mineria proyectos", "mineria exportaciones", "empleo minero", "litio", "organization:mineria"):
        try:
            res = get(f"{CKAN}/package_search", params={"q": q, "rows": 25}).json()["result"]["results"]
        except Exception as e:
            errores.append(f"{q}: {e}"[:160]); continue
        for p in res:
            if p["name"] in vistos:
                continue
            vistos.add(p["name"])
            out.append({"name": p["name"], "title": p.get("title"), "org": (p.get("organization") or {}).get("title"),
                        "modified": (p.get("metadata_modified") or "")[:10],
                        "resources": [{"name": r.get("name"), "format": (r.get("format") or "").lower(), "url": r.get("url"),
                                       "modified": (r.get("last_modified") or r.get("created") or "")[:10]} for r in p.get("resources", [])][:12]})
    diag["search_errors"] = errores
    diag["datasets"] = [d for d in out if "mine" in norm(d["title"] + " " + d["name"]) or "siacam" in d["name"] or "litio" in norm(d["title"])]
    # Columnas y muestra del primer recurso tabular de cada dataset minero.
    muestras = {}
    for d in diag["datasets"][:40]:
        r = next((r for r in d["resources"] if r["format"] in ("csv", "xlsx") or (r["url"] or "").lower().split("?")[0].endswith((".csv", ".xlsx"))), None)
        if not r:
            continue
        try:
            df = leer(r["url"], 8_000_000)
            muestras[d["name"]] = {"resource": r["name"], "rows": int(len(df)), "columns": list(df.columns)[:40],
                                   "sample": df.head(2).astype(str).to_dict(orient="records")}
        except Exception as e:
            muestras[d["name"]] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    diag["samples"] = muestras
    return {"n": len(diag["datasets"])}


def series_buscar(diag: dict) -> dict:
    out = []
    for q in ("exportaciones minerales", "exportaciones mineria", "exportaciones litio", "exportaciones oro", "empleo mineria", "produccion minera"):
        for r in get(f"{SERIES_API}/search/", params={"q": q, "limit": 20}).json().get("data", []):
            f = r.get("field", {})
            out.append([f.get("id"), (f.get("description") or "")[:100], f.get("frequency"), f.get("time_index_end"), (r.get("dataset") or {}).get("title", "")[:60]])
    diag["series"] = out
    return {"n": len(out)}


def banco_mundial(diag: dict) -> dict:
    html = get("https://www.worldbank.org/en/research/commodity-markets").text
    links = sorted(set(re.findall(r'href="([^"]+CMO-Historical-Data-Monthly\.xlsx)"', html)))
    diag["links"] = links
    if not links:
        raise RuntimeError("No se encontró el enlace a CMO-Historical-Data-Monthly.xlsx")
    url = links[0] if links[0].startswith("http") else "https://www.worldbank.org" + links[0]
    hojas = pd.read_excel(io.BytesIO(get(url, timeout=180).content), sheet_name=None, header=None, dtype=object)
    diag["sheets"] = {k: [len(v), v.shape[1]] for k, v in hojas.items()}
    m = hojas.get("Monthly Prices")
    if m is None:
        raise RuntimeError("Sin hoja Monthly Prices")
    diag["head"] = [[str(x)[:22] for x in m.iloc[i].tolist()[:80] if pd.notna(x)] for i in range(min(8, len(m)))]
    return precios_metales(m, url, diag)


def precios_metales(m: pd.DataFrame, url: str, diag: dict) -> dict:
    fila = next(i for i in range(15) if any(isinstance(v, str) and "copper" in v.lower() for v in m.iloc[i].tolist()))
    nombres = [str(v).strip() if pd.notna(v) else "" for v in m.iloc[fila].tolist()]
    unidades = [str(v).strip() if pd.notna(v) else "" for v in m.iloc[fila + 1].tolist()]
    quiero = {"copper": "copper", "gold": "gold", "silver": "silver", "aluminum": "aluminum", "zinc": "zinc", "lead": "lead"}
    cols = {}
    for j, n in enumerate(nombres):
        k = norm(n)
        for clave, pal in quiero.items():
            if k.startswith(pal) and clave not in cols:
                cols[clave] = j
    datos = m.iloc[fila + 2:]
    out = {}
    for clave, j in cols.items():
        pts = []
        for _, r in datos.iterrows():
            per = str(r.iloc[0])
            mm = re.match(r"^(\d{4})M(\d{2})$", per)
            v = pd.to_numeric(r.iloc[j], errors="coerce")
            if mm and pd.notna(v):
                pts.append({"period": f"{mm.group(1)}-{mm.group(2)}", "v": round(float(v), 2)})
        out[clave] = {"unit": unidades[cols[clave]], "name": nombres[cols[clave]], "monthly": [p for p in pts if p["period"] >= "2010-01"]}
    diag["found"] = {k: [v["name"], v["unit"], len(v["monthly"])] for k, v in out.items()}
    return {"source": {"name": "World Bank, Commodity Price Data (Pink Sheet)", "url": "https://www.worldbank.org/en/research/commodity-markets", "license": "CC BY 4.0"},
            "file": url, "metals": out}


def segemar(diag: dict) -> dict:
    import xml.etree.ElementTree as ET
    out = {}
    for base in ("https://sigam.segemar.gov.ar/geoserver/wfs", "https://sigam.segemar.gov.ar/geoserver/ows"):
        try:
            r = get(base, params={"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"}, timeout=60)
            root = ET.fromstring(r.content)
            capas = []
            for ft in root.iter():
                if ft.tag.endswith("FeatureType"):
                    n = next((c.text for c in ft if c.tag.endswith("Name")), None)
                    t = next((c.text for c in ft if c.tag.endswith("Title")), "")
                    if n:
                        capas.append([n, t])
            out[base] = capas[:200]
        except Exception as e:
            out[base] = f"{type(e).__name__}: {str(e)[:160]}"
    diag["capabilities"] = out
    return {"bases": list(out)}


def main() -> None:
    previo = {}
    salida_p = DATA / "mining.json"
    if salida_p.exists():
        try:
            previo = json.loads(salida_p.read_text(encoding="utf-8"))
        except Exception:
            previo = {}
    tareas = [("exports", exportaciones), ("geo", provincias_y_productos), ("lithium", litio), ("ipi", ipi),
              ("employment", empleo), ("prices", precios), ("projects", proyectos)]
    salida, status = dict(previo), {}
    for nombre, fn in tareas:
        diag: dict = {}
        try:
            salida[nombre] = fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
            print(f"OK {nombre}", file=sys.stderr)
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:400]}", "diag": diag, "trace": traceback.format_exc()[-1200:]}
            print(f"ERROR {nombre}: {e}", file=sys.stderr)
    for viejo in ("catalog", "series", "world_bank", "segemar", "structure"):
        salida.pop(viejo, None)
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    salida.pop("status", None)
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
    salida_p.write_text(json.dumps(limpio(salida), ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=str) + "\n", encoding="utf-8")
    (DATA / "mining_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
