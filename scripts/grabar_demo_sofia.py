#!/usr/bin/env python3
"""
🎬 DIRECTOR DE DEMO EN VIVO — SOFÍA AI AGENCY & BRIDGE
======================================================
Diseñado para grabar videos de alta conversión (15 a 30 segundos)
para Upwork, LinkedIn y clientes comerciales.

Muestra en vivo:
1. Audio de WhatsApp con aumento de precios -> Celdas en amarillo suave en Excel.
2. Audio de WhatsApp con venta en mostrador -> Registro en verde suave y baja de stock.
3. Consulta móvil de precios y márgenes por WhatsApp al instante.
"""

import os
import sys
import time
import subprocess
from datetime import datetime

# Asegurar path al proyecto
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tools.sofia_bridge import ExcelOperator
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

# Códigos de color ANSI para terminal
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

FILE_PATH = "ferreteria_demo.xlsx"

def setup_pristine_demo_file(file_path):
    """Crea una planilla con diseño profesional, bordes y formatos limpios lista para filmar."""
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass

    wb = openpyxl.Workbook()
    
    # 1. Hoja Precios
    ws = wb.active
    ws.title = "Precios"
    ws.views.sheetView[0].showGridLines = True

    headers = ["Código", "Descripción", "Costo", "Precio Venta", "Stock"]
    ws.append(headers)

    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9")
    )

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    sample_items = [
        ["ART-01", "Cal Hidratada Loma Negra 25kg", 3200, 4500, 25],
        ["ART-02", "Cemento Loma Negra 50kg", 7500, 10500, 40],
        ["ART-03", "Curva PVC 110mm Tigre", 5500, 7800, 15],
        ["ART-04", "Pegamento PVC 125cc Tigre", 2200, 3100, 18],
        ["ART-05", "Lija al Agua Grano 100", 450, 650, 100],
        ["ART-06", "Tornillo Autoperforante T1 (Caja x 100)", 1800, 2600, 60],
        ["ART-07", "Disco de Corte 115mm Tyrolit", 1200, 1800, 30]
    ]

    for row_idx, item in enumerate(sample_items, start=2):
        ws.append(item)
        for col_idx in range(1, 6):
            c = ws.cell(row=row_idx, column=col_idx)
            c.font = Font(name="Segoe UI", size=10)
            c.border = thin_border
            if col_idx in (3, 4):
                c.number_format = "$ #,##0"
                c.alignment = Alignment(horizontal="right")
            elif col_idx in (1, 5):
                c.alignment = Alignment(horizontal="center")

    # Ajuste de anchos
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 38
    ws.column_dimensions["C"].width = 15
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 12

    # 2. Hoja Ventas
    ws_v = wb.create_sheet(title="Ventas")
    ws_v.views.sheetView[0].showGridLines = True
    v_headers = ["Fecha", "Hora", "Detalle de Venta", "Total"]
    ws_v.append(v_headers)
    for col_idx in range(1, len(v_headers) + 1):
        cell = ws_v.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    ws_v.column_dimensions["A"].width = 14
    ws_v.column_dimensions["B"].width = 12
    ws_v.column_dimensions["C"].width = 42
    ws_v.column_dimensions["D"].width = 16

    wb.save(file_path)

