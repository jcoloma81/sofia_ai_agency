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

def read_excel_rows(file_path):
    """Lee filas de un archivo Excel o CSV y las devuelve como lista de diccionarios."""
    if not os.path.exists(file_path):
        return []

    ext = os.path.splitext(file_path)[1].lower()
    
    if HAS_PANDAS:
        try:
            if ext in [".xlsx", ".xls"]:
                df = pd.read_excel(file_path)
            elif ext == ".csv":
                df = pd.read_csv(file_path)
            else:
                return []
            
            # Limpiar filas completamente vacías
            df = df.dropna(how="all")
            # Convertir fechas a string legible
            for col in df.select_dtypes(include=['datetime', 'datetimetz']).columns:
                df[col] = df[col].dt.strftime('%d/%m/%Y %H:%M')
            
            # Reemplazar NaN por None
            records = df.where(pd.notnull(df), None).to_dict(orient="records")
            # Asegurar que objetos time/date sueltos de Excel se conviertan a string limpio
            for row in records:
                for k, v in list(row.items()):
                    if hasattr(v, "strftime"):
                        # Si es datetime.time (ej. 10:30:00) -> 10:30
                        if hasattr(v, "hour") and not hasattr(v, "year"):
                            row[k] = v.strftime("%H:%M")
                        else:
                            row[k] = v.strftime("%d/%m/%Y")
            return records
        except Exception as e:
            print(f"⚠️ Error al leer con pandas: {e}")

    # Fallback básico si pandas no está instalado
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

def main():
    parser = argparse.ArgumentParser(description="Centinela Sofía Desktop - Sincronizador de Excel Local")
    parser.add_argument("--file", "-f", required=False, default="Turnos.xlsx",
                        help="Ruta al archivo de Excel a monitorear (ej: Turnos.xlsx)")
    parser.add_argument("--slug", "-s", required=False, default="clinica_alvear",
                        help="Slug o identificador del negocio en Sofía (ej: clinica_alvear)")
    parser.add_argument("--server", required=False, default="https://sofia-ai-agency.onrender.com",
                        help="URL del servidor de Sofía (defecto: Render Producción)")
    args = parser.parse_args()

    file_path = os.path.abspath(args.file)
    print("\n" + "=" * 65)
    print(" 🤖 SOFÍA DESKTOP SYNC - CENTINELA DE EXCEL EN VIVO")
    print("=" * 65)
    print(f" • Negocio:          {args.slug}")
    print(f" • Archivo Excel:    {file_path}")
    print(f" • Servidor Central: {args.server}")
    print("-" * 65)
    print("💡 El centinela está activo. Cada vez que guardes el Excel,")
    print("   Sofía actualizará la base de datos automáticamente.\n")

    last_mtime = 0
    if os.path.exists(file_path):
        last_mtime = os.path.getmtime(file_path)
        # Sincronización inicial al arrancar
        print("⏳ Ejecutando sincronización inicial...")
        rows = read_excel_rows(file_path)
        if rows:
            ok, res = send_to_sofia(args.server, args.slug, rows)
            if ok:
                print(f"✅ [Inicio] {res.get('created_count', 0)} creados, {res.get('updated_count', 0)} actualizados.")
            else:
                print(f"⚠️ [Inicio] Aviso: {res}")
        else:
            print("ℹ️ Archivo sin filas de datos por el momento.")

    while True:
        try:
            time.sleep(2) # Verifica cada 2 segundos
            if not os.path.exists(file_path):
                continue

            current_mtime = os.path.getmtime(file_path)
            if current_mtime > last_mtime:
                # El archivo cambió (la secretaria guardó cambios)
                time.sleep(0.5) # Pausa breve para asegurar que el archivo terminó de escribirse
                last_mtime = current_mtime
                t_str = time.strftime("%H:%M:%S")
                print(f"\n⚡ [{t_str}] Cambio detectado en {os.path.basename(file_path)}. Leyendo filas...")

                rows = read_excel_rows(file_path)
                if rows:
                    ok, res = send_to_sofia(args.server, args.slug, rows)
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
