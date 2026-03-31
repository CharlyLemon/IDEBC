"""
IDEC-BC — Índice de Desarrollo Económico de Baja California
Secretaría de Economía e Innovación · Gobierno del Estado de Baja California

Archivo único — sin subcarpetas — compatible con Streamlit Cloud
"""

import os, sys, json, requests
import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from pathlib import Path
from datetime import datetime, timedelta

# ══════════════════════════════════════════════════════════════════════════════
# TOKENS — lee de st.secrets (Cloud) o variables de entorno (local)
# ══════════════════════════════════════════════════════════════════════════════

def _secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, "")

INEGI_TOKEN   = _secret("INEGI_TOKEN")
BANXICO_TOKEN = _secret("BANXICO_TOKEN")

# ══════════════════════════════════════════════════════════════════════════════
# CACHÉ LOCAL (carpeta data/cache dentro del repo)
# ══════════════════════════════════════════════════════════════════════════════

CACHE_DIR = Path(__file__).parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Limpiar caché de remesas si contiene valor negativo (dato corrupto de SE32)
_remesas_cache = CACHE_DIR / "remesas.json"
if _remesas_cache.exists():
    try:
        _rc = json.loads(_remesas_cache.read_text())
        if isinstance(_rc.get("value"), (int, float)) and _rc["value"] < 0:
            _remesas_cache.unlink()
    except Exception:
        pass

def _save(key, value):
    f = CACHE_DIR / f"{key}.json"
    f.write_text(json.dumps({"value": value, "ts": datetime.now().isoformat()}))

def _load(key, max_days=35):
    f = CACHE_DIR / f"{key}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    if datetime.now() - datetime.fromisoformat(d["ts"]) > timedelta(days=max_days):
        return None
    return d["value"]

def _fetch(key, fn, max_days=35):
    try:
        v = fn()
        if v is not None:
            _save(key, v)
            return v, "live"
    except Exception as e:
        pass
    c = _load(key, max_days)
    if c is not None:
        return c, "cache"
    return None, "unavailable"

# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 1 — INEGI BIE
# ══════════════════════════════════════════════════════════════════════════════

def _inegi(serie, banco="BISE", area="00"):
    """
    Consulta la API de INEGI.
    banco: BISE (Banco de Indicadores, nacional/estatal) o BIE (Banco de Info Económica)
    area: 00=nacional, 02=BC en BISE, 0700=BC en BIE clásico
    """
    url = (f"https://www.inegi.org.mx/app/api/indicadores/desarrolladores/"
           f"jsonxml/INDICATOR/{serie}/es/{area}/false/{banco}/2.0/{INEGI_TOKEN}?type=json")
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        series_list = data.get("Series", [])
        if not series_list:
            return None
        obs = series_list[0].get("OBSERVATIONS", [])
        vals = [(o["TIME_PERIOD"], float(o["OBS_VALUE"]))
                for o in obs if o.get("OBS_VALUE") not in (None, "", "N/A")]
        if not vals:
            return None
        return sorted(vals, reverse=True)[0][1]
    except Exception:
        return None

def _inegi_bise(serie, area="02"):
    """Shortcut para BISE con área BC por defecto."""
    return _inegi(serie, banco="BISE", area=area)

def _inegi_historico(serie, banco="BISE", area="02") -> pd.DataFrame:
    """
    Devuelve toda la serie histórica como DataFrame con columnas [periodo, valor].
    Cambia el parámetro true→false en la URL para obtener serie completa.
    """
    url = (f"https://www.inegi.org.mx/app/api/indicadores/desarrolladores/"
           f"jsonxml/INDICATOR/{serie}/es/{area}/false/{banco}/2.0/{INEGI_TOKEN}?type=json")
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json()
        series_list = data.get("Series", [])
        if not series_list:
            return pd.DataFrame()
        obs = series_list[0].get("OBSERVATIONS", [])
        rows = []
        for o in obs:
            if o.get("OBS_VALUE") not in (None, "", "N/A"):
                rows.append({"periodo": o["TIME_PERIOD"], "valor": float(o["OBS_VALUE"])})
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["periodo"] = pd.to_datetime(df["periodo"].str.replace("/", "-", regex=False),
                                       format="mixed", dayfirst=False)
        return df.sort_values("periodo").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()

def _banxico_historico(serie) -> pd.DataFrame:
    """Devuelve serie histórica de Banxico como DataFrame [periodo, valor]."""
    try:
        url = f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/{serie}/datos"
        r = requests.get(url, headers={"Bmx-Token": BANXICO_TOKEN}, timeout=20)
        r.raise_for_status()
        obs = r.json()["bmx"]["series"][0]["datos"]
        rows = []
        for o in obs:
            v = o["dato"].replace(",", "").strip()
            if v not in ("N/E", "N/A", "", "--"):
                try:
                    rows.append({"periodo": o["fecha"], "valor": float(v)})
                except ValueError:
                    pass
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["periodo"] = pd.to_datetime(df["periodo"], format="%d/%m/%Y", errors="coerce")
        return df.dropna(subset=["periodo"]).sort_values("periodo").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()

