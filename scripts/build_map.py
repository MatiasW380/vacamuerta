"""Genera las capas del mapa: bloques de Neuquén con su producción y ductos principales.

Fuente geográfica: Subsecretaría de Energía, Minería e Hidrocarburos de Neuquén,
servicios OGC (WFS). Producción: data/vm.json (Capítulo IV, Secretaría de Energía).

Salida:
    data/map_areas.geojson   polígonos simplificados con producción del último mes
    data/map_ducts.geojson   ductos principales simplificados (petróleo / gas)
    data/map_status.json     diagnóstico: capas encontradas, atributos, cruces de nombres
"""

from __future__ import annotations

import difflib
import json
import re
import sys
import traceback
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import mapping, shape

DATA = Path(__file__).resolve().parent.parent / "data"
WFS = "https://hidrocarburos.energianeuquen.gob.ar/geoserver/wfs"
SOURCE = {"name": "Subsecretaría de Energía, Minería e Hidrocarburos de Neuquén",
          "url": "https://hidrocarburos.energianeuquen.gob.ar/gis"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; VacaMuertaMonitor/1.0; +https://github.com/MatiasW380/vacamuerta)"}
TOL_AREAS = 0.0015   # grados (~150 m)
TOL_DUCTS = 0.002


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().upper()
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = re.sub(r"\b(AREA|LOTE|BLOQUE|CONCESION|EXPLOTACION|EXPLORACION|PERMISO|CNE|CENCH)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def capas(diag: dict) -> list[dict]:
    r = requests.get(WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"},
                     headers=UA, timeout=90)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    for ft in root.iter():
        if ft.tag.endswith("FeatureType"):
            nombre = next((c.text for c in ft if c.tag.endswith("Name")), None)
            titulo = next((c.text for c in ft if c.tag.endswith("Title")), "") or ""
            if nombre:
                out.append({"name": nombre, "title": titulo})
    diag["layers"] = out
    return out


def elegir(lista: list[dict], incluir: list[str], excluir: list[str] = ()) -> str | None:
    for c in lista:
        t = norm(c["name"] + " " + c["title"]).lower()
        if all(i in t for i in incluir) and not any(e in t for e in excluir):
            return c["name"]
    return None


def features(capa: str) -> list[dict]:
    r = requests.get(WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                  "typeNames": capa, "outputFormat": "application/json", "srsName": "EPSG:4326"},
                     headers=UA, timeout=300)
    r.raise_for_status()
    return r.json().get("features", [])


def redondear(geom: dict, nd: int = 4) -> dict:
    def r(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [r(x) for x in c]
    return {"type": geom["type"], "coordinates": r(geom["coordinates"])}


def simplificar(geom: dict, tol: float) -> dict | None:
    try:
        g = shape(geom)
        if g.is_empty:
            return None
        g = g.simplify(tol, preserve_topology=True)
        return redondear(mapping(g)) if not g.is_empty else None
    except Exception:
        return None


def clave_nombre(props: dict) -> str | None:
    """Atributo que contiene el nombre del área."""
    preferidas = ["nombre", "name", "area", "denominacion", "nom_area", "area_nombre"]
    claves = {k.lower(): k for k in props}
    for p in preferidas:
        for kl, k in claves.items():
            if p == kl or (p in kl and isinstance(props[k], str)):
                return k
    return next((k for k, v in props.items() if isinstance(v, str) and len(v) > 3), None)


def main() -> None:
    diag: dict = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")}
    try:
        lista = capas(diag)
        capa_areas = elegir(lista, ["area"], ["sism", "mina", "cante", "cateo"])
        capa_ductos = elegir(lista, ["ducto"], ["linea", "conducc"]) or elegir(lista, ["ducto"])
        diag.update({"areas_layer": capa_areas, "ducts_layer": capa_ductos})
        if not capa_areas:
            raise RuntimeError("No se encontró la capa de áreas hidrocarburíferas")

        vm = json.loads((DATA / "vm.json").read_text(encoding="utf-8"))
        prod = {norm(a["name"]): a for a in vm.get("areas_all", [])}

        feats = features(capa_areas)
        diag["areas_features"] = len(feats)
        kn = clave_nombre(feats[0]["properties"]) if feats else None
        diag["areas_name_key"] = kn
        diag["areas_sample_props"] = feats[0]["properties"] if feats else None

        usados, salida, sin_cruce = set(), [], []
        nombres_prod = list(prod)
        for f in feats:
            nombre = (f.get("properties") or {}).get(kn) or ""
            n = norm(nombre)
            match = prod.get(n)
            if not match and n:
                cerca = difflib.get_close_matches(n, nombres_prod, n=1, cutoff=0.86)
                match = prod.get(cerca[0]) if cerca else None
            geom = simplificar(f["geometry"], TOL_AREAS) if f.get("geometry") else None
            if not geom:
                continue
            props = {"name": str(nombre).strip().title() or "Sin nombre"}
            if match:
                usados.add(norm(match["name"]))
                props.update({k: match[k] for k in ("name", "operator", "oil_bbl_d", "gas_mmm3_d", "oil_yoy_pct", "gas_yoy_pct")})
            salida.append({"type": "Feature", "geometry": geom, "properties": props})
        sin_cruce = [a["name"] for k, a in prod.items() if k not in usados and (a.get("province", "").lower().startswith("neuq"))]
        diag["areas_matched"] = len(usados)
        diag["neuquen_blocks_without_shape"] = sin_cruce[:40]
        diag["blocks_outside_neuquen"] = [a["name"] for a in prod.values() if not a.get("province", "").lower().startswith("neuq")][:20]

        total = sum(a["oil_bbl_d"] for a in prod.values()) or 1
        cubierto = sum(prod[k]["oil_bbl_d"] for k in usados)
        diag["oil_share_on_map_pct"] = round(cubierto / total * 100, 1)

        (DATA / "map_areas.geojson").write_text(json.dumps({
            "type": "FeatureCollection", "source": SOURCE, "period": vm.get("latest_period"),
            "features": salida}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        if capa_ductos:
            dfe = features(capa_ductos)
            diag["ducts_features"] = len(dfe)
            diag["ducts_sample_props"] = dfe[0]["properties"] if dfe else None
            lineas = []
            for f in dfe:
                geom = simplificar(f["geometry"], TOL_DUCTS) if f.get("geometry") else None
                if not geom:
                    continue
                texto = norm(" ".join(str(v) for v in (f.get("properties") or {}).values())).lower()
                kind = "gas" if "gas" in texto else "oil" if ("oleo" in texto or "petrol" in texto or "crudo" in texto) else "other"
                nombre = next((str(v) for k, v in (f.get("properties") or {}).items()
                               if isinstance(v, str) and any(x in k.lower() for x in ("nombre", "name", "denom"))), "")
                lineas.append({"type": "Feature", "geometry": geom, "properties": {"kind": kind, "name": nombre.strip().title()}})
            diag["ducts_kinds"] = {k: sum(1 for l in lineas if l["properties"]["kind"] == k) for k in ("oil", "gas", "other")}
            (DATA / "map_ducts.geojson").write_text(json.dumps({
                "type": "FeatureCollection", "source": SOURCE, "features": lineas},
                ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        for nombre in ("map_areas.geojson", "map_ducts.geojson"):
            p = DATA / nombre
            if p.exists():
                diag[f"{nombre}_kb"] = round(p.stat().st_size / 1024)
        diag["ok"] = True
        print(f"OK mapa: {diag.get('areas_matched')} bloques con producción, {diag.get('oil_share_on_map_pct')}% del petróleo")
    except Exception as e:
        diag.update({"ok": False, "error": f"{type(e).__name__}: {str(e)[:500]}", "trace": traceback.format_exc()[-1500:]})
        print(f"ERROR mapa: {e}", file=sys.stderr)
    (DATA / "map_status.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
