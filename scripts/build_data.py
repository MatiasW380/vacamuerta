"""Genera data/vm.json con la producción de Vaca Muerta.

Fuente: Secretaría de Energía, Capítulo IV (Res. 319/93), datos.energia.gob.ar,
licencia CC BY 4.0. Se usa el archivo histórico de pozos no convencionales y,
para los meses que todavía no estén en él, los archivos anuales del año en curso
y el anterior.

Unidades de origen: petróleo en m3, gas en miles de m3.
Salida: petróleo en barriles por día (bbl/d), gas en millones de m3 por día (MMm3/d).

Uso:
    python scripts/build_data.py                 # descarga y procesa
    python scripts/build_data.py --local DIR     # usa CSV ya descargados en DIR
"""

from __future__ import annotations

import argparse
import calendar
import io
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "http://datos.energia.gob.ar/dataset/c846e79c-026c-4040-897f-1ad3543b407c/resource"
HISTORICO_NC = f"{BASE}/b5b58cdc-9e07-41f9-b392-fb9ec68b0725/download/produccin-de-pozos-de-gas-y-petrleo-no-convencional.csv"
ANUALES = {
    2025: f"{BASE}/d774b5d7-0756-48fe-88f2-8729b57b22da/download/produccin-de-pozos-de-gas-y-petrleo-2025.csv",
    2026: f"{BASE}/fb7a47a0-cba9-4667-a004-6f6c1c346c23/download/produccin-de-pozos-de-gas-y-petrleo-2026.csv",
}
SOURCE_PAGE = "http://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo"

M3_TO_BBL = 6.28981077
START_YEAR = 2015

OUT = Path(__file__).resolve().parent.parent / "data" / "vm.json"
HISTORY_FROM = 2019   # inicio de la serie por operadora
WELLS_MONTHS = 48     # meses de la serie de pozos

# Nombre canónico -> posibles nombres de columna en los distintos archivos.
COLUMNAS = {
    "empresa": ["empresa", "operadora"],
    "pozo": ["idpozo", "id_pozo", "pozoid"],
    "cuenca": ["cuenca"],
    "provincia": ["provincia"],
    "area": ["areapermisoconcesion", "area_permiso_concesion", "areayacimiento", "yacimiento"],
    "formacion": ["formacion", "formprod"],
    "tipo_recurso": ["tipo_de_recurso", "tiporecurso", "tipo_recurso", "sub_tipo_recurso", "subtipoderecurso"],
    "anio": ["anio", "ano", "year"],
    "mes": ["mes", "month"],
    "petroleo_m3": ["prod_pet", "produccion_petroleo", "pet_m3"],
    "gas_mm3": ["prod_gas", "produccion_gas", "gas_mm3"],
    "agua_m3": ["prod_agua", "produccion_agua", "agua"],
}

# Nombres cortos de operadoras: patrón sobre el nombre normalizado -> etiqueta.
OPERADORAS = [
    (r"\bYPF\b", "YPF"),
    (r"VISTA", "Vista"),
    (r"PAN AMERICAN", "Pan American Energy"),
    (r"TECPETROL", "Tecpetrol"),
    (r"PAMPA", "Pampa Energía"),
    (r"PLUSPETROL", "Pluspetrol"),
    (r"SHELL", "Shell"),
    (r"TOTAL", "TotalEnergies"),
    (r"CHEVRON", "Chevron"),
    (r"PHOENIX", "Phoenix Global"),
    (r"EXXON", "ExxonMobil"),
    (r"PETRONAS", "Petronas"),
    (r"WINTERSHALL|HARBOUR", "Harbour Energy"),
    (r"PAMPETROL", "Pampetrol"),
    (r"GYP|GAS Y PETROLEO DEL NEUQUEN", "GyP Neuquén"),
    (r"CAPEX", "Capex"),
    (r"PETROLERA ACONCAGUA", "Petrolera Aconcagua"),
    (r"MEDANITO", "Medanito"),
    (r"SAN JORGE", "Petrolera San Jorge"),
]


