"""Genera data/extras.json con fuentes complementarias.

Cada sección se procesa por separado: si una fuente falla, se conserva el valor
anterior de esa sección y el error queda registrado en "status".

Secciones:
  fracking     Secretaría de Energía, Adjunto IV (datos de fractura), CC BY 4.0
  fx           BCRA, API de Estadísticas Cambiarias (dólar oficial)
  oil_price    EIA (EE. UU.), Brent y WTI diarios, dominio público. Requiere EIA_API_KEY
  regulations  Boletín Oficial, primera sección, filtrada por palabras clave
  news         Titulares de medios del sector por RSS (solo título, fecha y enlace)
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import traceback
import unicodedata
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import nombre_corto  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "extras.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; VacaMuertaMonitor/1.0; +https://github.com/MatiasW380/vacamuerta)"}
TIMEOUT = 90


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=kw.pop("timeout", TIMEOUT), **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------------------
# 1. Fractura (Adjunto IV)
# ---------------------------------------------------------------------------
FRAC_DATASET = "datos-de-fractura-de-pozos-adjunto-iv"
FRAC_API = f"http://datos.energia.gob.ar/api/3/action/package_show?id={FRAC_DATASET}"
FRAC_PAGE = f"http://datos.energia.gob.ar/dataset/{FRAC_DATASET}"


def col(df: pd.DataFrame, *patrones: str) -> str | None:
    """Primera columna cuyo nombre contiene todos los fragmentos de algún patrón."""
    for patron in patrones:
        partes = patron.split("+")
        for c in df.columns:
            if all(p in c for p in partes):
                return c
    return None


def fracking(diag: dict) -> dict:
    meta = get(FRAC_API).json()["result"]
    recursos = [r for r in meta["resources"] if (r.get("format") or "").lower() == "csv" or r.get("url", "").lower().endswith(".csv")]
    diag["resources"] = [r.get("name") for r in recursos][:10]
    if not recursos:
        raise RuntimeError("El dataset no tiene recursos CSV")
    # El recurso principal suele ser el más grande; se prueba en orden hasta encontrar etapas de fractura.
    df = None
    for r in recursos:
        crudo = get(r["url"], timeout=300).content
        texto = crudo.decode("utf-8-sig", errors="replace")
        sep = ";" if texto[:3000].count(";") > texto[:3000].count(",") else ","
        cand = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, low_memory=False)
        cand.columns = [norm(c).replace(" ", "_") for c in cand.columns]
        if col(cand, "cantidad_fractura", "fracturas", "etapas"):
            df, diag["resource_used"] = cand, r.get("name")
            break
    if df is None:
        raise RuntimeError(f"Ningún CSV tiene columna de etapas. Columnas del primero: {list(cand.columns)[:40]}")
    diag["columns"] = list(df.columns)[:60]
    diag["rows"] = int(len(df))

    c_etapas = col(df, "cantidad_fractura", "fracturas", "etapas")
    c_arena = [c for c in df.columns if "arena" in c and ("tn" in c or "ton" in c)]
    c_fecha = col(df, "fecha_inicio_fractura", "fecha_inicio", "fecha+fractura")
    c_anio, c_mes = col(df, "anio_if", "anio_inicio"), col(df, "mes_if", "mes_inicio")
    c_empresa = col(df, "empresa_informante", "empresa", "operadora")
    c_form = col(df, "formacion_productiva", "formacion")
    c_cuenca = col(df, "cuenca")
    c_pozo = col(df, "idpozo", "id_pozo", "sigla")
    c_rama = col(df, "longitud_rama", "rama_horizontal")
    diag["mapped"] = {"etapas": c_etapas, "arena": c_arena, "fecha": c_fecha, "anio": c_anio, "mes": c_mes,
                      "empresa": c_empresa, "formacion": c_form, "cuenca": c_cuenca, "pozo": c_pozo, "rama": c_rama}

    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df["_etapas"] = num(df[c_etapas]).fillna(0)
    df["_arena"] = sum(num(df[c]).fillna(0) for c in c_arena) if c_arena else 0
    df["_rama"] = num(df[c_rama]) if c_rama else float("nan")
    if c_fecha:
        f = pd.to_datetime(df[c_fecha], errors="coerce", dayfirst=False)
        df["_anio"], df["_mes"] = f.dt.year, f.dt.month
    elif c_anio and c_mes:
        df["_anio"], df["_mes"] = num(df[c_anio]), num(df[c_mes])
    else:
        raise RuntimeError("No se encontró la fecha de inicio de fractura")

    vm = pd.Series(True, index=df.index)
    if c_form:
        vm &= df[c_form].fillna("").map(norm).str.contains("vaca muerta")
    if c_cuenca:
        vm &= df[c_cuenca].fillna("").map(norm).str.contains("neuquina")
    df = df[vm & df["_anio"].notna() & (df["_etapas"] > 0)].copy()
    df["_anio"], df["_mes"] = df["_anio"].astype(int), df["_mes"].astype(int)
    df["_op"] = df[c_empresa].map(nombre_corto) if c_empresa else "Sin dato"
    df["_per"] = df["_anio"] * 100 + df["_mes"]

    hoy = date.today()
    tope = hoy.year * 100 + hoy.month
    df = df[df["_per"] < tope]  # el mes en curso siempre está incompleto
    mens = df.groupby("_per").agg(stages=("_etapas", "sum"), sand_t=("_arena", "sum"),
                                  wells=("_etapas", "size"), lateral_m=("_rama", "mean")).sort_index()
    # Los últimos meses llegan incompletos (las operadoras declaran con demora):
    # se descartan mientras estén por debajo del 50% del promedio de los 6 meses previos.
    while len(mens) > 8 and mens["stages"].iloc[-1] < 0.5 * mens["stages"].iloc[-7:-1].mean():
        diag.setdefault("dropped_incomplete", []).append(int(mens.index[-1]))
        mens = mens.iloc[:-1]
    mens = mens.tail(48)
    monthly = [{
        "period": f"{p // 100:04d}-{p % 100:02d}",
        "stages": int(r.stages), "wells": int(r.wells),
        "sand_t": int(round(r.sand_t)) if r.sand_t else None,
        "lateral_m": int(round(r.lateral_m)) if pd.notna(r.lateral_m) else None,
    } for p, r in mens.iterrows()]

    ult12 = [m["period"] for m in monthly[-12:]]
    per12 = {int(p.replace("-", "")) for p in ult12}
    previos = {int(m["period"].replace("-", "")) for m in monthly[-24:-12]}
    d12 = df[df["_per"].isin(per12)]
    ops = d12.groupby("_op")["_etapas"].sum().sort_values(ascending=False)
    total12 = float(ops.sum())
    prev12 = float(df[df["_per"].isin(previos)]["_etapas"].sum())
    operators = [{"name": n, "stages_12m": int(v), "share_pct": round(v / total12 * 100, 1) if total12 else None}
                 for n, v in ops.head(8).items()]
    return {
        "source": {"name": "Secretaría de Energía, Adjunto IV (datos de fractura)", "url": FRAC_PAGE, "license": "CC BY 4.0"},
        "monthly": monthly,
        "stages_12m": int(total12),
        "stages_12m_yoy_pct": round((total12 / prev12 - 1) * 100, 1) if prev12 and len(previos) == 12 else None,
        "wells_12m": int(len(d12)),
        "sand_12m_t": int(round(d12["_arena"].sum())) if c_arena else None,
        "operators": operators,
        "last_period": monthly[-1]["period"] if monthly else None,
    }


# ---------------------------------------------------------------------------
# 2. Dólar oficial (BCRA)
# ---------------------------------------------------------------------------
BCRA = "https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones/USD"


def fx(diag: dict) -> dict:
    hasta = date.today()
    desde = hasta - timedelta(days=365)
    filas, offset = [], 0
    while True:
        r = get(BCRA, params={"fechadesde": desde.isoformat(), "fechahasta": hasta.isoformat(),
                              "limit": 1000, "offset": offset}).json()
        res = r.get("results") or []
        for dia in res:
            for d in dia.get("detalle", []):
                if d.get("codigoMoneda") == "USD" and d.get("tipoCotizacion"):
                    filas.append({"date": dia["fecha"], "ars_per_usd": round(float(d["tipoCotizacion"]), 2)})
        diag["pages"] = diag.get("pages", 0) + 1
        if len(res) < 1000 or offset > 5000:
            break
        offset += 1000
    if not filas:
        raise RuntimeError(f"Respuesta sin cotizaciones: {str(r)[:300]}")
    filas = sorted({f["date"]: f for f in filas}.values(), key=lambda f: f["date"])
    ult = filas[-1]
    hace_un_anio = next((f for f in filas if f["date"] >= (date.fromisoformat(ult["date"]) - timedelta(days=365)).isoformat()), filas[0])
    return {
        "source": {"name": "BCRA, Estadísticas Cambiarias (Comunicación A 3500)", "url": "https://www.bcra.gob.ar/en/central-bank-api-catalog/"},
        "latest": ult,
        "yoy_pct": round((ult["ars_per_usd"] / hace_un_anio["ars_per_usd"] - 1) * 100, 1),
        "daily": filas[-260:],
    }


# ---------------------------------------------------------------------------
# 3. Brent y WTI (EIA)
# ---------------------------------------------------------------------------
EIA = "https://api.eia.gov/v2/petroleum/pri/spt/data/"


def oil_price(diag: dict) -> dict:
    key = os.environ.get("EIA_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Falta EIA_API_KEY (secreto del repositorio)")
    params = [("api_key", key), ("frequency", "daily"), ("data[0]", "value"),
              ("facets[series][]", "RBRTE"), ("facets[series][]", "RWTC"),
              ("sort[0][column]", "period"), ("sort[0][direction]", "desc"), ("length", "800")]
    j = get(EIA, params=params).json()
    filas = j.get("response", {}).get("data", [])
    if not filas:
        raise RuntimeError(f"EIA sin datos: {str(j)[:300]}")
    series = {"RBRTE": {}, "RWTC": {}}
    for f in filas:
        if f.get("value") not in (None, ""):
            series.setdefault(f["series"], {})[f["period"]] = round(float(f["value"]), 2)
    fechas = sorted(set(series["RBRTE"]) | set(series["RWTC"]))[-260:]
    daily = [{"date": d, "brent": series["RBRTE"].get(d), "wti": series["RWTC"].get(d)} for d in fechas]
    ult_b = next(d for d in reversed(daily) if d["brent"] is not None)
    ult_w = next(d for d in reversed(daily) if d["wti"] is not None)
    return {
        "source": {"name": "U.S. Energy Information Administration (EIA)", "url": "https://www.eia.gov/dnav/pet/pet_pri_spt_s1_d.htm", "license": "Dominio público"},
        "brent": {"date": ult_b["date"], "usd_bbl": ult_b["brent"]},
        "wti": {"date": ult_w["date"], "usd_bbl": ult_w["wti"]},
        "daily": daily,
    }


# ---------------------------------------------------------------------------
# 4. Boletín Oficial, primera sección
# ---------------------------------------------------------------------------
BO_BASE = "https://www.boletinoficial.gob.ar"
BO_SECCION = f"{BO_BASE}/seccion/primera"
KEYWORDS = [
    "rigi", "regimen de incentivo para grandes inversiones", "hidrocarburo", "petroleo", "gas natural", "gnl",
    "gas natural licuado", "oleoducto", "gasoducto", "vaca muerta", "neuquen", "secretaria de energia",
    "ente nacional regulador del gas", "enargas", "cammesa", "upstream", "refinacion", "combustible",
    "concesion de explotacion", "no convencional", "exportacion de crudo", "biocombustible",
]
NOISE = ["licitacion privada", "designase", "designacion", "dase por designad", "prorrogase la designacion"]


def regulations(diag: dict, previo: dict | None) -> dict:
    from bs4 import BeautifulSoup

    viejos = (previo or {}).get("items", [])
    # Sin historial, se recorren los últimos 60 días; después alcanza con la última semana.
    dias = 60 if len(viejos) < 5 else 7
    paginas = [BO_SECCION] + [f"{BO_SECCION}/{(date.today() - timedelta(days=d)).strftime('%Y%m%d')}"
                              for d in range(1, dias + 1) if (date.today() - timedelta(days=d)).weekday() < 5]
    links, errores = [], 0
    for url in paginas:
        try:
            soup = BeautifulSoup(get(url, timeout=40).text, "html.parser")
            links += soup.select('a[href*="/detalleAviso/primera/"]')
        except Exception:
            errores += 1
    diag.update({"pages": len(paginas), "page_errors": errores, "links": len(links)})
    if not links:
        raise RuntimeError("No se encontraron avisos en la primera sección")
    diag["sample"] = [" | ".join(p.strip() for p in a.get_text("\n").split("\n") if p.strip())[:200] for a in links[:3]]

    nuevos = []
    for a in links:
        href = a.get("href", "")
        m = re.search(r"/detalleAviso/primera/(\d+)/(\d{8})", href)
        if not m:
            continue
        partes = [p.strip() for p in a.get_text("\n").split("\n") if p.strip()]
        texto = " ".join(partes)
        t = norm(texto)
        if not any(k in t for k in KEYWORDS) or any(n in t for n in NOISE):
            continue
        fecha = f"{m.group(2)[:4]}-{m.group(2)[4:6]}-{m.group(2)[6:]}"
        nuevos.append({
            "id": m.group(1),
            "date": fecha,
            "agency": partes[0][:160] if partes else "",
            "title": " ".join(partes[1:3])[:280] if len(partes) > 1 else texto[:280],
            "url": BO_BASE + href if href.startswith("/") else href,
            "tags": sorted({k for k in KEYWORDS if k in t})[:5],
        })
    diag["matched"] = len(nuevos)
    por_id = {i["id"]: i for i in viejos}
    por_id.update({i["id"]: i for i in nuevos})
    limite = (date.today() - timedelta(days=120)).isoformat()
    items = sorted((i for i in por_id.values() if i["date"] >= limite), key=lambda i: (i["date"], i["id"]), reverse=True)[:60]
    return {
        "source": {"name": "Boletín Oficial de la República Argentina, primera sección", "url": BO_BASE},
        "keywords": KEYWORDS,
        "items": items,
    }


# ---------------------------------------------------------------------------
# 5. Noticias por RSS
# ---------------------------------------------------------------------------
FEEDS = [
    ("EconoJournal", ["https://econojournal.com.ar/feed/"]),
    ("Infobae", ["https://www.infobae.com/arc/outboundfeeds/rss/category/economia/"]),
    ("Ámbito", ["https://www.ambito.com/rss/pages/energia.xml", "https://www.ambito.com/rss/pages/economia.xml"]),
]
NEWS_KW = ["vaca muerta", "shale", "neuquen", "ypf", "vista energy", "pluspetrol", "tecpetrol", "pampa energia",
           "rigi", "gnl", "oleoducto", "gasoducto", "hidrocarburo", "petroleo", "petrolera", "fracking", "fractura",
           "brent", "crudo", "barriles", "energia"]
# Medios dedicados a energía: no se filtran por palabra clave.
SECTORIALES = {"EconoJournal"}


def news(diag: dict) -> dict:
    import feedparser

    items, estado = [], {}
    for medio, urls in FEEDS:
        for url in urls:
            try:
                r = get(url, timeout=40)
                feed = feedparser.parse(r.content)
                if not feed.entries:
                    estado[medio] = f"sin entradas en {url}"
                    continue
                n = 0
                for e in feed.entries[:40]:
                    titulo = re.sub(r"\s+", " ", e.get("title", "")).strip()
                    link = e.get("link", "")
                    if not titulo or not link.startswith("http"):
                        continue
                    t = norm(titulo)
                    if medio not in SECTORIALES and not any(k in t for k in NEWS_KW):
                        continue
                    cuando = None
                    for campo in ("published", "updated"):
                        if e.get(campo):
                            try:
                                cuando = parsedate_to_datetime(e[campo]).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
                            except Exception:
                                pass
                            break
                    items.append({"source": medio, "title": titulo[:220], "url": link, "published": cuando})
                    n += 1
                estado[medio] = f"ok {n} de {url}"
                break
            except Exception as ex:
                estado[medio] = f"{type(ex).__name__}: {str(ex)[:120]} ({url})"
    diag["feeds"] = estado
    if not items:
        raise RuntimeError("Ningún feed devolvió titulares")
    vistos, unicos = set(), []
    for i in sorted(items, key=lambda i: i["published"] or "", reverse=True):
        clave = norm(i["title"])[:80]
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(i)
    return {"items": unicos[:24]}


# ---------------------------------------------------------------------------
def main() -> None:
    previo = {}
    if OUT.exists():
        try:
            previo = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            previo = {}
    salida = {k: v for k, v in previo.items() if k not in ("status", "generated_at")}
    status = {}
    tareas = [
        ("fracking", lambda d: fracking(d)),
        ("fx", lambda d: fx(d)),
        ("oil_price", lambda d: oil_price(d)),
        ("regulations", lambda d: regulations(d, previo.get("regulations"))),
        ("news", lambda d: news(d)),
    ]
    solo = set(sys.argv[1:])
    for nombre, fn in tareas:
        if solo and nombre not in solo:
            continue
        diag = {}
        try:
            salida[nombre] = fn(diag)
            status[nombre] = {"ok": True, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "diag": diag}
            print(f"OK {nombre}", file=sys.stderr)
        except Exception as e:
            status[nombre] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:500]}", "diag": diag,
                              "trace": traceback.format_exc()[-1200:]}
            print(f"ERROR {nombre}: {e}", file=sys.stderr)
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    salida["status"] = status
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(salida, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
