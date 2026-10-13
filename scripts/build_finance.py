"""Finanzas: reservas, tasas, dinero y crédito, inflación, actividad y cuentas fiscales.

Fuentes públicas sin clave: API de estadísticas del BCRA y API de Series de Tiempo (INDEC, Ministerio de Economía).
Etapa 1: relevamiento (data/finance_status.json).
"""

from __future__ import annotations

import json
import re
import sys
import time
import traceback
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ArgentinaInvestMonitor/1.0; +https://github.com/MatiasW380/vacamuerta)"}
BCRA = "https://api.bcra.gob.ar/estadisticas"
SERIES_API = "https://apis.datos.gob.ar/series/api"


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


def bcra_catalogo(diag: dict) -> dict:
    out = {}
    for v in ("v4.0", "v3.0"):
        try:
            j = get(f"{BCRA}/{v}/monetarias", timeout=60).json()
            res = j.get("results") or []
            out[v] = [{k: x.get(k) for k in ("idVariable", "descripcion", "categoria", "fecha", "valor", "ultFechaInformada", "ultValorInformado", "unidadExpresion", "periodicidad")} for x in res]
        except Exception as e:
            out[v] = f"{type(e).__name__}: {str(e)[:200]}"
    diag["variables"] = out
    return {}


def series_buscar(diag: dict) -> dict:
    out = []
    for q in ("ipc nivel general nacional", "inflacion mensual", "emae", "resultado primario sector publico nacional", "resultado financiero",
              "deuda bruta administracion central", "reservas internacionales", "tasa badlar", "tasa de politica monetaria", "depositos privados", "prestamos privados", "salarios registrados"):
        try:
            for r in get(f"{SERIES_API}/search/", params={"q": q, "limit": 10}).json().get("data", []):
                f = r.get("field", {})
                if (f.get("time_index_end") or "") >= "2026":
                    out.append([q, f.get("id"), (f.get("description") or "")[:100], f.get("frequency"), f.get("time_index_end"), (r.get("dataset") or {}).get("title", "")[:60]])
        except Exception as e:
            out.append([q, "ERROR", str(e)[:100]])
    diag["series"] = out
    return {}


def main() -> None:
    status = {}
    for nombre, fn in [("bcra", bcra_catalogo), ("series", series_buscar)]:
        diag: dict = {}
        try:
            fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diag": diag, "trace": traceback.format_exc()[-1000:]}
        print(nombre, status[nombre]["ok"], file=sys.stderr)
    (DATA / "finance_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
