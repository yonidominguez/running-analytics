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
# 5. DETALLE DE ACTIVIDAD E INTERVALOS
# ==========================================
print("🔄 Obteniendo detalle de la actividad...")
detail_res = requests.get(f"{BASE_URL}/activity/{activity_id}", auth=auth, params={"intervals": "true"}, timeout=15)
detail_res.raise_for_status()
detail = detail_res.json()

# Prioridad a icu_intervals (tabla exacta de la UI web)
laps_raw = (
    detail.get("icu_intervals") 
    or detail.get("icu_laps") 
    or detail.get("laps") 
    or []
)

print(f"🔎 Intervalos detectados: {len(laps_raw)}")
print("🔎 Tipos crudos:", sorted({(lap.get("type") or "SIN_TYPE") for lap in laps_raw}))

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
# 8. PROCESAMIENTO ESTRUCTURADO DE INTERVALOS
# ==========================================
TYPE_LABEL = {
    "WARMUP":   "ENTRADA EN CALOR",
    "COOLDOWN": "VUELTA A LA CALMA",
    "WORK":     None,   # Genera REP {work_count}
    "RECOVERY": None,   # Genera PAUSA {recovery_count}
    "REST":     None,   # Genera PAUSA {recovery_count}
}

lap_lines = []
work_count = 0
recovery_count = 0

