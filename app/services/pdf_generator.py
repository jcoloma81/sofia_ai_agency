import os
import logging
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
            Paragraph("Encuentra comercios, talleres o empresas afines en tu zona y les escribe de forma automática entre 12 y 15 por día para abrir cuentas nuevas.", body_style)
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
    elements.append(Paragraph("<b>Inversión del Servicio & Retorno:</b>", section_heading))

    pricing_data = [
        [
            Paragraph("<b>Concepto</b>", ParagraphStyle('H1', parent=bullet_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'))),
            Paragraph("<b>Detalle del Servicio</b>", ParagraphStyle('H2', parent=bullet_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'))),
            Paragraph("<b>Inversión</b>", ParagraphStyle('H3', parent=bullet_style, fontName='Helvetica-Bold', textColor=colors.HexColor('#0F172A'), alignment=TA_RIGHT))
        ],
        [
            Paragraph("<b>Setup & Puesta en Marcha</b>", bullet_style),
            Paragraph("Personalización de identidad de Sofía, carga de catálogo/tarifario, integración con la línea de WhatsApp y despliegue del servidor.", body_style),
            Paragraph("<b>$250.000 ARS</b><br/><font size=7 color='#64748B'>Pago único inicial</font>", ParagraphStyle('P1', parent=bullet_style, alignment=TA_RIGHT))
        ],
        [
            Paragraph("<b>Abono Mensual Operativo</b>", bullet_style),
            Paragraph("Operación continua 24/7, procesamiento de audios con IA, servidor en la nube, alertas automáticas y soporte técnico permanente.", body_style),
            Paragraph("<b>$100.000 ARS/mes</b><br/><font size=7 color='#64748B'>Facturación mensual</font>", ParagraphStyle('P2', parent=bullet_style, alignment=TA_RIGHT))
        ]
    ]

    pricing_table = Table(pricing_data, colWidths=[140, 260, 140])
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

if __name__ == "__main__":
    generate_agency_proposal_pdf()
