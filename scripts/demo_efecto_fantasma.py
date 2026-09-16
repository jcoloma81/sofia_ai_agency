#!/usr/bin/env python3
"""
🪄 DEMO EN VIVO — EFECTO FANTASMA DE SOFÍA BRIDGE
=================================================
Muestra en tiempo real cómo Sofía procesa audios de WhatsApp y
escribe/actualiza una planilla de Excel sin tocar el teclado.
"""

import os
import sys
import time
from datetime import datetime

# Asegurar path al proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.sofia_bridge import ExcelOperator

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_banner():
    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}🪄  SOFÍA BRIDGE — DEMOSTRACIÓN EN VIVO: EL EFECTO FANTASMA{RESET}")
    print(f"{CYAN}======================================================================{RESET}")
    print(f"Simulando lo que ve el comerciante en su pantalla cuando le habla a Sofía.\n")

def run_demo(file_path="ferreteria_demo.xlsx"):
    print_banner()

    # 1. Inicializar / Reiniciar planilla limpia
    if os.path.exists(file_path):
        os.remove(file_path)
    
    print(f"📂 [1/4] Creando planilla demo de mostrador: {BOLD}{file_path}{RESET}...")
    op = ExcelOperator(file_path, highlight=True)
    print(f"   {GREEN}✅ Planilla lista con hojas 'Precios' y 'Ventas'.{RESET}\n")
    time.sleep(1)

    # 2. Simulación Caso 1: Aumento de Precios por audio
    audio_1 = "«Che Sofi, subime 20% el Cemento Loma Negra que aumentó el proveedor y poné stock en 50»"
    print(f"🗣️  {BOLD}[2/4] El comerciante manda este audio a WhatsApp:{RESET}")
    print(f"    {YELLOW}{audio_1}{RESET}")
    print(f"    ⏳ Sofía procesa el audio y emite comando al Bridge local...")
    time.sleep(1.5)

    # Ejecutar cambio
    res_1 = op.update_product(
        search_term="cemento loma negra",
        updates={"precio": 12600, "stock": 50}, # 10500 + 20% = 12600
        sheet_name="Precios"
    )
    print(f"    {GREEN}✨ [EFECTO FANTASMA EXCEL]: {res_1}{RESET}")
    print(f"    🎨 Celdas modificadas resaltadas en {YELLOW}AMARILLO SUAVE{RESET} en la pantalla.\n")
    time.sleep(1.5)

    # 3. Simulación Caso 2: Venta rápida en mostrador por audio
    audio_2 = "«Sofi, anotá venta mostrador: 5 bolsas de Cal Loma Negra a $22.500»"
    print(f"🗣️  {BOLD}[3/4] El comerciante despacha y dicta por voz:{RESET}")
    print(f"    {YELLOW}{audio_2}{RESET}")
    print(f"    ⏳ Sofía procesa y emite orden de asiento...")
    time.sleep(1.5)

    now = datetime.now()
    res_2 = op.append_row(
        values=[
            now.strftime("%d/%m/%Y"),
            now.strftime("%H:%M"),
            "5x Cal Hidratada Loma Negra 25kg (Mostrador)",
            22500
        ],
        sheet_name="Ventas"
    )
    print(f"    {GREEN}✨ [EFECTO FANTASMA EXCEL]: {res_2}{RESET}")
    print(f"    🎨 Fila de venta agregada y resaltada en {GREEN}VERDE SUAVE{RESET}.\n")
    time.sleep(1)

    # 4. Resumen final y apertura
    print(f"{BOLD}{CYAN}======================================================================{RESET}")
    print(f"🎉 {BOLD}¡DEMOSTRACIÓN COMPLETADA CON ÉXITO!{RESET}")
    print(f"Archivo generado: {BOLD}{os.path.abspath(file_path)}{RESET}")
    print(f"Podés abrirlo en tu computadora para ver las celdas coloreadas y las dos hojas.")
    print(f"Comando para abrir en Linux:")
    print(f"   {CYAN}libreoffice {file_path} &{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")

if __name__ == "__main__":
    archivo = sys.argv[1] if len(sys.argv) > 1 else "ferreteria_demo.xlsx"
    run_demo(archivo)
