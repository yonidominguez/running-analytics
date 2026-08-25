# Running Analytics Pipeline

Pipeline serverless de análisis deportivo que extrae telemetría de **Intervals.icu**, cruza con clima histórico (**Open-Meteo**), calcula eficiencia aeróbica y genera informes diarios con **Gemini** y fallback a **Groq** (Llama 3.3 70B).

Automatizado de punta a punta con **GitHub Actions** con un **costo de infraestructura de $0/mes**.

---

## 🚀 Características

* **Ingesta automática:** Extrae actividades, laps, eventos y métricas de fatiga (CTL/ATL/TSB) desde Intervals.icu.
* **Clima histórico:** Consulta Open-Meteo Archive API para obtener temperatura, humedad y viento en las coordenadas exactas de la sesión.
* **Inferencia Multi-LLM con Failover:** Gemini 3.6 Flash como motor principal con fallback automático a Groq (Llama 3.3 70B) ante saturación de cuotas.
* **Reportes diarios:** Despacho automatizado por correo SMTP con análisis técnico kilómetro a kilómetro (ritmo, FC, cadencia y eficiencia).
* **Histórico y visualización:** Genera backups estructurados en CSV y gráficos de evolución de ritmo, volumen y fatiga.

---

## 🛠️ Stack Tecnológico

* **Lenguaje:** Python 3.11
* **Orquestación & CI/CD:** GitHub Actions (cron desatendido)
* **APIs de Datos:** Intervals.icu REST API, Open-Meteo Archive API
* **Modelos de Inferencia:** Google Gemini 3.6 Flash, Groq Cloud (Llama 3.3 70B Versatile)
* **Notificaciones:** Gmail SMTP
* **Visualización:** Looker Studio

---

## 📐 Arquitectura

    [Garmin Watch] ──► [Intervals.icu] ──► [daily_coach.py] (GitHub Actions)
                                                  │
                                                  ▼
                                     [Gemini / Groq Failover]
                                                  │
                                                  ▼
                                       [SMTP Gmail ──► Atleta]

> Para conocer en profundidad las decisiones técnicas, costos y trade-offs, consulta el [[ADR-001.md]]([ur](https://github.com/yonidominguez/running-analytics/blob/main/ADR-001.md)l).

---

## 📊 Dashboard

Los datos históricos consolidados se sincronizan con Looker Studio para seguimiento longitudinal de métricas de carga (modelo Banister), volumen semanal y eficiencia cardiovascular.

---

## 🔐 Seguridad

Todas las credenciales, API keys y contraseñas de aplicación se administran exclusivamente mediante **GitHub Secrets** e inyección por variables de entorno. Ningún dato sensible está expuesto en el código.

---

## 📄 Licencia

Este proyecto está bajo la Licencia MIT.
