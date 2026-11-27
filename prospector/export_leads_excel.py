"""
Exportador oficial de base de datos de prospección a Excel (.xlsx y .csv)
Mantiene un registro ordenado y actualizado de todos los comercios para seguimiento y control.
"""
import os
import sys
import csv
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import SessionLocal
from app.models.prospect import Prospect

STATUS_TRANSLATIONS = {
    "pending": "Pendiente de Envío",
    "contacted": "Mensaje Enviado",
    "demo_requested": "Pide Demo / Link",
    "meeting_scheduled": "Pide Hablar con Javier",
    "closed_won": "Venta Cerrada (Cliente)",
    "closed_lost": "No Interesado",
    "baja": "Dado de Baja"
}

STATUS_COLORS = {
    "pending": "F1F5F9",        # Gris claro
    "contacted": "DBEAFE",      # Azul suave
    "demo_requested": "FEF08A",  # Amarillo suave
    "meeting_scheduled": "FDE047", # Amarillo fuerte / Alerta
    "closed_won": "BBF7D0",     # Verde suave
    "closed_lost": "FEE2E2",    # Rojo suave
    "baja": "E2E8F0"            # Gris oscuro
}

def export_leads_to_excel(output_path: str = "control_prospeccion_actualizador.xlsx") -> str:
    """Exports all actualizador_pro prospects to a clean, styled Excel sheet."""
    db = SessionLocal()
    try:
        leads = db.query(Prospect).filter(
            Prospect.campaign == "actualizador_pro"
        ).order_by(Prospect.id.asc()).all()

        wb = Workbook()
        ws = wb.active
        ws.title = "Comercios Actualizador PRO"

        # Headers
        headers = [
            "ID", "Fecha Carga", "Comercio / Razón Social", "Contacto",
            "Ciudad", "Teléfono WhatsApp", "Email", "Estado Actual",
            "Última Actualización", "Notas / Seguimiento Manual"
        ]
        ws.append(headers)

        # Style header row
        header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws.row_dimensions[1].height = 28

        # Data rows
        for row_idx, lead in enumerate(leads, start=2):
            created_str = lead.created_at.strftime("%d/%m/%Y") if lead.created_at else "-"
            updated_str = lead.updated_at.strftime("%d/%m/%Y %H:%M") if lead.updated_at else "-"
            status_text = STATUS_TRANSLATIONS.get(lead.status, lead.status or "Pendiente")
            status_color = STATUS_COLORS.get(lead.status, "FFFFFF")

            row_data = [
                lead.id,
                created_str,
                lead.name or "S/D",
                lead.contact_name or "Titular / Encargado",
                lead.city or "S/D",
                lead.phone or "-",
                lead.email or "-",
                status_text,
                updated_str,
                "" # Espacio para notas manuales de Javier
            ]
            ws.append(row_data)

            # Style data row
            for col_idx in range(1, len(row_data) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = Font(name="Calibri", size=10)
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")

                # Center align specific columns
                if col_idx in [1, 2, 6, 8, 9]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

                # Color badge for status
                if col_idx == 8:
                    cell.fill = PatternFill(start_color=status_color, end_color=status_color, fill_type="solid")
                    cell.font = Font(name="Calibri", size=10, bold=True, color="1E293B")

            ws.row_dimensions[row_idx].height = 22

        # Auto-fit column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        # Extra width for notes column
        ws.column_dimensions["J"].width = 30

        wb.save(output_path)
        print(f"✅ Excel generado exitosamente con {len(leads)} comercios en: {output_path}")

        # Export CSV copy as well
        csv_path = output_path.replace(".xlsx", ".csv")
        with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for lead in leads:
                created_str = lead.created_at.strftime("%d/%m/%Y") if lead.created_at else "-"
                updated_str = lead.updated_at.strftime("%d/%m/%Y %H:%M") if lead.updated_at else "-"
                status_text = STATUS_TRANSLATIONS.get(lead.status, lead.status or "Pendiente")
                writer.writerow([
                    lead.id,
                    created_str,
                    lead.name or "S/D",
                    lead.contact_name or "Titular / Encargado",
                    lead.city or "S/D",
                    lead.phone or "-",
                    lead.email or "-",
                    status_text,
                    updated_str,
                    ""
                ])
        print(f"✅ Copia CSV generada en: {csv_path}")

        return output_path
    finally:
        db.close()

if __name__ == "__main__":
    export_leads_to_excel()