# ── IDs y parámetros confirmados directamente via API INEGI ──────────────────
# Verificados marzo 2026 — todos devuelven COBER_GEO:"02" (Baja California)

# BISE con área 02 = BC
_ID_POB_DESOCUPADA  = "6200093973"   # Pob desocupada 15+ BC — BISE área 02 ✓
_ID_PEA             = "6200093960"   # PEA 15+ BC             — BISE área 02 ✓
_ID_POB_OCUPADA     = "6200093954"   # Pob ocupada 15+ BC     — BISE área 02 ✓
_ID_CONSTRUCCION    = "796426"       # Valor producción construcción BC anual — BISE área 02 ✓
_ID_EXPORTACIONES   = "6207095692"   # Exportaciones totales BC trimestral    — BISE área 02 ✓
_ID_IMMEX           = "203932"       # Establecimientos IMMEX activos         — BIE-BISE área 00 (nacional, proxy)

# BIE-BISE con área 00 (no tienen desagregación estatal)
_ID_INPC_TJ         = "910392"       # INPC Tijuana — BIE-BISE área 00 ✓
_ID_CONFIANZA       = "454168"       # Confianza consumidor — BIE-BISE área 00 (proxy nacional) ✓

# No disponible vía API con área BC — se calcula
_ID_POB_INFORMAL    = None           # Informalidad BC: calculada = Pob informal / Pob ocupada

def _calc_desocupacion():
    """Tasa desocupación BC = (Pob desocupada / PEA) × 100 — ambas BISE área 02"""
    pob = _inegi_bise(_ID_POB_DESOCUPADA)
    pea = _inegi_bise(_ID_PEA)
    if pob is None or pea is None or pea == 0:
        return None
    return round((pob / pea) * 100, 2)

def _calc_informalidad():
    """
    Tasa informalidad BC — no disponible directamente en API para área 02.
    Usamos Población ocupada en sector informal del BIE visual (serie 6200093709)
    dividida entre Población ocupada BC (BISE área 02).
    El numerador se consulta con área 02 en BISE.
    """
    inf = _inegi_bise("6200093709")   # Pob ocupada sector informal BC
    ocu = _inegi_bise(_ID_POB_OCUPADA)
    if inf is None or ocu is None or ocu == 0:
        return None
    return round((inf / ocu) * 100, 2)

def get_desocupacion():  return _fetch("desocupacion", _calc_desocupacion, max_days=95)
def get_informalidad():  return _fetch("informalidad", _calc_informalidad, max_days=95)
def get_construccion():  return _fetch("construccion", lambda: _inegi_bise(_ID_CONSTRUCCION), max_days=40)
def get_inpc_tj():       return _fetch("inpc_tj",      lambda: _inegi(_ID_INPC_TJ, banco="BIE-BISE", area="00"), max_days=35)
def get_confianza():     return _fetch("confianza",    lambda: _inegi(_ID_CONFIANZA, banco="BIE-BISE", area="00"), max_days=35)
def get_exportaciones(): return _fetch("exportaciones",lambda: _inegi_bise(_ID_EXPORTACIONES), max_days=95)
def get_immex():         return _fetch("immex",        lambda: _inegi(_ID_IMMEX, banco="BIE-BISE", area="00"), max_days=35)

# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 2 — BANXICO SIE
# ══════════════════════════════════════════════════════════════════════════════

def _banxico(serie):
    url = f"https://www.banxico.org.mx/SieAPIRest/service/v1/series/{serie}/datos/oportuno"
    r = requests.get(url, headers={"Bmx-Token": BANXICO_TOKEN}, timeout=15)
    r.raise_for_status()
    obs = r.json()["bmx"]["series"][0]["datos"]
    if not obs: return None
    v = obs[-1]["dato"].replace(",", "").strip()
    if v in ("N/E", "N/A", "", "--"): return None
    try:
        return float(v)
    except ValueError:
        return None

def _banxico_remesas_bc():
    # SE29671 = Ingresos por Remesas Familiares Baja California (confirmado Banxico SIE)
    v = _banxico("SE29671")
    if v is not None and (v < 0 or v > 5000):
        return None
    return v

def get_tipo_cambio():  return _fetch("tipo_cambio", lambda: _banxico("SF43718"), max_days=3)
def get_remesas():      return _fetch("remesas", _banxico_remesas_bc, max_days=95)

# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 3 — IMSS datos abiertos
# ══════════════════════════════════════════════════════════════════════════════

