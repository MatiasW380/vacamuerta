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


def limpiar_nan(x):
    """JSON válido para el navegador: NaN/inf pasan a null y se descartan puntos de serie sin valor."""
    import math
    if isinstance(x, float):
        return None if math.isnan(x) or math.isinf(x) else x
    if isinstance(x, dict):
        return {k: limpiar_nan(v) for k, v in x.items()}
    if isinstance(x, list):
        out = [limpiar_nan(v) for v in x]
        return [v for v in out if not (isinstance(v, dict) and "usd_bbl" in v and v["usd_bbl"] is None)]
    return x


def tiene(texto: str, clave: str) -> bool:
    """Coincidencia de clave en texto normalizado; las claves cortas solo como palabra completa."""
    if len(clave) <= 5:
        return re.search(rf"\b{re.escape(clave)}\b", texto) is not None
    return clave in texto


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
    for patron in patrones:          # primero, coincidencia exacta
        if "+" not in patron and patron in df.columns:
            return patron
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
    c_agua = col(df, "agua_inyectada")
    diag["mapped"] = {"etapas": c_etapas, "arena": c_arena, "fecha": c_fecha, "anio": c_anio, "mes": c_mes,
                      "empresa": c_empresa, "formacion": c_form, "cuenca": c_cuenca, "pozo": c_pozo, "rama": c_rama}

    num = lambda s: pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False), errors="coerce")
    df["_etapas"] = num(df[c_etapas]).fillna(0)
    df["_arena"] = sum(num(df[c]).fillna(0) for c in c_arena) if c_arena else 0
    df["_rama"] = num(df[c_rama]) if c_rama else float("nan")
    df["_agua"] = num(df[c_agua]).fillna(0) if c_agua else 0
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
    mens = df.groupby("_per").agg(stages=("_etapas", "sum"), sand_t=("_arena", "sum"), water_m3=("_agua", "sum"),
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
        "stages_per_well": round(r.stages / r.wells, 1) if r.wells else None,
        "sand_per_stage_t": round(r.sand_t / r.stages, 1) if r.stages and r.sand_t else None,
        "water_per_stage_m3": round(r.water_m3 / r.stages) if r.stages and r.water_m3 else None,
    } for p, r in mens.iterrows()]
    # Tendencia anual de diseño de pozos (años completos o el año en curso hasta el último mes completo).
    anual = df.groupby("_anio").agg(stages=("_etapas", "sum"), wells=("_etapas", "size"),
                                    lateral_m=("_rama", "mean"), sand_t=("_arena", "sum"), water_m3=("_agua", "sum"))
    design = [{"year": int(a), "wells": int(r.wells), "lateral_m": int(round(r.lateral_m)) if pd.notna(r.lateral_m) else None,
               "stages_per_well": round(r.stages / r.wells, 1) if r.wells else None,
               "sand_per_well_t": int(round(r.sand_t / r.wells)) if r.wells and r.sand_t else None,
               "water_per_well_m3": int(round(r.water_m3 / r.wells)) if r.wells and r.water_m3 else None}
              for a, r in anual.iterrows() if a >= 2014 and r.wells >= 20]

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
        "design": design,
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
# Preselección por organismo o título (barata, sobre el listado del día).
PRESELECT = [
    "rigi", "regimen de incentivo para grandes inversiones", "hidrocarburo", "petroleo", "gas natural", "gnl",
    "oleoducto", "gasoducto", "vaca muerta", "neuquen", "secretaria de energia", "subsecretaria de combustibles",
    "subsecretaria de energia", "ente nacional regulador del gas", "enargas", "enrege", "upstream", "refinacion",
    "combustible", "concesion de explotacion", "no convencional", "biocombustible", "ministerio de economia",
]
# Confirmación sobre el texto completo: el aviso tiene que tratar de hidrocarburos, gas o RIGI.
TEMAS = {
    "RIGI": ["regimen de incentivo para grandes inversiones", "rigi"],
    "Hidrocarburos": ["hidrocarburo", "petroleo crudo", "petroleo y gas", "explotacion no convencional",
                      "concesion de explotacion", "permiso de exploracion", "ley 17.319", "ley n° 17.319", "upstream"],
    "Vaca Muerta": ["vaca muerta"],
    "Gas natural": ["gas natural licuado", "gnl", "gasoducto", "transporte de gas", "distribucion de gas", "plan gas"],
    "Petróleo": ["oleoducto", "refineria", "refinacion", "exportacion de crudo", "combustibles liquidos", "precio del crudo"],
    "Biocombustibles": ["biocombustible", "bioetanol", "biodiesel"],
}
NOISE = ["designase", "dase por designad", "prorrogase la designacion", "denuncia", "codigo aduanero",
         "sumario", "licitacion privada"]


def parte_dispositiva(texto: str) -> str:
    """Lo que sigue a RESUELVE/DECRETA/DISPONE (sin los considerandos), o el texto entero."""
    m = re.search(r"\b(RESUELVE|DECRETA|DISPONE|RESUELVEN|DISPONEN)\s*:\s*(.+)", texto)
    return m.group(2) if m else texto


def resumen_aviso(texto: str) -> str:
    cuerpo = parte_dispositiva(texto)
    cuerpo = re.sub(r"^ART[IÍ]CULO\s*1\s*[°º]?\s*[.\-–:]*\s*", "", cuerpo.strip(), flags=re.I)
    cuerpo = re.split(r"\s+ART[IÍ]CULO\s*2", cuerpo, maxsplit=1, flags=re.I)[0]
    cuerpo = re.sub(r"^[^\wÁÉÍÓÚÑ(]+", "", cuerpo)
    return cuerpo[:320].strip() + ("…" if len(cuerpo) > 320 else "")


RIGI_V = 3


