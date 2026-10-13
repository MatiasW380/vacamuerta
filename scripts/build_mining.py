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
    tareas = [("catalog", catalogo), ("series", series_buscar), ("world_bank", banco_mundial), ("segemar", segemar)]
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
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    salida.pop("status", None)
    salida_p.write_text(json.dumps(salida, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    (DATA / "mining_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