def _imss_bc():
    now = datetime.now()
    for delta in range(3):
        t = now - pd.DateOffset(months=delta)
        for day in [31, 30, 29, 28]:
            url = f"http://datos.imss.gob.mx/sites/default/files/asg-{t.year}-{t.month:02d}-{day:02d}.csv"
            try:
                r = requests.head(url, timeout=8)
                if r.status_code != 200: continue
                total = 0
                for chunk in pd.read_csv(url, chunksize=50_000,
                                         usecols=["cve_entidad","ta"],
                                         dtype={"cve_entidad":str,"ta":float},
                                         encoding="latin1", low_memory=False):
                    total += chunk[chunk["cve_entidad"]=="02"]["ta"].sum()
                return total if total > 0 else None
            except Exception:
                continue
    return None

def get_imss(): return _fetch("imss_bc", _imss_bc, max_days=40)

# ══════════════════════════════════════════════════════════════════════════════
# FUENTE 4 — SE federal IED (Data México API)
# Cubo: fdi_year_state_industry — Annual FDI by State and Industry
# Documentación: economia.gob.mx/datamexico/es/vizbuilder
# ══════════════════════════════════════════════════════════════════════════════

_DMX_BASE = "https://www.economia.gob.mx/apidatamexico/tesseract/data.jsonrecords"

