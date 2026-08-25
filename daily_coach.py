import os
import sys
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import requests
from google import genai

# ==========================================
# 1. CREDENCIALES
# ==========================================
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

# ==========================================
# 2. VENTANA TEMPORAL (ÚLTIMOS 7 DÍAS)
# ==========================================
arg_time = datetime.now(timezone.utc) - timedelta(hours=3)
start_date = (arg_time - timedelta(days=7)).strftime("%Y-%m-%d")

# ==========================================
# 3. INGESTA DE ACTIVIDADES
# ==========================================
print("🔄 Obteniendo listado de actividades...")
activities_res = requests.get(
    f"{BASE_URL}/athlete/{ATHLETE_ID}/activities",
    auth=auth,
    params={"oldest": start_date},
    timeout=15
)
activities_res.raise_for_status()
activities = activities_res.json()

if not activities or not isinstance(activities, list):
    print("No hay actividades registradas en los últimos 7 días.")
    sys.exit(0)

# ==========================================
# 4. SELECCIÓN DE ACTIVIDAD PRINCIPAL
# ==========================================
runs = [a for a in activities if a.get("type") in ["Run", "VirtualRun"]]
if not runs:
    print("No hay actividades de running en los últimos 7 días.")
    sys.exit(0)

latest_date = max(a.get("start_date_local", a.get("start_date", ""))[:10] for a in runs)
target_runs = [a for a in runs if (a.get("start_date_local") or a.get("start_date", "")).startswith(latest_date)]

primary_tag = "#principal"
tagged_runs = [a for a in target_runs if primary_tag in a.get("name", "").lower()]
activity = max(tagged_runs, key=lambda x: x.get("distance", 0)) if tagged_runs else max(target_runs, key=lambda x: x.get("distance", 0))

activity_id = activity["id"]
activity_name = activity.get("name", "Sin nombre")
start_time_local = activity.get("start_date_local", activity.get("start_date", ""))
print(f"✅ Actividad seleccionada: {activity_name} (ID: {activity_id}) - Fecha: {latest_date}")

# ==========================================
# 5. DETALLE DE ACTIVIDAD Y LAPS (CORREGIDO)
# ==========================================
print("🔄 Obteniendo detalle de la actividad...")
detail_res = requests.get(f"{BASE_URL}/activity/{activity_id}", auth=auth, timeout=15)
detail_res.raise_for_status()
detail = detail_res.json()

# 🔥 CORRECCIÓN CLAVE: priorizar icu_laps (autolaps de Garmin)
laps_raw = (
    detail.get("icu_laps") 
    or detail.get("laps") 
    or detail.get("icu_intervals") 
    or []
)

# ==========================================
# 6. MÉTRICAS BIOMECÁNICAS Y EFICIENCIA
# ==========================================
avg_cadence = detail.get("average_cadence") or activity.get("average_cadence")
max_cadence = detail.get("max_cadence") or activity.get("max_cadence")
elevation_gain = detail.get("total_elevation_gain") or activity.get("total_elevation_gain", 0)
avg_hr = detail.get("average_heartrate") or activity.get("average_heartrate")
max_hr = detail.get("max_heartrate") or activity.get("max_heartrate", "--")

avg_cadence_str = f"{avg_cadence:.0f} spm" if isinstance(avg_cadence, (int, float)) else "--"
max_cadence_str = f"{max_cadence:.0f} spm" if isinstance(max_cadence, (int, float)) else "--"

total_dist_km = activity.get("distance", 0) / 1000
total_dur_sec = activity.get("moving_time", activity.get("elapsed_time", 0))

if total_dist_km > 0 and total_dur_sec > 0:
    pace_total_sec = total_dur_sec / total_dist_km
    avg_pace_str = f"{int(pace_total_sec // 60)}:{int(pace_total_sec % 60):02d} min/km"
else:
    avg_pace_str = "--"

# EF (Eficiencia Aeróbica)
ef_str = "N/A"
if total_dist_km > 0 and total_dur_sec > 0 and isinstance(avg_hr, (int, float)) and avg_hr > 0:
    speed_m_min = (activity.get("distance", 0) / total_dur_sec) * 60
    ef_val = speed_m_min / avg_hr
    ef_str = f"{ef_val:.2f} m/min/bpm"