def norm(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().upper()


def nombre_corto(empresa: str) -> str:
    n = norm(empresa)
    for patron, etiqueta in OPERADORAS:
        if re.search(patron, n):
            return etiqueta
    limpio = re.sub(r"\b(S\.?A\.?U?|S\.?R\.?L\.?|SUCURSAL ARGENTINA|ARGENTINA)\b\.?", "", n).strip(" .,-")
    return limpio.title() or "Otras"


def nombre_area(area: str) -> str:
    if not str(area).strip():
        return "Sin dato"
    # Conserva acentos y eñes del original; solo se normaliza para comparar.
    palabras = re.sub(r"\s+", " ", str(area)).strip().title().split()
    menores = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y"}
    return " ".join(w.lower() if i and norm(w) in menores and palabras[i - 1] != "-" else w for i, w in enumerate(palabras))


def leer_csv(fuente: str | Path) -> pd.DataFrame:
    if isinstance(fuente, Path):
        crudo = fuente.read_bytes()
    else:
        print(f"Descargando {fuente}", file=sys.stderr)
        r = requests.get(fuente, timeout=600)
        r.raise_for_status()
        crudo = r.content
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = crudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if texto[:2000].count(";") > texto[:2000].count(",") else ","
    df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, low_memory=False)
    df.columns = [norm(c).lower() for c in df.columns]
    renombre = {}
    for canon, opciones in COLUMNAS.items():
        for op in opciones:
            if op in df.columns:
                renombre[op] = canon
                break
    df = df.rename(columns=renombre)
    faltan = [c for c in ("empresa", "cuenca", "anio", "mes", "petroleo_m3", "gas_mm3") if c not in df.columns]
    if faltan:
        raise ValueError(f"Faltan columnas {faltan} en {fuente}. Columnas: {list(df.columns)}")
    for c in ("formacion", "tipo_recurso", "pozo", "area", "provincia", "agua_m3"):
        if c not in df.columns:
            df[c] = ""
    df = df[["empresa", "pozo", "area", "provincia", "cuenca", "formacion", "tipo_recurso", "anio", "mes", "petroleo_m3", "gas_mm3", "agua_m3"]].copy()
    for c in ("petroleo_m3", "gas_mm3", "agua_m3"):
        df[c] = pd.to_numeric(df[c].str.replace(",", ".", regex=False), errors="coerce").fillna(0.0)
    df["anio"] = pd.to_numeric(df["anio"], errors="coerce")
    df["mes"] = pd.to_numeric(df["mes"], errors="coerce")
    return df.dropna(subset=["anio", "mes"]).astype({"anio": int, "mes": int})


def es_vaca_muerta(df: pd.DataFrame) -> pd.Series:
    cuenca = df["cuenca"].fillna("").map(norm)
    formacion = df["formacion"].fillna("").map(norm)
    recurso = df["tipo_recurso"].fillna("").map(norm)
    neuquina = cuenca.str.contains("NEUQUINA")
    vm = formacion.str.contains("VACA MUERTA")
    sin_formacion = formacion.eq("")
    no_conv = recurso.str.contains("NO CONVENCIONAL")
    return neuquina & (vm | (sin_formacion & no_conv))


def por_dia(df: pd.DataFrame) -> pd.DataFrame:
    dias = df.apply(lambda r: calendar.monthrange(int(r["anio"]), int(r["mes"]))[1], axis=1)
    df = df.copy()
    df["oil_bbl_d"] = df["petroleo_m3"] * M3_TO_BBL / dias
    df["gas_mmm3_d"] = df["gas_mm3"] / 1000 / dias
    return df


