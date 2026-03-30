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

def _inegi(serie):
    url = (f"https://www.inegi.org.mx/app/api/indicadores/desarrolladores/"
           f"jsonxml/INDICATOR/{serie}/es/0700/false/BIE/2.0/{INEGI_TOKEN}?type=json")
    r = requests.get(url, timeout=15); r.raise_for_status()
    obs = r.json()["Series"][0]["OBSERVATIONS"]
    vals = [(o["TIME_PERIOD"], float(o["OBS_VALUE"]))
            for o in obs if o.get("OBS_VALUE") not in (None, "", "N/A")]
    if not vals: return None
    return sorted(vals, reverse=True)[0][1]

# IDs confirmados desde el BIE de INEGI (formato: número entre #D y _18)
# Fuente: BIE INEGI, Baja California, consultados marzo 2026
_ID_POB_DESOCUPADA  = "6200093973"   # Población desocupada 15+ BC
_ID_PEA             = "6200093960"   # Población económicamente activa 15+ BC
_ID_POB_INFORMAL    = "6200093709"   # Población ocupada sector informal BC
_ID_POB_OCUPADA     = "6200093954"   # Población ocupada 15+ BC
# Pendientes de confirmar — se actualizan cuando lleguen los IDs
_ID_CONSTRUCCION    = "723135"    # Valor producción total Sector 23 Construcción BC, mensual (miles de pesos corrientes)
_ID_INPC_TJ         = "910392"    # INPC Tijuana, mensual (índice base 2018=100)
_ID_CONFIANZA       = "454168"    # Indicador confianza del consumidor — nacional (proxy; no existe desagregación estatal en BIE)
_ID_EXPORTACIONES   = "629659"    # Exportaciones totales BC, trimestral (miles de dólares)

def _inegi_calculada(key, fn, max_days=95):
    """Indicador calculado a partir de dos series INEGI."""
    return _fetch(key, fn, max_days)

def _calc_desocupacion():
    """Tasa desocupación = (Pob desocupada / PEA) × 100"""
    pob = _inegi(_ID_POB_DESOCUPADA)
    pea = _inegi(_ID_PEA)
    if pob is None or pea is None or pea == 0:
        return None
    return round((pob / pea) * 100, 2)

def _calc_informalidad():
    """Tasa informalidad = (Pob informal / Pob ocupada) × 100"""
    inf = _inegi(_ID_POB_INFORMAL)
    ocu = _inegi(_ID_POB_OCUPADA)
    if inf is None or ocu is None or ocu == 0:
        return None
    return round((inf / ocu) * 100, 2)

def get_desocupacion():   return _inegi_calculada("desocupacion", _calc_desocupacion)
def get_informalidad():   return _inegi_calculada("informalidad", _calc_informalidad)
def get_construccion():   return _fetch("construccion",   lambda: _inegi(_ID_CONSTRUCCION)   if _ID_CONSTRUCCION != "PENDIENTE" else None)
def get_inpc_tj():        return _fetch("inpc_tj",        lambda: _inegi(_ID_INPC_TJ)        if _ID_INPC_TJ != "PENDIENTE" else None)
def get_confianza():      return _fetch("confianza",      lambda: _inegi(_ID_CONFIANZA)      if _ID_CONFIANZA != "PENDIENTE" else None)
def get_exportaciones():  return _fetch("exportaciones",  lambda: _inegi(_ID_EXPORTACIONES)  if _ID_EXPORTACIONES != "PENDIENTE" else None)

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
    # CE168 = remesas recibidas Baja California (SIE Banxico sector externo)
    v = _banxico("CE168")
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
    ("desocupacion",  get_desocupacion,  "Tasa de desocupación BC",        "%",           "Empleo",    "negative", 1.8,   8.5,    0.40),
    ("informalidad",  get_informalidad,  "Tasa de informalidad BC",         "%",           "Empleo",    "negative", 17.0,  38.0,   0.25),  # BC tiene informalidad baja vs media nacional
    ("imss_bc",       get_imss,          "Trabajadores asegurados IMSS BC", "personas",    "Empleo",    "positive", 580e3, 1050e3, 0.35),
    ("construccion",  get_construccion,  "Valor construcción BC",           "miles MXN",   "Actividad", "positive", 400e3, 2.2e6,  1.00),  # mensual, miles pesos corrientes
    ("exportaciones", get_exportaciones, "Exportaciones BC",                "miles USD",   "Comercio",  "positive", 7e6,   16e6,   0.70),  # trimestral, miles de dólares
    ("tipo_cambio",   get_tipo_cambio,   "Tipo de cambio MXN/USD",          "MXN/USD",     "Comercio",  "neutral",  16.5,  25.0,   0.30),
    ("ied_bc",        get_ied,           "IED captada en BC",               "millones USD","Inversión", "positive", 50,    1200,   1.00),
    ("inpc_tj",       get_inpc_tj,       "INPC Tijuana",                    "índice",      "Bienestar", "negative", 100.0, 160.0,  0.35),  # índice base 2018=100; más alto = más inflación acumulada
    ("confianza",     get_confianza,     "Confianza del consumidor (nac.)", "puntos",      "Bienestar", "positive", 35.0,  55.0,   0.40),  # proxy nacional ENCO
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

st.markdown(f"""<div class="nota">
  <b>Metodología IDEC-BC:</b> Índice compuesto de {n_total} indicadores agrupados en 5 dimensiones 
  ponderadas. Cada indicador se normaliza 0–100 usando referencias históricas de Baja California (2010–2024). 
  Fuentes: INEGI, Banxico, Secretaría de Economía federal, IMSS Datos Abiertos. 
  Indicadores en caché (🟡) corresponden al último dato disponible cuando la fuente no respondió en tiempo real.<br>
  <b>Elaboración:</b> Secretaría de Economía e Innovación, Gobierno del Estado de Baja California.
</div>""", unsafe_allow_html=True)