def _ied_bc():
    """
    Consulta IED anual para Baja California desde Data México (SE federal).
    Filtra por State = Baja California y toma el año más reciente.
    Retorna millones de dólares.
    """
    params = {
        "cube": "fdi_year_state_industry",
        "drilldowns": "Year,State",
        "measures": "Investment",
        "parents": "false",
        "sparse": "false",
    }
    r = requests.get(_DMX_BASE, params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    records = data.get("data", [])
    if not records:
        return None
    # Filtrar Baja California — el campo puede ser "State" o "State Name"
    bc_records = [
        rec for rec in records
        if "baja california" in str(rec.get("State", "")).lower()
        and "sur" not in str(rec.get("State", "")).lower()
    ]
    if not bc_records:
        return None
    # Tomar el año más reciente
    bc_records.sort(key=lambda x: str(x.get("Year", "")), reverse=True)
    inv = bc_records[0].get("Investment", None)
    if inv is None:
        return None
    # Investment viene en millones USD directamente
    val = float(inv)
    # Validación: IED BC históricamente entre 50 y 5000 mdd anuales
    return val if 0 < val < 10000 else None

def get_ied(): return _fetch("ied_bc", _ied_bc, max_days=95)

# ══════════════════════════════════════════════════════════════════════════════
# RECOLECCIÓN COMPLETA
# ══════════════════════════════════════════════════════════════════════════════

INDICATORS = [
    # ── Empleo (25%) ──────────────────────────────────────────────────────────
    # Desocupación: BC cierra 2024 en 2.5% — rango histórico 1.5% (2022) a 6.5% (2020 pandemia)
    ("desocupacion",  get_desocupacion,  "Tasa de desocupación BC",        "%",           "Empleo",    "negative", 1.5,   6.5,    0.40),
    # Informalidad: BC tiene informalidad baja — rango 17% (mín) a 38% (máx pandemia)
    ("informalidad",  get_informalidad,  "Tasa de informalidad BC",         "%",           "Empleo",    "negative", 17.0,  38.0,   0.25),
    ("imss_bc",       get_imss,          "Trabajadores asegurados IMSS BC", "personas",    "Empleo",    "positive", 580e3, 1050e3, 0.35),

    # ── Actividad (25%) ───────────────────────────────────────────────────────
    # Construcción BC anual: valor real 2024 = 20.5M miles MXN — rango 8M a 25M
    ("construccion",  get_construccion,  "Valor construcción BC",           "miles MXN",   "Actividad", "positive", 8e6,   25e6,   0.70),
    # IMMEX: establecimientos activos nacionales — proxy actividad maquiladora
    ("immex",         get_immex,         "Establecimientos IMMEX activos",  "unidades",    "Actividad", "positive", 4500,  6000,   0.30),

    # ── Comercio (20%) ────────────────────────────────────────────────────────
    # Exportaciones BC trimestral: 2025 Q4 = 16,106 millones USD — rango 8,000 a 18,000
    ("exportaciones", get_exportaciones, "Exportaciones BC",                "miles USD",   "Comercio",  "positive", 8e6,   18e6,   0.70),
    ("tipo_cambio",   get_tipo_cambio,   "Tipo de cambio MXN/USD",          "MXN/USD",     "Comercio",  "neutral",  16.5,  25.0,   0.30),

    # ── Inversión (20%) ───────────────────────────────────────────────────────
    ("ied_bc",        get_ied,           "IED captada en BC",               "millones USD","Inversión", "positive", 200,   6000,   1.00),

    # ── Bienestar (10%) ───────────────────────────────────────────────────────
    # INPC Tijuana índice base 2018=100 — valor actual 144.3
    ("inpc_tj",       get_inpc_tj,       "INPC Tijuana",                    "índice",      "Bienestar", "negative", 100.0, 160.0,  0.35),
    # Confianza consumidor nacional (proxy) — valor actual 44.5 puntos
    ("confianza",     get_confianza,     "Confianza del consumidor (nac.)", "puntos",      "Bienestar", "positive", 35.0,  55.0,   0.40),
    # Remesas BC — nueva serie SE29671 directamente de Banxico para BC
    ("remesas",       get_remesas,       "Remesas recibidas BC",            "millones USD","Bienestar", "positive", 120,   550,    0.25),
]

DIM_WEIGHTS = {"Empleo":0.25, "Actividad":0.25, "Comercio":0.20, "Inversión":0.20, "Bienestar":0.10}

SIGNAL_SCALE = [
    (0,  25, "Contracción severa",  "desfavorable", "#E24B4A"),
    (25, 45, "Debilidad moderada",  "desfavorable", "#D85A30"),
    (45, 55, "Zona neutral",        "incertidumbre","#EF9F27"),
    (55, 75, "Expansión moderada",  "favorable",    "#1D9E75"),
    (75,101, "Expansión fuerte",    "favorable",    "#27500A"),
]

def fetch_all():
    out = {}
    for key, fn, name, unit, dim, direction, mn, mx, w_dim in INDICATORS:
        val, src = fn()
        out[key] = {"value":val, "source":src, "name":name,
                    "unit":unit, "dimension":dim,
                    "direction":direction, "min":mn, "max":mx, "w_dim":w_dim}
    return out

def fetch_historico() -> dict:
    """
    Descarga series históricas de los indicadores principales.
    Retorna dict {key: DataFrame[periodo, valor]}
    Usa caché de 24h para no sobrecargar las APIs.
    """
    cache_file = CACHE_DIR / "historico.json"
    if cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text())
            saved = datetime.fromisoformat(cached["ts"])
            if datetime.now() - saved < timedelta(hours=24):
                result = {}
                for k, rows in cached["data"].items():
                    if rows:
                        df = pd.DataFrame(rows)
                        df["periodo"] = pd.to_datetime(df["periodo"])
                        result[k] = df
                return result
        except Exception:
            pass

    series_config = [
        # (key, tipo, serie_id, banco, area)
        ("desocupacion_num", "inegi", _ID_POB_DESOCUPADA,  "BISE",     "02"),
        ("pea",              "inegi", _ID_PEA,              "BISE",     "02"),
        ("ocupada",          "inegi", _ID_POB_OCUPADA,      "BISE",     "02"),
        ("construccion",     "inegi", _ID_CONSTRUCCION,     "BISE",     "02"),
        ("exportaciones",    "inegi", _ID_EXPORTACIONES,    "BISE",     "02"),
        ("inpc_tj",          "inegi", _ID_INPC_TJ,          "BIE-BISE", "00"),
        ("confianza",        "inegi", _ID_CONFIANZA,        "BIE-BISE", "00"),
        ("tipo_cambio",      "banxico", "SF43718",          None,       None),
        ("remesas",          "banxico", "SE29671",          None,       None),
    ]

    result = {}
    for key, tipo, serie, banco, area in series_config:
        try:
            if tipo == "inegi":
                df = _inegi_historico(serie, banco=banco, area=area)
            else:
                df = _banxico_historico(serie)
            if not df.empty:
                result[key] = df
        except Exception:
            pass

    # Calcular tasas derivadas
    if "desocupacion_num" in result and "pea" in result:
        df_d = result["desocupacion_num"].set_index("periodo")
        df_p = result["pea"].set_index("periodo")
        merged = df_d.join(df_p, lsuffix="_d", rsuffix="_p").dropna()
        if not merged.empty:
            tasa = (merged["valor_d"] / merged["valor_p"] * 100).reset_index()
            tasa.columns = ["periodo", "valor"]
            result["desocupacion"] = tasa

    # Guardar caché
    try:
        cache_data = {}
        for k, df in result.items():
            cache_data[k] = df.assign(periodo=df["periodo"].dt.strftime("%Y-%m-%d")).to_dict("records")
        cache_file.write_text(json.dumps({"ts": datetime.now().isoformat(), "data": cache_data}))
    except Exception:
        pass

    return result

# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DEL ÍNDICE
# ══════════════════════════════════════════════════════════════════════════════