def curvas_tipo(df: pd.DataFrame, primeros: pd.Series) -> dict:
    """Producción acumulada de petróleo de cada pozo en sus primeros 6 y 12 meses, por camada.

    Camada = año en que el pozo empezó a producir. Solo pozos petroleros (más del 50% de su
    producción en barriles equivalentes es petróleo durante los primeros 6 meses).
    """
    d = df[["pozo", "empresa", "anio", "mes", "petroleo_m3", "gas_mm3"]].copy()
    d["idx"] = d["anio"] * 12 + d["mes"]
    ini = primeros.map(lambda p: (p // 100) * 12 + p % 100)
    d["k"] = d["idx"] - d["pozo"].map(ini)
    d = d[(d["k"] >= 0) & (d["k"] < 12)]
    ultimo = int(d["idx"].max())
    d6 = d[d["k"] < 6].groupby("pozo")[["petroleo_m3", "gas_mm3"]].sum().rename(columns={"petroleo_m3": "oil6", "gas_mm3": "gas6"})
    agg = d.groupby("pozo").agg(oil12=("petroleo_m3", "sum"), empresa=("empresa", "first")).join(d6, how="left").fillna({"oil6": 0, "gas6": 0})
    agg["inicio"] = agg.index.map(ini)
    agg["cohorte"] = (agg["inicio"] - 1) // 12
    agg["operadora"] = agg["empresa"].map(nombre_corto)
    boe_oil = agg["oil6"] * M3_TO_BBL
    agg = agg[(boe_oil > 0) & (boe_oil / (boe_oil + agg["gas6"] * 5.886) > 0.5)]
    con6 = agg[agg["inicio"] <= ultimo - 5]
    con12 = agg[agg["inicio"] <= ultimo - 11]
    kbbl = lambda m3: round(float(m3) * M3_TO_BBL / 1000, 1)
    cohortes = []
    for c in sorted(con6["cohorte"].unique()):
        if c < 2014:
            continue
        g6, g12 = con6[con6["cohorte"] == c], con12[con12["cohorte"] == c]
        if len(g6) < 10:
            continue
        cohortes.append({
            "year": int(c), "wells_6m": int(len(g6)),
            "avg_6m_kbbl": kbbl(g6["oil6"].mean()), "median_6m_kbbl": kbbl(g6["oil6"].median()),
            "wells_12m": int(len(g12)),
            "avg_12m_kbbl": kbbl(g12["oil12"].mean()) if len(g12) >= 10 else None,
        })
    # Operadoras: pozos de los últimos 24 meses con 6 meses completos.
    rec = con6[con6["inicio"] > ultimo - 30]
    ops = []
    for nombre, g in rec.groupby("operadora"):
        if len(g) >= 8:
            ops.append({"name": nombre, "wells": int(len(g)), "avg_6m_kbbl": kbbl(g["oil6"].mean())})
    ops.sort(key=lambda o: o["avg_6m_kbbl"], reverse=True)
    return {"cohorts": cohortes, "operators_recent": ops[:10],
            "operators_window": f"{(ultimo - 30) // 12}-{((ultimo - 30) % 12) + 1:02d}"}


def construir(historico: pd.DataFrame, anuales: list[pd.DataFrame]) -> dict:
    hist_vm = historico[es_vaca_muerta(historico)]
    ultimo_hist = hist_vm["anio"] * 100 + hist_vm["mes"]
    tope = int(ultimo_hist.max()) if len(hist_vm) else 0

    partes = [hist_vm]
    nacional = []
    for df in anuales:
        nacional.append(df)
        periodo = df["anio"] * 100 + df["mes"]
        nuevos = df[es_vaca_muerta(df) & (periodo > tope)]
        if len(nuevos):
            partes.append(nuevos)
    vm = pd.concat(partes, ignore_index=True)
    vm["periodo"] = vm["anio"] * 100 + vm["mes"]
    produce = (vm["petroleo_m3"] > 0) | (vm["gas_mm3"] > 0)
    con_id = vm["pozo"].fillna("").str.strip().ne("")
    # Mes de primera producción de cada pozo (sobre toda la historia disponible).
    primeros = vm[produce & con_id].groupby("pozo")["periodo"].min()
    type_curves = curvas_tipo(vm[produce & con_id], primeros)
    nuevos_por_mes = primeros.value_counts()
    activos_por_mes = vm[produce & con_id].groupby("periodo")["pozo"].nunique()
    vm = vm[vm["anio"] >= START_YEAR]
    vm["operadora"] = vm["empresa"].map(nombre_corto)
    vm["area_n"] = vm["area"].fillna("").map(nombre_area)

    mensual = (
        vm.groupby(["anio", "mes"], as_index=False)[["petroleo_m3", "gas_mm3", "agua_m3"]].sum()
        .sort_values(["anio", "mes"])
    )
    mensual = por_dia(mensual)

    # Se descarta el último mes si su volumen cae más de 25% contra el anterior:
    # suele ser un mes con declaraciones juradas todavía incompletas.
    if len(mensual) >= 2:
        a, b = mensual.iloc[-2]["oil_bbl_d"], mensual.iloc[-1]["oil_bbl_d"]
        if a > 0 and b < a * 0.75:
            mensual = mensual.iloc[:-1]

    ult = mensual.iloc[-1]
    ult_a, ult_m = int(ult["anio"]), int(ult["mes"])

    def valor(df, anio, mes, col):
        fila = df[(df["anio"] == anio) & (df["mes"] == mes)]
        return float(fila[col].iloc[0]) if len(fila) else None

    def variacion(actual, previo):
        return round((actual / previo - 1) * 100, 1) if actual and previo else None

    oil = float(ult["oil_bbl_d"])
    gas = float(ult["gas_mmm3_d"])
    oil_ya = valor(mensual, ult_a - 1, ult_m, "oil_bbl_d")
    gas_ya = valor(mensual, ult_a - 1, ult_m, "gas_mmm3_d")

    # Participación en el total nacional del último mes (si hay archivo anual).
    share = None
    for df in nacional:
        mes_df = df[(df["anio"] == ult_a) & (df["mes"] == ult_m)]
        if len(mes_df):
            total = mes_df["petroleo_m3"].sum()
            vm_mes = vm[(vm["anio"] == ult_a) & (vm["mes"] == ult_m)]["petroleo_m3"].sum()
            if total > 0:
                share = round(vm_mes / total * 100, 1)
            break

    # Operadoras: último mes y mismo mes del año anterior.
    ops = vm.groupby(["operadora", "anio", "mes"], as_index=False)[["petroleo_m3", "gas_mm3"]].sum()
    ops = por_dia(ops)
    actual = ops[(ops["anio"] == ult_a) & (ops["mes"] == ult_m)].set_index("operadora")
    previo = ops[(ops["anio"] == ult_a - 1) & (ops["mes"] == ult_m)].set_index("operadora")
    total_oil = actual["oil_bbl_d"].sum()
    filas = []
    for nombre, f in actual.sort_values("oil_bbl_d", ascending=False).iterrows():
        prev = previo["oil_bbl_d"].get(nombre) if nombre in previo.index else None
        filas.append({
            "name": nombre,
            "oil_bbl_d": round(float(f["oil_bbl_d"])),
            "gas_mmm3_d": round(float(f["gas_mmm3_d"]), 2),
            "share_pct": round(float(f["oil_bbl_d"]) / total_oil * 100, 1) if total_oil else None,
            "oil_yoy_pct": variacion(float(f["oil_bbl_d"]), prev),
        })
    top = filas[:10]
    resto = filas[10:]
    if resto:
        top.append({
            "name": "Otras",
            "oil_bbl_d": sum(r["oil_bbl_d"] for r in resto),
            "gas_mmm3_d": round(sum(r["gas_mmm3_d"] for r in resto), 2),
            "share_pct": round(sum(r["share_pct"] or 0 for r in resto), 1),
            "oil_yoy_pct": None,
        })

    # Pozos: nuevos y en producción, últimos WELLS_MONTHS meses hasta el último mes.
    periodos = [int(f"{r.anio}{r.mes:02d}") for r in mensual.itertuples()]
    wells = []
    for per in periodos[-WELLS_MONTHS:]:
        act = int(activos_por_mes.get(per, 0))
        fila_m = mensual[(mensual["anio"] == per // 100) & (mensual["mes"] == per % 100)].iloc[0]
        wells.append({
            "period": f"{per // 100:04d}-{per % 100:02d}",
            "new": int(nuevos_por_mes.get(per, 0)),
            "active": act,
            "oil_per_well_bbl_d": round(float(fila_m["oil_bbl_d"]) / act, 1) if act else None,
        })

    # Áreas (permisos o concesiones): último mes, operadora principal y variación anual.
    ar = vm.groupby(["area_n", "anio", "mes"], as_index=False)[["petroleo_m3", "gas_mm3"]].sum()
    ar = por_dia(ar)
    ar_act = ar[(ar["anio"] == ult_a) & (ar["mes"] == ult_m)].set_index("area_n")
    ar_prev = ar[(ar["anio"] == ult_a - 1) & (ar["mes"] == ult_m)].set_index("area_n")
    ult_vm = vm[(vm["anio"] == ult_a) & (vm["mes"] == ult_m)]
    # Operadora principal por bloque: la de mayor producción en barriles equivalentes (petróleo + gas).
    ult_vm = ult_vm.assign(boe=ult_vm["petroleo_m3"] * M3_TO_BBL + ult_vm["gas_mm3"] * 5.886)
    op_area = ult_vm.groupby(["area_n", "operadora"])["boe"].sum().reset_index()
    op_area = op_area.sort_values("boe", ascending=False).drop_duplicates("area_n").set_index("area_n")["operadora"]
    prov_area = (ult_vm[ult_vm["provincia"].fillna("").str.strip() != ""].groupby("area_n")["provincia"]
                 .agg(lambda x: x.mode().iat[0] if len(x.mode()) else "").map(lambda p: str(p).strip().title()))
    areas = []
    for nombre, f in ar_act.sort_values("oil_bbl_d", ascending=False).head(15).iterrows():
        prev = ar_prev["oil_bbl_d"].get(nombre) if nombre in ar_prev.index else None
        areas.append({
            "name": nombre,
            "operator": op_area.get(nombre, ""),
            "oil_bbl_d": round(float(f["oil_bbl_d"])),
            "gas_mmm3_d": round(float(f["gas_mmm3_d"]), 2),
            "share_pct": round(float(f["oil_bbl_d"]) / total_oil * 100, 1) if total_oil else None,
            "oil_yoy_pct": variacion(float(f["oil_bbl_d"]), prev),
        })

    # Todos los bloques con producción en el último mes (para el mapa).
    areas_all = []
    for nombre, f in ar_act.sort_values("oil_bbl_d", ascending=False).iterrows():
        if f["oil_bbl_d"] <= 0 and f["gas_mmm3_d"] <= 0:
            continue
        p_oil = ar_prev["oil_bbl_d"].get(nombre) if nombre in ar_prev.index else None
        p_gas = ar_prev["gas_mmm3_d"].get(nombre) if nombre in ar_prev.index else None
        areas_all.append({
            "name": nombre,
            "province": prov_area.get(nombre, ""),
            "operator": op_area.get(nombre, ""),
            "oil_bbl_d": round(float(f["oil_bbl_d"])),
            "gas_mmm3_d": round(float(f["gas_mmm3_d"]), 3),
            "oil_yoy_pct": variacion(float(f["oil_bbl_d"]), p_oil),
            "gas_yoy_pct": variacion(float(f["gas_mmm3_d"]), p_gas),
        })

    # Serie mensual de las cinco operadoras principales del último mes.
    top5 = [r["name"] for r in filas[:5]]
    hist = ops[(ops["operadora"].isin(top5)) & (ops["anio"] >= HISTORY_FROM)]
    operators_history = {
        "names": top5,
        "periods": [f"{r.anio:04d}-{r.mes:02d}" for r in mensual[mensual["anio"] >= HISTORY_FROM].itertuples()],
    }
    series = {}
    for nombre in top5:
        h = hist[hist["operadora"] == nombre].set_index(["anio", "mes"])["oil_bbl_d"]
        series[nombre] = [round(float(h.get((int(p[:4]), int(p[5:])), 0.0))) for p in operators_history["periods"]]
    operators_history["oil_bbl_d"] = series

    activos_ult = wells[-1]["active"] if wells else None
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "latest_period": f"{ult_a:04d}-{ult_m:02d}",
        "source": {
            "name": "Secretaría de Energía de la Nación, Capítulo IV (Res. 319/93)",
            "url": SOURCE_PAGE,
            "license": "CC BY 4.0",
        },
        "kpis": {
            "oil_bbl_d": round(oil),
            "oil_yoy_pct": variacion(oil, oil_ya),
            "gas_mmm3_d": round(gas, 1),
            "gas_yoy_pct": variacion(gas, gas_ya),
            "national_oil_share_pct": share,
            "operators": int(len(actual)),
            "active_wells": activos_ult,
            "new_wells_12m": sum(w["new"] for w in wells[-12:]) if wells else None,
            "oil_per_well_bbl_d": wells[-1]["oil_per_well_bbl_d"] if wells else None,
        },
        "wells": wells,
        "areas": areas,
        "areas_all": areas_all,
        "type_curves": type_curves,
        "operators_history": operators_history,
        "monthly": [
            {
                "period": f"{int(r.anio):04d}-{int(r.mes):02d}",
                "oil_bbl_d": round(float(r.oil_bbl_d)),
                "gas_mmm3_d": round(float(r.gas_mmm3_d), 2),
                "water_cut_pct": round(float(r.agua_m3) / float(r.agua_m3 + r.petroleo_m3) * 100, 1) if (r.agua_m3 + r.petroleo_m3) > 0 else None,
            }
            for r in mensual.itertuples()
        ],
        "operators": top,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--local", type=Path, help="directorio con CSV ya descargados")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()

    anio_actual = date.today().year
    anios = [a for a in sorted(ANUALES) if a >= anio_actual - 1]

    if args.local:
        historico = leer_csv(args.local / "no_convencional.csv")
        anuales = [leer_csv(args.local / f"{a}.csv") for a in anios if (args.local / f"{a}.csv").exists()]
    else:
        historico = leer_csv(HISTORICO_NC)
        anuales = []
        for a in anios:
            try:
                anuales.append(leer_csv(ANUALES[a]))
            except Exception as e:  # un archivo anual caído no frena el resto
                print(f"Aviso: no se pudo leer {a}: {e}", file=sys.stderr)

    datos = construir(historico, anuales)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    pozos = {w["period"]: w for w in datos["wells"]}
    lineas = ["period,oil_bbl_d,gas_mmm3_d,new_wells,active_wells"]
    for r in datos["monthly"]:
        w = pozos.get(r["period"], {})
        lineas.append(f'{r["period"]},{r["oil_bbl_d"]},{r["gas_mmm3_d"]},{w.get("new", "")},{w.get("active", "")}')
    (args.out.parent / "vm_monthly.csv").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    k = datos["kpis"]
    print(f"OK {datos['latest_period']}: {k['oil_bbl_d']:,} bbl/d, {k['gas_mmm3_d']} MMm3/d, "
          f"{len(datos['monthly'])} meses, {k['operators']} operadoras")


if __name__ == "__main__":
    main()