def datos_rigi(texto: str) -> dict | None:
    """De una resolución de adhesión al RIGI: proyecto, empresa y monto."""
    if not re.search(r"adhesi[oó]n al R[eé]gimen de Incentivo para Grandes Inversiones|adhesi[oó]n al RIGI", texto, re.I):
        return None
    disp = parte_dispositiva(texto)
    proyecto = re.search(r"(?:proyecto|denominado)\s*[“\"«]([^”\"»]{3,140})[”\"»]", disp, re.I) or \
               re.search(r"(?:proyecto|denominado)\s*[“\"«]([^”\"»]{3,140})[”\"»]", texto, re.I)
    empresa = re.search(r"presentad[oa]s?\s+por\s+(?:la\s+(?:empresa|firma|sociedad)\s+)?(.+?)\s*,?\s*\(\s*CUIT", disp, re.I) or \
              re.search(r"(?:presentada|solicitada|formulada) por (?:la (?:empresa|firma|sociedad)\s+)?([A-ZÁÉÍÓÚÑ0-9][A-ZÁÉÍÓÚÑ0-9 .,&\-]{2,90}?(?:S\.?A\.?U?\.?|S\.?R\.?L\.?|SOCIEDAD AN[OÓ]NIMA(?: UNIPERSONAL)?|S\.?A\.?S\.?))", texto)
    montos = [float(m.replace(".", "").replace(",", "."))
              for m in re.findall(r"(?:USD|U\$S|US\$|D[OÓ]LARES ESTADOUNIDENSES[^()]{0,200}\(\s*(?:USD|U\$S|US\$)?)\s*([\d]{1,3}(?:\.\d{3})+(?:,\d+)?)", texto)]
    monto = max(montos) if montos else None
    sector = next((s for s, k in [("Petróleo y gas", "hidrocarbur"), ("Petróleo y gas", "petr"), ("Gas natural licuado", "licuado"),
                                  ("Minería", "miner"), ("Energía eléctrica", "energ[ií]a el[eé]ctrica"), ("Siderurgia", "sider"),
                                  ("Infraestructura", "infraestructura|puerto")] if re.search(k, disp, re.I)), None)
    sub = re.search(r"[Ss]ubsector\s*[“\"«]([^”\"»]{3,200})[”\"»]", disp)
    area = re.search(r"[áa]rea(?: de hidrocarburos)?\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ .\-]{2,60}?)\s*\(", disp)
    i = disp.find("Apru")
    return {"excerpt": disp[max(0, i): max(0, i) + 700],
            "project": proyecto.group(1).strip() if proyecto else None,
            "company": empresa.group(1).strip(" ,.") if empresa else None,
            "usd_million": round(monto / 1e6, 1) if monto and monto > 1e6 else None,
            "sector": sector, "subsector": sub.group(1).strip() if sub else None,
            "area": area.group(1).strip() if area else None, "v": RIGI_V}


def regulations(diag: dict, previo: dict | None) -> dict:
    from bs4 import BeautifulSoup

    VERSION = 4   # al cambiar el criterio de filtrado se rearma el historial
    vigente = (previo or {}).get("version") == VERSION
    viejos = [i for i in (previo or {}).get("raw_items", []) if i.get("topics")] if vigente else []
    descartados = set((previo or {}).get("rejected_ids", [])) if vigente else set()
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

    conocidos = {i["id"] for i in viejos} | descartados
    candidatos = {}
    for a in links:
        href = a.get("href", "")
        m = re.search(r"/detalleAviso/primera/(\d+)/(\d{8})", href)
        if not m or m.group(1) in conocidos or m.group(1) in candidatos:
            continue
        partes = [p.strip() for p in a.get_text("\n").split("\n") if p.strip()]
        t = norm(" ".join(partes))
        if not any(tiene(t, k) for k in PRESELECT) or any(n in t for n in NOISE):
            continue
        candidatos[m.group(1)] = {
            "id": m.group(1),
            "date": f"{m.group(2)[:4]}-{m.group(2)[4:6]}-{m.group(2)[6:]}",
            "agency": partes[0][:160] if partes else "",
            "title": " ".join(partes[1:3])[:200] if len(partes) > 1 else " ".join(partes)[:200],
            "url": BO_BASE + href if href.startswith("/") else href,
        }
    diag["candidates"] = len(candidatos)

    nuevos, fallas = [], 0
    for c in candidatos.values():
        try:
            det = BeautifulSoup(get(c["url"], timeout=40).text, "html.parser")
            cuerpo = det.select_one("#cuerpoDetalleAviso") or det.select_one(".cuerpo-aviso") or det.body
            texto = re.sub(r"\s+", " ", cuerpo.get_text(" ")).strip() if cuerpo else ""
        except Exception:
            fallas += 1
            continue
        t = norm(c["title"] + " " + parte_dispositiva(texto)[:3000])
        temas = [tema for tema, claves in TEMAS.items() if any(tiene(t, k) for k in claves)]
        if not temas or any(n in norm(c["title"]) for n in NOISE):
            descartados.add(c["id"])
            continue
        c["topics"] = temas
        c["summary"] = resumen_aviso(texto)
        if "RIGI" in temas:
            c["rigi"] = datos_rigi(texto)
        nuevos.append(c)
    diag.update({"kept": len(nuevos), "details_failed": fallas})
    # Re-procesa los avisos RIGI ya guardados cuando cambia el extractor.
    for i in viejos:
        if "RIGI" in i.get("topics", []) and (i.get("rigi") or {}).get("v") != RIGI_V:
            try:
                det = BeautifulSoup(get(i["url"], timeout=40).text, "html.parser")
                cuerpo = det.select_one("#cuerpoDetalleAviso") or det.body
                i["rigi"] = datos_rigi(re.sub(r"\s+", " ", cuerpo.get_text(" ")).strip())
            except Exception:
                pass

    por_id = {i["id"]: i for i in viejos}
    por_id.update({i["id"]: i for i in nuevos})
    limite = (date.today() - timedelta(days=120)).isoformat()
    todos = sorted((i for i in por_id.values() if i["date"] >= limite), key=lambda i: (i["date"], i["id"]), reverse=True)
    # Agrupa avisos casi idénticos del mismo día y organismo (p. ej. un cuadro tarifario por distribuidora).
    grupos, items = {}, []
    for i in todos:
        clave = (i["date"], norm(i["agency"])[:40], norm(i.get("summary") or "")[:28])
        if clave in grupos:
            grupos[clave]["similar"] = grupos[clave].get("similar", 0) + 1
            continue
        g = {k: v for k, v in i.items() if k != "similar"}
        grupos[clave] = g
        items.append(g)
    return {
        "version": VERSION,
        "source": {"name": "Boletín Oficial de la República Argentina, primera sección", "url": BO_BASE},
        "items": items[:60],
        "raw_items": todos[:200],
        "rejected_ids": sorted(descartados)[-3000:],
    }


