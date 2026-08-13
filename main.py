import os
import sys
from datetime import datetime
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib.pyplot as plt
import seaborn as sns

# 1. Lectura de la API Key
API_KEY = os.environ.get("INTERVALS_API_KEY")
if not API_KEY:
    sys.exit("❌ Error: INTERVALS_API_KEY no está configurada.")

# 2. Descarga de datos
url = "https://intervals.icu/api/v1/athlete/0/activities"
params = {
    "oldest": "2020-01-01",
    "newest": datetime.now().strftime("%Y-%m-%d")
}

print("🔄 Conectando a Intervals.icu...")
response = requests.get(
    url,
    auth=HTTPBasicAuth("API_KEY", API_KEY),
    params=params,
    timeout=30
)

if response.status_code != 200:
    print(f"⚠️ Error {response.status_code}: {response.text}")
    sys.exit(1)

data = response.json()
print(f"✅ Actividades descargadas: {len(data)}")

if not data:
    print("❌ No se encontraron actividades.")
    sys.exit(1)

# --- DEPURACIÓN: Mostrar las primeras claves del primer elemento ---
print("🔍 Primer elemento del JSON (claves):", list(data[0].keys()) if data else "No hay datos")

# 3. Procesamiento de datos
print("📊 Creando DataFrame...")
df_api = pd.DataFrame(data)
print(f"   ✅ DataFrame creado con {len(df_api)} filas y {len(df_api.columns)} columnas.")

print("🔍 Columnas disponibles:", list(df_api.columns))

# Filtrar actividades de running
print("🏃 Filtrando por tipo 'Run'...")
df_runs = df_api[df_api["type"] == "Run"].copy()
print(f"   ✅ Actividades de running encontradas: {len(df_runs)}")

if df_runs.empty:
    print("❌ No se encontraron actividades de running.")
    sys.exit(1)

# Transformaciones
print("🔄 Transformando métricas...")
df_runs["Fecha_dt"] = pd.to_datetime(df_runs["start_date_local"])
df_runs["Distancia_km"] = df_runs["distance"] / 1000.0
df_runs["Tiempo_min"] = df_runs["moving_time"] / 60.0
df_runs["Pace_min_km"] = df_runs["Tiempo_min"] / df_runs["Distancia_km"]
print("   ✅ Transformaciones completadas.")

# Seleccionar columnas
cols = ["id", "Fecha_dt", "name", "Distancia_km", "Tiempo_min", "Pace_min_km", "average_heartrate", "icu_training_load"]
print("🔍 Columnas disponibles después de transformar:", list(df_runs.columns))
# Filtrar columnas existentes (por si alguna no está)
cols_existentes = [col for col in cols if col in df_runs.columns]
print(f"🔍 Columnas a guardar: {cols_existentes}")
df_runs = df_runs[cols_existentes].sort_values("Fecha_dt").reset_index(drop=True)

print(f"🏃‍♂️ Carreras de running procesadas: {len(df_runs)}")
print("💾 Guardando CSV...")
df_runs.to_csv("running_historico.csv", index=False)
print("   ✅ CSV guardado.")

# 4. Generación de gráficos
print("📈 Generando gráficos...")
os.makedirs("reports", exist_ok=True)
sns.set_theme(style="whitegrid")

# Gráfico 1: Evolución del Pace
fig, ax = plt.subplots(figsize=(10, 5))
sns.scatterplot(data=df_runs, x="Fecha_dt", y="Pace_min_km", hue="Distancia_km", palette="viridis", size="Distancia_km", sizes=(40, 200), ax=ax)
sns.regplot(data=df_runs, x=df_runs["Fecha_dt"], y="Pace_min_km", scatter=False, ax=ax, color="red", line_kws={"linestyle": "--"})
ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Fecha")
ax.set_title("Evolución del Ritmo de Carrera y Tendencia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/01_evolucion_pace.png", dpi=300)
plt.close()

# Gráfico 2: Volumen Semanal
df_runs["Año"] = df_runs["Fecha_dt"].dt.isocalendar().year
df_runs["Semana"] = df_runs["Fecha_dt"].dt.isocalendar().week
weekly = df_runs.groupby(["Año", "Semana"])["Distancia_km"].sum().reset_index()
weekly["Año_Semana"] = weekly["Año"].astype(str) + "-S" + weekly["Semana"].astype(str)

fig, ax = plt.subplots(figsize=(12, 5))
sns.barplot(data=weekly, x="Año_Semana", y="Distancia_km", color="steelblue", ax=ax)
ax.set_ylabel("Kilómetros Totales")
ax.set_xlabel("Semana (Año-Semana)")
ax.set_title("Volumen Semanal Acumulado (km)", fontweight="bold")
plt.xticks(rotation=45, ha="right")
plt.tight_layout()
plt.savefig("reports/02_volumen_semanal.png", dpi=300)
plt.close()

# Gráfico 3: Eficiencia Cardiovascular (solo si existe la columna)
if "average_heartrate" in df_runs.columns:
    df_clean_hr = df_runs[df_runs["average_heartrate"] > 0]
    if not df_clean_hr.empty:
        fig, ax = plt.subplots(figsize=(8, 6))
        sns.scatterplot(data=df_clean_hr, x="Pace_min_km", y="average_heartrate", hue="Distancia_km", palette="magma", s=100, ax=ax)
        ax.set_xlabel("Ritmo (min/km)")
        ax.set_ylabel("Frecuencia Cardíaca Media (ppm)")
        ax.set_title("Relación Frecuencia Cardíaca vs. Ritmo", fontweight="bold")
        plt.tight_layout()
        plt.savefig("reports/03_eficiencia_fc_ritmo.png", dpi=300)
        plt.close()

print("✅ Procesamiento completado. Revisá la carpeta 'reports' para ver los gráficos.")