def normalize(v, mn, mx, direction):
    if mx == mn: return 50.0
    v = max(mn, min(mx, v))
    s = (v - mn) / (mx - mn) * 100
    if direction == "negative": s = 100 - s
    elif direction == "neutral":
        mid = (mn + mx) / 2
        s = max(0, 100 - abs(v - mid) / ((mx - mn) / 2) * 100)
    return round(s, 2)

def calculate(data):
    scores = {}
    for key, d in data.items():
        if d["value"] is not None:
            scores[key] = normalize(d["value"], d["min"], d["max"], d["direction"])

    dim_scores = {}
    for dim, dw in DIM_WEIGHTS.items():
        items = [(key, d) for key, d in data.items()
                 if d["dimension"] == dim and key in scores]
        if not items:
            continue
        tw = sum(d["w_dim"] for _, d in items)
        ds = sum(scores[k] * d["w_dim"] / tw for k, d in items)
        dim_scores[dim] = (round(ds, 2), dw)

    if not dim_scores:
        composite = 50.0
    else:
        tw = sum(w for _, w in dim_scores.values())
        composite = round(sum(s * w / tw for s, w in dim_scores.values()), 2)

    signal = ("Zona neutral", "incertidumbre", "#EF9F27")
    for lo, hi, long_, short_, color in SIGNAL_SCALE:
        if lo <= composite < hi:
            signal = (long_, short_, color); break

    return composite, signal, dim_scores, scores

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="IDEC-BC", page_icon="📊", layout="wide")

st.markdown("""
<style>
.header{background:linear-gradient(135deg,#1a3a5c,#0f6e56);color:white;
        padding:1.2rem 1.8rem;border-radius:12px;margin-bottom:1rem}
.header h1{color:white;margin:0;font-size:1.5rem}
.header p{color:rgba(255,255,255,.8);margin:.2rem 0 0;font-size:.85rem}
.nota{font-size:.75rem;color:#888;border-top:1px solid #eee;padding-top:.6rem;margin-top:1rem}
</style>""", unsafe_allow_html=True)

st.markdown("""
<div class="header">
  <h1>IDEC-BC &nbsp;·&nbsp; Índice de Desarrollo Económico de Baja California</h1>
  <p>Secretaría de Economía e Innovación · Gobierno del Estado de Baja California</p>
</div>""", unsafe_allow_html=True)

