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


BCRA_SRC = {"name": "BCRA, API de estadísticas monetarias", "url": "https://www.bcra.gob.ar/en/central-bank-api-catalog/", "license": "Datos públicos"}
VARS = {"reserves": 1, "fx_retail": 4, "fx_wholesale": 5, "badlar": 7, "tamar": 44, "term30": 12, "personal": 14, "overdraft": 13,
        "infl_m": 27, "infl_y": 28, "rem": 29, "base": 15, "dep_ars": 100, "dep_usd": 108, "loan_ars": 117, "loan_usd": 125}


def bcra_serie(idv: int, desde: str, diag: dict) -> list:
    """Serie diaria o mensual del BCRA, en tramos de un año (límite de la API)."""
    out, ini = [], date.fromisoformat(desde)
    hoy = date.today()
    while ini <= hoy:
        fin = min(hoy, ini + timedelta(days=364))
        j = None
        for v in ("v4.0", "v3.0"):
            try:
                j = get(f"{BCRA}/{v}/monetarias/{idv}", params={"desde": ini.isoformat(), "hasta": fin.isoformat(), "limit": 3000}, timeout=60).json()
                break
            except Exception as e:
                diag.setdefault("errors", []).append(f"{idv} {v} {ini}: {type(e).__name__}")
        res = (j or {}).get("results") or []
        if res and isinstance(res[0], dict) and "detalle" in res[0]:
            res = [d for r in res for d in r.get("detalle", [])]
        for r in res:
            if r.get("fecha") and r.get("valor") is not None:
                out.append((r["fecha"][:10], float(r["valor"])))
        ini = fin + timedelta(days=1)
    return sorted(set(out))


def mensual(serie: list) -> dict:
    """Último valor de cada mes."""
    m = {}
    for f, v in serie:
        m[f[:7]] = v
    return m


def bcra_datos(diag: dict) -> dict:
    out = {}
    largos = {"reserves": "2016-01-01", "infl_m": "2017-01-01", "infl_y": "2017-01-01", "rem": "2018-01-01"}
    for k, i in VARS.items():
        s = bcra_serie(i, largos.get(k, "2021-01-01"), diag)
        diag.setdefault("points", {})[k] = [len(s), s[-1] if s else None]
        out[k] = s
    if not out["reserves"]:
        raise RuntimeError("La API del BCRA no devolvió reservas")
    semanal = lambda s, desde: [{"date": f, "v": round(v, 2)} for i, (f, v) in enumerate(s) if f >= desde and (i % 5 == 0 or i == len(s) - 1)]
    ult = lambda k: {"date": out[k][-1][0], "v": out[k][-1][1]} if out[k] else None
    hace = lambda k, dias: next((v for f, v in reversed(out[k]) if f <= (date.fromisoformat(out[k][-1][0]) - timedelta(days=dias)).isoformat()), None) if out[k] else None
    tasas = {}
    for k in ("badlar", "tamar", "term30", "personal", "overdraft"):
        if out[k]:
            tasas[k] = {"latest": ult(k), "m1": hace(k, 30), "y1": hace(k, 365)}
    # Depósitos y préstamos privados: pesos convertidos a dólares con el mayorista, dólares tal cual
    fxm = mensual(out["fx_wholesale"])
    credito = {}
    for k in ("dep_ars", "dep_usd", "loan_ars", "loan_usd"):
        mm = mensual(out[k])
        credito[k] = [{"period": p, "v": round(v / fxm[p] if k.endswith("ars") and fxm.get(p) else v, 1)} for p, v in sorted(mm.items()) if (not k.endswith("ars") or fxm.get(p))]
    im, iy = mensual(out["infl_m"]), mensual(out["infl_y"])
    return {"source": BCRA_SRC,
            "reserves": {"latest": ult("reserves"), "y1": hace("reserves", 365), "weekly": semanal(out["reserves"], "2016-01-01")},
            "fx": {"wholesale": ult("fx_wholesale"), "retail": ult("fx_retail"), "wholesale_y1": hace("fx_wholesale", 365),
                   "weekly_wholesale": semanal(out["fx_wholesale"], "2023-01-01"), "weekly_retail": semanal(out["fx_retail"], "2023-01-01")},
            "rates": tasas,
            "rates_weekly": {k: semanal(out[k], "2024-01-01") for k in ("badlar", "tamar", "term30")},
            "inflation": {"monthly": [{"period": p, "m": im[p], "y": iy.get(p)} for p in sorted(im)], "expected_12m": ult("rem")},
            "credit_usd_equiv": credito,
            "monetary_base_ars_m": ult("base")}


