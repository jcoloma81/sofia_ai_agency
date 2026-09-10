import os
import logging
from typing import Any, Optional
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

logger = logging.getLogger(__name__)

def generate_agency_proposal_pdf(output_path: str = "assets/propuesta_sofia_ai_agency.pdf") -> str:
    """
    Generates a professional corporate PDF presentation for Sofía AI Agency.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=colors.HexColor('#0F172A'),
        alignment=TA_LEFT
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#6366F1'),
        alignment=TA_LEFT
    )

    section_heading = ParagraphStyle(
        'SectionHeading',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=10,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=13.5,
        textColor=colors.HexColor('#334155')
    )

    bullet_style = ParagraphStyle(
        'BulletStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1E293B')
    )

    box_text_style = ParagraphStyle(
        'BoxText',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#047857')
    )

    elements = []

    # 1. HEADER WITH LOGO
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "sofia_agency_logo.png")
    header_data = []

    logo_img = None
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=64, height=64)
        except Exception:
            logo_img = None

    header_text = [
        Paragraph("<b>SOFÍA AGENCIA DE IA</b>", subtitle_style),
        Paragraph("<b>Soluciones de Automatización Comercial 24/7</b>", title_style),
        Paragraph("Paraná, Entre Ríos • Argentina • WhatsApp: +54 9 343 572-0312", body_style)
    ]

    if logo_img:
        header_table = Table([[logo_img, header_text]], colWidths=[75, 465])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (1, 0), (1, 0), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
    else:
        elements.extend(header_text)

    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#6366F1'), spaceBefore=2, spaceAfter=12))

    # 2. INTRO / PROPUESTA DE VALOR
    elements.append(Paragraph("<b>¿Qué es Sofía y cómo potencia las ventas de tu empresa?</b>", section_heading))
    intro_p = (
        "<b>Sofía no es un chatbot tradicional de respuestas automáticas.</b> Funciona como una "
        "<b>Ejecutiva Comercial Digital (SDR) con Inteligencia Artificial</b> que trabaja en equipo "
        "con tus preventistas y vendedores humanos. Se encarga de hacer todo el trabajo pesado de prospección "
        "en frío, atención de consultas inmediatas y calificación de leads, liberando el tiempo de tu equipo "
        "para que se enfoquen únicamente en cerrar pedidos y facturar."
    )
    elements.append(Paragraph(intro_p, body_style))
    elements.append(Spacer(1, 10))

    # 3. PILARES CLAVE (TABLA CON ICONOS)
    elements.append(Paragraph("<b>Funcionalidades Principales del Sistema:</b>", section_heading))

    features = [
        [
            Paragraph("<b>🎯 Prospección Autónoma en Google Maps</b>", bullet_style),
            Paragraph("Encuentra comercios y empresas de tu interés en la zona y les escribe de forma automática a entre 12 y 15 por día, con el logo de tu empresa, para contactar nuevos clientes.", body_style)
        ],
        [
            Paragraph("<b>📄 Envío Instantáneo de Catálogo / Tarifario en PDF</b>", bullet_style),
            Paragraph("Cuando un cliente pide la lista de precios o catálogo, Sofía se lo envía al instante por WhatsApp, 24 horas al día, 7 días a la semana (incluso feriados).", body_style)
        ],
        [
            Paragraph("<b>🎙️ Comprensión Multimodal de Notas de Voz</b>", bullet_style),
            Paragraph("Escucha audios de WhatsApp enviados por los clientes con modismos argentinos, los interpreta en segundos y responde en texto con total naturalidad.", body_style)
        ],
        [
            Paragraph("<b>🔔 Alertas Instantáneas de Cierre a tu Celular</b>", bullet_style),
            Paragraph("Apenas un cliente pide una cotización o confirma día y hora para una reunión, Sofía envía una alerta automática con todos los datos al celular del titular.", body_style)
        ],
        [
            Paragraph("<b>👤 Control Humano con 1 Clic (Human Takeover)</b>", bullet_style),
            Paragraph("Si un vendedor o el dueño decide responder manualmente desde el teléfono o la web, Sofía se silencia al instante en ese chat para no interferir.", body_style)
        ]
    ]

    feat_table = Table(features, colWidths=[200, 340])
    feat_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(feat_table)
    elements.append(Spacer(1, 12))

    # 4. PLAN DE INVERSIÓN Y COSTOS
    elements.append(Paragraph("<b>Inversión del Servicio — Programa Lanzamiento (Cupo Limitado: 5 Empresas):</b>", section_heading))

    pricing_data = [
        [
            Paragraph("<b>Concepto</b>", ParagraphStyle('H1', parent=bullet_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'))),
            Paragraph("<b>Detalle del Servicio</b>", ParagraphStyle('H2', parent=bullet_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'))),
            Paragraph("<b>Inversión</b>", ParagraphStyle('H3', parent=bullet_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'), alignment=TA_RIGHT))
        ],
        [
            Paragraph("<b>Setup & Puesta en Marcha</b><br/><font size=7.5 color='#059669'><b>✨ 100% BONIFICADO</b></font>", bullet_style),
            Paragraph("Personalización completa de Sofía, carga de catálogo/servicios, integración con la línea de WhatsApp y conexión de alertas.<br/><font size=7 color='#059669'><i>*Beneficio exclusivo para los primeros 5 clientes seleccionados.</i></font>", body_style),
            Paragraph("<strike><font color='#94A3B8'>$250.000 ARS</font></strike><br/><b>$0 ARS</b><br/><font size=7 color='#059669'>Sin costo inicial</font>", ParagraphStyle('P1', parent=bullet_style, alignment=TA_RIGHT))
        ],
        [
            Paragraph("<b>Abono Mensual Operativo</b>", bullet_style),
            Paragraph("Operación continua 24/7, procesamiento de notas de voz con IA, servidor en la nube, alertas automáticas de ventas y soporte técnico.", body_style),
            Paragraph("<b>$70.000 a $100.000 ARS/mes</b><br/><font size=7 color='#64748B'>Según volumen de la empresa</font>", ParagraphStyle('P2', parent=bullet_style, alignment=TA_RIGHT))
        ]
    ]

    pricing_table = Table(pricing_data, colWidths=[140, 250, 150])
    pricing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EEF2F6')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('PADDING', (0, 0), (-1, -1), 7),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(pricing_table)
    elements.append(Spacer(1, 12))

    # 5. CALL TO ACTION BOX
    cta_data = [[
        Paragraph(
            "<b>🎯 Próximo Paso: Coordinar una Demostración Breve de 10 Minutos</b><br/>"
            "<font size=8.5 color='#065F46'>Podemos realizar una demostración práctica (presencial en la zona o virtual) "
            "con los productos o servicios de tu empresa. Nuestro asesor <b>Lucas</b> se pone en contacto puntual para responder cualquier duda.</font>",
            box_text_style
        )
    ]]
    cta_table = Table(cta_data, colWidths=[540])
    cta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#ECFDF5')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#10B981')),
        ('PADDING', (0, 0), (-1, -1), 10),
    ]))
    elements.append(cta_table)

    # Build PDF
    doc.build(elements)
    logger.info(f"Corporate proposal PDF generated successfully at {output_path}")
    return output_path

def generate_remito_pdf(
    client_name: str,
    contact_name: str,
    phone: str,
    city: str,
    order_draft: Any,
    order_number: str = "PED-001",
    output_path: str = None
) -> bytes:
    """
    Generates a formal order / remito PDF document for warehouse preparation or supplier dispatch.
    """
    import io
    from datetime import datetime

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer if output_path is None else output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'RemitoTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0F172A')
    )
    header_right = ParagraphStyle(
        'HeaderRight',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#475569'),
        alignment=TA_RIGHT
    )
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12
    )

    elements = []

    # Header banner
    date_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    hdr_data = [
        [
            Paragraph(f"<b>REMITO / ORDEN DE COMPRA</b><br/><font size=9 color='#64748B'>Sofía Asistente Comercial</font>", title_style),
            Paragraph(f"<b>N° Orden:</b> {order_number}<br/><b>Fecha:</b> {date_str}", header_right)
        ]
    ]
    hdr_table = Table(hdr_data, colWidths=[340, 200])
    hdr_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(hdr_table)
    elements.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#6366F1'), spaceAfter=12))

    # Client / Business info
    info_data = [
        [
            Paragraph(f"<b>Comercio Emisor:</b> {client_name}<br/><b>Contacto:</b> {contact_name}", cell_style),
            Paragraph(f"<b>Teléfono:</b> +{phone}<br/><b>Ubicación:</b> {city}", cell_style)
        ]
    ]
    info_table = Table(info_data, colWidths=[270, 270])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 14))

    # Items Table
    table_rows = [
        [
            Paragraph("<b>Cant.</b>", cell_style),
            Paragraph("<b>Producto / Descripción</b>", cell_style),
            Paragraph("<b>P. Unitario</b>", cell_style),
            Paragraph("<b>Subtotal</b>", cell_style)
        ]
    ]
    for it in getattr(order_draft, "items", []):
        name = it.product.name if hasattr(it, "product") else str(it)
        pres = it.product.presentation if hasattr(it, "product") and it.product.presentation else ""
        desc = f"{name} ({pres})" if pres else name
        subtotal_str = it.formatted_subtotal() if hasattr(it, "formatted_subtotal") else f"${getattr(it, 'subtotal', 0)}"
        unit_str = f"${getattr(it, 'unit_price', 0):,.0f}".replace(",", ".")
        table_rows.append([
            Paragraph(str(getattr(it, "quantity", 1)), cell_style),
            Paragraph(desc, cell_style),
            Paragraph(unit_str, cell_style),
            Paragraph(subtotal_str, cell_style)
        ])

    total_str = order_draft.formatted_total() if hasattr(order_draft, "formatted_total") else "$0"
    table_rows.append([
        Paragraph("", cell_style),
        Paragraph("", cell_style),
        Paragraph("<b>TOTAL ESTIMADO:</b>", cell_style),
        Paragraph(f"<b>{total_str}</b>", cell_style)
    ])

    items_table = Table(table_rows, colWidths=[45, 295, 100, 100])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EEF2F6')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('PADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (2, -1), (-1, -1), colors.HexColor('#F1F5F9')),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 14))

    footer_p = Paragraph(
        "<font size=8 color='#64748B'>* Este documento es un comprobante formal emitido automáticamente mediante Sofía Asistente Comercial. "
        "Favor de confirmar recepción y fecha de entrega al chat emisor.</font>",
        cell_style
    )
    elements.append(footer_p)

    doc.build(elements)
    if output_path is not None:
        with open(output_path, "rb") as f:
            return f.read()
    return buffer.getvalue()

if __name__ == "__main__":
    generate_agency_proposal_pdf()