# ── Carga de datos ─────────────────────────────────────────────────────────────
# ── Diagnóstico de tokens (visible solo si hay problemas) ─────────────────────
_token_inegi   = bool(INEGI_TOKEN and INEGI_TOKEN != "tu_token_inegi_aqui")
_token_banxico = bool(BANXICO_TOKEN and BANXICO_TOKEN != "tu_token_banxico_aqui")
if not _token_inegi or not _token_banxico:
    with st.expander("⚠️ Configuración de tokens incompleta — ver detalle", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            if _token_inegi:
                st.success("✅ INEGI_TOKEN configurado")
            else:
                st.error("❌ INEGI_TOKEN no encontrado  \n"
                         "Ve a Streamlit Cloud → tu app → Settings → Secrets  \n"
                         "y agrega exactamente: `INEGI_TOKEN = \"tu_token\"`")
        with c2:
            if _token_banxico:
                st.success("✅ BANXICO_TOKEN configurado")
            else:
                st.error("❌ BANXICO_TOKEN no encontrado")

col_btn, col_info = st.columns([1, 5])
with col_btn:
    if st.button("🔄 Actualizar", use_container_width=True):
        st.cache_data.clear(); st.rerun()

@st.cache_data(ttl=3600, show_spinner=False)
def load():
    data = fetch_all()
    composite, signal, dim_scores, scores = calculate(data)
    return data, composite, signal, dim_scores, scores

with st.spinner("Consultando fuentes..."):
    data, composite, signal, dim_scores, scores = load()

signal_long, signal_short, signal_color = signal
n_ok = sum(1 for d in data.values() if d["source"] != "unavailable")
n_total = len(data)

with col_info:
    st.caption(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  "
               f"Indicadores disponibles: {n_ok}/{n_total}")

# ── Velocímetro + señal ────────────────────────────────────────────────────────
col_g, col_d = st.columns([1, 1.4], gap="large")

with col_g:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=composite,
        number={"font":{"size":52,"color":signal_color}},
        title={"text":f"<b>{signal_long}</b>","font":{"size":15}},
        gauge={
            "axis":{"range":[0,100],"nticks":6},
            "bar":{"color":signal_color,"thickness":0.25},
            "bgcolor":"white","borderwidth":0,
            "steps":[
                {"range":[0,25],  "color":"#FCEBEB"},
                {"range":[25,45], "color":"#FAECE7"},
                {"range":[45,55], "color":"#FAEEDA"},
                {"range":[55,75], "color":"#E1F5EE"},
                {"range":[75,100],"color":"#EAF3DE"},
            ],
        },
    ))
    fig.update_layout(height=280, margin=dict(l=20,r=20,t=40,b=5),
                      paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

    bg = {"favorable":"#E1F5EE","incertidumbre":"#FAEEDA","desfavorable":"#FAECE7"}.get(signal_short,"#eee")
    tc = {"favorable":"#0F6E56","incertidumbre":"#854F0B","desfavorable":"#993C1D"}.get(signal_short,"#333")
    st.markdown(f"""<div style="text-align:center;background:{bg};border-radius:10px;padding:.7rem">
      <span style="font-size:1.4rem;font-weight:700;color:{tc}">{signal_short.upper()}</span><br>
      <span style="font-size:.85rem;color:{tc}">Puntaje: <b>{composite:.1f} / 100</b></span>
    </div>""", unsafe_allow_html=True)

with col_d:
    st.markdown("**Puntaje por dimensión**")
    names, vals, colors = [], [], []
    for dim in DIM_WEIGHTS:
        if dim in dim_scores:
            s = dim_scores[dim][0]
            names.append(dim); vals.append(s)
            colors.append("#1D9E75" if s>=55 else ("#EF9F27" if s>=45 else "#E24B4A"))

    fig2 = go.Figure(go.Bar(x=vals, y=names, orientation="h",
                            marker_color=colors,
                            text=[f"{v:.1f}" for v in vals],
                            textposition="outside"))
    fig2.add_vline(x=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig2.update_layout(xaxis=dict(range=[0,115],showgrid=False),
                       yaxis=dict(showgrid=False), height=220,
                       margin=dict(l=5,r=40,t=10,b=10),
                       paper_bgcolor="rgba(0,0,0,0)",
                       plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("""<div style="display:flex;gap:5px;flex-wrap:wrap;font-size:11px">
      <span style="background:#FCEBEB;color:#A32D2D;padding:2px 7px;border-radius:8px">0–25 Contracción</span>
      <span style="background:#FAECE7;color:#993C1D;padding:2px 7px;border-radius:8px">26–45 Debilidad</span>
      <span style="background:#FAEEDA;color:#854F0B;padding:2px 7px;border-radius:8px">46–54 Neutral</span>
      <span style="background:#E1F5EE;color:#0F6E56;padding:2px 7px;border-radius:8px">55–74 Expansión</span>
      <span style="background:#EAF3DE;color:#3B6D11;padding:2px 7px;border-radius:8px">75–100 Expansión fuerte</span>
    </div>""", unsafe_allow_html=True)

# ── Detalle por dimensión ──────────────────────────────────────────────────────
st.divider()
st.markdown("### Detalle por dimensión")
dim_cols = st.columns(len(DIM_WEIGHTS))
for col, (dim, dw) in zip(dim_cols, DIM_WEIGHTS.items()):
    with col:
        ds = dim_scores.get(dim)
        score_val = ds[0] if ds else None
        sc = f"{score_val:.1f}" if score_val is not None else "N/D"
        cc = "#1D9E75" if (score_val or 0)>=55 else ("#EF9F27" if (score_val or 0)>=45 else "#E24B4A")
        dim_inds = [d for d in data.values() if d["dimension"]==dim]
        n_av = sum(1 for d in dim_inds if d["source"]!="unavailable")
        st.markdown(f"""<div style="background:#f8f9fa;border-radius:10px;padding:.8rem;
                        border-left:4px solid {cc};margin-bottom:.4rem">
          <div style="font-weight:600;font-size:.9rem;color:#1a3a5c">{dim}</div>
          <div style="font-size:1.3rem;font-weight:700;color:{cc}">{sc}</div>
          <div style="font-size:.72rem;color:#888">Peso {int(dw*100)}% &nbsp;|&nbsp; {n_av}/{len(dim_inds)} indicadores</div>
        </div>""", unsafe_allow_html=True)

        with st.expander("Ver indicadores"):
            for key, d in data.items():
                if d["dimension"] != dim: continue
                badge = {"live":"🟢","cache":"🟡","unavailable":"🔴"}.get(d["source"],"⚪")
                val_s = f"{d['value']:,.1f}" if d["value"] is not None else "—"
                sc_s  = f"{scores[key]:.1f}/100" if key in scores else "—"
                st.markdown(f"""<div style="font-size:12px;padding:4px 0;
                                border-bottom:1px solid #eee">
                  {badge} <b>{d['name']}</b><br>
                  <span style="color:#666">Valor: {val_s} &nbsp; Puntaje: {sc_s}</span>
                </div>""", unsafe_allow_html=True)

# ── Tabla completa ─────────────────────────────────────────────────────────────
st.divider()
with st.expander("📋 Tabla completa de indicadores"):
    rows = []
    for key, d in data.items():
        rows.append({
            "Dimensión": d["dimension"],
            "Indicador": d["name"],
            "Valor": f"{d['value']:,.1f}" if d["value"] is not None else "—",
            "Puntaje (0–100)": f"{scores[key]:.1f}" if key in scores else "—",
            "Fuente": {"live":"🟢 En vivo","cache":"🟡 Caché","unavailable":"🔴 No disponible"}.get(d["source"],"—"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ══════════════════════════════════════════════════════════════════════════════
# SECCIÓN HISTÓRICA
# ══════════════════════════════════════════════════════════════════════════════
st.divider()
st.markdown("### Evolución histórica de indicadores")

@st.cache_data(ttl=86400, show_spinner=False)
def load_historico():
    return fetch_historico()

with st.spinner("Cargando series históricas..."):
    hist = load_historico()

if not hist:
    st.info("No se pudieron cargar las series históricas.")
else:
    # ── Selector de indicador ──────────────────────────────────────────────────
    opciones = {
        "Tasa de desocupación BC (%)":         ("desocupacion",  "%",           False),
        "Exportaciones BC (miles USD)":         ("exportaciones", "miles USD",   False),
        "Valor construcción BC (miles MXN)":   ("construccion",  "miles MXN",   False),
        "INPC Tijuana (índice 2018=100)":      ("inpc_tj",       "índice",      False),
        "Confianza del consumidor (puntos)":   ("confianza",     "puntos",      False),
        "Tipo de cambio MXN/USD":              ("tipo_cambio",   "MXN/USD",     False),
        "Remesas recibidas BC (millones USD)": ("remesas",       "millones USD",False),
    }
    opciones_disp = {k:v for k,v in opciones.items() if v[0] in hist}

    col_sel, col_rng = st.columns([2, 1])
    with col_sel:
        ind_sel = st.selectbox("Indicador", list(opciones_disp.keys()))
    with col_rng:
        años = st.slider("Años a mostrar", min_value=3, max_value=20, value=10)

    if ind_sel and opciones_disp:
        key, unit, _ = opciones_disp[ind_sel]
        df_hist = hist[key].copy()

        # Filtrar por rango de años
        cutoff = pd.Timestamp.now() - pd.DateOffset(years=años)
        df_hist = df_hist[df_hist["periodo"] >= cutoff]

        if df_hist.empty:
            st.info("No hay datos suficientes para el rango seleccionado.")
        else:
            # Línea principal
            fig_h = go.Figure()
            fig_h.add_trace(go.Scatter(
                x=df_hist["periodo"],
                y=df_hist["valor"],
                mode="lines",
                line=dict(color="#1D9E75", width=2),
                fill="tozeroy",
                fillcolor="rgba(29,158,117,0.08)",
                name=ind_sel,
                hovertemplate="%{x|%b %Y}<br><b>%{y:,.1f}</b> " + unit + "<extra></extra>",
            ))

            # Línea de tendencia (media móvil 4 períodos)
            if len(df_hist) >= 4:
                df_hist = df_hist.copy()
                df_hist["ma"] = df_hist["valor"].rolling(4, min_periods=2).mean()
                fig_h.add_trace(go.Scatter(
                    x=df_hist["periodo"],
                    y=df_hist["ma"],
                    mode="lines",
                    line=dict(color="#EF9F27", width=1.5, dash="dot"),
                    name="Tendencia (MA4)",
                    hovertemplate="%{x|%b %Y}<br>MA4: <b>%{y:,.1f}</b><extra></extra>",
                ))

            fig_h.update_layout(
                height=320,
                margin=dict(l=10, r=10, t=20, b=10),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                yaxis=dict(title=unit, showgrid=True,
                           gridcolor="rgba(128,128,128,0.15)"),
                xaxis=dict(showgrid=False),
                legend=dict(orientation="h", y=-0.15),
                hovermode="x unified",
            )
            st.plotly_chart(fig_h, use_container_width=True)

            # Estadísticas rápidas
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Valor actual",  f"{df_hist['valor'].iloc[-1]:,.1f} {unit}")
            c2.metric("Máximo",        f"{df_hist['valor'].max():,.1f} {unit}")
            c3.metric("Mínimo",        f"{df_hist['valor'].min():,.1f} {unit}")
            pct = ((df_hist['valor'].iloc[-1] / df_hist['valor'].iloc[0]) - 1) * 100
            c4.metric(f"Cambio ({años}a)", f"{pct:+.1f}%")

    # ── Comparativa de dimensiones históricas ──────────────────────────────────
    st.markdown("#### Evolución por serie — comparativa")
    st.caption("Cada serie normalizada 0–100 según sus rangos históricos del índice")

    fig_multi = go.Figure()
    colores = {"desocupacion":"#E24B4A", "exportaciones":"#1D9E75",
               "construccion":"#378ADD", "inpc_tj":"#EF9F27",
               "confianza":"#7F77DD",    "tipo_cambio":"#888780",
               "remesas":"#5DCAA5"}
    etiquetas = {"desocupacion":"Desocupación", "exportaciones":"Exportaciones",
                 "construccion":"Construcción", "inpc_tj":"INPC Tijuana",
                 "confianza":"Confianza",       "tipo_cambio":"Tipo cambio",
                 "remesas":"Remesas"}
    config_norm = {d[0]: (d[6], d[7], d[5]) for d in INDICATORS}

    cutoff_comp = pd.Timestamp.now() - pd.DateOffset(years=10)
    for key, df_s in hist.items():
        if key in ("desocupacion_num","pea","ocupada"): continue
        if key not in config_norm: continue
        mn, mx, direction = config_norm[key]
        df_s2 = df_s[df_s["periodo"] >= cutoff_comp].copy()
        if df_s2.empty: continue
        df_s2["norm"] = df_s2["valor"].apply(lambda v: normalize(v, mn, mx, direction))
        fig_multi.add_trace(go.Scatter(
            x=df_s2["periodo"], y=df_s2["norm"],
            mode="lines", name=etiquetas.get(key, key),
            line=dict(color=colores.get(key, "#888"), width=1.5),
            hovertemplate="%{x|%b %Y}<br>" + etiquetas.get(key,key) + ": <b>%{y:.1f}</b><extra></extra>",
        ))

    fig_multi.add_hline(y=50, line_dash="dash", line_color="rgba(128,128,128,0.4)",
                        annotation_text="Zona neutral (50)")
    fig_multi.update_layout(
        height=350,
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(range=[0,100], title="Puntaje normalizado (0–100)",
                   showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
        xaxis=dict(showgrid=False),
        legend=dict(orientation="h", y=-0.2),
        hovermode="x unified",
    )
    st.plotly_chart(fig_multi, use_container_width=True)

# ── Diagnóstico técnico INEGI (expandible) ────────────────────────────────────
with st.expander("🔧 Diagnóstico técnico — solo para administradores"):
    st.markdown("**Test directo de la API de INEGI**")
    if st.button("Ejecutar diagnóstico INEGI"):
        token_display = INEGI_TOKEN[:8] + "..." if len(INEGI_TOKEN) > 8 else "(vacío)"
        st.code(f"Token detectado: {token_display} (longitud: {len(INEGI_TOKEN)} chars)")

        # Test con serie conocida — Pob desocupada BC
        test_serie = "6200093973"
        resultados = []
        for area in ["02", "00", "0700", "0200"]:
            url = (f"https://www.inegi.org.mx/app/api/indicadores/desarrolladores/"
                   f"jsonxml/INDICATOR/{test_serie}/es/{area}/false/BIE/2.0/{INEGI_TOKEN}?type=json")
            try:
                r = requests.get(url, timeout=15)
                body_preview = r.text[:300] if r.text else "(sin cuerpo)"
                resultados.append(f"Area={area} → HTTP {r.status_code}\n{body_preview}\n")
            except Exception as e:
                resultados.append(f"Area={area} → ERROR: {e}\n")

        st.code("\n".join(resultados))

        # Sugerencia basada en resultado
        for res in resultados:
            if "HTTP 200" in res:
                st.success("✅ Conexión exitosa — revisa si hay datos en la respuesta")
                break
            elif "HTTP 401" in res or "HTTP 403" in res:
                st.error("❌ Token inválido o sin autorización — genera un token nuevo en inegi.org.mx")
                break
            elif "HTTP 404" in res:
                st.warning("⚠️ Serie no encontrada con ese área geográfica")
                break
        else:
            st.error("❌ No se pudo conectar — posible bloqueo de red o token expirado")

        st.markdown("**Genera token nuevo aquí:**")
        st.markdown("[https://www.inegi.org.mx/app/api/denue/v1/tokenVerify.aspx](https://www.inegi.org.mx/app/api/denue/v1/tokenVerify.aspx)")

st.markdown(f"""<div class="nota">
  <b>Metodología IDEC-BC:</b> Índice compuesto de {n_total} indicadores agrupados en 5 dimensiones 
  ponderadas. Cada indicador se normaliza 0–100 usando referencias históricas de Baja California (2010–2024). 
  Fuentes: INEGI, Banxico, Secretaría de Economía federal, IMSS Datos Abiertos. 
  Indicadores en caché (🟡) corresponden al último dato disponible cuando la fuente no respondió en tiempo real.<br>
  <b>Elaboración:</b> Secretaría de Economía e Innovación, Gobierno del Estado de Baja California.
</div>""", unsafe_allow_html=True)