def serie_api(ids, desde="2015-01-01"):
    j = get(f"{SERIES_API}/series/", params={"ids": ",".join(ids), "format": "json", "limit": 1000, "start_date": desde}).json()
    return [x for x in j.get("data", []) if all(v is not None for v in x[1:])]


def buscar(q, debe, prefijo, diag, clave):
    res = get(f"{SERIES_API}/search/", params={"q": q, "limit": 40}).json().get("data", [])
    c = []
    for r in res:
        f = r.get("field", {})
        txt = norm(f.get("description"))
        if all(d in txt for d in debe) and (f.get("id") or "").startswith(prefijo) and f.get("frequency") == "R/P1M":
            c.append({"id": f["id"], "desc": f.get("description"), "end": f.get("time_index_end"), "units": f.get("units")})
    c.sort(key=lambda x: x["end"] or "", reverse=True)
    diag[f"cand_{clave}"] = c[:5]
    return c[0] if c else None


def fiscal(diag: dict) -> dict:
    prim = buscar("resultado primario metodologia 2017 sector publico nacional", ["resultado primario"], "379.9", diag, "prim")
    fin = buscar("resultado financiero metodologia 2017 sector publico nacional", ["resultado financiero"], "379.9", diag, "fin")
    if not prim or not fin:
        raise RuntimeError("No se encontraron las series fiscales mensuales")
    d = serie_api([prim["id"], fin["id"]], "2017-01-01")
    filas = [{"period": x[0][:7], "primary": round(x[1], 1), "financial": round(x[2], 1)} for x in d]
    anio = filas[-1]["period"][:4]
    ytd = [f for f in filas if f["period"][:4] == anio]
    return {"source": {"name": "Ministerio de Economía, resultado del Sector Público Nacional (API de Series de Tiempo)", "url": "https://datos.gob.ar/series", "license": "CC BY 4.0"},
            "units": prim.get("units"), "ids": [prim["id"], fin["id"]], "monthly": filas,
            "ytd": {"year": anio, "months": len(ytd), "primary": round(sum(f["primary"] for f in ytd), 1), "financial": round(sum(f["financial"] for f in ytd), 1)}}


def actividad(diag: dict) -> dict:
    c = buscar("emae nivel general desestacionalizado", ["emae"], "143", diag, "emae") or buscar("estimador mensual actividad economica desestacionalizada", ["desestacionalizad"], "143", diag, "emae2")
    o = buscar("emae original nivel general", ["emae"], "143", diag, "emae_o")
    if not c:
        raise RuntimeError("Sin EMAE")
    d = serie_api([c["id"]], "2016-01-01")
    return {"source": {"name": "INDEC, Estimador Mensual de Actividad Económica (API de Series de Tiempo)", "url": "https://datos.gob.ar/series", "license": "CC BY 4.0"},
            "id": c["id"], "desc": c["desc"], "monthly": [{"period": x[0][:7], "v": round(x[1], 2)} for x in d]}


def main() -> None:
    status, salida = {}, {}
    destino = DATA / "finance.json"
    if destino.exists():
        try:
            salida = json.loads(destino.read_text(encoding="utf-8"))
        except Exception:
            salida = {}
    for nombre, fn in [("bcra", bcra_datos), ("fiscal", fiscal), ("activity", actividad)]:
        diag: dict = {}
        try:
            salida[nombre] = fn(diag)
            status[nombre] = {"ok": True, "diag": diag}
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diag": diag, "trace": traceback.format_exc()[-1000:]}
        print(nombre, status[nombre]["ok"], file=sys.stderr)
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    destino.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":"), default=str) + "\n", encoding="utf-8")
    (DATA / "finance_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
