"""
data_fetcher.py
---------------
Recolecta datos de todas las fuentes para el IDEC-BC.
Cada función devuelve el valor más reciente disponible del indicador.
Si la fuente falla, usa caché local para no romper el cálculo del índice.
"""

import os
import json
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Rutas ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── Tokens: st.secrets en Streamlit Cloud, .env en local ──────────────────────
def _get_secret(key: str) -> str:
    try:
        import streamlit as st
        return st.secrets.get(key, os.getenv(key, ""))
    except Exception:
        return os.getenv(key, "")

INEGI_TOKEN = _get_secret("INEGI_TOKEN")
BANXICO_TOKEN = _get_secret("BANXICO_TOKEN")


# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES DE CACHÉ
# ══════════════════════════════════════════════════════════════════════════════

def _save_cache(key: str, value: float | dict):
    """Guarda un valor en caché local con timestamp."""
    cache_file = CACHE_DIR / f"{key}.json"
    payload = {"value": value, "timestamp": datetime.now().isoformat()}
    with open(cache_file, "w") as f:
        json.dump(payload, f)


def _load_cache(key: str, max_age_days: int = 35) -> float | dict | None:
    """
    Carga valor del caché si existe y no tiene más de max_age_days días.
    Retorna None si no existe o está vencido.
    """
    cache_file = CACHE_DIR / f"{key}.json"
    if not cache_file.exists():
        return None
    with open(cache_file, "r") as f:
        payload = json.load(f)
    saved_at = datetime.fromisoformat(payload["timestamp"])
    if datetime.now() - saved_at > timedelta(days=max_age_days):
        return None
    return payload["value"]


def _fetch_with_cache(key: str, fetch_fn, max_age_days: int = 35):
    """
    Intenta obtener dato fresco. Si falla, usa caché.
    Si no hay caché, retorna None (el calculador lo manejará).
    """
    try:
        value = fetch_fn()
        if value is not None:
            _save_cache(key, value)
            return value, "live"
    except Exception as e:
        print(f"[WARN] {key}: fuente falló ({e}), usando caché")

    cached = _load_cache(key, max_age_days)
    if cached is not None:
        return cached, "cache"

    return None, "unavailable"


# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 1: INEGI — BIE (Banco de Información Económica)
# ══════════════════════════════════════════════════════════════════════════════

INEGI_BASE = "https://www.inegi.org.mx/app/api/indicadores/desarrolladores/jsonxml/INDICATOR"

def _inegi_get(serie_id: str) -> float | None:
    """
    Consulta una serie del BIE de INEGI y retorna el valor más reciente.
    serie_id: clave numérica de la serie en el BIE.
    """
    url = (
        f"{INEGI_BASE}/{serie_id}/es/0700/false/BIE/2.0/{INEGI_TOKEN}?type=json"
    )
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    obs = data["Series"][0]["OBSERVATIONS"]
    # Filtra observaciones con valor numérico y toma la más reciente
    valid = [(o["TIME_PERIOD"], float(o["OBS_VALUE"]))
             for o in obs if o.get("OBS_VALUE") not in (None, "", "N/A")]
    if not valid:
        return None
    valid.sort(key=lambda x: x[0], reverse=True)
    return valid[0][1]


def get_tasa_desocupacion_bc() -> tuple:
    """Tasa de desocupación BC — ENOE trimestral (%)."""
    # Serie BIE: Tasa de desocupación BC
    return _fetch_with_cache(
        "tasa_desocupacion_bc",
        lambda: _inegi_get("444024"),
    )


def get_tasa_informalidad_bc() -> tuple:
    """Tasa de informalidad laboral BC — ENOE trimestral (%)."""
    return _fetch_with_cache(
        "tasa_informalidad_bc",
        lambda: _inegi_get("444079"),
    )


def get_valor_construccion_bc() -> tuple:
    """Valor de producción en construcción BC — ENEC mensual (miles de pesos)."""
    return _fetch_with_cache(
        "valor_construccion_bc",
        lambda: _inegi_get("400729"),
    )


