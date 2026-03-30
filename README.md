# IDEC-BC — Índice de Desarrollo Económico de Baja California

**Secretaría de Economía e Innovación · Gobierno del Estado de Baja California**

---

## ¿Qué hace este proyecto?

El IDEC-BC es un índice compuesto que integra indicadores económicos oficiales
para producir una lectura sintética del panorama económico de Baja California,
en escala 0–100 con señal verbal: **Favorable / Incertidumbre / Desfavorable**.

---

## Estructura del proyecto

```
idec_bc/
├── app.py                  ← Dashboard Streamlit (punto de entrada)
├── requirements.txt        ← Dependencias Python
├── .gitignore
├── .streamlit/
│   └── secrets.toml        ← Tokens (NO subir a GitHub)
├── src/
│   ├── data_fetcher.py     ← Conexión con APIs (INEGI, Banxico, SE, IMSS)
│   └── calculator.py       ← Normalización y cálculo del índice
└── data/
    └── cache/              ← Caché local de datos (generado automáticamente)
```

---

## Fuentes de datos

| Fuente | Qué aporta | Frecuencia |
|--------|-----------|-----------|
| INEGI BIE | ENOE, ENEC, INPC, ENCO, exportaciones | Mensual / Trimestral |
| Banxico SIE | Tipo de cambio, remesas, crédito | Diario / Trimestral |
| SE Federal | IED por entidad federativa | Trimestral |
| IMSS Datos Abiertos | Trabajadores asegurados BC | Mensual |

---

## Cómo desplegarlo en Streamlit Cloud (paso a paso)

### Paso 1 — Subir a GitHub

1. Crea un repositorio nuevo en github.com (puede ser privado)
2. Sube todos los archivos **excepto** `.streamlit/secrets.toml`
   (ese archivo está en `.gitignore` precisamente para proteger los tokens)

### Paso 2 — Crear la app en Streamlit Cloud

1. Ve a [share.streamlit.io](https://share.streamlit.io)
2. Inicia sesión con tu cuenta de GitHub
3. Haz clic en **"New app"**
4. Selecciona tu repositorio y elige `app.py` como archivo principal
5. Haz clic en **"Deploy"**

### Paso 3 — Configurar los tokens (secretos)

Una vez desplegada la app:
1. En Streamlit Cloud, abre tu app y ve a **Settings → Secrets**
2. Agrega el siguiente contenido (sustituyendo con tus tokens reales):

```toml
INEGI_TOKEN = "tu_token_inegi"
BANXICO_TOKEN = "tu_token_banxico"
```

3. Haz clic en **Save** — la app se reiniciará automáticamente

> **¿Dónde obtengo los tokens?**
> - INEGI: https://www.inegi.org.mx/servicios/api_indicadores.html
> - Banxico: https://www.banxico.org.mx/SieAPIRest/service/v1/token

### Paso 4 — Acceder a la app

La URL será algo como: `https://tu-usuario-idec-bc.streamlit.app`
Puedes compartir este enlace internamente con tu equipo.

---

## Cómo actualizar los valores históricos de referencia

Los valores mínimos y máximos históricos están en `src/calculator.py`,
en el diccionario `INDICATOR_CONFIG`. Si quieres ajustarlos:

1. Abre `src/calculator.py`
2. Busca el indicador que quieres actualizar
3. Modifica `hist_min` y/o `hist_max`
4. Sube el cambio a GitHub → Streamlit se actualiza automáticamente

---

## Preguntas frecuentes

**¿Qué pasa si una API no responde?**
El sistema usa caché local. Si el dato fresco no está disponible, usa el
último dato guardado (máximo 35 días de antigüedad). El dashboard indica
con un badge amarillo qué indicadores vienen del caché.

**¿Cada cuánto se actualizan los datos?**
El dashboard refresca las APIs cada hora automáticamente. También puedes
forzar actualización con el botón "🔄 Actualizar datos".

**¿Por qué el índice muestra 50 si no hay datos?**
Es la señal neutral por defecto cuando no hay ningún indicador disponible.
Significa incertidumbre, no que la economía esté en punto medio.