# ==========================================
# 7. DETECCIÓN DE MODO: CARRERA vs ENTRENAMIENTO
# ==========================================
race_keywords = ["carrera", "maraton", "maratón", "21k", "42k", "10k", "5k", "race", "competencia", "torneo"]
is_race = any(k in activity_name.lower() for k in race_keywords) or activity.get("icu_training_load_type") == "Race"
mode_tag = "COMPETICIÓN / CARRERA" if is_race else "ENTRENAMIENTO REGULAR"

# ==========================================
# 8. PROCESAMIENTO DE LAPS (VUELTAS)
# ==========================================
lap_lines = []
for i, lap in enumerate(laps_raw, start=1):
    dist = lap.get("distance", 0)
    dur = lap.get("moving_time", lap.get("elapsed_time", 0))
    hr = lap.get("average_heartrate", "--")
    cad = lap.get("average_cadence")
    
    # Normalización de cadencia: si es <120, asumimos que es RPM de una pierna -> multiplicar por 2
    if isinstance(cad, (int, float)):
        cad_spm = cad * 2 if cad < 120 else cad
        cad_str = f" | Cad: {cad_spm:.0f} spm"
    else:
        cad_str = ""
    
    if dist > 0 and dur > 0:
        p_sec = (dur / dist) * 1000
        p_str = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} min/km"
    else:
        p_str = "--"
        
    lap_lines.append(f"Km {i} ({dist:.0f}m): {p_str} | FC: {hr} bpm{cad_str}")

laps_summary = "\n".join(lap_lines) if lap_lines else "Sin laps segmentados"

# ==========================================
# 9. CLIMA DINÁMICO (OPEN-METEO)
# ==========================================
def get_historical_weather(date_str, start_iso):
    try:
        lat, lon = -34.6037, -58.3816
        url = (
            f"https://archive-api.open-meteo.com/v1/archive?"
            f"latitude={lat}&longitude={lon}&start_date={date_str}&end_date={date_str}"
            f"&hourly=temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m"
        )
        r = requests.get(url, timeout=10).json()
        hourly = r.get("hourly", {})
        
        start_hour = 8
        if "T" in start_iso:
            try:
                start_hour = int(start_iso.split("T")[1].split(":")[0])
            except (ValueError, IndexError):
                start_hour = 8
                
        end_hour = min(start_hour + 3, 24)
        temps = hourly.get("temperature_2m", [])[start_hour:end_hour] or hourly.get("temperature_2m", [20])
        humids = hourly.get("relative_humidity_2m", [])[start_hour:end_hour] or hourly.get("relative_humidity_2m", [70])
        apparent = hourly.get("apparent_temperature", [])[start_hour:end_hour] or hourly.get("apparent_temperature", [20])
        winds = hourly.get("wind_speed_10m", [])[start_hour:end_hour] or hourly.get("wind_speed_10m", [10])
        
        t_avg = sum(temps) / len(temps)
        h_avg = sum(humids) / len(humids)
        app_avg = sum(apparent) / len(apparent)
        w_avg = sum(winds) / len(winds)
        
        return f"Temp: {t_avg:.1f}°C (Sensación: {app_avg:.1f}°C) | Humedad: {h_avg:.0f}% | Viento: {w_avg:.1f} km/h (Ventana ~{start_hour:02d}:00-{end_hour:02d}:00 ART)"
    except Exception as e:
        return f"Condiciones no disponibles ({e})"

print("🌤️ Consultando clima histórico...")
weather_info = get_historical_weather(latest_date, start_time_local)

# ==========================================
# 10. PLANIFICACIÓN Y WELLNESS (CTL/ATL/TSB + HRV/RHR)
# ==========================================
print("🔄 Obteniendo planificación y recuperación...")
events_res = requests.get(f"{BASE_URL}/athlete/{ATHLETE_ID}/events", auth=auth, params={"oldest": latest_date, "newest": latest_date}, timeout=15).json()
planned_txt = "Sin evento planificado asociado en Intervals"
if events_res and isinstance(events_res, list):
    best_event = max(events_res, key=lambda x: x.get("planned_distance", 0) or x.get("duration", 0))
    planned_txt = f"{best_event.get('name', 'Plan')} - {best_event.get('description', '')}"

