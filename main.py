import os
from datetime import datetime
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth
import matplotlib.pyplot as plt
import seaborn as sns

# 1. Lectura segura de Variables de Entorno
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")

if not ATHLETE_ID or not API_KEY:
    raise ValueError("Error: Las credenciales no están configuradas correctamente en los Secrets.")

# 2. CONEXIÓN CON PAGINADO (Descarga TODO el historial)
print("🔄 Conectando con Intervals.icu para descargar TODAS tus actividades...")
url_base = f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities"

todas_las_actividades = []
pagina = 0
limite_por_pagina = 100  # Máximo permitido por la API

while True:
    params = {
        "limit": limite_por_pagina,
        "offset": pagina * limite_por_pagina,
        "newest": datetime.now().strftime("%Y-%m-%d"),
        "oldest": "2020-01-01"  # Fecha vieja para asegurar que agarre todo
    }
    
    response = requests.get(url_base, auth=HTTPBasicAuth(API_KEY, ""), params=params)
    
    if response.status_code != 200:
        print(f"⚠️ Error en la página {pagina + 1}: {response.status_code}")
        print(f"🔍 Detalle del error: {response.text}")  # <--- NUEVA LÍNEA
        break
    
    datos_pagina = response.json()
    
    # Si la API devuelve una lista vacía, significa que no hay más datos
    if not datos_pagina:
        break
    
    todas_las_actividades.extend(datos_pagina)
    print(f"   ✅ Descargadas {len(todas_las_actividades)} actividades hasta ahora...")
    
    # Si la cantidad de actividades que vino en esta página es MENOR al límite,
    # significa que esta es la última página. Cortamos el bucle.
    if len(datos_pagina) < limite_por_pagina:
        break
    
    pagina += 1

print(f"🎯 Total de actividades descargadas: {len(todas_las_actividades)}")

# Si no trajo nada, cortamos la ejecución
if not todas_las_actividades:
    print("❌ No se encontraron actividades. Revisá tu ID o tu clave API.")
    exit()

# 3. Procesamiento de Datos (igual que antes, pero usando TODAS las actividades)
df_api = pd.DataFrame(todas_las_actividades)

# Filtrar solo carreras de Running
df_runs = df_api[df_api["type"] == "Run"].copy()

# Transformación de métricas
df_runs["Fecha_dt"] = pd.to_datetime(df_runs["start_date_local"])
df_runs["Distancia_km"] = df_runs["distance"] / 1000.0
df_runs["Tiempo_min"] = df_runs["moving_time"] / 60.0
df_runs["Pace_min_km"] = df_runs["Tiempo_min"] / df_runs["Distancia_km"]

cols = ["id", "Fecha_dt", "name", "Distancia_km", "Tiempo_min", "Pace_min_km", "average_heartrate", "icu_training_load"]
df_runs = df_runs[cols].sort_values("Fecha_dt").reset_index(drop=True)

print(f"🏃‍♂️ Carreras de running encontradas: {len(df_runs)}")

# Guardar CSV consolidado
df_runs.to_csv("running_historico.csv", index=False)

# 4. Generación de Reportes Gráficos (IDÉNTICO al de Gemini)
os.makedirs("reports", exist_ok=True)
sns.set_theme(style="whitegrid")

# Gráfico 1: Evolución del Pace
fig, ax = plt.subplots(figsize=(10, 5))
sns.scatterplot(data=df_runs, x="Fecha_dt", y="Pace_min_km", hue="Distancia_km", palette="viridis", size="Distancia_km", sizes=(40, 200), ax=ax)
sns.regplot(data=df_runs, x=df_runs.index, y="Pace_min_km", scatter=False, ax=ax, color="red", line_kws={"linestyle": "--"})
ax.set_ylabel("Ritmo (min/km)")
ax.set_xlabel("Fecha")
ax.set_title("Evolución del Ritmo de Carrera y Tendencia", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/01_evolucion_pace.png", dpi=300)
plt.close()

# Gráfico 2: Volumen Semanal
df_runs['Semana'] = df_runs['Fecha_dt'].dt.isocalendar().week
weekly = df_runs.groupby('Semana')['Distancia_km'].sum().reset_index()
fig, ax = plt.subplots(figsize=(10, 5))
sns.barplot(data=weekly, x="Semana", y="Distancia_km", color="steelblue", ax=ax)
ax.set_ylabel("Kilómetros Totales")
ax.set_xlabel("Semana del Año")
ax.set_title("Volumen Semanal Acumulado (km)", fontweight="bold")
plt.tight_layout()
plt.savefig("reports/02_volumen_semanal.png", dpi=300)
plt.close()

# Gráfico 3: Eficiencia Cardiovascular (solo si hay datos de FC)
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
