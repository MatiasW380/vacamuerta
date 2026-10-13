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


def estructura(diag: dict) -> dict:
    est = leer("https://datos.magyp.gob.ar/dataset/9e1e77ba-267e-4eaa-a59f-3296e86b5f36/resource/95d066e6-8a0f-4a80-b59d-6f28f88eacd5/download/estimaciones-agricolas-2026-03.csv")
    diag["est_cultivos"] = est.groupby("cultivo")["campania"].max().to_dict()
    diag["est_rows"] = int(len(est))
    fob = leer("https://infra.datos.gob.ar/catalog/sspm/dataset/358/distribution/358.1/download/precios-fob-oficiales-valores-diarios.csv")
    diag["fob_cols"] = list(fob.columns)
    diag["fob_tail"] = fob.tail(2).to_dict(orient="records")
    pk = get("https://datos.magyp.gob.ar/api/3/action/package_show", params={"id": "estimaciones-agricolas"}).json()["result"]
    diag["est_resources"] = [(r.get("name"), r.get("url")) for r in pk.get("resources", [])]
    g = get("https://apis.datos.gob.ar/georef/api/departamentos", params={"max": 3, "campos": "id,nombre,centroide,provincia.nombre"}).json()
    diag["georef_sample"] = g
    return {}


def main() -> None:
    status, salida = {}, {}
    for nombre, fn in [("structure", estructura)]:
        diag: dict = {}
        try:
            salida[nombre] = fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diag": diag, "trace": traceback.format_exc()[-1000:]}
        print(nombre, status[nombre]["ok"], file=sys.stderr)
    (DATA / "agro_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