# ---------------------------------------------------------------------------
# Utilidades CKAN (portales de datos abiertos)
# ---------------------------------------------------------------------------
def ckan_paquete(bases: list[str], ids: list[str], diag: dict) -> tuple[dict, str]:
    errores = []
    for base in bases:
        for pid in ids:
            try:
                j = get(f"{base}/api/3/action/package_show", params={"id": pid}, timeout=60).json()
                if j.get("success"):
                    diag["package"] = f"{base} {pid}"
                    return j["result"], base
            except Exception as e:
                errores.append(f"{base} {pid}: {type(e).__name__}")
    raise RuntimeError(f"No se encontró el dataset: {errores}")


def leer_tabla(url: str, timeout: int = 300) -> pd.DataFrame:
    crudo = get(url, timeout=timeout).content
    if url.lower().split("?")[0].endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(crudo), dtype=str)
    else:
        for enc in ("utf-8-sig", "latin-1"):
            try:
                texto = crudo.decode(enc); break
            except UnicodeDecodeError:
                continue
        sep = ";" if texto[:3000].count(";") > texto[:3000].count(",") else ","
        df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, low_memory=False)
    df.columns = [norm(c).replace(" ", "_") for c in df.columns]
    return df


def recursos(paquete: dict) -> list[dict]:
    return [{"name": r.get("name") or "", "url": r.get("url") or "", "format": (r.get("format") or "").lower(),
             "modified": r.get("last_modified") or r.get("created") or ""} for r in paquete.get("resources", [])]


def numero(s: pd.Series) -> pd.Series:
    t = s.astype(str).str.strip()
    # 1.234,56 -> 1234.56 ; 1234.56 se deja igual
    t = t.where(~t.str.contains(r"\d\.\d{3},"), t.str.replace(".", "", regex=False))
    return pd.to_numeric(t.str.replace(",", ".", regex=False), errors="coerce")


# ---------------------------------------------------------------------------
# 6. Reservas de petróleo y gas
# ---------------------------------------------------------------------------
def _plano(t) -> str:
    return norm(t) if isinstance(t, str) else ""


def tabla_reservas(raw: pd.DataFrame, diag: dict) -> pd.DataFrame:
    """Excel de reservas con encabezado en varios niveles (grupo / fluido / categoría)."""
    fila = next((i for i in range(min(30, len(raw)))
                 if any(re.search(r"\b(empresa|operador)", _plano(v)) for v in raw.iloc[i].tolist())), None)
    diag["header_row"] = fila
    diag["head_rows"] = [[str(v)[:40] for v in raw.iloc[i].tolist() if isinstance(v, str)] for i in range(min(12, len(raw)))]
    if fila is None:
        raise RuntimeError("No se encontró la fila de encabezados (empresa/operador)")
    niveles = []
    for i in range(max(0, fila - 5), fila + 1):
        filav = raw.iloc[i].copy()
        if i < fila:
            filav = filav.ffill()
        niveles.append([_plano(v) for v in filav.tolist()])
    # Si la fila siguiente a los encabezados también es texto (unidades/categorías), se suma.
    sig = raw.iloc[fila + 1].tolist() if fila + 1 < len(raw) else []
    extra = sum(isinstance(v, str) for v in sig) >= 3 and not any(isinstance(v, (int, float)) and not pd.isna(v) for v in sig)
    if extra:
        niveles.append([_plano(v) for v in pd.Series(sig).tolist()])
    cols = []
    for j in range(raw.shape[1]):
        partes = []
        for n in niveles:
            v = n[j] if j < len(n) else ""
            if v and v not in partes and "reservas y recursos al" not in v:
                partes.append(v)
        cols.append(" | ".join(partes) or f"c{j}")
    df = raw.iloc[fila + (2 if extra else 1):].copy()
    df.columns = cols
    return df.reset_index(drop=True)


def clave_reserva(nombre: str) -> str | None:
    n = nombre
    if "convencional + no" in n or "conv + no" in n or "total" in n.split(" | ")[0]:
        grupo = "all"
    elif "no convencional" in n:
        grupo = "nc"
    elif "convencional" in n:
        grupo = "conv"
    else:
        grupo = "all"
    fluido = "oil" if re.search(r"\bpet\b|petr|crudo|oil|liquid", n) else "gas" if re.search(r"\bgas\b", n) else None
    cat = ("resources" if "recurso" in n else "proved" if re.search(r"probad|\bp1\b|comprobad", n) else "probable" if re.search(r"probable|\bp2\b", n)
           else "possible" if re.search(r"posible|\bp3\b", n) else "resources" if "recurso" in n else None)
    if not fluido or not cat:
        return None
    return f"{grupo}_{fluido}_{cat}"


