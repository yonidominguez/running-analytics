import os
import sys
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import requests
from google import genai

# 1. Validación de variables de entorno
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD")

if not all([ATHLETE_ID, API_KEY, GEMINI_KEY, GMAIL_USER, GMAIL_PASS]):
    sys.exit("❌ Faltan credenciales en los Secrets de GitHub.")

auth = ("API_KEY", API_KEY)

# 2. Ventana temporal (Buscamos en los últimos 7 días)
arg_time = datetime.now(timezone.utc) - timedelta(hours=3)
start_date = (arg_time - timedelta(days=7)).strftime("%Y-%m-%d")

# 3. Obtener actividades recientes
act_res = requests.get(
    f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities?oldest={start_date}",
    auth=auth
).json()

if not act_res or not isinstance(act_res, list):
    print("No hay actividades registradas en los últimos 7 días.")
    sys.exit(0)

# Filtrar actividades de Running
runs = [a for a in act_res if a.get("type") in ["Run", "VirtualRun"]] or act_res

# Tomamos la fecha de la actividad más reciente
latest_date = max(a.get("start_date_local", a.get("start_date", ""))[:10] for a in runs)
target_runs = [a for a in runs if (a.get("start_date_local") or a.get("start_date", "")).startswith(latest_date)]

# Estrategia híbrida: si existe etiqueta '#principal', tiene prioridad; si no, mayor distancia
primary_tag = "#principal"
tagged_runs = [a for a in target_runs if primary_tag in a.get("name", "").lower()]

if tagged_runs:
    activity = max(tagged_runs, key=lambda x: x.get("distance", 0))
else:
    activity = max(target_runs, key=lambda x: x.get("distance", 0))

activity_id = activity["id"]

# Cálculo de ritmo promedio general
total_dist_km = activity.get("distance", 0) / 1000
total_dur_sec = activity.get("moving_time", activity.get("elapsed_time", 0))
if total_dist_km > 0 and total_dur_sec > 0:
    pace_total_sec = total_dur_sec / total_dist_km
    avg_pace_str = f"{int(pace_total_sec // 60)}:{int(pace_total_sec % 60):02d} min/km"
else:
    avg_pace_str = "--"

# 4. Detalle de intervalos / laps (conversión m/s -> min/km)
detail = requests.get(
    f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/activities/{activity_id}",
    auth=auth
).json()

laps_raw = detail.get("icu_intervals", [])
lap_lines = []
for i, lap in enumerate(laps_raw, start=1):
    dist = lap.get("distance", 0)
    dur = lap.get("moving_time", lap.get("elapsed_time", 0))
    hr = lap.get("average_heartrate", "--")
    
    if dist > 0 and dur > 0:
        p_sec = (dur / dist) * 1000
        p_str = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} min/km"
    else:
        p_str = "--"
        
    lap_lines.append(f"Vuelta {i}: {dist:.0f}m | {dur}s | {p_str} | FC: {hr} bpm")

laps_summary = "\n".join(lap_lines) if lap_lines else "Sin laps segmentados"

# 5. Plan del día (Evento en Intervals en la fecha de la actividad)
events_res = requests.get(
    f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/events?oldest={latest_date}&newest={latest_date}",
    auth=auth
).json()

planned_txt = "Sin evento planificado asociado en Intervals"
if events_res and isinstance(events_res, list):
    best_event = max(events_res, key=lambda x: x.get("planned_distance", 0) or x.get("duration", 0))
    planned_txt = f"{best_event.get('name', 'Plan')} - {best_event.get('description', '')}"

# 6. Estado de fatiga (Wellness para esa fecha)
wellness_res = requests.get(
    f"https://intervals.icu/api/v1/athlete/{ATHLETE_ID}/wellness?oldest={latest_date}&newest={latest_date}",
    auth=auth
).json()

ctl_str, atl_str, tsb_str = "N/A", "N/A", "N/A"
if wellness_res and isinstance(wellness_res, list):
    w = wellness_res[-1]
    ctl = w.get("ctl")
    atl = w.get("atl")
    tsb = w.get("tsb")
    ctl_str = f"{ctl:.1f}" if isinstance(ctl, (int, float)) else "N/A"
    atl_str = f"{atl:.1f}" if isinstance(atl, (int, float)) else "N/A"
    tsb_str = f"{tsb:.1f}" if isinstance(tsb, (int, float)) else "N/A"

# 7. Generación del reporte con Gemini
client = genai.Client(api_key=GEMINI_KEY)

prompt = f"""
Sos un entrenador de atletismo y analista de rendimiento. 
Generá una devolución técnica del entrenamiento contrastando lo planificado con lo ejecutado.

OBJETIVO PLANIFICADO:
{planned_txt}

EJECUTADO (Sesión Principal - Fecha: {latest_date}):
- Nombre: {activity.get('name')}
- Distancia total: {total_dist_km:.2f} km
- Tiempo en movimiento: {total_dur_sec/60:.1f} min
- Ritmo promedio: {avg_pace_str}
- FC Promedio: {activity.get('average_heartrate', '--')} bpm | FC Máx: {activity.get('max_heartrate', '--')} bpm
- Compliance/Cumplimiento declarado: {activity.get('icu_compliance', 'N/A')}%

DETALLE DE VUELTAS / INTERVALOS:
{laps_summary}

FATIGA ACUMULADA:
- Fitness (CTL): {ctl_str} | Fatiga (ATL): {atl_str} | Forma (TSB): {tsb_str}

Respondé en 4 bloques directos y concisos:
1. Precisión de ritmos por bloque respecto al plan.
2. Análisis cardiovascular (deriva cardíaca, zonas de esfuerzo).
3. Biomecánica y consistencia de cadencia.
4. Veredicto y recomendación para la próxima sesión considerando el TSB actual.
"""

try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    feedback = response.text
except Exception as e:
    feedback = f"❌ Error al consultar la API de Gemini: {str(e)}"

# 8. Envío por correo
msg = MIMEText(feedback, "plain", "utf-8")
msg["Subject"] = f"🏃 Coach Report: {activity.get('name')} ({latest_date})"
msg["From"] = GMAIL_USER
msg["To"] = GMAIL_USER

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
    print("✅ Feedback generado y enviado por correo.")
except Exception as e:
    print(f"❌ Error en el envío de correo: {e}")
