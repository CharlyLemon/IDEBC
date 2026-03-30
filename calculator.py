"""
calculator.py
-------------
Normaliza cada indicador y calcula el puntaje compuesto del IDEC-BC.

Metodología:
  1. Cada indicador se normaliza a escala 0–100 usando percentiles históricos
     (mínimo histórico = 0, máximo histórico = 100).
  2. Los indicadores "negativos" (mayor valor = peor situación, ej. desocupación)
     se invierten: score = 100 - score_raw.
  3. Se promedia por dimensión con ponderación igual entre indicadores de la misma.
  4. Se aplican los pesos por dimensión para obtener el puntaje compuesto final.
"""

import numpy as np
from dataclasses import dataclass


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE INDICADORES
# ══════════════════════════════════════════════════════════════════════════════

# Referencias históricas para normalización (mín/máx observado en BC)
# Estos valores deben revisarse y actualizarse con datos históricos reales.
# Son puntos de anclaje para que el índice sea comparable en el tiempo.
# Fuente: BIE INEGI / Banxico SIE (series 2010–2024)

INDICATOR_CONFIG = {
    # ── Empleo ─────────────────────────────────────────────────────────────────
    "tasa_desocupacion_bc": {
        "name": "Tasa de desocupación BC",
        "direction": "negative",   # más alto = peor
        "hist_min": 1.8,           # mínimo histórico BC (2022 T4)
        "hist_max": 8.5,           # máximo histórico BC (2020 T2, pandemia)
        "dimension": "Empleo",
        "weight_in_dim": 0.40,     # peso dentro de la dimensión Empleo
    },
    "tasa_informalidad_bc": {
        "name": "Tasa de informalidad BC",
        "direction": "negative",
        "hist_min": 30.0,          # BC tiene informalidad baja vs. media nacional
        "hist_max": 45.0,
        "dimension": "Empleo",
        "weight_in_dim": 0.25,
    },
    "asegurados_imss_bc": {
        "name": "Trabajadores asegurados IMSS BC",
        "direction": "positive",   # más alto = mejor
        "hist_min": 580_000,       # mín histórico (2009 crisis)
        "hist_max": 1_050_000,     # máx proyectado con nearshoring
        "dimension": "Empleo",
        "weight_in_dim": 0.35,
    },

    # ── Actividad productiva ────────────────────────────────────────────────────
    "valor_construccion_bc": {
        "name": "Valor producción construcción BC",
        "direction": "positive",
        "hist_min": 1_200_000,
        "hist_max": 6_500_000,
        "dimension": "Actividad",
        "weight_in_dim": 1.0,       # único indicador confirmado en esta dimensión
    },

    # ── Comercio exterior ──────────────────────────────────────────────────────
    "exportaciones_bc": {
        "name": "Exportaciones BC",
        "direction": "positive",
        "hist_min": 1_500,
        "hist_max": 4_500,
        "dimension": "Comercio",
        "weight_in_dim": 0.70,
    },
    "tipo_cambio": {
        "name": "Tipo de cambio MXN/USD",
        "direction": "neutral",    # depende del contexto; usamos estabilidad
        "hist_min": 16.5,
        "hist_max": 25.0,
        # Para BC exportadora: tipo de cambio alto beneficia exportadores
        # pero encarece importaciones de insumos. Usamos como señal de
        # condiciones financieras externas, no como positivo puro.
        "dimension": "Comercio",
        "weight_in_dim": 0.30,
    },

    # ── Inversión y empresa ────────────────────────────────────────────────────
    "ied_bc": {
        "name": "IED captada en BC",
        "direction": "positive",
        "hist_min": 50,
        "hist_max": 1_200,
        "dimension": "Inversión",
        "weight_in_dim": 1.0,
    },

    # ── Bienestar y consumo ────────────────────────────────────────────────────
    "inpc_tijuana": {
        "name": "INPC Tijuana",
        "direction": "negative",   # inflación alta = presión al consumidor
        # Para INPC usamos la variación anual, no el nivel. Se calcula en runtime.
        "hist_min": 2.0,           # inflación mín anual (%)
        "hist_max": 9.5,           # inflación máx anual (%)
        "dimension": "Bienestar",
        "weight_in_dim": 0.35,
    },
    "confianza_consumidor_bc": {
        "name": "Confianza del consumidor BC",
        "direction": "positive",
        "hist_min": 75.0,
        "hist_max": 115.0,
        "dimension": "Bienestar",
        "weight_in_dim": 0.40,
    },
    "remesas_bc": {
        "name": "Remesas recibidas BC",
        "direction": "positive",
        "hist_min": 120,
        "hist_max": 550,
        "dimension": "Bienestar",
        "weight_in_dim": 0.25,
    },
}

# ── Pesos por dimensión (suman 100%) ──────────────────────────────────────────
DIMENSION_WEIGHTS = {
    "Empleo":     0.25,
    "Actividad":  0.25,
    "Comercio":   0.20,
    "Inversión":  0.20,
    "Bienestar":  0.10,
}

# ── Escala de señal verbal ─────────────────────────────────────────────────────
SIGNAL_SCALE = [
    (0,  25,  "Contracción severa",   "desfavorable", "#E24B4A"),
    (25, 45,  "Debilidad moderada",   "desfavorable", "#D85A30"),
    (45, 55,  "Zona neutral",         "incertidumbre","#EF9F27"),
    (55, 75,  "Expansión moderada",   "favorable",    "#1D9E75"),
    (75, 100, "Expansión fuerte",     "favorable",    "#27500A"),
]


# ══════════════════════════════════════════════════════════════════════════════
# DATACLASSES PARA RESULTADOS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class IndicatorScore:
    key: str
    name: str
    raw_value: float
    normalized_score: float   # 0–100
    dimension: str
    source: str               # 'live' | 'cache' | 'unavailable'


