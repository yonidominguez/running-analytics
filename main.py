import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
import numpy as np
from google import genai

# ==========================================
# 1. CREDENCIALES
# ==========================================
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY_INTERVALS = os.environ.get("INTERVALS_API_KEY")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

if not all([ATHLETE_ID, API_KEY_INTERVALS, API_KEY_GEMINI]):
    raise ValueError("Error: Faltan credenciales en los Secrets de GitHub.")

# ==========================================
# 2. EXTRACCIÓN DE ACTIVIDADES (Intervals.icu)
# ==========================================
print("🔄 Descargando actividades...")
url_acts = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
params_acts = {"newest": datetime.now().strftime("%Y-%m-%d"), "oldest": "2024-01-01"}
res_acts = requests.get(url_acts, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS), params=params_acts)

if res_acts.status_code != 200:
    raise Exception(f"Error en API de actividades: {res_acts.text}")

df_api = pd.DataFrame(res_acts.json())
df_runs = df_api[df_api["type"] == "Run"].copy()
df_runs["Fecha_dt"] = pd.to_datetime(df_runs["start_date_local"])
df_runs["Distancia_km"] = df_runs["distance"] / 1000.0
df_runs["Tiempo_min"] = df_runs["moving_time"] / 60.0
df_runs["Pace_min_km"] = df_runs["Tiempo_min"] / df_runs["Distancia_km"]
df_runs["Speed_m_min"] = (df_runs["Distancia_km"] * 1000) / df_runs["Tiempo_min"]
df_runs["average_heartrate"] = df_runs["average_heartrate"].fillna(0)
df_runs["EF"] = np.where(df_runs["average_heartrate"] > 0, df_runs["Speed_m_min"] / df_runs["average_heartrate"], np.nan)
df_runs["Rango_Distancia"] = pd.cut(df_runs["Distancia_km"], bins=[0, 5, 10, 15, 21, 30, 50])

cols = ["id", "Fecha_dt", "name", "Distancia_km", "Tiempo_min", "Pace_min_km", "average_heartrate", "icu_training_load", "EF", "Rango_Distancia"]
df_runs = df_runs[cols].sort_values("Fecha_dt").reset_index(drop=True)
df_runs.to_csv("running_historico.csv", index=False)

# ==========================================
# 3. BIOMETRÍA Y CLIMA (Contexto)
# ==========================================
print("🩺 Extrayendo biometría y métricas de carga...")
hace_7_dias_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
hoy_str = datetime.now().strftime("%Y-%m-%d")
url_well = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness?oldest={hace_7_dias_str}&newest={hoy_str}"
res_well = requests.get(url_well, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS))
wellness_data = res_well.json() if res_well.status_code == 200 else []

latest_well = wellness_data[-1] if wellness_data else {}
ctl = latest_well.get('ctl', 0)
atl = latest_well.get('atl', 0)
tsb = latest_well.get('tsb', 0)

print("🌤️ Consultando clima histórico de Buenos Aires (Open-Meteo)...")
url_clima = f"https://api.open-meteo.com/v1/forecast?latitude=-34.61&longitude=-58.42&daily=temperature_2m_max,precipitation_sum&past_days=7&forecast_days=1&timezone=America%2FArgentina%2FBuenos_Aires"
res_clima = requests.get(url_clima)
clima_txt = "Datos de clima no disponibles."
if res_clima.status_code == 200:
    clima_data = res_clima.json().get('daily', {})
    temp_prom = np.mean(clima_data.get('temperature_2m_max', [0]))
    lluvia_total = np.sum(clima_data.get('precipitation_sum', [0]))
    clima_txt = f"Temp Máx Promedio: {temp_prom:.1f}°C | Lluvia Total Semanal: {lluvia_total:.1f}mm"

# ==========================================
# 4. GENERACIÓN DE GRÁFICOS
# ==========================================
print("📈 Generando gráficos...")
os.makedirs("reports", exist_ok=True)
sns.set_theme(style="whitegrid")

def format_xaxis(ax):
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

# Gráfico 1: Evolución del Pace
fig, ax = plt.subplots(figsize=(10, 5))
sns.scatterplot(data=df_runs, x="Fecha_dt", y="Pace_min_km", hue="Distancia_km", palette="viridis", size="Distancia_km", sizes=(40, 200), ax=ax, legend=False)
df_runs_clean = df_runs.dropna(subset=['Pace_min_km'])
x_nums = mdates.date2num(df_runs_clean["Fecha_dt"])
tendencia = np.poly1d(np.polyfit(x_nums, df_runs_clean["Pace_min_km"], 1))
ax.plot(df_runs_clean["Fecha_dt"], tendencia(x_nums), color="red", linestyle="--", linewidth=2)
format_xaxis(ax)
ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Fecha")
ax.set_title("Evolución del Ritmo de Carrera y Tendencia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/01_evolucion_pace.png", dpi=300)
plt.close()

