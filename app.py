"""
app.py — Dashboard IDEC-BC
Secretaría de Economía e Innovación de Baja California

Despliegue: Streamlit Cloud (github → streamlit.io)
"""

import sys
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from pathlib import Path
from datetime import datetime

# ── Configurar path para importar módulos propios ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent / "src"))

from data_fetcher import fetch_all_indicators
from calculator import calculate_idec, DIMENSION_WEIGHTS, SIGNAL_SCALE


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE PÁGINA
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="IDEC-BC | Secretaría de Economía e Innovación",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS personalizado ──────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Encabezado institucional */
  .idec-header {
    background: linear-gradient(135deg, #1a3a5c 0%, #0f6e56 100%);
    color: white;
    padding: 1.5rem 2rem;
    border-radius: 12px;
    margin-bottom: 1.5rem;
  }
  .idec-header h1 { color: white; margin: 0; font-size: 1.6rem; }
  .idec-header p  { color: rgba(255,255,255,0.8); margin: 0.3rem 0 0; font-size: 0.9rem; }

  /* Tarjetas de dimensión */
  .dim-card {
    background: #f8f9fa;
    border-radius: 10px;
    padding: 1rem;
    border-left: 4px solid #1D9E75;
    margin-bottom: 0.5rem;
  }
  .dim-title { font-weight: 600; font-size: 0.95rem; color: #1a3a5c; }
  .dim-score { font-size: 1.4rem; font-weight: 700; }
  .dim-weight { font-size: 0.75rem; color: #888; }

  /* Badge de fuente */
  .badge-live  { background:#d4edda; color:#155724; padding:2px 8px; border-radius:10px; font-size:11px; }
  .badge-cache { background:#fff3cd; color:#856404; padding:2px 8px; border-radius:10px; font-size:11px; }
  .badge-na    { background:#f8d7da; color:#721c24; padding:2px 8px; border-radius:10px; font-size:11px; }

  /* Nota metodológica */
  .nota { font-size: 0.78rem; color: #6c757d; border-top: 1px solid #dee2e6; padding-top: 0.5rem; margin-top: 1rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE VISUALIZACIÓN
# ══════════════════════════════════════════════════════════════════════════════

def gauge_chart(score: float, signal_long: str, color: str) -> go.Figure:
    """Velocímetro principal del índice."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=score,
        number={"font": {"size": 48, "color": color}, "suffix": ""},
        title={"text": f"<b>{signal_long}</b>", "font": {"size": 16}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1,
                     "tickcolor": "#666", "nticks": 6},
            "bar": {"color": color, "thickness": 0.25},
            "bgcolor": "white",
            "borderwidth": 0,
            "steps": [
                {"range": [0,  25], "color": "#FCEBEB"},
                {"range": [25, 45], "color": "#FAECE7"},
                {"range": [45, 55], "color": "#FAEEDA"},
                {"range": [55, 75], "color": "#E1F5EE"},
                {"range": [75, 100],"color": "#EAF3DE"},
            ],
            "threshold": {
                "line": {"color": color, "width": 4},
                "thickness": 0.8,
                "value": score,
            },
        },
    ))
    fig.update_layout(
        height=300,
        margin=dict(l=20, r=20, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        font={"family": "sans-serif"},
    )
    return fig


def dimension_bar_chart(dimensions) -> go.Figure:
    """Barras horizontales por dimensión."""
    names  = [d.name for d in dimensions if d.score is not None]
    scores = [d.score for d in dimensions if d.score is not None]
    colors = []
    for s in scores:
        if s >= 55:   colors.append("#1D9E75")
        elif s >= 45: colors.append("#EF9F27")
        else:         colors.append("#E24B4A")

    fig = go.Figure(go.Bar(
        x=scores, y=names,
        orientation="h",
        marker_color=colors,
        text=[f"{s:.1f}" for s in scores],
        textposition="outside",
    ))
    fig.add_vline(x=50, line_dash="dash", line_color="#aaa", line_width=1)
    fig.update_layout(
        xaxis=dict(range=[0, 110], showgrid=False, title="Puntaje (0–100)"),
        yaxis=dict(showgrid=False),
        height=240,
        margin=dict(l=10, r=40, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "sans-serif", "size": 12},
        showlegend=False,
    )
    return fig


def indicator_table(result) -> pd.DataFrame:
    """Construye dataframe para tabla de indicadores."""
    rows = []
    for ind in result.indicator_scores:
        badge = {
            "live": "🟢 En vivo",
            "cache": "🟡 Caché",
            "unavailable": "🔴 No disponible",
        }.get(ind.source, "—")

        rows.append({
            "Dimensión": ind.dimension,
            "Indicador": ind.name,
            "Valor": f"{ind.raw_value:,.1f}" if ind.raw_value is not None else "—",
            "Puntaje": f"{ind.normalized_score:.1f}" if ind.normalized_score is not None else "—",
            "Fuente": badge,
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# CARGA DE DATOS (con caché de Streamlit para no reconsultar en cada refresh)
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)   # refresca cada hora
def load_data():
    raw = fetch_all_indicators()
    result = calculate_idec(raw)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# LAYOUT PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

# ── Encabezado ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="idec-header">
  <h1>IDEC-BC &nbsp;·&nbsp; Índice de Desarrollo Económico de Baja California</h1>
  <p>Secretaría de Economía e Innovación · Gobierno del Estado de Baja California</p>
</div>
""", unsafe_allow_html=True)

# ── Botón de actualización ─────────────────────────────────────────────────────
col_refresh, col_timestamp = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── Carga con spinner ──────────────────────────────────────────────────────────
with st.spinner("Consultando fuentes de datos..."):
    try:
        result = load_data()
    except Exception as e:
        st.error(f"Error al cargar datos: {e}")
        st.stop()

with col_timestamp:
    avail_pct = result.n_indicators_available / result.n_indicators_total * 100
    st.caption(
        f"Última actualización: {result.timestamp} &nbsp;|&nbsp; "
        f"Indicadores disponibles: {result.n_indicators_available}/{result.n_indicators_total} "
        f"({avail_pct:.0f}%)"
    )

# ── Fila principal: velocímetro + señal + dimensiones ─────────────────────────
col_gauge, col_dims = st.columns([1, 1.4], gap="large")

with col_gauge:
    st.plotly_chart(
        gauge_chart(result.composite_score, result.signal_long, result.signal_color),
        use_container_width=True,
    )

    # Señal verbal destacada
    signal_bg = {
        "favorable":     "#E1F5EE",
        "incertidumbre": "#FAEEDA",
        "desfavorable":  "#FAECE7",
    }.get(result.signal_short, "#f0f0f0")

    signal_text_color = {
        "favorable":     "#0F6E56",
        "incertidumbre": "#854F0B",
        "desfavorable":  "#993C1D",
    }.get(result.signal_short, "#333")

    st.markdown(f"""
    <div style="text-align:center; background:{signal_bg}; border-radius:10px;
                padding:0.8rem; margin-top:-0.5rem;">
      <span style="font-size:1.5rem; font-weight:700; color:{signal_text_color}; text-transform:uppercase;">
        {result.signal_short.upper()}
      </span><br>
      <span style="font-size:0.85rem; color:{signal_text_color};">
        Puntaje compuesto: <b>{result.composite_score:.1f} / 100</b>
      </span>
    </div>
    """, unsafe_allow_html=True)

with col_dims:
    st.markdown("**Puntaje por dimensión**")
    st.plotly_chart(
        dimension_bar_chart(result.dimensions),
        use_container_width=True,
    )

    # Escala de referencia compacta
    st.markdown("""
    <div style="display:flex; gap:6px; flex-wrap:wrap; font-size:11px; margin-top:-0.5rem;">
      <span style="background:#FCEBEB;color:#A32D2D;padding:2px 8px;border-radius:8px;">0–25 Contracción severa</span>
      <span style="background:#FAECE7;color:#993C1D;padding:2px 8px;border-radius:8px;">26–45 Debilidad</span>
      <span style="background:#FAEEDA;color:#854F0B;padding:2px 8px;border-radius:8px;">46–54 Neutral</span>
      <span style="background:#E1F5EE;color:#0F6E56;padding:2px 8px;border-radius:8px;">55–74 Expansión</span>
      <span style="background:#EAF3DE;color:#3B6D11;padding:2px 8px;border-radius:8px;">75–100 Expansión fuerte</span>
    </div>
    """, unsafe_allow_html=True)

# ── Detalle por dimensión ──────────────────────────────────────────────────────
st.divider()
st.markdown("### Detalle por dimensión")

dim_cols = st.columns(len(result.dimensions))
for col, dim in zip(dim_cols, result.dimensions):
    with col:
        score_display = f"{dim.score:.1f}" if dim.score is not None else "N/D"
        color = "#1D9E75" if (dim.score or 0) >= 55 else (
                "#EF9F27" if (dim.score or 0) >= 45 else "#E24B4A")
        st.markdown(f"""
        <div class="dim-card" style="border-left-color:{color}">
          <div class="dim-title">{dim.name}</div>
          <div class="dim-score" style="color:{color}">{score_display}</div>
          <div class="dim-weight">Peso: {int(dim.weight*100)}% &nbsp;|&nbsp; {dim.n_available}/{dim.n_total} indicadores</div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("Ver indicadores"):
            for ind in dim.indicators:
                badge_html = {
                    "live": '<span class="badge-live">En vivo</span>',
                    "cache": '<span class="badge-cache">Caché</span>',
                    "unavailable": '<span class="badge-na">No disponible</span>',
                }.get(ind.source, "")
                val_str = f"{ind.raw_value:,.1f}" if ind.raw_value is not None else "—"
                score_str = f"{ind.normalized_score:.1f}/100" if ind.normalized_score is not None else "—"
                st.markdown(f"""
                <div style="font-size:12px; padding:4px 0; border-bottom:1px solid #eee;">
                  <b>{ind.name}</b><br>
                  Valor: {val_str} &nbsp; Puntaje: {score_str} &nbsp; {badge_html}
                </div>
                """, unsafe_allow_html=True)

# ── Tabla completa de indicadores ──────────────────────────────────────────────
st.divider()
with st.expander("📋 Tabla completa de indicadores y puntajes"):
    df = indicator_table(result)
    st.dataframe(df, use_container_width=True, hide_index=True)

# ── Nota metodológica ──────────────────────────────────────────────────────────
st.markdown("""
<div class="nota">
  <b>Metodología:</b> El IDEC-BC es un índice compuesto que integra {n} indicadores económicos 
  agrupados en 5 dimensiones ponderadas. Cada indicador se normaliza a escala 0–100 usando 
  referencias históricas (Baja California, 2010–2024). Las fuentes primarias son INEGI, Banxico 
  y la Secretaría de Economía federal. Los valores en caché corresponden al último dato 
  disponible cuando la fuente no respondió en tiempo real. 
  <br><b>Elaboración:</b> Secretaría de Economía e Innovación, Gobierno del Estado de Baja California.
</div>
""".format(n=result.n_indicators_total), unsafe_allow_html=True)
