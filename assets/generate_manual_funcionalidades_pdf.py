import os
import sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable, Image
)
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and draw total page count
    and clean header/footer on every page.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#64748B'))
        
        # Footer
        footer_text = f"Guía de Funcionalidades & Manual de Uso • Sofía IA • Página {self._pageNumber} de {page_count}"
        self.drawString(1.2 * cm, 0.8 * cm, "Guía Oficial de Uso para el Comercio • Sofía Asistente Comercial")
        self.drawRightString(A4[0] - 1.2 * cm, 0.8 * cm, footer_text)
        
        # Running thin line above footer
        self.setStrokeColor(colors.HexColor('#CBD5E1'))
        self.setLineWidth(0.5)
        self.line(1.2 * cm, 1.1 * cm, A4[0] - 1.2 * cm, 1.1 * cm)
        self.restoreState()


def build_manual_pdf(filename="assets/Manual_Funcionalidades_Sofia.pdf"):
    os.makedirs(os.path.dirname(filename), exist_ok=True)

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.5 * cm
    )

    styles = getSampleStyleSheet()

    # Custom typography hierarchy
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14.5,
        leading=17.5,
        textColor=colors.HexColor('#0F172A'),
        spaceAfter=2
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#4338CA')
    )

    badge_style = ParagraphStyle(
        'Badge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=7.5,
        leading=9.5,
        alignment=2,
        textColor=colors.HexColor('#1E293B')
    )

    h1_section = ParagraphStyle(
        'Heading1Section',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13.5,
        textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=7,
        spaceAfter=3.5
    )

    body_style = ParagraphStyle(
        'BodyCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#334155')
    )

    bold_label = ParagraphStyle(
        'BoldLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#0F172A')
    )

    cmd_style = ParagraphStyle(
        'CmdStyle',
        parent=styles['Normal'],
        fontName='Courier-Bold',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#0369A1')
    )

    action_style = ParagraphStyle(
        'ActionStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#065F46')
    )

    story = []

    # =========================================================================
    # HEADER & LOGO
    # =========================================================================
    logo_path = os.path.join(os.path.dirname(__file__), "sofia_agency_logo.png")
    logo_img = None
    if os.path.exists(logo_path):
        try:
            logo_img = Image(logo_path, width=40, height=40)
        except Exception:
            logo_img = None

    header_text_cell = [
        Paragraph("<b>GUÍA RÁPIDA DE USO & MANUAL DE FUNCIONALIDADES</b>", title_style),
        Paragraph("<b>Sofía IA • Central Inteligente de Compras, Reposición y Ventas para Comercios</b>", subtitle_style),
        Paragraph("WhatsApp Oficial: +54 9 343 572-0312 • Paraná, Entre Ríos, Argentina", body_style)
    ]

    if logo_img:
        t_header = Table([[logo_img, header_text_cell, Paragraph("<b>EDICIÓN OFICIAL 2026</b><br/>GUÍA DEL COMERCIO<br/>100% OPERATIVA", badge_style)]], colWidths=[1.8*cm, 12.8*cm, 4.0*cm])
        t_header.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (1,0), (1,0), 6),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
    else:
        t_header = Table([[header_text_cell, Paragraph("<b>EDICIÓN OFICIAL 2026</b><br/>GUÍA DEL COMERCIO<br/>100% OPERATIVA", badge_style)]], colWidths=[14.6*cm, 4.0*cm])
        t_header.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))

    story.append(t_header)
    story.append(Spacer(1, 3))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#4F46E5'), spaceAfter=5))

    # Highlight Banner
    banner_text = (
        "<b>🎯 GUÍA PRÁCTICA PARA EL COMERCIANTE:</b> Órdenes de voz y texto para sacarle el máximo provecho a Sofía en tu día a día, "
        "con <b>Sofía Bridge</b> (conector que escribe en vivo en tu Microsoft Excel de mostrador sin tocar el teclado) y los 4 blindajes "
        "automáticos de seguridad comercial que protegen a tu negocio de errores en compras y listas desactualizadas."
    )
    t_banner = Table([[Paragraph(banner_text, ParagraphStyle('Banner', parent=body_style, fontSize=7.5, leading=10, textColor=colors.HexColor('#1E1B4B')))]], colWidths=[18.6*cm])
    t_banner.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#EEF2FF')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#6366F1')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_banner)
    story.append(Spacer(1, 5))

    # =========================================================================
    # CAPÍTULO 1: COMANDOS CLAVE DE VOZ Y TEXTO (TABLA PRINCIPAL)
    # =========================================================================
    story.append(Paragraph("<b>📋 CAPÍTULO 1: COMANDOS CLAVE DE VOZ Y TEXTO (DÍA A DÍA)</b>", h1_section))

    table_data = [
        [
            Paragraph("<b>OPERACIÓN / ACCIÓN</b>", bold_label),
            Paragraph("<b>QUÉ DECIRLE A SOFÍA (EJEMPLOS REALES)</b>", ParagraphStyle('H1', parent=bold_label, textColor=colors.HexColor('#0369A1'))),
            Paragraph("<b>RESPUESTA Y ACCIÓN DE SOFÍA</b>", ParagraphStyle('H2', parent=bold_label, textColor=colors.HexColor('#065F46')))
        ],
        # 1. Anotar faltantes
        [
            Paragraph("<b>Anotar Faltantes</b><br/>(Canasta compartida)", bold_label),
            Paragraph("• <i>«Sofi, anotame 3 cajas de alfajores triples y 5 packs de turrones para Carlos»</i><br/>"
                      "• <i>«Anotá 10 bolsas de harina y 5 cajas de aceite»</i><br/>"
                      "• <i>«Me faltan 4 pinzas y 2 discos de corte para Litoral»</i>", cmd_style),
            Paragraph("Guarda los items en la canasta. Si no especificás proveedor, <b>compara precios y asigna automáticamente al más barato</b> con lista vigente (regla 7 días). Confirma cantidades y subtotal.", action_style)
        ],
        # 2. Consultar pedidos
        [
            Paragraph("<b>Consultar Pedidos</b><br/>(Revisar borradores)", bold_label),
            Paragraph("• <i>«Sofi, ¿qué le tengo anotado a Carlos?»</i><br/>"
                      "• <i>«Mostrame lo de Distribuidora Alem»</i><br/>"
                      "• <i>«Mostrame los pedidos pendientes»</i> / <i>«resumen»</i>", cmd_style),
            Paragraph("Muestra la lista prolija con cantidades, subtotales, semáforo de precios (🟢 fresco / ⚠️ más de 7 días) y total estimado.", action_style)
        ],
        # 3. Despachar Pedido
        [
            Paragraph("<b>Despachar Pedido</b><br/>(Cierre y Remito)", bold_label),
            Paragraph("• <i>«Sofi, pasale el pedido a Carlos»</i><br/>"
                      "• <i>«Mandale el pedido a Distribuidora Alem»</i><br/>"
                      "• <i>«Despachale a Litoral al 3434556677»</i>", cmd_style),
            Paragraph("<b>1)</b> Envía mensaje formal al WhatsApp del preventista.<br/>"
                      "<b>2)</b> Adjunta el <b>Remito formal en PDF</b> con código de orden.<br/>"
                      "<b>3)</b> <b>Vacía el borrador inmediatamente</b> para no duplicar en la próxima reposición.<br/>"
                      "<b>4)</b> Notifica confirmación de despacho al titular.", action_style)
        ],
        # 4. Vaciar / Cancelar Borrador
        [
            Paragraph("<b>Vaciar Borrador</b><br/>(Sin despachar)", bold_label),
            Paragraph("• <i>«Sofi, vaciá el borrador de Carlos»</i><br/>"
                      "• <i>«Limpiá los faltantes de Alem»</i><br/>"
                      "• <i>«Borrá el pedido anotado de Carlos»</i>", cmd_style),
            Paragraph("Elimina de inmediato la mercadería anotada en los servidores del sistema. La canasta queda en 0 sin enviarle ningún mensaje al proveedor.", action_style)
        ],
        # 5. Agendar Proveedor
        [
            Paragraph("<b>Agendar Proveedor</b><br/>(Preventista / Viajante)", bold_label),
            Paragraph("• <i>«Sofi, agendá al preventista Carlos de Arcor al 3434556677»</i><br/>"
                      "• <i>«Anotá a la distribuidora Alem al 3434112233»</i><br/>"
                      "• <i>«Agendá al corredor Martín al 3434889900»</i>", cmd_style),
            Paragraph("Registra empresa, persona y teléfono. <b>Le envía de inmediato un WhatsApp de presentación formal</b> presentándose como la asistente del local para recibir pedidos y listas.", action_style)
        ],
        # 6. Consultas al Preventista
        [
            Paragraph("<b>Pregunta Rápida</b><br/>(Stock / Reparto)", bold_label),
            Paragraph("• <i>«Sofi, preguntale a Carlos si el lunes reparten»</i><br/>"
                      "• <i>«Consultale a Alem si tienen stock de cal»</i>", cmd_style),
            Paragraph("Sofía redacta un mensaje respetuoso y se lo manda al preventista. Cuando el preventista responde (con audio o texto), <b>Sofía te reenvía la respuesta exacta al instante</b>.", action_style)
        ],
        # 7. Cambio de WhatsApp
        [
            Paragraph("<b>Cambio de Teléfono</b><br/>(Preventista)", bold_label),
            Paragraph("• <i>«Sofi, el preventista Carlos de Arcor cambió de número al 3434998877»</i><br/>"
                      "• <i>«Actualizá el número de Distribuidora Alem al 3434...»</i>", cmd_style),
            Paragraph("Actualiza el contacto en el acto para que futuros pedidos y consultas vayan a la nueva línea sin perder el historial ni los precios cargados.", action_style)
        ],
        # 8. Carga de Precios y Sofía Bridge
        [
            Paragraph("<b>Actualizar Precios & Excel</b><br/>(Bridge en Vivo)", bold_label),
            Paragraph("• <i>Reenviar archivo Excel/PDF del viajante por WhatsApp</i>.<br/>"
                      "• <i>«Sofi, subí 15% todo lo de Loma Negra»</i><br/>"
                      "• <i>«Anotá venta: 10 bolsas de cemento a $120.000»</i>", cmd_style),
            Paragraph("Lee las tablas en segundos y actualiza costos. Con <b>Sofía Bridge</b>, escribe directamente en tu Excel abierto en la PC (Efecto Fantasma) y resalta los cambios en pantalla.", action_style)
        ],
        # 9. Cambio de Rubro
        [
            Paragraph("<b>Modo de Comercio</b><br/>(Ferretería / Kiosco)", bold_label),
            Paragraph("• <i>«rubro ferreteria»</i><br/>"
                      "• <i>«rubro kiosco»</i> / <i>«rubro almacen»</i>", cmd_style),
            Paragraph("Cambia el catálogo activo y el vocabulario según el rubro (focos, pinturas, tornillos vs alfajores, galletitas, gaseosas).", action_style)
        ],
        # 10. Multi-Empleado
        [
            Paragraph("<b>Gestión Equipo</b><br/>(Permisos)", bold_label),
            Paragraph("• <i>«Sofi, alta de empleado Martín al 3434112233»</i><br/>"
                      "• <i>«Sofi, autorizá a Martín a despachar pedidos»</i><br/>"
                      "• <i>«Quitar permisos a Martín»</i>", cmd_style),
            Paragraph("Permite que los empleados anoten mercadería desde sus celulares. El despacho formal queda restringido al dueño salvo autorización expresa.", action_style)
        ]
    ]

    t_cmds = Table(table_data, colWidths=[3.2*cm, 7.8*cm, 7.6*cm])
    t_cmds.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F8FAFC')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 2.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2.5),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#F8FAFC')])
    ]))
    story.append(t_cmds)
    story.append(Spacer(1, 8))

    # =========================================================================
    # CAPÍTULO 2: LOS 4 GRANDES BLINDAJES DE SEGURIDAD COMERCIAL
    # =========================================================================
    story.append(KeepTogether([
        Paragraph("<b>🛡️ CAPÍTULO 2: LOS 4 GRANDES BLINDAJES DE SEGURIDAD COMERCIAL</b>", h1_section),
        Paragraph("Para que el comercio opere con absoluta tranquilidad, Sofía cuenta con 4 mecanismos de defensa automáticos:", body_style),
        Spacer(1, 4)
    ]))

    blindajes_data = [
        [
            Paragraph("<b>1. TRIPLE BLINDAJE ANTI-CRUCES DE VIAJANTES</b>", ParagraphStyle('BH1', parent=bold_label, textColor=colors.HexColor('#1E3A8A'))),
            Paragraph("<b>2. VACIADO ATÓMICO POST-DESPACHO</b>", ParagraphStyle('BH2', parent=bold_label, textColor=colors.HexColor('#065F46')))
        ],
        [
            Paragraph("<b>¿Qué pasa si un preventista atiende a varios comercios que usan Sofía?</b><br/>"
                      "• <b>Capa 1 (Citar / Deslizar):</b> Si responde deslizando el mensaje, Sofía sabe exactamente a qué comercio responde.<br/>"
                      "• <b>Capa 2 (Mención de Negocio):</b> Si dice <i>'Para Alem...'</i> o <i>'Decile a Javier...'</i>, Sofía detecta el destinatario.<br/>"
                      "• <b>Capa 3 (Desambiguación Interactiva):</b> Si responde a secas y tiene 2 preguntas abiertas, Sofía frena y le pregunta: <i>«¿Para cuál negocio es tu respuesta? Respondé 1 o 2»</i>. <b>Imposible que se mezclen mensajes.</b>", body_style),
            Paragraph("<b>¿Qué pasa con los faltantes anotados una vez enviados?</b><br/>"
                      "• Vincula automáticamente la persona (<i>Carlos</i>) con la empresa (<i>Distribuidora Alem</i>).<br/>"
                      "• Al despachar el pedido, Sofía <b>vacía y limpia de inmediato el borrador de sus servidores seguros</b> para ambos nombres.<br/>"
                      "• Si 1 segundo después preguntás qué hay anotado, Sofía confirma: <i>«No tenés nada anotado todavía»</i>. <b>Cero riesgo de compras duplicadas.</b>", body_style)
        ],
        [
            Paragraph("<b>3. BLINDAJE ANTE LISTAS EQUIVOCADAS</b>", ParagraphStyle('BH3', parent=bold_label, textColor=colors.HexColor('#991B1B'))),
            Paragraph("<b>4. REGLA DE LOS 7 DÍAS (PRECIOS FRESCOS)</b>", ParagraphStyle('BH4', parent=bold_label, textColor=colors.HexColor('#92400E')))
        ],
        [
            Paragraph("<b>¿Qué pasa si el viajante manda un archivo que no corresponde?</b><br/>"
                      "• Si un viajante de golosinas manda por error una lista de bulonería (0 coincidencias con el catálogo), <b>Sofía frena en el acto la actualización</b>.<br/>"
                      "• Mantiene los precios vigentes 100% intactos y le envía una alerta preventiva al dueño sugiriéndole consultar al viajante.", body_style),
            Paragraph("<b>¿Cómo se controla la inflación y listas viejas?</b><br/>"
                      "• Sofía marca con 🟢 las listas recibidas en los últimos 7 días y con ⚠️ las que tienen más de una semana.<br/>"
                      "• Al despachar a un proveedor con lista vieja, incluye automáticamente una cláusula en el remito: <i>«Por favor confirmar precios vigentes al facturar»</i>.", body_style)
        ]
    ]

    t_blindajes = Table(blindajes_data, colWidths=[9.2*cm, 9.2*cm])
    t_blindajes.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#EFF6FF')),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#ECFDF5')),
        ('BACKGROUND', (0,2), (0,2), colors.HexColor('#FEF2F2')),
        ('BACKGROUND', (1,2), (1,2), colors.HexColor('#FFFBEB')),
        ('BOX', (0,0), (0,1), 1, colors.HexColor('#3B82F6')),
        ('BOX', (1,0), (1,1), 1, colors.HexColor('#10B981')),
        ('BOX', (0,2), (0,3), 1, colors.HexColor('#EF4444')),
        ('BOX', (1,2), (1,3), 1, colors.HexColor('#F59E0B')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(t_blindajes)
    story.append(Spacer(1, 8))

    # =========================================================================
    # CAPÍTULO 3: ROLES, EQUIPO Y ARQUITECTURA MULTI-EMPLEADO
    # =========================================================================
    story.append(KeepTogether([
        Paragraph("<b>👥 CAPÍTULO 3: ROLES DE USUARIO Y CONTROL DE EQUIPO</b>", h1_section),
        Paragraph("Sofía permite que todo el personal del local colabore en el armado de pedidos sin perder el control:", body_style),
        Spacer(1, 4)
    ]))

    roles_data = [
        [
            Paragraph("<b>ROL</b>", bold_label),
            Paragraph("<b>PERMISOS HABILITADOS</b>", bold_label),
            Paragraph("<b>RESTRICCIONES Y CONTROL</b>", bold_label)
        ],
        [
            Paragraph("<b>DUEÑO / TITULAR</b><br/>(Línea Principal)", bold_label),
            Paragraph("• Alta y baja de comercios, proveedores y empleados.<br/>"
                      "• Dictado de faltantes, comparación de precios y despacho de pedidos.<br/>"
                      "• Actualización y blindaje de listas de precios.<br/>"
                      "• Modificación de rubro y directivas comerciales.", body_style),
            Paragraph("Control total del sistema. Recibe notificaciones espejo de cualquier pedido despachado por empleados.", action_style)
        ],
        [
            Paragraph("<b>EMPLEADO / REPOSITOR</b><br/>(Línea Autorizada)", bold_label),
            Paragraph("• Consultar precios de venta y stock al instante.<br/>"
                      "• Dictar faltantes por voz que se suman a la <b>canasta compartida del negocio</b>.<br/>"
                      "• Consultar lo que hay anotado para cada proveedor.", body_style),
            Paragraph("<b>Despacho bloqueado por defecto.</b> Si intenta enviar un pedido formal, Sofía le avisa que requiere autorización del titular.", ParagraphStyle('R2', parent=body_style, textColor=colors.HexColor('#991B1B')))
        ],
        [
            Paragraph("<b>EMPLEADO CON DESPACHO</b><br/>(Encargado / Subencargado)", bold_label),
            Paragraph("• Todo lo anterior + despacho formal de pedidos y remitos PDF a los distribuidores.", body_style),
            Paragraph("Habilitado por el dueño diciendo: <i>«Sofi, autorizá a [Nombre] a despachar pedidos»</i>. Cada envío emite alerta inmediata al dueño.", action_style)
        ]
    ]

    t_roles = Table(roles_data, colWidths=[3.6*cm, 7.8*cm, 7.2*cm])
    t_roles.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_roles)
    story.append(Spacer(1, 8))

    # =========================================================================
    # CAPÍTULO 4: PREGUNTAS FRECUENTES (FAQ DE MOSTRADOR)
    # =========================================================================
    story.append(KeepTogether([
        Paragraph("<b>❓ CAPÍTULO 4: PREGUNTAS FRECUENTES & DUDAS EN MOSTRADOR</b>", h1_section),
        Spacer(1, 2)
    ]))

    faq_items = [
        ("¿El viajante o preventista tiene que instalar alguna aplicación especial?",
         "<b>No, ninguna.</b> El viajante usa su WhatsApp normal de todos los días. Recibe los pedidos como mensajes de texto limpios con el remito formal en PDF adjunto, y responde por audio o texto como si hablara con una persona."),
        
        ("¿Qué pasa si en el local se corta internet o la luz?",
         "<b>Sofía no depende de la computadora del comercio; corre 100% en servidores seguros en la nube.</b> Si tu local se queda sin luz o internet, podés seguir dictándole pedidos o despachando desde tu celular con datos 4G."),
         
        ("¿Cómo sabe Sofía qué proveedor vende cada producto?",
         "Por dos vías: <b>1)</b> Por las listas de precios en Excel o PDF que vas cargando de cada distribuidor. <b>2)</b> Por el dictado explícito cuando decís <i>'anotá para Carlos...'</i>. Sofía recuerda los proveedores históricos y asocia los productos automáticamente."),
         
        ("¿Los demás comercios pueden ver mis costos o a quién le compro?",
         "<b>Absolutamente NO.</b> Tu cuenta opera en un circuito cerrado e independiente. La información de tu comercio, las listas de precios que cargás y tus notas de pedido están 100% aisladas y protegidas bajo estricta confidencialidad comercial: ningún otro negocio puede ver tus costos ni a quién le comprás.")
    ]

    faq_table_data = []
    for q, a in faq_items:
        faq_table_data.append([
            Paragraph(f"<b>P: {q}</b><br/><font color='#334155'>{a}</font>", body_style)
        ])

    t_faq = Table(faq_table_data, colWidths=[18.6*cm])
    t_faq.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FAFAFA')),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0'))
    ]))
    story.append(t_faq)
    story.append(Spacer(1, 10))

    # Final Guarantee Note
    final_note = (
        "<b>📞 SOPORTE & ASISTENCIA AL COMERCIO:</b> Desarrollado por <b>Agencia Sofía IA</b> • "
        "Atención personalizada: <b>Javier Coloma</b>. "
        "Línea oficial WhatsApp: <b>+54 9 343 572-0312</b>."
    )
    t_final = Table([[Paragraph(final_note, ParagraphStyle('Final', parent=body_style, fontSize=7.5, leading=10, textColor=colors.HexColor('#1E3A8A')))]], colWidths=[18.6*cm])
    t_final.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F0FDF4')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#22C55E')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_final)

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"✅ Manual PDF generado exitosamente en: {filename}")

if __name__ == "__main__":
    out_pdf = sys.argv[1] if len(sys.argv) > 1 else "assets/Manual_Funcionalidades_Sofia.pdf"
    build_manual_pdf(out_pdf)
