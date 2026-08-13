import os
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
# 2. EXTRACCIÓN DE RUNNING (Intervals.icu)
# ==========================================
print("🔄 Descargando actividades...")
url_acts = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
params_acts = {"newest": datetime.now().strftime("%Y-%m-%d"), "oldest": "2024-01-01"}
res_acts = requests.get(url_acts, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS), params=params_acts)

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
# 3. BIOMETRÍA Y CLIMA (Variables de Contexto)
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
    clima_txt = f"Temp Máx Promedio: {np.mean(clima_data.get('temperature_2m_max', [0])):.1f}°C | Lluvia Total Semanal: {np.sum(clima_data.get('precipitation_sum', [0])):.1f}mm"

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
# 5. INTELIGENCIA DEPORTIVA CON GEMINI (VIA HTTP DIRECTO)
# ==========================================
print("🧠 Procesando IA...")

# Diagnóstico de modelos disponibles en tu cuenta específica
print("🔍 Diagnosticando modelos disponibles en tu API Key...")
try:
    client_diag = genai.Client(api_key=API_KEY_GEMINI)
    for m in client_diag.models.list():
        if "gemini" in m.name:
            print(f" - {m.name}")
except Exception as e:
    print(f"⚠️ No se pudieron listar los modelos: {e}")

runs_semana = df_runs[df_runs["Fecha_dt"] >= (datetime.now() - timedelta(days=7))]
def safe_sleep(val): return round((val or 0) / 3600, 1)
bio_text = "\n".join([f"Día {w['id']}: HRV {w.get('hrv', 'N/A')}ms, RHR {w.get('restingHR', 'N/A')}ppm, Sueño {safe_sleep(w.get('sleepSecs'))}hs" for w in wellness_data])

prompt_maestro = f"""
Actuás como mi Analista de Datos de Rendimiento Deportivo. Mi entrenador (Marcos) planifica la estrategia; tu rol es puramente analítico.

Contexto vital:
- Mis horas de sueño son estructuralmente bajas algunos días debido a cursada universitaria nocturna. No generes alertas alarmistas por falta de sueño a menos que haya un desplome del HRV o pico de RHR.
- Me encuentro en Tapering para la Media Maratón de Buenos Aires (23 de agosto).

Datos de carga actuales (Modelo Banister):
- CTL (Fitness acumulado): {ctl:.1f}
- ATL (Fatiga reciente): {atl:.1f}
- TSB (Forma actual): {tsb:.1f}

Datos de la última semana:
- Kilómetros recorridos: {runs_semana["Distancia_km"].sum():.2f} km
- Ritmo promedio: {runs_semana["Pace_min_km"].mean():.2f} min/km
- Carga de entrenamiento (TSS): {runs_semana["icu_training_load"].sum():.0f}
- Clima registrado: {clima_txt}

Biometría diaria:
{bio_text}

Instrucciones:
1. Evaluá la asimilación de la carga cruzando el TSB con mi HRV/RHR, entendiendo que el TSB debe empezar a positivizarse por el Tapering.
2. Considerá el impacto del clima en mi fatiga reciente.
3. Redactá un diagnóstico directo de 3 párrafos. Sin saludos ni frases motivacionales. Solo datos duros y evaluación de readiness.
"""

MODELOS = [
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.0-pro"
]

analisis = None

for modelo in MODELOS:
    print(f"🔄 Probando endpoint HTTP directo con {modelo}...")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={API_KEY_GEMINI}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt_maestro}]}]
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=60)
        
        if resp.status_code != 200:
            print(f"⚠️ {modelo} devolvió error HTTP {resp.status_code}: {resp.text[:200]}...")
            continue
            
        data = resp.json()
        analisis = data["candidates"][0]["content"]["parts"][0]["text"]
        
        print(f"✅ Éxito absoluto con {modelo}")
        break
        
    except Exception as e:
        print(f"⚠️ Error de conexión con {modelo}: {e}")

if analisis is None:
    raise Exception("❌ Ningún endpoint HTTP respondió correctamente. Revisá el log de diagnóstico arriba para ver qué modelos tenés habilitados.")

with open("reports/00_Analisis_Inteligencia_Deportiva.txt", "w", encoding="utf-8") as f:
    f.write(analisis)

print("✅ Análisis guardado exitosamente.")
