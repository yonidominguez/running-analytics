import os
import sys
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import requests
from google import genai

# 1. Variables de entorno
ATHLETE_ID = os.environ.get("INTERVALS_ATHLETE_ID")
API_KEY = os.environ.get("INTERVALS_API_KEY")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_KEY = os.environ.get("GROQ_API_KEY")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD")

if not all([ATHLETE_ID, API_KEY, GMAIL_USER, GMAIL_PASS]):
    sys.exit("❌ Faltan credenciales base en los Secrets de GitHub.")

auth = ("API_KEY", API_KEY)
BASE_URL = "https://intervals.icu/api/v1"

# 2. Ventana temporal (últimos 7 días UTC-3)
arg_time = datetime.now(timezone.utc) - timedelta(hours=3)
start_date = (arg_time - timedelta(days=7)).strftime("%Y-%m-%d")

# 3. Ingesta de actividades
print("🔄 Obteniendo listado de actividades...")
activities_res = requests.get(
    f"{BASE_URL}/athlete/{ATHLETE_ID}/activities",
    auth=auth,
    params={"oldest": start_date}
)
activities_res.raise_for_status()
activities = activities_res.json()

if not activities or not isinstance(activities, list):
    print("No hay actividades registradas en los últimos 7 días.")
    sys.exit(0)

# 4. Selección de actividad principal de Running
runs = [a for a in activities if a.get("type") in ["Run", "VirtualRun"]]
if not runs:
    print("No hay actividades de running recientes.")
    sys.exit(0)

latest_date = max(a.get("start_date_local", a.get("start_date", ""))[:10] for a in runs)
target_runs = [a for a in runs if (a.get("start_date_local") or a.get("start_date", "")).startswith(latest_date)]

primary_tag = "#principal"
tagged_runs = [a for a in target_runs if primary_tag in a.get("name", "").lower()]
activity = max(tagged_runs, key=lambda x: x.get("distance", 0)) if tagged_runs else max(target_runs, key=lambda x: x.get("distance", 0))

activity_id = activity["id"]
activity_name = activity.get("name", "Sin nombre")
print(f"✅ Actividad seleccionada: {activity_name} (ID: {activity_id}) - Fecha: {latest_date}")

# 5. Detalle de actividad e intervalos
print("🔄 Obteniendo detalle de la actividad...")
detail_res = requests.get(f"{BASE_URL}/activity/{activity_id}", auth=auth)
detail_res.raise_for_status()
detail = detail_res.json()
laps_raw = detail.get("icu_intervals", []) if isinstance(detail, dict) else []

total_dist_km = activity.get("distance", 0) / 1000
total_dur_sec = activity.get("moving_time", activity.get("elapsed_time", 0))
if total_dist_km > 0 and total_dur_sec > 0:
    pace_total_sec = total_dur_sec / total_dist_km
    avg_pace_str = f"{int(pace_total_sec // 60)}:{int(pace_total_sec % 60):02d} min/km"
else:
    avg_pace_str = "--"

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

# 6. Evento planificado y Wellness
print("🔄 Obteniendo planificación y fatiga...")
events_res = requests.get(f"{BASE_URL}/athlete/{ATHLETE_ID}/events", auth=auth, params={"oldest": latest_date, "newest": latest_date}).json()
planned_txt = "Sin evento planificado asociado en Intervals"
if events_res and isinstance(events_res, list):
    best_event = max(events_res, key=lambda x: x.get("planned_distance", 0) or x.get("duration", 0))
    planned_txt = f"{best_event.get('name', 'Plan')} - {best_event.get('description', '')}"

wellness_res = requests.get(f"{BASE_URL}/athlete/{ATHLETE_ID}/wellness", auth=auth, params={"oldest": latest_date, "newest": latest_date}).json()
ctl_str, atl_str, tsb_str = "N/A", "N/A", "N/A"
if wellness_res and isinstance(wellness_res, list):
    w = wellness_res[-1]
    ctl, atl, tsb = w.get("ctl"), w.get("atl"), w.get("tsb")
    ctl_str = f"{ctl:.1f}" if isinstance(ctl, (int, float)) else "N/A"
    atl_str = f"{atl:.1f}" if isinstance(atl, (int, float)) else "N/A"
    tsb_str = f"{tsb:.1f}" if isinstance(tsb, (int, float)) else "N/A"

# 7. Motor de Inteligencia con Fallback
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
- Compliance declarado: {activity.get('icu_compliance', 'N/A')}%

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

def call_groq(p):
    if not GROQ_KEY:
        return None
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "Sos un entrenador de atletismo y analista de rendimiento. Generá análisis técnico conciso y riguroso."},
            {"role": "user", "content": p}
        ],
        "temperature": 0.3
    }
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

feedback = None
model_used = None

# Intento 1: Gemini 3.6 Flash
if GEMINI_KEY:
    try:
        print("🧠 Intentando análisis con Gemini (gemini-3.6-flash)...")
        client = genai.Client(api_key=GEMINI_KEY)
        resp = client.models.generate_content(model="gemini-3.6-flash", contents=prompt)
        feedback = resp.text
        model_used = "Gemini 3.6 Flash"
        print("✅ Análisis completado con Gemini.")
    except Exception as e:
        print(f"⚠️ Gemini no disponible ({e}). Activando fallback...")

# Intento 2: Groq Llama 3.3 70B
if not feedback and GROQ_KEY:
    try:
        print("🧠 Intentando análisis con Groq (Llama 3.3 70B)...")
        feedback = call_groq(prompt)
        model_used = "Groq Llama 3.3 70B"
        print("✅ Análisis completado con Groq.")
    except Exception as e:
        print(f"⚠️ Error con Groq: {e}")

if not feedback:
    feedback = "❌ Error: No se pudo generar el análisis con ninguno de los modelos configurados."

# 8. Envío por correo
print("📧 Enviando reporte por correo...")
msg = MIMEText(f"[{model_used}]\n\n{feedback}", "plain", "utf-8")
msg["Subject"] = f"🏃 Coach Report: {activity.get('name')} ({latest_date})"
msg["From"] = GMAIL_USER
msg["To"] = GMAIL_USER

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
    print("✅ Reporte despachado exitosamente.")
except Exception as e:
    print(f"❌ Error en el envío SMTP: {e}")