def reserves(diag: dict) -> dict:
    from build_data import nombre_corto
    paq, base = ckan_paquete(["http://datos.energia.gob.ar", "https://datos.gob.ar"],
                             ["reservas-de-petroleo-y-gas", "energia-reservas-petroleo-gas"], diag)
    todos = recursos(paq)
    def anio(r):
        m = re.findall(r"(20\d\d)", r["name"] + r["url"])
        return int(m[-1]) if m else 0
    zips = sorted([r for r in todos if r["format"] == "zip" or r["url"].lower().endswith(".zip")], key=anio, reverse=True)
    if not zips:
        raise RuntimeError("Sin archivos ZIP de reservas")
    import zipfile
    r = zips[0]
    z = zipfile.ZipFile(io.BytesIO(get(r["url"], timeout=300).content))
    diag["zip_files"] = [(n.filename, n.file_size) for n in z.infolist()][:20]
    cand = sorted([n for n in z.infolist() if n.filename.lower().endswith((".xlsx", ".xls"))], key=lambda n: n.file_size, reverse=True)
    if not cand:
        raise RuntimeError("El ZIP no trae Excel")
    hojas = pd.read_excel(io.BytesIO(z.read(cand[0].filename)), sheet_name=None, header=None, dtype=object)
    diag["sheets"] = list(hojas)
    # Hasta el fin de la concesión: es el criterio de reservas comprobadas que informa la Secretaría.
    hoja = next((k for k in hojas if "concesi" in _plano(k)), max(hojas, key=lambda k: len(hojas[k])))
    diag["sheet_used"] = hoja
    df = tabla_reservas(hojas[hoja], diag)
    diag["columns"] = list(df.columns)[:40]
    c_emp = next((c for c in df.columns if re.search(r"\b(empresa|operador)", c.split(" | ")[-1])), None)
    c_cuenca = next((c for c in df.columns if "cuenca" in c.split(" | ")[-1]), None)
    c_area = next((c for c in df.columns if re.search(r"\b(area|yacimiento|concesion)", c.split(" | ")[-1])), None)
    c_prov = next((c for c in df.columns if "provincia" in c.split(" | ")[-1]), None)
    claves = {}
    for c in df.columns:
        if c in (c_emp, c_cuenca, c_area, c_prov):
            continue
        k = clave_reserva(c)
        if k and k not in claves and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.3:
            claves[k] = c
    diag["mapped"] = {"empresa": c_emp, "cuenca": c_cuenca, "area": c_area, "provincia": c_prov, "values": claves}
    if not c_emp or not claves:
        raise RuntimeError("No se pudieron identificar operadora o volúmenes (ver diag)")
    d = df[df[c_emp].map(lambda v: isinstance(v, str) and v.strip() != "" and "total" not in norm(v))].copy()
    if c_cuenca:
        d[c_cuenca] = d[c_cuenca].ffill()
    for k, c in claves.items():
        d[k] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    c_yac = next((c for c in df.columns if "yacimiento" in c.split(" | ")[-1]), None)
    vals = list(claves)
    clave_dup = [c for c in (c_area, c_yac) if c] + vals
    antes = len(d)
    if c_area:   # el mismo yacimiento cargado dos veces bajo dos razones sociales del mismo grupo
        d = d[~(d.duplicated(subset=clave_dup, keep="first") & (d[vals].sum(axis=1) > 0))]
    diag["duplicates_dropped"] = int(antes - len(d))
    diag["rows"] = int(len(d))
    neu = d[d[c_cuenca].map(lambda v: "neuquina" in _plano(v))] if c_cuenca else d
    diag["rows_neuquina"] = int(len(neu))
    vals = list(claves)
    def agrupar(x, por):
        g = x.groupby(por)[vals].sum()
        orden = next((k for k in ("nc_oil_proved", "all_oil_proved") if k in vals), vals[0])
        return g.sort_values(orden, ascending=False)
    por_op = agrupar(neu, neu[c_emp].map(nombre_corto))
    por_area = agrupar(neu, neu[c_area].map(lambda v: str(v).strip().title())) if c_area else None
    if por_area is not None:
        ops = neu.groupby(neu[c_area].map(lambda v: str(v).strip().title()))[c_emp].agg(lambda x: nombre_corto(x.mode().iat[0]))
    por_cuenca = agrupar(d, d[c_cuenca].map(lambda v: str(v).strip().title())) if c_cuenca else None
    redo = lambda fila: {k: round(float(v), 1) for k, v in fila.items()}
    return {
        "source": {"name": "Secretaría de Energía, reservas de petróleo y gas", "url": "http://datos.energia.gob.ar/dataset/reservas-de-petroleo-y-gas", "license": "CC BY 4.0"},
        "resource": r["name"], "year": anio(r) or None, "sheet": hoja,
        "units": {"oil": "Mm3", "gas": "MMm3"},
        "keys": vals,
        "neuquina_by_operator": [{"name": n, **redo(f)} for n, f in por_op.head(12).iterrows()],
        "neuquina_totals": redo(neu[vals].sum()),
        "neuquina_by_area": [{"name": n, "operator": ops.get(n), **redo(f)} for n, f in por_area.head(25).iterrows()] if por_area is not None else [],
        "by_basin": [{"name": n, **redo(f)} for n, f in por_cuenca.iterrows()] if por_cuenca is not None else [],
        "national_totals": redo(d[vals].sum()),
    }


# ---------------------------------------------------------------------------
# 7. Precio de exportación del petróleo crudo
# ---------------------------------------------------------------------------
def export_price(diag: dict) -> dict:
    paq, base = ckan_paquete(["https://datos.gob.ar", "http://datos.energia.gob.ar"],
                             ["energia-precio-exportacion-petroleo-crudo", "precio-de-exportacion-de-petroleo-crudo",
                              "precio-exportacion-petroleo-crudo"], diag)
    rs = [r for r in recursos(paq) if r["url"].lower().split("?")[0].endswith((".csv", ".xlsx")) or r["format"] in ("csv", "xlsx")]
    diag["resources"] = [r["name"] for r in rs][:10]
    # Este dataset se discontinuó en 2021: se buscan reemplazos para seguirlos en el diagnóstico.
    try:
        for base_b in ("http://datos.energia.gob.ar", "https://datos.gob.ar"):
            res = get(f"{base_b}/api/3/action/package_search", params={"q": "precio petroleo crudo", "rows": 15}, timeout=60).json()["result"]["results"]
            diag.setdefault("alternatives", []).extend({"base": base_b, "name": x.get("name"), "title": x.get("title"), "modified": x.get("metadata_modified", "")[:10],
                                                        "resources": [(r.get("name"), (r.get("last_modified") or "")[:10]) for r in x.get("resources", [])][:6]} for x in res)
    except Exception as e:
        diag["alternatives_error"] = str(e)[:200]
    if not rs:
        raise RuntimeError("Sin recursos tabulares")
    crudo = get(rs[0]["url"], timeout=120).content
    raw = pd.read_excel(io.BytesIO(crudo), header=None, dtype=object)
    fila = next((i for i in range(min(15, len(raw))) if any(norm(v).startswith("mes/tipo") for v in raw.iloc[i].tolist() if isinstance(v, str))), None)
    if fila is not None:
        grupos = raw.iloc[fila - 1].ffill().tolist() if fila > 0 else [""] * raw.shape[1]
        tipos = raw.iloc[fila].tolist()
        series = {}
        for j in range(1, raw.shape[1]):
            if not isinstance(tipos[j], str):
                continue
            g = norm(grupos[j] if isinstance(grupos[j], str) else "")
            grupo = ("brent" if "bloomberg" in g or "futures" in g else "fob" if "fob" in g and "brent" not in g else
                     "domestic" if "interno" in g and "brent" not in g else "fob_vs_brent" if "fob" in g else "domestic_vs_brent")
            puntos = []
            for i in range(fila + 1, len(raw)):
                f, v = raw.iat[i, 0], raw.iat[i, j]
                try:
                    per = pd.to_datetime(f).strftime("%Y-%m")
                    val = float(v)
                except Exception:
                    continue
                puntos.append({"period": per, "usd_bbl": round(val, 2)})
            if puntos:
                series[f"{grupo}|{str(tipos[j]).strip().title()}"] = puntos[-60:]
        diag["series"] = list(series)
        if series:
            return {"source": {"name": "Secretaría de Energía, precios de petróleo crudo por tipo",
                               "url": "https://datos.gob.ar/dataset/energia-precio-exportacion-petroleo-crudo", "license": "CC BY 4.0"},
                    "series": series, "main": "fob|Medanito" if "fob|Medanito" in series else next(iter(series))}
    df = leer_tabla(rs[0]["url"])
    diag.update({"resource_used": rs[0]["name"], "columns": list(df.columns)[:40], "rows": int(len(df))})
    c_fecha = col(df, "indice_tiempo", "fecha", "periodo", "mes")
    c_anio, c_mes = col(df, "anio", "ano"), col(df, "mes")
    nums = [c for c in df.columns if c not in (c_fecha, c_anio, c_mes) and numero(df[c]).notna().mean() > 0.6]
    c_precio = next((c for c in nums if "precio" in c or "usd" in c or "dolar" in c), nums[0] if nums else None)
    c_tipo = col(df, "tipo_de_crudo", "crudo", "tipo", "calidad", "producto")
    diag["mapped"] = {"fecha": c_fecha, "anio": c_anio, "mes": c_mes, "precio": c_precio, "tipo": c_tipo}
    if not c_precio:
        raise RuntimeError("No se encontró la columna de precio")
    if c_fecha:
        f = pd.to_datetime(df[c_fecha], errors="coerce")
    else:
        f = pd.to_datetime(df[c_anio].astype(str) + "-" + df[c_mes].astype(str).str.zfill(2) + "-01", errors="coerce")
    d = pd.DataFrame({"fecha": f, "precio": numero(df[c_precio]), "tipo": df[c_tipo].fillna("") if c_tipo else ""}).dropna(subset=["fecha", "precio"])
    d["period"] = d["fecha"].dt.strftime("%Y-%m")
    series = {}
    for tipo, g in d.groupby("tipo"):
        g = g.groupby("period")["precio"].mean().sort_index().tail(60)
        series[str(tipo).strip().title() or "Total"] = [{"period": p, "usd_bbl": round(float(v), 2)} for p, v in g.items()]
    principal = max(series, key=lambda k: len(series[k]))
    return {"source": {"name": "Secretaría de Energía, precio de exportación de petróleo crudo",
                       "url": "https://datos.gob.ar/dataset/energia-precio-exportacion-petroleo-crudo", "license": "CC BY 4.0"},
            "unit_column": c_precio, "main": principal, "series": series}


