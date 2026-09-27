import time
import urllib.request
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

TARGET_URLS = [
    "https://sofia-ai-agency.onrender.com/health",
    "https://sofia-ai-agency.onrender.com/",
    "https://air-control-mp-new.onrender.com/"
]

def ping_servers():
    for url in TARGET_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SofiaKeepAlive/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                logging.info(f"Keep-Alive: {url} -> HTTP {response.status} (OK)")
        except Exception as e:
            logging.warning(f"Keep-Alive Warning for {url}: {e}")

if __name__ == "__main__":
    logging.info("🚀 Keep-Alive Pinger iniciado. Manteniendo servicios calientes cada 10 minutos...")
    while True:
        ping_servers()
        time.sleep(600)  # 10 minutos