def get_inpc_tijuana() -> tuple:
    """INPC Tijuana — mensual (índice base 2018=100)."""
    return _fetch_with_cache(
        "inpc_tijuana",
        lambda: _inegi_get("628229"),
    )


def get_confianza_consumidor_bc() -> tuple:
    """Índice de confianza del consumidor BC — ENCO mensual."""
    return _fetch_with_cache(
        "confianza_consumidor_bc",
        lambda: _inegi_get("516844"),
    )


def get_exportaciones_bc() -> tuple:
    """Exportaciones totales BC — mensual (millones de dólares)."""
    return _fetch_with_cache(
        "exportaciones_bc",
        lambda: _inegi_get("158023"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 2: BANXICO — SIE
# ══════════════════════════════════════════════════════════════════════════════

BANXICO_BASE = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"

def _banxico_get(serie_id: str) -> float | None:
    """
    Consulta una serie del SIE de Banxico usando requests directo.
    Endpoint /datos/oportuno devuelve el dato más reciente disponible.
    """
    url = f"{BANXICO_BASE}/{serie_id}/datos/oportuno"
    headers = {"Bmx-Token": BANXICO_TOKEN}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    obs = data["bmx"]["series"][0]["datos"]
    if not obs:
        return None
    valor = obs[-1]["dato"].replace(",", "").strip()
    if valor in ("N/E", "N/A", ""):
        return None
    return float(valor)


def get_tipo_cambio() -> tuple:
    """Tipo de cambio MXN/USD — diario (SF43718)."""
    return _fetch_with_cache(
        "tipo_cambio",
        lambda: _banxico_get("SF43718"),
        max_age_days=3,
    )


def get_remesas_bc() -> tuple:
    """
    Remesas recibidas en BC — trimestral (millones de dólares).
    Nota: Banxico publica remesas por estado desde 2015.
    """
    # Serie de remesas Baja California (SE32) — verificar en SIE
    return _fetch_with_cache(
        "remesas_bc",
        lambda: _banxico_get("SE32"),
        max_age_days=95,
    )


# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 3: IMSS — Datos Abiertos (datos.gob.mx)
# ══════════════════════════════════════════════════════════════════════════════

IMSS_BASE_URL = "http://datos.imss.gob.mx/sites/default/files/asg-{year}-{month:02d}-{day:02d}.csv"

# Clave IMSS de Baja California
CLAVE_BC = "02"

def _get_imss_url_for_month(year: int, month: int) -> str:
    """
    El IMSS publica el archivo el último día hábil del mes.
    Intenta el día 31, 30, 29, 28 hasta encontrar uno válido.
    """
    for day in [31, 30, 29, 28]:
        try:
            url = IMSS_BASE_URL.format(year=year, month=month, day=day)
            resp = requests.head(url, timeout=10)
            if resp.status_code == 200:
                return url
        except Exception:
            continue
    return None


def _fetch_imss_asegurados_bc() -> float | None:
    """
    Descarga el archivo CSV del IMSS más reciente y filtra Baja California.
    Retorna el total de asegurados permanentes en BC.
    """
    now = datetime.now()
    # Intenta mes actual, si no el anterior
    for delta in [0, 1, 2]:
        target = now - pd.DateOffset(months=delta)
        year, month = target.year, target.month
        url = _get_imss_url_for_month(year, month)
        if url:
            break
    else:
        return None

    # El archivo es grande (~500MB) — filtramos en chunks
    total = 0
    chunk_size = 50_000
    for chunk in pd.read_csv(
        url,
        chunksize=chunk_size,
        usecols=["cve_entidad", "ta"],  # entidad y total asegurados
        dtype={"cve_entidad": str, "ta": float},
        encoding="latin1",
        low_memory=False,
    ):
        bc_chunk = chunk[chunk["cve_entidad"] == CLAVE_BC]
        total += bc_chunk["ta"].sum()

    return total if total > 0 else None


def get_asegurados_imss_bc() -> tuple:
    """Total de trabajadores asegurados IMSS en BC — mensual."""
    return _fetch_with_cache(
        "asegurados_imss_bc",
        _fetch_imss_asegurados_bc,
        max_age_days=40,
    )


# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 4: SE FEDERAL — IED por entidad
# ══════════════════════════════════════════════════════════════════════════════

SE_IED_URL = "https://datos.gob.mx/busca/api/3/action/datastore_search"

def _fetch_ied_bc() -> float | None:
    """
    Consulta IED captada en BC desde el portal de datos abiertos de la SE.
    Retorna el valor del trimestre más reciente en millones de dólares.
    """
    # Resource ID del dataset de IED por entidad federativa
    resource_id = "ed67f8f9-c47a-4b76-8a14-1cf1bd3c7fbb"
    params = {
        "resource_id": resource_id,
        "filters": json.dumps({"entidad": "Baja California"}),
        "sort": "periodo desc",
        "limit": 1,
    }
    resp = requests.get(SE_IED_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    records = data.get("result", {}).get("records", [])
    if not records:
        return None
    return float(records[0].get("ied_mdd", 0))


def get_ied_bc() -> tuple:
    """IED captada en Baja California — trimestral (millones USD)."""
    return _fetch_with_cache(
        "ied_bc",
        _fetch_ied_bc,
        max_age_days=95,
    )


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL — recolecta todos los indicadores
# ══════════════════════════════════════════════════════════════════════════════

def fetch_all_indicators() -> dict:
    """
    Ejecuta todas las consultas y devuelve un diccionario con:
      - value: valor numérico del indicador
      - source: 'live' | 'cache' | 'unavailable'
      - name: nombre legible
      - unit: unidad de medida
      - dimension: dimensión del índice a la que pertenece
    """
    fetchers = [
        ("tasa_desocupacion_bc",   get_tasa_desocupacion_bc,   "Tasa de desocupación BC",       "%",             "Empleo"),
        ("tasa_informalidad_bc",   get_tasa_informalidad_bc,   "Tasa de informalidad BC",        "%",             "Empleo"),
        ("asegurados_imss_bc",     get_asegurados_imss_bc,     "Trabajadores asegurados IMSS BC","personas",      "Empleo"),
        ("valor_construccion_bc",  get_valor_construccion_bc,  "Valor producción construcción BC","miles MXN",    "Actividad"),
        ("exportaciones_bc",       get_exportaciones_bc,       "Exportaciones BC",               "millones USD",  "Comercio"),
        ("tipo_cambio",            get_tipo_cambio,            "Tipo de cambio MXN/USD",         "MXN/USD",       "Comercio"),
        ("ied_bc",                 get_ied_bc,                 "IED captada en BC",              "millones USD",  "Inversión"),
        ("inpc_tijuana",           get_inpc_tijuana,           "INPC Tijuana",                   "índice",        "Bienestar"),
        ("confianza_consumidor_bc",get_confianza_consumidor_bc,"Confianza del consumidor BC",    "índice",        "Bienestar"),
        ("remesas_bc",             get_remesas_bc,             "Remesas recibidas BC",           "millones USD",  "Bienestar"),
    ]

    results = {}
    for key, fn, name, unit, dimension in fetchers:
        value, source = fn()
        results[key] = {
            "value": value,
            "source": source,
            "name": name,
            "unit": unit,
            "dimension": dimension,
        }
        status = "OK" if source == "live" else ("CACHÉ" if source == "cache" else "NO DISPONIBLE")
        print(f"  [{status}] {name}: {value}")

    return results


if __name__ == "__main__":
    print("Recolectando indicadores IDEC-BC...\n")
    datos = fetch_all_indicators()
    print(f"\nTotal indicadores: {len(datos)}")
    disponibles = sum(1 for v in datos.values() if v["source"] != "unavailable")
    print(f"Disponibles: {disponibles}/{len(datos)}")
