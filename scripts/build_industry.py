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


def main() -> None:
    status = {}
    for nombre, fn in [("series", series_buscar), ("catalog", catalogo)]:
        diag: dict = {}
        try:
            fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diag": diag, "trace": traceback.format_exc()[-1000:]}
        print(nombre, status[nombre]["ok"], file=sys.stderr)
    (DATA / "industry_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
