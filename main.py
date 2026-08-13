import os
import time
from datetime import datetime, timedelta
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib.pyplot as plt
import seaborn as sns
import google.generativeai as genai

# 1. Credenciales
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY_INTERVALS = os.environ.get("INTERVALS_API_KEY")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

if not all([ATHLETE_ID, API_KEY_INTERVALS, API_KEY_GEMINI]):
    raise ValueError("Error: Faltan credenciales en los Secrets de GitHub.")

# 2. Descarga del Historial de Running (Para CSV y Gráficos)
print("🔄 Descargando actividades de Intervals.icu...")
url_acts = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
params_acts = {"newest": datetime.now().strftime("%Y-%m-%d"), "oldest": "2024-01-01"}
res_acts = requests.get(url_acts, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS), params=params_acts)

if res_acts.status_code != 200:
    raise Exception(f"Error en API Activities: {res_acts.text}")

df_runs = pd.DataFrame(res_acts.json())
df_runs = df_runs[df_runs["type"] == "Run"].copy()
df_runs["Fecha_dt"] = pd.to_datetime(df_runs["start_date_local"])
df_runs["Distancia_km"] = df_runs["distance"] / 1000.0
df_runs["Tiempo_min"] = df_runs["moving_time"] / 60.0
df_runs["Pace_min_km"] = df_runs["Tiempo_min"] / df_runs["Distancia_km"]

cols = ["id", "Fecha_dt", "name", "Distancia_km", "Tiempo_min", "Pace_min_km", "average_heartrate", "icu_training_load"]
df_runs = df_runs[cols].sort_values("Fecha_dt").reset_index(drop=True)
df_runs.to_csv("running_historico.csv", index=False)

# 3. Descarga de Biometría (Últimos 7 días)
print("🩺 Extrayendo biometría (HRV, Sueño, RHR)...")
hace_7_dias = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
hoy = datetime.now().strftime("%Y-%m-%d")
url_wellness = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness?oldest={hace_7_dias}&newest={hoy}"
res_well = requests.get(url_wellness, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS))
wellness_data = res_well.json() if res_well.status_code == 200 else []

# 4. Generación de Gráficos Históricos (Se mantienen tus 3 gráficos base)
os.makedirs("reports", exist_ok=True)
sns.set_theme(style="whitegrid")

# Gráfico 1: Volumen
df_runs['Semana'] = df_runs['Fecha_dt'].dt.isocalendar().week
weekly = df_runs.groupby('Semana')['Distancia_km'].sum().reset_index()
fig, ax = plt.subplots(figsize=(10, 5))
sns.barplot(data=weekly, x="Semana", y="Distancia_km", color="steelblue", ax=ax)
ax.set_title("Volumen Semanal (km)", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/01_volumen_semanal.png", dpi=300)
plt.close()

# 5. El Cerebro: Resumen Semanal con Gemini
print("🧠 Procesando Inteligencia Deportiva con Gemini API...")
genai.configure(api_key=API_KEY_GEMINI)
model = genai.GenerativeModel('gemini-1.5-pro')

# Preparamos el resumen de la semana para dárselo a la IA
runs_semana = df_runs[df_runs["Fecha_dt"] >= (datetime.now() - timedelta(days=7))]
km_totales = runs_semana["Distancia_km"].sum()
pace_prom = runs_semana["Pace_min_km"].mean()
carga_tot = runs_semana["icu_training_load"].sum()

# Resumen de biometría en texto
bio_text = "\n".join([f"Día {w['id']}: HRV {w.get('hrv', 'N/A')}ms, RHR {w.get('restingHR', 'N/A')}ppm, Sueño {round(w.get('sleepSecs', 0)/3600, 1)}hs" for w in wellness_data])

prompt_maestro = f"""
Actuás como mi Analista de Datos de Rendimiento Deportivo. Mi entrenador principal (Marcos) ya se encarga de la planificación estratégica, por lo que tu rol es puramente analítico.

Contexto vital del atleta:
- Mi semana incluye jornadas nocturnas de cursada universitaria (Maestría en Negocios y Tecnología), por lo que mis horas de sueño serán estructuralmente bajas en ciertos días. 
- Bajo ninguna circunstancia generes alertas alarmistas sobre la falta de horas de sueño a menos que vengan acompañadas de un desplome de la Variabilidad de la Frecuencia Cardíaca (HRV) y un pico en la Frecuencia Cardíaca en Reposo (RHR).
- Me encuentro a escasos días de la Media Maratón de Buenos Aires (23 de agosto).

Mis datos de los últimos 7 días:
- Kilómetros recorridos: {km_totales:.2f} km
- Ritmo promedio global: {pace_prom:.2f} min/km
- Carga de entrenamiento (TSS): {carga_tot:.0f}

Biometría diaria registrada (Intervals.icu):
{bio_text}

Tus instrucciones:
1. Evaluá si mi sistema nervioso asimiló la carga observando la tendencia de mi HRV y RHR de los últimos días, asumiendo que el sueño corto es por estudio y no por insomnio clínico.
2. Redactá un diagnóstico ejecutivo y directo de 3 párrafos. Sin saludos, sin frases motivacionales genéricas. Solo datos, tendencias de asimilación y evaluación de fatiga real de cara al Tapering de los 21K.
"""

response = model.generate_content(prompt_maestro)

# Guardar el análisis en la carpeta de reportes
with open("reports/00_Analisis_Inteligencia_Deportiva.txt", "w", encoding="utf-8") as file:
    file.write(response.text)

print("✅ Pipeline ejecutado con éxito. Archivos e Informe de IA guardados en /reports/")
