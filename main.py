import os
import sys
from datetime import datetime
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
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

# 3. Procesamiento de datos
print("📊 Procesando datos...")
df_api = pd.DataFrame(data)
df_runs = df_api[df_api["type"] == "Run"].copy()

if df_runs.empty:
    print("❌ No se encontraron actividades de running.")
    sys.exit(1)

# Transformaciones
df_runs["Fecha_dt"] = pd.to_datetime(df_runs["start_date_local"])
df_runs["Distancia_km"] = df_runs["distance"] / 1000.0
df_runs["Tiempo_min"] = df_runs["moving_time"] / 60.0
df_runs["Pace_min_km"] = df_runs["Tiempo_min"] / df_runs["Distancia_km"]

# Para la regresión: días desde la primera carrera
df_runs["Dias"] = (df_runs["Fecha_dt"] - df_runs["Fecha_dt"].min()).dt.days

# Columnas a conservar
cols = ["id", "Fecha_dt", "name", "Distancia_km", "Tiempo_min", "Pace_min_km", "average_heartrate", "icu_training_load", "Dias"]
cols_existentes = [col for col in cols if col in df_runs.columns]
df_runs = df_runs[cols_existentes].sort_values("Fecha_dt").reset_index(drop=True)

print(f"🏃‍♂️ Carreras de running procesadas: {len(df_runs)}")
print("💾 Guardando CSV...")
df_runs.to_csv("running_historico.csv", index=False)
print("   ✅ CSV guardado.")

# 4. Generación de gráficos
print("📈 Generando gráficos...")
os.makedirs("reports", exist_ok=True)
sns.set_theme(style="whitegrid")

# ------------------------------------------------------------
# Gráfico 1: Evolución del Pace (con tendencia CORREGIDA)
# ------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5))

# Scatter con fechas reales
sns.scatterplot(data=df_runs, x="Fecha_dt", y="Pace_min_km", hue="Distancia_km", palette="viridis", size="Distancia_km", sizes=(40, 200), ax=ax)

# Regresión usando la columna numérica "Dias"
sns.regplot(data=df_runs, x="Dias", y="Pace_min_km", scatter=False, ax=ax, color="red", line_kws={"linestyle": "--", "linewidth": 2})

# Formatear el eje X con fechas legibles
ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
plt.xticks(rotation=45, ha="right")

ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Fecha")
ax.set_title("Evolución del Ritmo de Carrera y Tendencia (corregida)", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/01_evolucion_pace.png", dpi=300)
plt.close()

# ------------------------------------------------------------
# Gráfico 2: Volumen Semanal (agrupado por año-semana)
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# Gráfico 3: Eficiencia Cardiovascular (EF = Velocidad / FC)
# ------------------------------------------------------------
if "average_heartrate" in df_runs.columns:
    df_ef = df_runs[df_runs["average_heartrate"] > 0].copy()
    df_ef["Velocidad_m_min"] = (df_ef["Distancia_km"] * 1000) / df_ef["Tiempo_min"]
    df_ef["EF"] = df_ef["Velocidad_m_min"] / df_ef["average_heartrate"]

    fig, ax = plt.subplots(figsize=(10, 5))
    sns.scatterplot(data=df_ef, x="Fecha_dt", y="EF", hue="Distancia_km", palette="coolwarm", size="Distancia_km", sizes=(40, 200), ax=ax)
    ax.set_ylabel("Eficiencia (m/min / ppm)")
    ax.set_xlabel("Fecha")
    ax.set_title("Evolución de la Eficiencia Cardiovascular", fontweight="bold")
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    plt.savefig("reports/03_eficiencia_cardiovascular.png", dpi=300)
    plt.close()

    # Gráfico 3b: Boxplot de EF por rango de distancia (para ver consistencia)
    df_ef["Rango_Distancia"] = pd.cut(df_ef["Distancia_km"], bins=[0, 5, 10, 15, 21, 30, 50])
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.boxplot(data=df_ef, x="Rango_Distancia", y="EF", palette="Set2", ax=ax)
    ax.set_ylabel("Eficiencia (m/min / ppm)")
    ax.set_xlabel("Distancia (km)")
    ax.set_title("Eficiencia Cardiovascular por Rango de Distancia", fontweight="bold")
    plt.tight_layout()
    plt.savefig("reports/04_eficiencia_por_distancia.png", dpi=300)
    plt.close()

# ------------------------------------------------------------
# Gráfico 4: Ritmo por rango de distancia (consistencia)
# ------------------------------------------------------------
df_runs["Rango_Distancia"] = pd.cut(df_runs["Distancia_km"], bins=[0, 5, 10, 15, 21, 30, 50])
fig, ax = plt.subplots(figsize=(10, 5))
sns.boxplot(data=df_runs, x="Rango_Distancia", y="Pace_min_km", palette="Set3", ax=ax)
ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Distancia (km)")
ax.set_title("Consistencia del Ritmo por Distancia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/05_ritmo_por_distancia.png", dpi=300)
plt.close()

print("✅ Procesamiento completado. Revisá la carpeta 'reports' para ver los gráficos.")