# Gráfico 2: Volumen Semanal
df_runs['Semana'] = df_runs['Fecha_dt'].dt.strftime('%G-W%V')
weekly = df_runs.groupby('Semana')['Distancia_km'].sum().reset_index()
fig, ax = plt.subplots(figsize=(12, 5))
sns.barplot(data=weekly, x="Semana", y="Distancia_km", color="steelblue", ax=ax)
plt.setp(ax.get_xticklabels(), rotation=90, fontsize=8)
ax.set_ylabel("Kilómetros Totales")
ax.set_title("Volumen Semanal Acumulado (km)", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/02_volumen_semanal.png", dpi=300)
plt.close()

# Gráfico 3: Eficiencia Cardiovascular
df_clean_hr = df_runs[df_runs["average_heartrate"] > 0]
fig, ax = plt.subplots(figsize=(8, 6))
sns.scatterplot(data=df_clean_hr, x="Pace_min_km", y="average_heartrate", hue="Distancia_km", palette="magma", s=100, ax=ax, legend=False)
ax.set_xlabel("Ritmo (min/km)")
ax.set_ylabel("Frecuencia Cardíaca Media (ppm)")
ax.set_title("Eficiencia Cardiovascular Absoluta", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/03_eficiencia_fc.png", dpi=300)
plt.close()

# ==========================================
# 5. INTELIGENCIA DEPORTIVA (Gemini Interactions API)
# ==========================================
print("🧠 Procesando IA con Gemini Interactions API...")

def generar_analisis_gemini(client, prompt, modelos=None):
    """
    Encapsula la llamada a Gemini usando Interactions API.
    Retorna (texto_analisis, modelo_usado) o lanza RuntimeError.
    """
    if modelos is None:
        modelos = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]

    errores = []
    for modelo in modelos:
        try:
            print(f"🔄 Probando Interactions API con {modelo}...")
            interaction = client.interactions.create(
                model=modelo,
                input=prompt,
                store=False
            )
            texto = interaction.output_text
            if texto and texto.strip():
                print(f"✅ Análisis generado con {modelo}")
                return texto.strip(), modelo
            else:
                errores.append(f"{modelo}: respuesta vacía")
        except Exception as e:
            errores.append(f"{modelo}: {type(e).__name__}: {e}")
            print(f"⚠️ Falló {modelo}")

    raise RuntimeError(
        "❌ Fallaron todos los modelos.\n" + "\n".join(errores)
    )

# Preparar datos para el prompt
runs_semana = df_runs[df_runs["Fecha_dt"] >= (datetime.now() - timedelta(days=7))]
km_semana = runs_semana["Distancia_km"].sum()
ritmo_semana = runs_semana["Pace_min_km"].mean()
tss_semana = runs_semana["icu_training_load"].sum()

def safe_sleep(val):
    return round((val or 0) / 3600, 1)

bio_text = "\n".join([
    f"Día {w.get('id', 'N/A')}: HRV {w.get('hrv', 'N/A')}ms, RHR {w.get('restingHR', 'N/A')}ppm, Sueño {safe_sleep(w.get('sleepSecs'))}hs"
    for w in wellness_data
]) or "No hay datos biométricos disponibles para esta semana."

ritmo_txt = f"{ritmo_semana:.2f} min/km" if pd.notna(ritmo_semana) else "No disponible"

# Editá esta línea cuando cambie tu objetivo (carrera, bloque de base, etc.)
OBJETIVO_ACTUAL = "Sin competencia inmediata: priorizo continuidad y construcción de base."

prompt_maestro = f"""
Sos mi entrenador de running de confianza. Me hablás de vos, cercano y directo, como un coach que me conoce, no como un informe ni un paper.

Analizá mis datos por tu cuenta (HRV, pulso en reposo, carga, clima), pero NO me muestres el análisis: decime qué significa para mi cuerpo y qué hago. Si usás un término técnico (HRV, TSB, ATL, Banister), traducilo en la misma frase: "piernas cargadas", "venís fresco", "el sistema nervioso descansó bien". Nunca uses palabras como "autonómica", "readiness", "asimilación" ni "modelo".

Contexto:
- Objetivo actual: {OBJETIVO_ACTUAL}
- Marcos planifica la estrategia: no contradigas su plan, ayudame a encararlo.
- Duermo poco algunos días por la cursada nocturna. Preocupate por el sueño solo si además cae el HRV o sube el pulso en reposo.

Datos de la semana:
- Fitness {ctl:.1f} | Fatiga {atl:.1f} | Forma {tsb:.1f} (forma positiva = descansado, negativa = cargado)
- {km_semana:.2f} km, ritmo promedio {ritmo_txt}, carga {tss_semana:.0f}
- Clima: {clima_txt}
- Biometría diaria:
{bio_text}

Respondé en máximo 150 palabras, sin títulos, listas ni saludos:
1. Cómo venís esta semana, en una frase.
2. Qué significa para tus piernas hoy.
3. Cómo encarar mañana: tipo de sesión y esfuerzo (fácil / moderado / fuerte), sin números de TSB.
4. Solo si corresponde, una advertencia.

Ejemplo de TONO (no copies el contenido): "Venís bien. Las piernas deberían sentirse livianas y el pulso en reposo se mantiene estable, así que el sueño corto no te pasó factura. Mañana, trote suave y sin apurarte."

No diagnostiques enfermedades ni reemplaces a un médico. Si faltan datos para concluir algo, decilo en una frase y no inventes.
"""

# Ejecutar análisis
client = genai.Client(api_key=API_KEY_GEMINI)
try:
    analisis, modelo_usado = generar_analisis_gemini(client, prompt_maestro)
except RuntimeError as e:
    # En caso de error, guardamos el traceback en el archivo de salida
    with open("reports/00_Analisis_Inteligencia_Deportiva.txt", "w", encoding="utf-8") as f:
        f.write(f"Error en el análisis de IA:\n{str(e)}")
    print(f"❌ Error: {e}")
    sys.exit(1)

# Guardar el análisis
ruta_reporte = "reports/00_Analisis_Inteligencia_Deportiva.txt"
with open(ruta_reporte, "w", encoding="utf-8") as f:
    f.write(analisis + "\n")
print(f"✅ Análisis guardado en {ruta_reporte} (modelo: {modelo_usado})")

print("✅ Pipeline completado con éxito.")