@dataclass
class DimensionScore:
    name: str
    score: float              # 0–100
    weight: float             # peso en el índice compuesto
    indicators: list[IndicatorScore]
    n_available: int
    n_total: int


@dataclass
class IDECResult:
    composite_score: float           # 0–100
    signal_short: str                # "favorable" | "incertidumbre" | "desfavorable"
    signal_long: str                 # "Expansión moderada", etc.
    signal_color: str                # hex color
    dimensions: list[DimensionScore]
    indicator_scores: list[IndicatorScore]
    n_indicators_available: int
    n_indicators_total: int
    timestamp: str


# ══════════════════════════════════════════════════════════════════════════════
# NORMALIZACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def normalize(value: float, hist_min: float, hist_max: float,
              direction: str) -> float:
    """
    Normaliza un valor a escala 0–100.
    direction: 'positive' (más = mejor), 'negative' (más = peor), 'neutral'
    """
    if hist_max == hist_min:
        return 50.0

    # Clampear al rango histórico para evitar scores fuera de 0-100
    value_clamped = max(hist_min, min(hist_max, value))
    score = (value_clamped - hist_min) / (hist_max - hist_min) * 100

    if direction == "negative":
        score = 100 - score
    elif direction == "neutral":
        # Para tipo de cambio: puntuamos estabilidad (cercano a media histórica)
        mid = (hist_min + hist_max) / 2
        deviation = abs(value_clamped - mid) / ((hist_max - hist_min) / 2)
        score = max(0, 100 - deviation * 100)

    return round(float(score), 2)


# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def calculate_idec(raw_data: dict) -> IDECResult:
    """
    Recibe el diccionario de fetch_all_indicators() y calcula el IDEC-BC.
    
    Manejo de datos faltantes:
    - Si un indicador no está disponible, se excluye del promedio dimensional
      pero NO se le asigna 0 (eso distorsionaría el índice a la baja).
    - Si una dimensión entera no tiene datos, esa dimensión se excluye y los
      pesos de las demás se renormalizan para sumar 100%.
    """
    from datetime import datetime

    indicator_scores = []
    dimension_buckets = {dim: [] for dim in DIMENSION_WEIGHTS}

    # ── 1. Normalizar cada indicador disponible ────────────────────────────────
    for key, config in INDICATOR_CONFIG.items():
        raw = raw_data.get(key, {})
        value = raw.get("value")
        source = raw.get("source", "unavailable")

        if value is None or source == "unavailable":
            ind_score = IndicatorScore(
                key=key,
                name=config["name"],
                raw_value=None,
                normalized_score=None,
                dimension=config["dimension"],
                source="unavailable",
            )
        else:
            norm = normalize(value, config["hist_min"], config["hist_max"],
                             config["direction"])
            ind_score = IndicatorScore(
                key=key,
                name=config["name"],
                raw_value=value,
                normalized_score=norm,
                dimension=config["dimension"],
                source=source,
            )

        indicator_scores.append(ind_score)
        dimension_buckets[config["dimension"]].append(
            (ind_score, config["weight_in_dim"])
        )

    # ── 2. Score por dimensión (promedio ponderado interno) ────────────────────
    dimension_scores = []
    available_dim_weights = {}

    for dim_name, weight in DIMENSION_WEIGHTS.items():
        items = dimension_buckets[dim_name]
        available = [(s, w) for s, w in items if s.normalized_score is not None]

        if not available:
            dim_score = DimensionScore(
                name=dim_name, score=None, weight=weight,
                indicators=[s for s, _ in items],
                n_available=0, n_total=len(items),
            )
            dimension_scores.append(dim_score)
            continue

        # Renormalizar pesos internos si hay indicadores faltantes
        total_w = sum(w for _, w in available)
        dim_value = sum(s.normalized_score * (w / total_w) for s, w in available)

        dim_score = DimensionScore(
            name=dim_name, score=round(dim_value, 2), weight=weight,
            indicators=[s for s, _ in items],
            n_available=len(available), n_total=len(items),
        )
        dimension_scores.append(dim_score)
        available_dim_weights[dim_name] = (weight, dim_value)

    # ── 3. Score compuesto (renormalizar si hay dimensiones sin datos) ─────────
    if not available_dim_weights:
        composite = 50.0  # sin datos: señal neutral
    else:
        total_dim_weight = sum(w for w, _ in available_dim_weights.values())
        composite = sum(
            (w / total_dim_weight) * score
            for w, score in available_dim_weights.values()
        )
        composite = round(composite, 2)

    # ── 4. Señal verbal ────────────────────────────────────────────────────────
    signal_long, signal_short, signal_color = "Zona neutral", "incertidumbre", "#EF9F27"
    for lo, hi, long_, short_, color in SIGNAL_SCALE:
        if lo <= composite < hi or (composite >= 75 and hi == 100):
            signal_long, signal_short, signal_color = long_, short_, color
            break

    n_available = sum(1 for s in indicator_scores if s.source != "unavailable")

    return IDECResult(
        composite_score=composite,
        signal_short=signal_short,
        signal_long=signal_long,
        signal_color=signal_color,
        dimensions=dimension_scores,
        indicator_scores=indicator_scores,
        n_indicators_available=n_available,
        n_indicators_total=len(indicator_scores),
        timestamp=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )


def get_signal_info(score: float) -> tuple[str, str, str]:
    """Retorna (señal corta, señal larga, color) para un puntaje dado."""
    for lo, hi, long_, short_, color in SIGNAL_SCALE:
        if lo <= score < hi or (score >= 75 and hi == 100):
            return short_, long_, color
    return "incertidumbre", "Zona neutral", "#EF9F27"