wellness_res = requests.get(f"{BASE_URL}/athlete/{ATHLETE_ID}/wellness", auth=auth, params={"oldest": latest_date, "newest": latest_date}, timeout=15).json()
ctl_str, atl_str, tsb_str, hrv_str, rhr_str = "N/A", "N/A", "N/A", "N/A", "N/A"

if wellness_res and isinstance(wellness_res, list):
    w = wellness_res[-1]
    ctl, atl, tsb = w.get("ctl"), w.get("atl"), w.get("tsb")
    hrv = w.get("hrv") or w.get("hrvSDNN")
    rhr = w.get("restingHR")
    
    ctl_str = f"{ctl:.1f}" if isinstance(ctl, (int, float)) else "N/A"
    atl_str = f"{atl:.1f}" if isinstance(atl, (int, float)) else "N/A"
    tsb_str = f"{tsb:.1f}" if isinstance(tsb, (int, float)) else "N/A"
    hrv_str = f"{hrv:.0f} ms" if isinstance(hrv, (int, float)) else "N/A"
    rhr_str = f"{rhr:.0f} bpm" if isinstance(rhr, (int, float)) else "N/A"

# ==========================================
# 11. PROMPT DINÁMICO SEGÚN MODO
# ==========================================
guideline_mode = (
    "Esta sesión fue una COMPETICIÓN/CARRERA. Enfocate en gestión táctica del pacing (splits), entrega en umbral y protocolo de descarga post-esfuerzo máximo."
    if is_race else
    "Esta sesión fue un ENTRENAMIENTO REGULAR. Enfocate en disciplina de ritmos, cumplimiento de zonas objetivo y control de fatiga para construir continuidad."
)

prompt = f"""
Sos un entrenador de atletismo y analista de rendimiento.
Generá una devolución técnica estructurada de la sesión.

CONTEXTO DE LA SESIÓN: {mode_tag}
{guideline_mode}

CONDICIONES AMBIENTALES (Buenos Aires):
{weather_info}

OBJETIVO PLANIFICADO:
{planned_txt}

EJECUTADO (Fecha: {latest_date}):
- Nombre: {activity.get('name')}
- Distancia: {total_dist_km:.2f} km | Desnivel acumulado: {elevation_gain:.0f} m
- Tiempo: {total_dur_sec/60:.1f} min | Ritmo Promedio: {avg_pace_str}
- FC Promedio: {avg_hr} bpm | FC Máxima: {max_hr} bpm
- Factor de Eficiencia Aeróbica (EF): {ef_str}
- Cadencia Promedio: {avg_cadence_str} | Cadencia Máx: {max_cadence_str}
- Cumplimiento declarado: {activity.get('icu_compliance', 'N/A')}%

DETALLE DE VUELTAS / LAPS (1 km):
{laps_summary}

ESTADO FISIOLÓGICO Y RECUPERACIÓN PREVIA:
- Estado del Sistema Nervioso (HRV previo): {hrv_str} | Pulso en Reposo (RHR): {rhr_str}
- Modelo de Carga: Fitness (CTL): {ctl_str} | Fatiga (ATL): {atl_str} | Forma (TSB): {tsb_str}

Respondé en 4 bloques directos y concisos:
1. Precisión de ritmos y gestión del pacing (contrastando plan vs laps).
2. Respuesta cardiovascular y Eficiencia Aeróbica (análisis de EF en {ef_str} cruzado con clima y deriva cardíaca).
3. Biomecánica y recuperación previa (evaluación de cadencia en {avg_cadence_str} y estado del HRV/RHR al largar).
4. Veredicto y recomendación para la próxima sesión considerando el TSB actual ({tsb_str}).
"""

# ==========================================
# 12. INFERENCIA CON FALLBACK (Gemini -> Groq)
# ==========================================
def call_groq(p):
    if not GROQ_KEY:
        return None
    headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "Sos un entrenador de atletismo y analista de rendimiento. Respondé con rigurosidad técnica y sin preámbulos vacíos."},
            {"role": "user", "content": p}
        ],
        "temperature": 0.3
    }
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

feedback = None
model_used = None

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
    model_used = "Error Engine"

# ==========================================
# 13. ENVÍO POR CORREO SMTP
# ==========================================
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
