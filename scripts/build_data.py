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

# Nombre canónico -> posibles nombres de columna en los distintos archivos.
COLUMNAS = {
    "empresa": ["empresa", "operadora"],
    "pozo": ["idpozo", "id_pozo", "pozoid"],
    "cuenca": ["cuenca"],
    "formacion": ["formacion", "formprod"],
    "tipo_recurso": ["tipo_de_recurso", "tiporecurso", "tipo_recurso", "sub_tipo_recurso", "subtipoderecurso"],
    "anio": ["anio", "ano", "year"],
    "mes": ["mes", "month"],
    "petroleo_m3": ["prod_pet", "produccion_petroleo", "pet_m3"],
    "gas_mm3": ["prod_gas", "produccion_gas", "gas_mm3"],
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
    for c in ("formacion", "tipo_recurso"):
        if c not in df.columns:
            df[c] = ""
    df = df[["empresa", "cuenca", "formacion", "tipo_recurso", "anio", "mes", "petroleo_m3", "gas_mm3"]].copy()
    for c in ("petroleo_m3", "gas_mm3"):
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
    vm = vm[vm["anio"] >= START_YEAR]
    vm["operadora"] = vm["empresa"].map(nombre_corto)

    mensual = (
        vm.groupby(["anio", "mes"], as_index=False)[["petroleo_m3", "gas_mm3"]].sum()
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
        },
        "monthly": [
            {
                "period": f"{int(r.anio):04d}-{int(r.mes):02d}",
                "oil_bbl_d": round(float(r.oil_bbl_d)),
                "gas_mmm3_d": round(float(r.gas_mmm3_d), 2),
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
    k = datos["kpis"]
    print(f"OK {datos['latest_period']}: {k['oil_bbl_d']:,} bbl/d, {k['gas_mmm3_d']} MMm3/d, "
          f"{len(datos['monthly'])} meses, {k['operators']} operadoras")


if __name__ == "__main__":
    main()