for i, lap in enumerate(laps_raw, start=1):
    dist = lap.get("distance") or 0
    dur = lap.get("moving_time") or lap.get("elapsed_time") or 0
    hr = lap.get("average_heartrate") or "--"
    cad = lap.get("average_cadence")
    raw_type = (lap.get("type") or "").upper()

    if raw_type in TYPE_LABEL:
        label = TYPE_LABEL[raw_type]
        if label is None:
            if raw_type == "WORK":
                work_count += 1
                tag = f"REP {work_count}"
            else:
                recovery_count += 1
                tag = f"PAUSA {recovery_count}"
        else:
            tag = label
    else:
        tag = f"BLOQUE {i}"

    # Normalización de cadencia (Intervals v1 API entrega RPM por pierna en running)
    if isinstance(cad, (int, float)):
        cad_spm = cad * 2 if cad < 120 else cad
        cad_str = f" | Cad: {cad_spm:.0f} spm"
    else:
        cad_str = ""

    # Ritmo
    if dist > 0 and dur > 0:
        p_sec = (dur / dist) * 1000
        p_str = f"{int(p_sec // 60)}:{int(p_sec % 60):02d} min/km"
    else:
        p_str = "--"

    dur_min = int(dur // 60)
    dur_sec = int(dur % 60)
    dur_str = f"{dur_min}m{dur_sec:02d}s" if dur_min > 0 else f"{dur_sec}s"

    lap_lines.append(f"[{tag}] {dist:.0f}m en {dur_str} ({p_str}) | FC: {hr} bpm{cad_str}")

# Clasificación y formateo limpio de cabecera (pluralización simétrica)
if work_count >= 1:
    session_type = "interval"
    reps_word = "REP" if work_count == 1 else "REPS"
    pause_word = "PAUSA" if recovery_count == 1 else "PAUSAS"
    pause_part = f" + {recovery_count} {pause_word}" if recovery_count > 0 else ""
    laps_header = f"{work_count} {reps_word}{pause_part}"
elif lap_lines:
    session_type = "continuous"
    laps_header = "BLOQUES DE RODAJE CONTINUO"
else:
    session_type = "continuous"
    laps_header = "RODAJE CONTINUO SIN INTERVALOS"

laps_summary = "\n".join(lap_lines) if lap_lines else "No se recibieron vueltas de esta actividad."

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
# 11. PROMPT DINÁMICO
# ==========================================
guideline_mode = (
    "Esta sesión fue una COMPETICIÓN/CARRERA. Enfocate en gestión táctica del pacing (splits), entrega en umbral y protocolo de descarga post-esfuerzo máximo."
    if is_race else
    "Esta sesión fue un ENTRENAMIENTO REGULAR. Enfocate en disciplina de ritmos, cumplimiento de zonas objetivo y control de fatiga para construir continuidad."
)

prompt = f"""
Sos mi entrenador de running de confianza. Me hablás de vos, cercano y directo, como un coach que me conoce, no como un informe ni con jerga académica.

Analizá estos datos de mi entrenamiento de hoy. Los datos crudos son para vos, no me los repitas como una lista. Traducí qué significan para mi cuerpo.

Datos de la sesión (Modo: {mode_tag}):
- Nombre: {activity.get('name')}
- Distancia: {total_dist_km:.2f} km | Desnivel: {elevation_gain:.0f} m
- Tiempo: {total_dur_sec/60:.1f} min | Ritmo: {avg_pace_str}
- FC Promedio: {avg_hr} bpm | FC Máx: {max_hr} bpm
- Cadencia: {avg_cadence_str}
- Estado previo (HRV/RHR): {hrv_str} / {rhr_str}
- Clima: {weather_info}
- Planificado: {planned_txt}

Vueltas/Intervalos detectados ({laps_header}):
{laps_summary}

Respondé en máximo 180 palabras, sin títulos, sin viñetas y sin saludos:
1. Cómo salió la sesión hoy (una frase directa cruzando lo ejecutado con lo planificado).
2. Qué se notó en el cuerpo (usa las métricas de pulso, ritmo y clima para deducir fatiga o frescura).
3. Un solo punto a corregir o destacar.
4. Qué hacer mañana (tipo de esfuerzo, sin mencionar números de TSB).

Regla estricta: Si la sección de Vueltas dice 'No se recibieron vueltas de esta actividad', asumí que hubo una falla de sincronización de datos, decímelo en una frase y evaluá el resto de las métricas.
"""

# ==========================================
# 12. INFERENCIA CON FALLBACK (Gemini -> Groq)
# ==========================================
errors = []  # acumula el motivo exacto de cada fallo (se incluye en el mail si todo falla)

def call_gemini(p):
    if not GEMINI_KEY:
        errors.append("Gemini: GEMINI_API_KEY vacía en el workflow")
        return None, None
    client = genai.Client(api_key=GEMINI_KEY)
    # Misma vía (Interactions API) y mismos modelos que ya funcionan en main.py
    for modelo in ["gemini-3.6-flash", "gemini-3.5-flash-lite"]:
        try:
            print(f"🧠 Intentando análisis con Gemini ({modelo})...")
            interaction = client.interactions.create(model=modelo, input=p, store=False)
            texto = (interaction.output_text or "").strip()
            if texto:
                print(f"✅ Análisis completado con {modelo}.")
                return texto, f"Gemini {modelo}"
            errors.append(f"{modelo}: respuesta vacía")
            print(f"⚠️ {modelo}: respuesta vacía")
        except Exception as e:
            errors.append(f"{modelo}: {type(e).__name__}: {e}")
            print(f"⚠️ Falló {modelo}: {type(e).__name__}: {e}")
    return None, None

def call_groq(p):
    if not GROQ_KEY:
        errors.append("Groq: GROQ_API_KEY vacía en el workflow (fallback omitido)")
        print("⚠️ GROQ_API_KEY vacía: no hay fallback disponible.")
        return None, None
    try:
        print("🧠 Intentando análisis con Groq (Llama 3.3 70B)...")
        headers = {"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "Sos un entrenador de running de confianza. Hablás de vos, cercano y directo, sin jerga técnica ni preámbulos."},
                {"role": "user", "content": p}
            ],
            "temperature": 0.4
        }
        r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=25)
        if not r.ok:
            errors.append(f"Groq: HTTP {r.status_code}: {r.text[:300]}")
            print(f"⚠️ Groq HTTP {r.status_code}: {r.text[:300]}")
            return None, None
        texto = (r.json()["choices"][0]["message"]["content"] or "").strip()
        if texto:
            print("✅ Análisis completado con Groq.")
            return texto, "Groq Llama 3.3 70B"
        errors.append("Groq: respuesta vacía")
    except Exception as e:
        errors.append(f"Groq: {type(e).__name__}: {e}")
        print(f"⚠️ Error con Groq: {type(e).__name__}: {e}")
    return None, None

feedback, model_used = call_gemini(prompt)
if not feedback:
    print("⚠️ Gemini no disponible. Activando fallback a Groq...")
    feedback, model_used = call_groq(prompt)

if not feedback:
    feedback = "❌ No se pudo generar el análisis con ninguno de los modelos.\n\nDetalle técnico:\n- " + "\n- ".join(errors)
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
