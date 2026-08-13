import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from google import genai  # SDK nuevo

# ==========================================
# 1. CREDENCIALES Y CONFIGURACIÓN
# ==========================================
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY_INTERVALS = os.environ.get("INTERVALS_API_KEY")
API_KEY_GEMINI = os.environ.get("GEMINI_API_KEY")

if not all([ATHLETE_ID, API_KEY_INTERVALS, API_KEY_GEMINI]):
    raise ValueError("Error: Faltan credenciales en los Secrets de GitHub.")

# ==========================================
# 2. EXTRACCIÓN Y TRANSFORMACIÓN DE DATOS
# ==========================================
print("🔄 Descargando actividades de Intervals.icu...")
url_acts = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"
params_acts = {"newest": datetime.now().strftime("%Y-%m-%d"), "oldest": "2024-01-01"}
res_acts = requests.get(url_acts, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS), params=params_acts)

if res_acts.status_code != 200:
    raise Exception(f"Error en API Activities: {res_acts.text}")

df_api = pd.DataFrame(res_acts.json())
df_runs = df_api[df_api["type"] == "Run"].copy()
df_runs["Fecha_dt"] = pd.to_datetime(df_runs["start_date_local"])
df_runs["Distancia_km"] = df_runs["distance"] / 1000.0
df_runs["Tiempo_min"] = df_runs["moving_time"] / 60.0
df_runs["Pace_min_km"] = df_runs["Tiempo_min"] / df_runs["Distancia_km"]

# Nuevas métricas para gráficos
df_runs["Speed_m_min"] = (df_runs["Distancia_km"] * 1000) / df_runs["Tiempo_min"]
df_runs["average_heartrate"] = df_runs["average_heartrate"].fillna(0)
df_runs["EF"] = np.where(df_runs["average_heartrate"] > 0, df_runs["Speed_m_min"] / df_runs["average_heartrate"], np.nan)
df_runs["Rango_Distancia"] = pd.cut(df_runs["Distancia_km"], bins=[0, 5, 10, 15, 21, 30, 50])

cols = ["id", "Fecha_dt", "name", "Distancia_km", "Tiempo_min", "Pace_min_km", "average_heartrate", "icu_training_load", "EF", "Rango_Distancia"]
df_runs = df_runs[cols].sort_values("Fecha_dt").reset_index(drop=True)
df_runs.to_csv("running_historico.csv", index=False)

# ==========================================
# 3. EXTRACCIÓN DE BIOMETRÍA (WELLNESS)
# ==========================================
print("🩺 Extrayendo biometría (HRV, Sueño, RHR)...")
hace_7_dias = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
hoy = datetime.now().strftime("%Y-%m-%d")
url_wellness = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness?oldest={hace_7_dias}&newest={hoy}"
res_well = requests.get(url_wellness, auth=HTTPBasicAuth("API_KEY", API_KEY_INTERVALS))
wellness_data = res_well.json() if res_well.status_code == 200 else []

# ==========================================
# 4. GENERACIÓN DE 5 GRÁFICOS
# ==========================================
print("📈 Generando 5 gráficos históricos...")
os.makedirs("reports", exist_ok=True)
sns.set_theme(style="whitegrid")

# Gráfico 1: Volumen Semanal
df_runs['Semana'] = df_runs['Fecha_dt'].dt.isocalendar().week
weekly = df_runs.groupby('Semana')['Distancia_km'].sum().reset_index()
fig, ax = plt.subplots(figsize=(10, 5))
sns.barplot(data=weekly, x="Semana", y="Distancia_km", color="steelblue", ax=ax)
ax.set_ylabel("Kilómetros Totales")
ax.set_title("Volumen Semanal Acumulado (km)", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/01_volumen_semanal.png", dpi=300)
plt.close()

# Gráfico 2: Evolución del Pace (corregido)
fig, ax = plt.subplots(figsize=(10, 5))
sns.scatterplot(data=df_runs, x="Fecha_dt", y="Pace_min_km", hue="Distancia_km", palette="viridis", size="Distancia_km", sizes=(40, 200), ax=ax, legend=False)
df_runs_clean = df_runs.dropna(subset=['Pace_min_km'])
df_runs_clean["Fecha_ordinal"] = df_runs_clean["Fecha_dt"].apply(lambda x: x.toordinal())
tendencia = np.poly1d(np.polyfit(df_runs_clean["Fecha_ordinal"], df_runs_clean["Pace_min_km"], 1))
ax.plot(df_runs_clean["Fecha_dt"], tendencia(df_runs_clean["Fecha_ordinal"]), color="red", linestyle="--", linewidth=2)
ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Fecha")
ax.set_title("Evolución del Ritmo de Carrera y Tendencia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/02_evolucion_pace.png", dpi=300)
plt.close()

# Gráfico 3: Relación FC vs Ritmo
df_clean_hr = df_runs[df_runs["average_heartrate"] > 0]
fig, ax = plt.subplots(figsize=(8, 6))
sns.scatterplot(data=df_clean_hr, x="Pace_min_km", y="average_heartrate", hue="Distancia_km", palette="magma", s=100, ax=ax, legend=False)
ax.set_xlabel("Ritmo (min/km)")
ax.set_ylabel("Frecuencia Cardíaca Media (ppm)")
ax.set_title("Relación Frecuencia Cardíaca vs. Ritmo", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/03_eficiencia_fc_ritmo.png", dpi=300)
plt.close()

# Gráfico 4: Consistencia del Ritmo por Distancia
fig, ax = plt.subplots(figsize=(10, 5))
sns.boxplot(data=df_runs, x="Rango_Distancia", y="Pace_min_km", color="lightseagreen", ax=ax)
ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Distancia (km)")
ax.set_title("Consistencia del Ritmo por Distancia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/04_ritmo_por_distancia.png", dpi=300)
plt.close()

# Gráfico 5: Eficiencia Cardiovascular por Distancia
df_ef_clean = df_runs.dropna(subset=['EF'])
fig, ax = plt.subplots(figsize=(10, 5))
sns.boxplot(data=df_ef_clean, x="Rango_Distancia", y="EF", color="coral", ax=ax)
ax.set_ylabel("Eficiencia (m/min / ppm)")
ax.set_xlabel("Distancia (km)")
ax.set_title("Eficiencia Cardiovascular por Rango de Distancia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/05_eficiencia_por_distancia.png", dpi=300)
plt.close()

# ==========================================
# 5. INTELIGENCIA DEPORTIVA CON GEMINI (NUEVO SDK)
# ==========================================
print("🧠 Procesando Inteligencia Deportiva con Gemini API...")
client = genai.Client(api_key=API_KEY_GEMINI)

runs_semana = df_runs[df_runs["Fecha_dt"] >= (datetime.now() - timedelta(days=7))]
km_totales = runs_semana["Distancia_km"].sum()
pace_prom = runs_semana["Pace_min_km"].mean()
carga_tot = runs_semana["icu_training_load"].sum()

def safe_sleep(val):
    return round((val or 0) / 3600, 1)

bio_text = "\n".join([f"Día {w['id']}: HRV {w.get('hrv', 'N/A')}ms, RHR {w.get('restingHR', 'N/A')}ppm, Sueño {safe_sleep(w.get('sleepSecs'))}hs" for w in wellness_data])

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

response = client.models.generate_content(
    model='gemini-3.6-flash',
    contents=prompt_maestro,
)

with open("reports/00_Analisis_Inteligencia_Deportiva.txt", "w", encoding="utf-8") as f:
    f.write(response.text)

print("✅ Pipeline ejecutado con éxito. Todos los archivos guardados en /reports/")