# ---------------------------------------------------------------------------
# 8. Precios de combustibles en surtidor (Res. 314/2016)
# ---------------------------------------------------------------------------
PRODUCTOS = {"super": ["super", "92 y 95"], "premium": ["premium", "mas de 95"], "diesel": ["grado 2"], "diesel_premium": ["grado 3"]}


def fuel_prices(diag: dict) -> dict:
    paq, base = ckan_paquete(["http://datos.energia.gob.ar", "https://datos.gob.ar"],
                             ["precios-en-surtidor", "energia-precios-surtidor---resolucion-3142016"], diag)
    rs = [r for r in recursos(paq) if r["url"].lower().split("?")[0].endswith(".csv") or r["format"] == "csv"]
    diag["resources"] = [r["name"] for r in rs][:10]
    vig = next((r for r in rs if "vigente" in norm(r["name"])), rs[0] if rs else None)
    if not vig:
        raise RuntimeError("Sin recurso CSV")
    df = leer_tabla(vig["url"], timeout=600)
    diag.update({"resource_used": vig["name"], "columns": list(df.columns)[:40], "rows": int(len(df))})
    c_prod, c_prec = col(df, "producto"), col(df, "precio")
    c_prov, c_band = col(df, "provincia"), col(df, "empresabandera", "bandera")
    c_hor, c_fecha = col(df, "tipohorario", "horario"), col(df, "fecha_vigencia", "fecha")
    diag["mapped"] = {"producto": c_prod, "precio": c_prec, "provincia": c_prov, "bandera": c_band, "horario": c_hor, "fecha": c_fecha}
    if not (c_prod and c_prec and c_prov):
        raise RuntimeError("Faltan columnas de producto, precio o provincia")
    d = pd.DataFrame({"prod": df[c_prod].fillna("").map(norm), "precio": numero(df[c_prec]),
                      "prov": df[c_prov].fillna("").map(lambda x: str(x).strip().title()),
                      "band": df[c_band].fillna("").map(lambda x: str(x).strip()) if c_band else "",
                      "hor": df[c_hor].fillna("").map(norm) if c_hor else "diurno",
                      "fecha": pd.to_datetime(df[c_fecha], errors="coerce") if c_fecha else pd.NaT})
    d = d[(d["precio"] > 50) & (d["precio"] < 1e6)]
    if c_hor:
        d = d[d["hor"].str.contains("diurno")]
    # Solo precios informados en los últimos 120 días.
    if c_fecha and d["fecha"].notna().any():
        d = d[d["fecha"] >= d["fecha"].max() - pd.Timedelta(days=120)]
    d["clave"] = None
    for clave, pats in PRODUCTOS.items():
        d.loc[d["clave"].isna() & d["prod"].map(lambda p: any(x in p for x in pats)), "clave"] = clave
    d = d.dropna(subset=["clave"])
    diag["rows_used"] = int(len(d))
    por_prov = (d.groupby(["prov", "clave"])["precio"].median().unstack().round(0))
    marcas = d["band"].map(lambda b: "YPF" if "YPF" in b.upper() else "Shell" if "SHELL" in b.upper() else
                           "Axion" if "AXION" in b.upper() else "Puma" if "PUMA" in b.upper() else "Otras")
    por_marca = d.assign(marca=marcas).groupby(["marca", "clave"])["precio"].median().unstack().round(0)
    estaciones = d.assign(marca=marcas).groupby("marca").size()
    fmt = lambda df_: [{"name": n, **{k: (None if pd.isna(v) else int(v)) for k, v in fila.items()}} for n, fila in df_.iterrows()]
    return {"source": {"name": "Secretaría de Energía, precios en surtidor (Res. 314/2016)",
                       "url": "http://datos.energia.gob.ar/dataset/precios-en-surtidor", "license": "CC BY 4.0"},
            "as_of": d["fecha"].max().strftime("%Y-%m-%d") if c_fecha and d["fecha"].notna().any() else None,
            "by_province": fmt(por_prov.sort_values("super", ascending=False) if "super" in por_prov else por_prov),
            "by_brand": fmt(por_marca), "stations_by_brand": {k: int(v) for k, v in estaciones.items()},
            "national_median": {k: int(v) for k, v in d.groupby("clave")["precio"].median().round(0).items()}}


