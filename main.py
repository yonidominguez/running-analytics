import os
import sys
from datetime import datetime
import pandas as pd
import requests
from requests.auth import HTTPBasicAuth

API_KEY = os.environ.get("INTERVALS_API_KEY")
if not API_KEY:
    sys.exit("❌ Error: INTERVALS_API_KEY no está configurada.")

url = "https://intervals.icu/api/v1/athlete/0/activities"
params = {
    "oldest": "2020-01-01",
    "newest": datetime.now().strftime("%Y-%m-%d")
}

print("🔄 Conectando a Intervals.icu...")
response = requests.get(
    url,
    auth=HTTPBasicAuth("API_KEY", API_KEY),  # <--- CORREGIDO
    params=params,
    timeout=30
)

if response.status_code != 200:
    print(f"⚠️ Error {response.status_code}: {response.text}")
    sys.exit(1)

data = response.json()
print(f"✅ Actividades descargadas: {len(data)}")

# Si llegas acá, la autenticación funciona
# Ahora podés agregar el procesamiento y gráficos...
