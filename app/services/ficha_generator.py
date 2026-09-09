import os
import logging
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

logger = logging.getLogger(__name__)

def generate_ficha_alta_pdf(output_path: str = "assets/ficha_alta_cliente.pdf") -> str:
    """
    Generates an executive, printable PDF onboarding sheet for new distributor clients.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=28,
        bottomMargin=28
    )

    styles = getSampleStyleSheet()

    # Colors
    c_primary = colors.HexColor('#0F172A')       # Dark Navy
    c_accent = colors.HexColor('#2563EB')        # Blue
    c_slate = colors.HexColor('#475569')         # Slate
    c_border = colors.HexColor('#94A3B8')        # Border grey
    c_light_bg = colors.HexColor('#F8FAFC')      # Light background
    c_header_bg = colors.HexColor('#0F172A')     # Table header dark

    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=17,
        textColor=c_primary,
        alignment=TA_LEFT
    )

    badge_style = ParagraphStyle(
        'DocBadge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#2563EB'),
        alignment=TA_LEFT
    )

    sec_title_style = ParagraphStyle(
        'SecTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.white
    )

    label_style = ParagraphStyle(
        'FieldLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#1E293B')
    )

    val_style = ParagraphStyle(
        'FieldValue',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#475569')
    )

    note_style = ParagraphStyle(
        'NoteText',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=7,
        leading=9,
        textColor=colors.HexColor('#64748B')
    )

    legal_style = ParagraphStyle(
        'LegalText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=6.8,
        leading=9,
        textColor=colors.HexColor('#475569'),
        alignment=TA_JUSTIFY
    )

    elements = []

    # 1. HEADER (LOGO + TITULO)
    logo_path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "sofia_agency_logo.png")
    logo_img = None
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=44, height=44)
        except Exception:
            logo_img = None

    header_text = [
        Paragraph("<b>SOFÍA AI AGENCY • IMPLEMENTACIÓN EMPRESARIAL</b>", badge_style),
        Paragraph("<b>FICHA DE ALTA DE CLIENTE & RELEVAMIENTO OPERATIVO</b>", title_style),
        Paragraph("Puesta en marcha del Asistente Comercial Autónomo • Entre Ríos & Santa Fe", note_style)
    ]

    if logo_img:
        header_table = Table([[logo_img, header_text]], colWidths=[50, 490])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (1, 0), (1, 0), 10),
            ('PADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(header_table)
    else:
        elements.extend(header_text)

    elements.append(Spacer(1, 4))
    elements.append(HRFlowable(width="100%", thickness=1.5, color=c_accent, spaceBefore=2, spaceAfter=6))

    def make_section_banner(title_text):
        t = Table([[Paragraph(f"<b>{title_text}</b>", sec_title_style)]], colWidths=[540])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), c_header_bg),
            ('TOPPADDING', (0, 0), (-1, -1), 2.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ]))
        return t

    # SECCIÓN 1: DATOS DE LA DISTRIBUIDORA / EMPRESA
    elements.append(make_section_banner("1. DATOS DE LA EMPRESA & FACTURACIÓN"))
    sec1_data = [
        [
            Paragraph("<b>Razón Social / Fantasía:</b>", label_style),
            Paragraph("____________________________________________________", val_style),
            Paragraph("<b>CUIT:</b>", label_style),
            Paragraph("__________________", val_style)
        ],
        [
            Paragraph("<b>Dirección Central / Depósito:</b>", label_style),
            Paragraph("____________________________________________________", val_style),
            Paragraph("<b>Condición IVA:</b>", label_style),
            Paragraph("[  ] RI   [  ] Mono", val_style)
        ],
        [
            Paragraph("<b>Localidad & Provincia:</b>", label_style),
            Paragraph("____________________________________________________", val_style),
            Paragraph("<b>Teléfono / WA:</b>", label_style),
            Paragraph("__________________", val_style)
        ]
    ]
    t_sec1 = Table(sec1_data, colWidths=[130, 240, 80, 90])
    t_sec1.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec1)
    elements.append(Spacer(1, 5))

    # SECCIÓN 2: LIDERAZGO & DESTINATARIOS DE ALERTAS
    elements.append(make_section_banner("2. CONTACTOS CLAVE & RECEPCIÓN DE PEDIDOS"))
    sec2_data = [
        [
            Paragraph("<b>Titular / Gerente Comercial:</b>", label_style),
            Paragraph("Nombre: _________________________", val_style),
            Paragraph("WhatsApp: ____________________", val_style),
            Paragraph("Email: __________________________", val_style)
        ],
        [
            Paragraph("<b>Encargado de Depósito:</b><br/><font size=6 color='#2563EB'>Recibe órdenes en vivo</font>", label_style),
            Paragraph("Nombre: _________________________", val_style),
            Paragraph("WhatsApp: ____________________", val_style),
            Paragraph("[  ] Vía WhatsApp   [  ] Vía Email", val_style)
        ],
        [
            Paragraph("<b>Administración / Facturación:</b>", label_style),
            Paragraph("Nombre: _________________________", val_style),
            Paragraph("WhatsApp: ____________________", val_style),
            Paragraph("Email: __________________________", val_style)
        ]
    ]
    t_sec2 = Table(sec2_data, colWidths=[130, 140, 130, 140])
    t_sec2.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec2)
    elements.append(Spacer(1, 5))

    # SECCIÓN 3: CONFIGURACIÓN DE SOFÍA (WHATSAPP)
    elements.append(make_section_banner("3. CONFIGURACIÓN DEL NÚMERO DE SOFÍA"))
    sec3_data = [
        [
            Paragraph("<b>Línea Telefónica Asignada:</b>", label_style),
            Paragraph("[  ] Chip nuevo provisto por el cliente   [  ] Línea existente a migrar   [  ] Provisto por Agencia", val_style)
        ],
        [
            Paragraph("<b>Número de WhatsApp:</b>", label_style),
            Paragraph("+54 9 _________________________________ (Línea donde operará Sofía)", val_style)
        ],
        [
            Paragraph("<b>Nombre visible en WhatsApp:</b>", label_style),
            Paragraph("Ej: <i>Sofía Distribuciones / Ventas Mayoristas</i>: ____________________________________", val_style)
        ]
    ]
    t_sec3 = Table(sec3_data, colWidths=[140, 400])
    t_sec3.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec3)
    elements.append(Spacer(1, 5))

    # SECCIÓN 4: REGLAS COMERCIALES & POLÍTICA DE DESPACHO
    elements.append(make_section_banner("4. REGLAS COMERCIALES & LOGÍSTICA DE REPARTO"))
    sec4_data = [
        [
            Paragraph("<b>Monto Mínimo Flete Bonificado:</b>", label_style),
            Paragraph("$ ____________________ (Ej: $50.000)", val_style),
            Paragraph("<b>Horario Límite de Pedidos:</b>", label_style),
            Paragraph("______ hs (para reparto siguiente)", val_style)
        ],
        [
            Paragraph("<b>Zonas & Días de Entrega:</b>", label_style),
            Paragraph("Lunes / Miércoles / Viernes: __________________________________________________<br/>"
                      "Martes / Jueves / Sábados: __________________________________________________", val_style),
            Paragraph("<b>Formas de Pago:</b>", label_style),
            Paragraph("[  ] Contado contra entrega<br/>[  ] Transferencia bancaria<br/>[  ] Cheque (Plazo: ___ días)<br/>[  ] Cuenta corriente", val_style)
        ]
    ]
    t_sec4 = Table(sec4_data, colWidths=[140, 210, 110, 80])
    t_sec4.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec4)
    elements.append(Spacer(1, 5))

    # SECCIÓN 5: CATÁLOGO DE PRODUCTOS & ACTUALIZACIÓN DE PRECIOS
    elements.append(make_section_banner("5. CATÁLOGO INICIAL & PROVEEDORES"))
    sec5_data = [
        [
            Paragraph("<b>Formato de la Lista Actual:</b>", label_style),
            Paragraph("[  ] Excel (.xlsx / .csv)   [  ] PDF de fábrica   [  ] Exportación Tango/Bejerman/Zeus   [  ] Google Sheets", val_style)
        ],
        [
            Paragraph("<b>Cantidad aprox. de productos:</b>", label_style),
            Paragraph("[  ] Menos de 100   [  ] 100 a 500   [  ] 500 a 2.000   [  ] Más de 2.000", val_style)
        ],
        [
            Paragraph("<b>Actualización de Aumentos:</b>", label_style),
            Paragraph("El cliente enviará los Excel de aumento directamente al WhatsApp privado de Sofía o por correo electrónico. Sofía recalculará e impactará los nuevos precios de forma automática.", note_style)
        ]
    ]
    t_sec5 = Table(sec5_data, colWidths=[140, 400])
    t_sec5.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec5)
    elements.append(Spacer(1, 5))

    # SECCIÓN 6: PROSPECCIÓN AUTOMÁTICA EN GOOGLE MAPS (OUTBOUND)
    elements.append(make_section_banner("6. RADAR DE PROSPECCIÓN (CAPTACIÓN DE NUEVOS KIOSCOS & ALMACENES)"))
    sec6_data = [
        [
            Paragraph("<b>Zonas / Ciudades Prioritarias:</b>", label_style),
            Paragraph("____________________________________________________________________________", val_style)
        ],
        [
            Paragraph("<b>Comercios a Contactar:</b>", label_style),
            Paragraph("[  ] Kioscos / Maxikioscos   [  ] Almacenes y Despensas   [  ] Autoservicios y Minimarkets   [  ] Gastronomía / Bares", val_style)
        ],
        [
            Paragraph("<b>Ritmo de Contacto Sugerido:</b>", label_style),
            Paragraph("[  ] Moderado: 12-15 comercios/día   [  ] Estándar: 20-25 comercios/día   [  ] Agresivo: 35-40 comercios/día", val_style)
        ]
    ]
    t_sec6 = Table(sec6_data, colWidths=[140, 400])
    t_sec6.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec6)
    elements.append(Spacer(1, 5))

    # SECCIÓN 7: CONDICIONES COMERCIALES & FIRMA
    elements.append(make_section_banner("7. CONDICIONES DEL SERVICIO & PUESTA EN MARCHA"))
    sec7_data = [
        [
            Paragraph("<b>Plan Contratado:</b>", label_style),
            Paragraph("<b>[  ] Plan B2B Distribución & Despacho</b>   [  ] Plan Enterprise Multi-Línea", val_style),
            Paragraph("<b>Puesta en Marcha:</b>", label_style),
            Paragraph("24 a 48 hs hábiles", val_style)
        ],
        [
            Paragraph("<b>Setup Inicial (Única vez):</b>", label_style),
            Paragraph("$ _________________________ (Configuración y carga)", val_style),
            Paragraph("<b>Abono Mensual:</b>", label_style),
            Paragraph("$ _________________ / mes", val_style)
        ],
        [
            Paragraph("<b>Alcance del Servicio:</b>", label_style),
            Paragraph(
                "Incluye operación de Sofía 24/7 sobre WhatsApp, transcripción de notas de voz con IA, "
                "envío de listas de precios actualizadas en Excel, toma de pedidos con cálculo exacto, alerta instantánea a depósito, "
                "radar de prospección automática en Google Maps, hosting de infraestructura y soporte técnico continuo.",
                legal_style
            ),
            Paragraph("", label_style),
            Paragraph("", label_style)
        ]
    ]
    t_sec7 = Table(sec7_data, colWidths=[130, 240, 90, 80])
    t_sec7.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 2.5),
        ('SPAN', (1, 2), (3, 2)),
        ('BACKGROUND', (0, 0), (-1, -1), c_light_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    elements.append(t_sec7)
    elements.append(Spacer(1, 8))

    # FIRMAS
    sig_data = [
        [
            Paragraph("<b>Por la Empresa / Distribuidora:</b><br/><br/><br/>________________________________________<br/>Firma y Aclaración<br/>DNI / Cargo:", label_style),
            Paragraph("<b>Por Sofía AI Agency:</b><br/><br/><br/>________________________________________<br/>Javier Coloma • Director de Operaciones<br/>Sofía AI Agency — Paraná, Entre Ríos", label_style)
        ]
    ]
    t_sig = Table(sig_data, colWidths=[270, 270])
    t_sig.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
    ]))
    elements.append(KeepTogether([t_sig]))

    doc.build(elements)
    logger.info(f"Ficha de alta de cliente generated successfully at {output_path}")
    return output_path

if __name__ == "__main__":
    generate_ficha_alta_pdf()