# ---------------------------------------------------------------------------
# 9. RIGI: plan de inversiones del portal oficial
# ---------------------------------------------------------------------------
RIGI_PORTAL = "https://www.argentina.gob.ar/economia/rigi"


def rigi_portal(diag: dict) -> dict:
    html = get(RIGI_PORTAL).text
    diag["html_len"] = len(html)
    i = html.lower().find("petroleo")
    diag["context"] = html[max(0, i - 700): i + 500] if i >= 0 else None
    inline = [b for b in re.findall(r"<script(?![^>]*src=)[^>]*>(.*?)</script>", html, re.S) if "petroleo" in b.lower() or "rigi" in b.lower()]
    diag["inline_scripts"] = [b.strip()[:1800] for b in inline][:3]
    scripts = re.findall(r"<script[^>]*src=[\"']([^\"']+)[\"']", html)
    diag["scripts"] = [x for x in scripts if "rigi" in x.lower() or "mapa" in x.lower() or "economia" in x.lower()][:15]
    # Recursos que el portal podría cargar con JavaScript (para seguirlos en futuras corridas).
    urls = sorted(set(re.findall(r"""["'](https?://[^"'\s]+?\.(?:json|csv|xlsx|js)(?:\?[^"'\s]*)?)["']""", html) +
                      ["https://www.argentina.gob.ar" + u for u in re.findall(r"""["'](/[^"'\s]+?\.(?:json|csv|xlsx)(?:\?[^"'\s]*)?)["']""", html)]))
    diag["candidate_urls"] = [u for u in urls if "rigi" in u.lower() or u.endswith((".json", ".csv", ".xlsx"))][:30]
    # JSON incrustado (elemento #raw-data-json) con el plan de inversiones anual por sector.
    plan = None
    from bs4 import BeautifulSoup
    el = BeautifulSoup(html, "html.parser").find(id="raw-data-json")
    if el is not None:
        try:
            plan = json.loads(el.get_text().strip())
        except Exception as e:
            diag["json_error"] = str(e)[:200]
            diag["json_head"] = el.get_text()[:400]
    if not plan:
        raise RuntimeError("No se encontró el plan de inversiones incrustado")
    diag["plan_sample"] = plan[0]
    filas = []
    for r in plan:
        anio = str(r.get("year") or r.get("anio") or r.get("fecha") or next(iter(r.values())))[:4]
        fila = {"year": int(anio) if anio.isdigit() else anio}
        for k, v in r.items():
            if isinstance(v, dict) and "total" in v:
                fila[norm(k)] = v.get("total")
                for sk, sv in (v.get("sub") or {}).items():
                    fila[f"{norm(k)}:{sk}"] = sv
            elif isinstance(v, (int, float)) and norm(k) not in ("year", "anio"):
                fila[norm(k)] = v
        filas.append(fila)
    return {"source": {"name": "Ministerio de Economía, portal oficial del RIGI", "url": RIGI_PORTAL},
            "plan_by_year": filas}


# ---------------------------------------------------------------------------
# Regalías de petróleo crudo: precio declarado en boca de pozo, mensual
# ---------------------------------------------------------------------------
def _decodifica(b: bytes, enc: str) -> bool:
    try:
        b.decode(enc); return True
    except UnicodeDecodeError:
        return False


