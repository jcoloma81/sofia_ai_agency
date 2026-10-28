#!/usr/bin/env python3
"""
=====================================================================
🤖 SOFÍA AI AGENCY - CENTINELA DESKTOP PARA EXCEL LOCAL (WINDOWS / PC)
=====================================================================
Monitorea silenciosamente un archivo de Excel (.xlsx / .xls / .csv)
en la PC de la secretaría o negocio. Cada vez que la secretaria guarda
el archivo, el centinela lee las filas nuevas y las envía al servidor
de Sofía en Render en tiempo real.
=====================================================================
"""

import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.error

# Intentar importar pandas u openpyxl si están disponibles
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

def _format_cell_value(v):
    """Normaliza objetos fecha/hora de Excel a texto legible DD/MM/YYYY o HH:MM."""
    if v is None:
        return None
    if hasattr(v, "strftime"):
        if hasattr(v, "hour") and not hasattr(v, "year"):
            return v.strftime("%H:%M")
        if hasattr(v, "hour") and (v.hour != 0 or v.minute != 0):
            return v.strftime("%d/%m/%Y %H:%M")
        return v.strftime("%d/%m/%Y")
    return v

def read_excel_rows(file_path):
    """Lee filas de un archivo Excel o CSV y las devuelve como lista de diccionarios."""
    if not os.path.exists(file_path):
        return []

    ext = os.path.splitext(file_path)[1].lower()
    
    # 1. Lectura con pandas (si está instalado)
    if HAS_PANDAS:
        try:
            if ext in [".xlsx", ".xls"]:
                df = pd.read_excel(file_path)
            elif ext == ".csv":
                df = pd.read_csv(file_path)
            else:
                return []
            
            df = df.dropna(how="all")
            for col in df.select_dtypes(include=['datetime', 'datetimetz']).columns:
                df[col] = df[col].dt.strftime('%d/%m/%Y %H:%M')
            
            records = df.where(pd.notnull(df), None).to_dict(orient="records")
            for row in records:
                for k, v in list(row.items()):
                    row[k] = _format_cell_value(v)
            return records
        except Exception as e:
            print(f"⚠️ Error al leer con pandas: {e}")

    # 2. Lectura nativa de .xlsx con openpyxl (liviano y estándar)
    if ext == ".xlsx" and HAS_OPENPYXL:
        try:
            wb = openpyxl.load_workbook(file_path, data_only=True)
            ws = wb.active
            rows_iter = list(ws.iter_rows(values_only=True))
            wb.close()
            if len(rows_iter) < 2:
                return []
            headers = [str(h).strip() if h is not None else f"col_{i}" for i, h in enumerate(rows_iter[0])]
            records = []
            for r in rows_iter[1:]:
                if not any(cell is not None and str(cell).strip() != "" for cell in r):
                    continue
                row_dict = {}
                for idx, h in enumerate(headers):
                    val = r[idx] if idx < len(r) else None
                    row_dict[h] = _format_cell_value(val)
                records.append(row_dict)
            return records
        except Exception as e:
            print(f"⚠️ Error al leer con openpyxl: {e}")

    # 3. Fallback sin dependencias para .csv
    try:
        import csv
        if ext == ".csv":
            with open(file_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                return [row for row in reader if any(row.values())]
    except Exception as e:
        print(f"⚠️ Error en lectura fallback: {e}")

    return []

def send_to_sofia(server_url, tenant_slug, rows):
    """Envía las filas leídas al servidor de Sofía."""
    endpoint = f"{server_url.rstrip('/')}/api/v1/sync/{tenant_slug}"
    payload = {
        "source": "desktop_excel",
        "rows": rows
    }
    
    data_bytes = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "SofiaDesktopSync/1.0"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                res = json.loads(resp.read().decode("utf-8"))
                return True, res
            return False, f"HTTP Status {resp.status}"
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            return False, err_data.get("detail", str(e))
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, str(e)

def get_base_dir():
    """Retorna el directorio base del script o del ejecutable empaquetado con PyInstaller."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def load_or_create_config(base_dir, config_name="centinela_config.json"):
    """Carga la configuración desde JSON o crea una plantilla si no existe."""
    config_path = os.path.join(base_dir, config_name)
    default_cfg = {
        "tenant_slug": "clinica_alvear",
        "excel_file": "Turnos.xlsx",
        "server_url": "https://sofia-ai-agency.onrender.com",
        "check_interval_seconds": 2
    }
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data, config_path
        except Exception as e:
            print(f"⚠️ Aviso: Error al leer {config_path}: {e}. Usando valores por defecto.")
            return default_cfg, config_path
    
    # Si no existe, creamos la plantilla por defecto
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_cfg, f, indent=4, ensure_ascii=False)
        print(f"📄 Se generó el archivo de configuración inicial en: {config_path}")
    except Exception as e:
        print(f"⚠️ No se pudo guardar plantilla de configuración: {e}")
        
    return default_cfg, config_path

def main():
    base_dir = get_base_dir()
    cfg, config_path = load_or_create_config(base_dir)

    parser = argparse.ArgumentParser(description="Centinela Sofía Desktop - Sincronizador de Excel Local")
    parser.add_argument("--file", "-f", required=False, default=None,
                        help="Ruta al archivo de Excel a monitorear (ej: Turnos.xlsx)")
    parser.add_argument("--slug", "-s", required=False, default=None,
                        help="Slug o identificador del negocio en Sofía (ej: clinica_alvear)")
    parser.add_argument("--server", required=False, default=None,
                        help="URL del servidor de Sofía (defecto: Render Producción)")
    parser.add_argument("--interval", "-i", type=int, required=False, default=None,
                        help="Intervalo de verificación en segundos")
    args = parser.parse_args()

    # Prioridad: argumentos CLI > valores en centinela_config.json > defaults
    slug = args.slug or cfg.get("tenant_slug") or "clinica_alvear"
    server_url = args.server or cfg.get("server_url") or "https://sofia-ai-agency.onrender.com"
    raw_file = args.file or cfg.get("excel_file") or "Turnos.xlsx"
    interval = args.interval or cfg.get("check_interval_seconds") or 2

    # Resolver ruta del archivo (absoluta o relativa a la carpeta del Centinela)
    if os.path.isabs(raw_file):
        file_path = raw_file
    else:
        file_candidate = os.path.join(base_dir, raw_file)
        if os.path.exists(file_candidate):
            file_path = file_candidate
        else:
            file_path = os.path.abspath(raw_file)

    if sys.platform == "win32":
        try:
            os.system(f"title Sofía Centinela - {slug}")
        except Exception:
            pass

    print("\n" + "=" * 65)
    print(" 🤖 SOFÍA DESKTOP SYNC - CENTINELA DE EXCEL EN VIVO")
    print("=" * 65)
    print(f" • Negocio / Tenant: {slug}")
    print(f" • Archivo Excel:    {file_path}")
    print(f" • Configuración:    {config_path}")
    print(f" • Servidor Central: {server_url}")
    print(f" • Intervalo:        Cada {interval} segundos")
    print("-" * 65)
    print("💡 El centinela está activo. Cada vez que guardes el Excel,")
    print("   Sofía actualizará la base de datos automáticamente.\n")

    last_mtime = 0
    file_warned = False

    if os.path.exists(file_path):
        last_mtime = os.path.getmtime(file_path)
        # Sincronización inicial al arrancar
        print("⏳ Ejecutando sincronización inicial...")
        rows = read_excel_rows(file_path)
        if rows:
            ok, res = send_to_sofia(server_url, slug, rows)
            if ok:
                print(f"✅ [Inicio] {res.get('created_count', 0)} creados, {res.get('updated_count', 0)} actualizados.")
            else:
                print(f"⚠️ [Inicio] Aviso: {res}")
        else:
            print("ℹ️ Archivo sin filas de datos por el momento.")
    else:
        print(f"⚠️ El archivo '{os.path.basename(file_path)}' aún no existe en esa ruta.")
        print(f"   El Centinela esperará a que sea colocado o creado allí...\n")
        file_warned = True

    while True:
        try:
            time.sleep(interval)
            if not os.path.exists(file_path):
                if not file_warned:
                    print(f"⚠️ [{time.strftime('%H:%M:%S')}] Esperando que aparezca el archivo: {file_path}")
                    file_warned = True
                continue

            if file_warned:
                print(f"✅ [{time.strftime('%H:%M:%S')}] Archivo detectado: {file_path}")
                file_warned = False

            current_mtime = os.path.getmtime(file_path)
            if current_mtime > last_mtime:
                # El archivo cambió (la secretaria guardó cambios)
                time.sleep(0.5) # Pausa breve para asegurar que el archivo terminó de escribirse
                last_mtime = current_mtime
                t_str = time.strftime("%H:%M:%S")
                print(f"\n⚡ [{t_str}] Cambio detectado en {os.path.basename(file_path)}. Leyendo filas...")

                rows = read_excel_rows(file_path)
                if rows:
                    ok, res = send_to_sofia(server_url, slug, rows)
                    if ok:
                        print(f"✅ [{t_str}] Sincronización Exitosa: {res.get('created_count', 0)} creados, {res.get('updated_count', 0)} actualizados.")
                    else:
                        print(f"❌ [{t_str}] Error al sincronizar: {res}")
                else:
                    print(f"ℹ️ [{t_str}] Archivo guardado sin filas nuevas.")

        except KeyboardInterrupt:
            print("\n🛑 Centinela detenido por el usuario.")
            break
        except Exception as err:
            print(f"⚠️ Error en bucle de centinela: {err}")
            time.sleep(3)

if __name__ == "__main__":
    main()