def open_file_in_system(file_path):
    """Abre la planilla en el software predeterminado (Excel / LibreOffice)."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(file_path)
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", file_path])
        else:
            # Linux: intentar libreoffice o xdg-open en background
            subprocess.Popen(["xdg-open", file_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"{DIM}[Aviso: Podés abrir {file_path} manualmente si no abrió solo]{RESET}")

def print_whatsapp_card(sender: str, message: str, is_audio: bool = True):
    tag = "🎙️ NOTA DE VOZ WHATSAPP" if is_audio else "💬 MENSAJE WHATSAPP"
    border = "─" * 66
    print(f"\n{GREEN}┌{border}┐{RESET}")
    print(f"{GREEN}│{RESET} {BOLD}{WHITE}{tag} [{sender}]{RESET}")
    print(f"{GREEN}│{RESET} {YELLOW}«{message}»{RESET}")
    print(f"{GREEN}└{border}┘{RESET}")

def run_cinematic_demo(step_mode: bool = False):
    os.system("clear" if os.name == "posix" else "cls")
    
    print(f"{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║     🎬 SOFÍA AI AGENCY — DIRECTOR DE DEMOSTRACIÓN EN VIVO        ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════════╝{RESET}")
    print(f"{WHITE}Preparando la planilla limpia en {BOLD}{FILE_PATH}{RESET}...")
    setup_pristine_demo_file(FILE_PATH)
    time.sleep(0.5)

    print(f"\n{GREEN}✅ Planilla lista para filmar.{RESET}")
    print(f"Abriendo {BOLD}{FILE_PATH}{RESET} en tu pantalla...")
    open_file_in_system(FILE_PATH)

    print(f"\n{BOLD}{MAGENTA}👉 INSTRUCCIONES PARA TU VIDEO DE UPWORK / LINKEDIN:{RESET}")
    print(f"   1. Ubicá la planilla de Excel en la mitad derecha de tu monitor.")
    print(f"   2. Dejá esta terminal en la mitad izquierda (o filmá con el celular directo a la pantalla).")
    print(f"   3. Dale al botón de GRABAR.")

    input(f"\n{BOLD}{CYAN}Presioná ENTER cuando estés listo para comenzar la cuenta regresiva...{RESET}")

    # Cuenta regresiva
    print()
    for i in range(3, 0, -1):
        print(f"{BOLD}{YELLOW}⏱️  Iniciando en {i}... (Prepará la cámara / grabador){RESET}")
        time.sleep(1)
    print(f"{BOLD}{GREEN}🔴 ¡ACCION! GRABANDO DEMO EN VIVO{RESET}\n")
    time.sleep(1)

    op = ExcelOperator(FILE_PATH, highlight=True)

    # -------------------------------------------------------------
    # ACTO 1: AUMENTO DE PRECIOS POR VOZ (EFECTO FANTASMA)
    # -------------------------------------------------------------
    audio_1 = "Che Sofi, subime 20% el Cemento Loma Negra y poné stock en 50 bolsas que llegó el camión"
    print_whatsapp_card("Dueño / Distribuidora", audio_1, is_audio=True)
    
    print(f"   {DIM}🤖 Google Gemini: Transcribiendo nota de voz y extrayendo entidad...{RESET}")
    time.sleep(1.2)
    print(f"   {DIM}⚡ Sofía Bridge: Enviando comando a Excel (Windows COM / openpyxl)...{RESET}")
    time.sleep(1.0)

    res_1 = op.update_product(
        search_term="cemento loma negra",
        updates={"precio": 12600, "stock": 50},  # 10500 + 20% = 12600
        sheet_name="Precios"
    )
    print(f"   {GREEN}✨ [EXCEL EN VIVO IMPACTADO]:{RESET} {BOLD}{res_1}{RESET}")
    print(f"   {YELLOW}🎨 Celdas coloreadas en AMARILLO SUAVE en la pantalla del comerciante.{RESET}")

    if step_mode:
        input(f"\n{DIM}[Presioná ENTER para pasar al Acto 2 (Venta mostrador)...]{RESET}")
    else:
        time.sleep(3.5)

    # -------------------------------------------------------------
    # ACTO 2: VENTA RÁPIDA DE MOSTRADOR POR AUDIO
    # -------------------------------------------------------------
    audio_2 = "Sofi, anotá venta mostrador: 5 bolsas de Cal Loma Negra por $22.500 al contado"
    print_whatsapp_card("Cajero / Repositor", audio_2, is_audio=True)

    print(f"   {DIM}🤖 Google Gemini: Detectando registro de ticket de venta...{RESET}")
    time.sleep(1.2)
    print(f"   {DIM}⚡ Sofía Bridge: Asentando en libro 'Ventas' y descontando stock...{RESET}")
    time.sleep(1.0)

    now = datetime.now()
    res_2 = op.append_row(
        values=[
            now.strftime("%d/%m/%Y"),
            now.strftime("%H:%M"),
            "5x Cal Hidratada Loma Negra 25kg (Contado Mostrador)",
            22500
        ],
        sheet_name="Ventas"
    )
    # Actualizar también stock de la cal
    op.update_product("cal hidratada", {"stock": 20}, sheet_name="Precios")

    print(f"   {GREEN}✨ [EXCEL EN VIVO IMPACTADO]:{RESET} {BOLD}{res_2}{RESET}")
    print(f"   {GREEN}🎨 Fila de venta registrada y resaltada en VERDE SUAVE. Stock actualizado.{RESET}")

    if step_mode:
        input(f"\n{DIM}[Presioná ENTER para pasar al Acto 3 (Consulta de bolsillo)...]{RESET}")
    else:
        time.sleep(3.5)

    # -------------------------------------------------------------
    # ACTO 3: CONSULTA MÓVIL DE BOLSILLO (POCKET PRICE)
    # -------------------------------------------------------------
    pregunta_3 = "¿A cuánto tenemos la caja de tornillos T1 y cuánto stock nos queda?"
    print_whatsapp_card("Dueño desde la calle", pregunta_3, is_audio=False)

    print(f"   {DIM}⚡ Sofía: Búsqueda difusa (Fuzzy Matching) en catálogo instantáneo...{RESET}")
    time.sleep(0.8)

    respuesta_sofia = (
        "📊 *Tornillo Autoperforante T1 (Caja x 100)*\n"
        "• Costo: $1.800 | Venta: $2.600\n"
        "• Margen comercial: +44.4%\n"
        "• Stock disponible: 60 cajas\n"
        "¿Querés que te prepare un remito o actualice el precio?"
    )
    print(f"\n{CYAN}┌──────────────────────────────────────────────────────────────────┐{RESET}")
    print(f"{CYAN}│ 📱 RESPUESTA DE SOFÍA EN WHATSAPP (< 1 segundo)                 │{RESET}")
    for line in respuesta_sofia.split("\n"):
        print(f"{CYAN}│{RESET} {WHITE}{line:<64}{RESET}{CYAN}│{RESET}")
    print(f"{CYAN}└──────────────────────────────────────────────────────────────────┘{RESET}")

    time.sleep(2.5)

    # -------------------------------------------------------------
    # CIERRE DE LA DEMO
    # -------------------------------------------------------------
    print(f"\n{BOLD}{GREEN}======================================================================{RESET}")
    print(f"🎉 {BOLD}¡CORTE! DEMOSTRACIÓN FINALIZADA CON ÉXITO.{RESET}")
    print(f"{GREEN}======================================================================{RESET}")
    print(f"Archivo modificado: {BOLD}{os.path.abspath(FILE_PATH)}{RESET}")
    print(f"Ambas hojas ('Precios' y 'Ventas') tienen los cambios y los colores listos.")
    print(f"¡Este video de 25 segundos es tu pasaporte directo para cerrar contratos en Upwork!\n")

if __name__ == "__main__":
    is_step = "--step" in sys.argv
    run_cinematic_demo(step_mode=is_step)