def tabla_pivote(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Tabla dinámica AÑO / MES x provincia → filas por período con una columna por provincia."""
    fila = next((i for i in range(min(40, len(raw))) if [_plano(v) for v in raw.iloc[i].tolist()[:2]] == ["ano", "mes"]), None)
    if fila is None:
        return None
    cols = [_plano(v) for v in raw.iloc[fila].tolist()]
    titulo = next((str(v) for i in range(max(0, fila - 3), fila) for v in raw.iloc[i].tolist() if isinstance(v, str) and "suma de" in v.lower()), "")
    d = raw.iloc[fila + 1:].copy()
    d.columns = [c or f"c{j}" for j, c in enumerate(cols)]
    d["ano"] = pd.to_numeric(d["ano"], errors="coerce").ffill()
    d["mes"] = pd.to_numeric(d["mes"], errors="coerce")
    d = d[d["ano"].notna() & d["mes"].between(1, 12)]
    d["period"] = d["ano"].astype(int).astype(str) + "-" + d["mes"].astype(int).astype(str).str.zfill(2)
    for c in d.columns:
        if c not in ("ano", "mes", "period"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.set_index("period").drop(columns=["ano", "mes"])
    d.attrs["title"] = titulo
    return d


def regalias_excel(hojas: dict, diag: dict, base: str, fluido: str = "crudo") -> dict:
    t = {}
    for k, v in hojas.items():
        n = _plano(k)
        clave = "price" if "precio" in n else "volume" if "produc" in n else "royalties" if "regal" in n else None
        if clave:
            piv = tabla_pivote(v)
            if piv is not None:
                t[clave] = piv
    diag["tables"] = {k: [v.attrs.get("title"), list(v.columns)[:14], v.index[-1] if len(v) else None] for k, v in t.items()}
    if "price" not in t:
        raise RuntimeError("No se encontró la tabla de precios")
    provs = {"neuquen": "Neuquén", "chubut": "Chubut", "santa cruz": "Santa Cruz", "mendoza": "Mendoza", "rio negro": "Río Negro"}
    precio = t["price"]
    precio = precio[(precio.get("neuquen", 0) > 0)]
    unidad = _plano(precio.attrs.get("title", ""))
    if fluido == "crudo":
        clave, factor = "usd_bbl", 1 / 6.2898                      # USD/m³ → USD/bbl
    else:
        # Gas: USD por miles de m³ (Mm3/dam3) o por m³ → USD/MMBtu, con 9.300 kcal/m³ (1 MMBtu = 27,1 m³).
        clave = "usd_mmbtu"
        factor = 27.1 if re.search(r"/ ?m3\b", unidad) else 27.1 / 1000 if re.search(r"(mm3|dam3|miles)", unidad) else None
        if re.search(r"mmbtu", unidad):
            factor = 1.0
        diag["gas_unit"] = unidad
        if factor is None:
            raise RuntimeError(f"Unidad de precio de gas desconocida: {unidad!r}")
    en_pesos = "ars" in unidad
    tc = fx_mensual(diag) if en_pesos else {}
    a_usd = (lambda p, v: v / tc[p] if p in tc else None) if en_pesos else (lambda p, v: v)
    series = {}
    for c, nombre in provs.items():
        if c in precio.columns:
            pts = []
            for p, v in precio[c].items():
                if pd.notna(v) and v > 0:
                    u = a_usd(p, float(v))
                    if u is not None:
                        pts.append({"period": p, clave: round(u * factor, 2)})
            series[nombre] = pts[-84:]
    nombre_fuente = "regalías de petróleo crudo" if fluido == "crudo" else "regalías de gas natural"
    out = {"source": {"name": f"Secretaría de Energía, {nombre_fuente}", "url": f"{base}/dataset/regalias-de-petroleo-crudo-gas-natural-glp-gasolina-y-condensado", "license": "CC BY 4.0"},
           ("price_usd_bbl" if fluido == "crudo" else "price_usd_mmbtu"): series, "unit_raw": precio.attrs.get("title"),
           "last_period": precio.index[-1] if len(precio) else None}
    if "royalties" in t and "volume" in t:
        r, vol = t["royalties"].copy(), t["volume"]
        if "ars" in _plano(r.attrs.get("title", "")):
            tc = fx_mensual(diag)
            r = r[r.index.isin(list(tc))]
            r = r.div(pd.Series({p: tc[p] for p in r.index}), axis=0)
            out["royalties_converted_from_ars"] = True
        ult = [p for p in r.index if r.loc[p].get("neuquen", 0) > 0][-12:]
        if ult:
            out["neuquen_12m"] = {"from": ult[0], "to": ult[-1],
                                  "royalties_usd_m": round(float(r.loc[ult, "neuquen"].sum()) / 1e6, 1),
                                  "volume_m3": round(float(vol.loc[[p for p in ult if p in vol.index], "neuquen"].sum())),
                                  "national_royalties_usd_m": round(float(r.loc[ult, "total provincia"].sum()) / 1e6, 1) if "total provincia" in r.columns else None}
            out["royalties_monthly"] = [{"period": p, "neuquen_usd_m": round(float(r.loc[p, "neuquen"]) / 1e6, 2),
                                         "total_usd_m": round(float(r.loc[p].get("total provincia", 0)) / 1e6, 2)} for p in r.index if r.loc[p].get("neuquen", 0) > 0][-84:]
    return out


def royalties(diag: dict, fluido: str = "crudo") -> dict:
    paq, base = ckan_paquete(["http://datos.energia.gob.ar", "https://datos.gob.ar"],
                             ["regalias-de-petroleo-crudo-gas-natural-glp-gasolina-y-condensado"], diag)
    if fluido == "crudo":
        rs = [r for r in recursos(paq) if "petr" in norm(r["name"]) or "crudo" in r["url"].lower()]
    else:
        rs = [r for r in recursos(paq) if "gas natural" in norm(r["name"]) or r["url"].lower().endswith("regalias_gas.zip")]
    diag["resources"] = [(r["name"], r["format"], r["url"][-80:]) for r in recursos(paq)][:12]
    if not rs:
        raise RuntimeError("Sin recurso de regalías de petróleo")
    if rs[0]["format"] == "zip" or rs[0]["url"].lower().endswith(".zip"):
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(get(rs[0]["url"], timeout=300).content))
        diag["zip_files"] = [(n.filename, n.file_size) for n in z.infolist()][:20]
        cand = sorted([n for n in z.infolist() if n.filename.lower().endswith((".csv", ".xlsx", ".xls", ".txt"))], key=lambda n: n.file_size, reverse=True)
        if not cand:
            raise RuntimeError("El ZIP no trae tablas")
        datos = z.read(cand[0].filename)
        if cand[0].filename.lower().endswith((".xlsx", ".xls")):
            hojas = pd.read_excel(io.BytesIO(datos), sheet_name=None, header=None, dtype=object)
            diag["sheets"] = {k: [len(v), v.shape[1]] for k, v in hojas.items()}
            diag["sheet_heads"] = {k: [[str(x)[:24] for x in v.iloc[i].tolist() if pd.notna(x)][:16] for i in range(min(14, len(v)))]
                                   for k, v in list(hojas.items())[:8]}
            return regalias_excel(hojas, diag, base, fluido)
        else:
            enc = "utf-8-sig" if _decodifica(datos[:200000], "utf-8-sig") else "latin-1"
            cab = datos[:5000].decode(enc, errors="replace")
            sep = ";" if cab.count(";") > cab.count(",") else ","
            muestra = pd.read_csv(io.BytesIO(datos), sep=sep, dtype=str, nrows=5, encoding=enc)
            diag["raw_columns"] = list(muestra.columns)[:40]
            utiles = [c for c in muestra.columns if re.search(r"a(n|ñ)o|mes|fecha|tiempo|periodo|provinc|jurisd|empresa|operador|volum|cantidad|precio|cambio", norm(c))]
            df = pd.read_csv(io.BytesIO(datos), sep=sep, dtype=str, encoding=enc, usecols=utiles or None, low_memory=False)
        del datos
        df.columns = [norm(c).replace(" ", "_") for c in df.columns]
    else:
        df = leer_tabla(rs[0]["url"])
    diag.update({"resource_used": rs[0]["name"], "columns": list(df.columns)[:40], "rows": int(len(df)),
                 "sample": df.tail(3).to_dict(orient="records")})
    c_anio = col(df, "anio", "ano", "año")
    c_mes = col(df, "mes")
    c_fecha = col(df, "indice_tiempo", "fecha", "periodo")
    c_prov = col(df, "provincia", "jurisdiccion")
    c_emp = col(df, "empresa", "operador")
    c_vol = col(df, "volumen", "cantidad", "produccion")
    c_pre = next((c for c in df.columns if "precio" in c and ("usd" in c or "dolar" in c or "u$s" in c)), None) or col(df, "precio")
    c_tc = col(df, "tipo_de_cambio", "tc")
    diag["mapped"] = {"anio": c_anio, "mes": c_mes, "fecha": c_fecha, "provincia": c_prov, "empresa": c_emp,
                      "volumen": c_vol, "precio": c_pre, "tc": c_tc}
    if not c_pre or not (c_fecha or (c_anio and c_mes)):
        raise RuntimeError("No se identificaron columnas de precio o período (ver diag)")
    d = df.copy()
    if c_fecha:
        d["period"] = d[c_fecha].astype(str).str[:7]
    else:
        d["period"] = numero(d[c_anio]).astype("Int64").astype(str) + "-" + numero(d[c_mes]).astype("Int64").astype(str).str.zfill(2)
    d["precio"] = numero(d[c_pre])
    d["vol"] = numero(d[c_vol]).fillna(0) if c_vol else 1.0
    d = d[d["precio"].notna() & (d["precio"] > 0) & d["period"].str.match(r"^\d{4}-\d{2}$")]
    diag["price_unit_hint"] = c_pre
    def serie(x):
        g = x.groupby("period").apply(lambda t: (t["precio"] * t["vol"]).sum() / t["vol"].sum() if t["vol"].sum() > 0 else t["precio"].median())
        return [{"period": p, "price": round(float(v), 2)} for p, v in g.sort_index().items() if pd.notna(v)][-72:]
    out = {"source": {"name": "Secretaría de Energía, regalías de petróleo crudo", "url": f"{base}/dataset/regalias-de-petroleo-crudo-gas-natural-glp-gasolina-y-condensado", "license": "CC BY 4.0"},
           "price_column": c_pre, "national": serie(d)}
    if c_prov:
        neu = d[d[c_prov].fillna("").map(norm).str.contains("neuqu")]
        out["neuquen"] = serie(neu)
    return out


# ---------------------------------------------------------------------------
# Balanza comercial energética (INDEC, vía API de Series de Tiempo)
# ---------------------------------------------------------------------------
SERIES_API = "https://apis.datos.gob.ar/series/api"


def _buscar_serie(q: str, debe: list[str], diag: dict, clave: str) -> dict | None:
    res = get(f"{SERIES_API}/search/", params={"q": q, "limit": 40}, timeout=60).json().get("data", [])
    cands = []
    for r in res:
        f, ds = r.get("field", {}), r.get("dataset", {})
        texto = norm(" ".join(str(x) for x in (f.get("description"), f.get("title"), ds.get("title"))))
        cands.append({"id": f.get("id"), "title": f.get("title"), "desc": (f.get("description") or "")[:120], "freq": f.get("frequency"),
                      "end": f.get("time_index_end"), "units": f.get("units"), "dataset": (ds.get("title") or "")[:80], "ok": all(d in texto for d in debe)})
    diag[f"candidates_{clave}"] = cands[:15]
    buenas = [c for c in cands if c["ok"] and c["freq"] == "R/P1M" and c["end"]]
    buenas.sort(key=lambda c: (c["end"], "dolar" in norm(str(c["units"]))), reverse=True)
    return buenas[0] if buenas else None


def serie_api(ids: list[str], diag: dict, desde: str = "2010-01-01") -> list:
    r = requests.get(f"{SERIES_API}/series/", params={"ids": ",".join(ids), "format": "json", "limit": 1000, "start_date": desde},
                     headers=UA, timeout=60)
    diag["series_status"] = r.status_code
    try:
        j = r.json()
    except Exception:
        diag["series_body"] = r.text[:400]
        raise
    if "data" not in j:
        diag["series_body"] = str(j)[:400]
    diag.setdefault("series_head", {})[",".join(ids)[:60]] = {"keys": list(j)[:8], "n": len(j.get("data", [])), "first": j.get("data", [])[:2], "last": j.get("data", [])[-2:]}
    return j.get("data", [])


_FX_MENSUAL: dict | None = None


def fx_mensual(diag: dict) -> dict:
    """Tipo de cambio mayorista, promedio mensual (ARS por USD), desde la API de Series de Tiempo."""
    global _FX_MENSUAL
    if _FX_MENSUAL is None:
        c = _buscar_serie("tipo de cambio mayorista promedio mensual", ["tipo de cambio"], diag, "fx")
        diag["fx_series"] = c
        if not c:
            raise RuntimeError("No se encontró la serie mensual de tipo de cambio")
        _FX_MENSUAL = {d[0][:7]: d[1] for d in serie_api([c["id"]], diag, "2005-01-01") if d[1]}
    return _FX_MENSUAL


def trade_balance(diag: dict) -> dict:
    exp = _buscar_serie("exportaciones combustibles y energia", ["export", "combustibles", "energia"], diag, "exp")
    imp = _buscar_serie("importaciones combustibles y lubricantes", ["import", "combustibles", "lubricantes"], diag, "imp")
    diag["chosen"] = {"exp": exp, "imp": imp}
    if not exp or not imp:
        raise RuntimeError("No se encontraron las series mensuales de exportación e importación de energía")
    j = serie_api([exp["id"], imp["id"]], diag)
    filas = [{"period": d[0][:7], "exports": d[1], "imports": d[2]} for d in j if d[1] is not None and d[2] is not None]
    for f in filas:
        f["balance"] = round(f["exports"] - f["imports"], 1)
        f["exports"], f["imports"] = round(f["exports"], 1), round(f["imports"], 1)
    if len(filas) < 24:
        raise RuntimeError(f"Serie demasiado corta: {len(filas)} meses")
    ult = filas[-12:]; prev = filas[-24:-12]
    return {"source": {"name": "INDEC, intercambio comercial argentino (API de Series de Tiempo)", "url": "https://datos.gob.ar/series", "license": "CC BY 4.0"},
            "units": exp.get("units"), "ids": [exp["id"], imp["id"]], "monthly": filas,
            "last_12m": {"from": ult[0]["period"], "to": ult[-1]["period"], "exports": round(sum(f["exports"] for f in ult), 1),
                         "imports": round(sum(f["imports"] for f in ult), 1), "balance": round(sum(f["balance"] for f in ult), 1),
                         "balance_prev": round(sum(f["balance"] for f in prev), 1)}}


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
                    if medio not in SECTORIALES and not any(tiene(t, k) for k in NEWS_KW):
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
        ("reserves", lambda d: reserves(d)),
        ("export_price", lambda d: export_price(d)),
        ("fuel_prices", lambda d: fuel_prices(d)),
        ("rigi_portal", lambda d: rigi_portal(d)),
        ("royalties", lambda d: royalties(d)),
        ("royalties_gas", lambda d: royalties(d, "gas")),
        ("trade_balance", lambda d: trade_balance(d)),
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
    # Aprobaciones RIGI detectadas en el Boletín Oficial: se acumulan sin vencimiento.
    previas = {a["id"]: a for a in previo.get("rigi_approvals", [])}
    for i in (salida.get("regulations") or {}).get("raw_items", []):
        if i.get("rigi"):
            previas[i["id"]] = {"id": i["id"], "date": i["date"], "url": i["url"], "title": i["title"], **i["rigi"]}
    salida["rigi_approvals"] = sorted(previas.values(), key=lambda a: a["date"], reverse=True)
    salida["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    salida["status"] = status
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(limpiar_nan(salida), ensure_ascii=False, indent=1, allow_nan=False, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
