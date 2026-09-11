import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)

def build_pdf(filename="assets/machete_venta_calle.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm
    )

    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=2
    )
    
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#475569')
    )
    
    badge_style = ParagraphStyle(
        'Badge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        alignment=2,
        textColor=colors.HexColor('#1E3A8A')
    )

    h2_style = ParagraphStyle(
        'Heading2Custom',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=8,
        spaceAfter=4
    )

    body_style = ParagraphStyle(
        'BodyCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#1E293B')
    )

    bold_label = ParagraphStyle(
        'BoldLabel',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#0F172A')
    )

    do_style = ParagraphStyle(
        'DoCol',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#0369A1')
    )

    see_style = ParagraphStyle(
        'SeeCol',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor('#065F46')
    )

    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor('#0F172A')
    )

    story = []

    # 1. Header Table
    header_data = [
        [
            Paragraph("<b>MACHETE DE VENTA EN CALLE & DEMO EN VIVO</b>", title_style),
            Paragraph("VERSIÓN 3.0 SUIZA<br/><b>CENTRALIZACIÓN 20 PROVEEDORES</b>", badge_style)
        ],
        [
            Paragraph("Sofía Asistente Comercial • Estrategia Caballo de Troya (Comercio Chico ➔ Mayorista)", subtitle_style),
            Paragraph("<b>AGENCIA SOFÍA IA</b>", badge_style)
        ]
    ]
    t_header = Table(header_data, colWidths=[13*cm, 5*cm])
    t_header.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1E3A8A'), spaceAfter=6))

    # 2. Alert Box
    alert_text = (
        "<b>⚠️ REGLA DE ORO DE CALLE:</b> PROHIBIDO decir 'Inteligencia Artificial' o tecnicismos. "
        "Hablamos en criollo: <i>'Empleada virtual que atiende WhatsApp', 'Actualización de listas en 2 segundos', "
        "'Canasta de pedidos sin papelitos' y 'Rescate de ventas los fines de semana'</i>."
    )
    t_alert = Table([[Paragraph(alert_text, ParagraphStyle('Alert', parent=body_style, fontSize=8, leading=10.5, textColor=colors.HexColor('#991B1B')))]], colWidths=[18.6*cm])
    t_alert.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FEF2F2')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#EF4444')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_alert)
    story.append(Spacer(1, 6))

    # 3. Pricing Grid
    price_data = [
        [
            Paragraph("<b>PLAN COMERCIO CHICO (PUERTA DE ENTRADA) ★</b>", ParagraphStyle('PT1', parent=bold_label, textColor=colors.HexColor('#065F46'))),
            Paragraph("<b>PLAN DISTRIBUIDORA / MAYORISTA</b>", ParagraphStyle('PT2', parent=bold_label, textColor=colors.HexColor('#1E3A8A')))
        ],
        [
            Paragraph("<b>$35.000 ARS / mes</b> ($1.160/día - Menos de 1 alfajor)<br/>Cotizaciones voz a voz 24/7, actualización de precios en vivo, hasta 20 proveedores en un solo chat y canastas de reposición.", body_style),
            Paragraph("<b>$65.000 ARS / mes</b> (Solución Integral B2B)<br/>Multi-sucursal, control de reparto, recepción masiva de pedidos por remito PDF y catálogo mayorista autogestionado.", body_style)
        ]
    ]
    t_price = Table(price_data, colWidths=[9.2*cm, 9.2*cm])
    t_price.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#ECFDF5')),
        ('BACKGROUND', (1,0), (1,-1), colors.HexColor('#F0F9FF')),
        ('BOX', (0,0), (0,-1), 1, colors.HexColor('#10B981')),
        ('BOX', (1,0), (1,-1), 1, colors.HexColor('#0284C7')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t_price)
    story.append(Spacer(1, 6))

    # 4. Bloque 1: Paso a Paso Demo
    story.append(Paragraph("<b>📌 BLOQUE 1: EL PASO A PASO DE LA DEMO EN EL MOSTRADOR</b>", h2_style))
    
    steps_table_data = [
        [
            Paragraph("<b>PASO & ROL</b>", bold_label),
            Paragraph("<b>QUÉ HACES VOS (ACCION)</b>", ParagraphStyle('DH', parent=bold_label, textColor=colors.HexColor('#0369A1'))),
            Paragraph("<b>QUÉ VE EL COMERCIANTE (IMPACTO)</b>", ParagraphStyle('SH', parent=bold_label, textColor=colors.HexColor('#065F46')))
        ],
        [
            Paragraph("<b>PASO 0</b><br/>Alta Flash<br/>(Modo Jefe)", body_style),
            Paragraph("Mandás audio a Sofía: <i>'Sofía, cargar cliente Ferretería Nogoyá, titular Ricardo, cel [número]'</i>.", do_style),
            Paragraph("Sofía confirma en 2 seg. Ricardo ve que su comercio ya quedó registrado sin tocar una PC.", see_style)
        ],
        [
            Paragraph("<b>PASO 1</b><br/>Disparo Demo<br/>(Plantilla A)", body_style),
            Paragraph("Audio a Sofía: <i>'Sofía, mandale la demo a Ricardo con 4 martillos y 2 alicates'</i>.", do_style),
            Paragraph("Suena el celular de Ricardo con la <b>Plantilla A de Meta</b> aprobada, invitándolo a hablar.", see_style)
        ],
        [
            Paragraph("<b>PASO 2</b><br/>Voz a Voz<br/>(Ventana 24h)", body_style),
            Paragraph("Le decís: <i>'Ricardo, mandale un audio a Sofía preguntando precios de esos martillos'</i>.", do_style),
            Paragraph("Ricardo habla, se abre la ventana 24h y Sofía responde con voz cotizando ($14.500 y $11.000).", see_style)
        ],
        [
            Paragraph("<b>PASO 3</b><br/>Aumento Vivo<br/>(Inflación)", body_style),
            Paragraph("<i>'Ricardo, mirá cuando llega lista nueva'</i>. Reenviás a Sofía el Excel con aumento (+20%).", do_style),
            Paragraph("Sofía procesa en 3 seg. Ricardo vuelve a preguntar por audio y Sofía cotiza con aumento ($17.400).", see_style)
        ],
        [
            Paragraph("<b>PASO 4</b><br/>Multi-Canasta<br/>(Despacho)", body_style),
            Paragraph("Carga faltante: <i>'Sofi, anotá para la Bulonera 5 cajas de tornillos T1 y 2 pinzas'</i>. Luego: <i>'Mandale el pedido'</i>.", do_style),
            Paragraph("Suena tu cel con el <b>Remito PDF formal</b> membretado y la canasta de la Bulonera se vacía sola.", see_style)
        ],
        [
            Paragraph("<b>PASO 5</b><br/>Cierre Cero<br/>Riesgo", body_style),
            Paragraph("<b>Pitch:</b> <i>'$35.000/mes ($1.160/día). Se lo dejo instalado 7 días 100% gratis. Si en una semana no le ahorró 2 horas o no rescató ventas, no paga un solo peso.'</i>", ParagraphStyle('PitchMini', parent=bold_label, fontSize=8, leading=10, textColor=colors.HexColor('#B45309'))),
            Paragraph("Cero riesgo. Si no le sirve me dice 'Javier, desconectalo' y amigos como siempre. ¿Lo probamos?", see_style)
        ]
    ]
    t_steps = Table(steps_table_data, colWidths=[2.8*cm, 7.8*cm, 8.0*cm])
    t_steps.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_steps)
    story.append(Spacer(1, 6))

    # 5. Bloque 2: Protocolo Multi-Proveedor
    story.append(Paragraph("<b>📦 BLOQUE 2: PROTOCOLO MULTI-PROVEEDOR (HASTA 20 EN 1 SOLO CHAT)</b>", h2_style))
    supplier_data = [
        [
            Paragraph("<b>1. Alta Automática por Lista (Sin Fricción)</b><br/>Cuando el viajante le manda el Excel o PDF, Don Carlos se lo reenvía a Sofía: <i>'Sofi, lista de Tornillos Centro'</i>. Sofía actualiza los precios y registra al proveedor en el catálogo sin pedirle nada más.", body_style),
            Paragraph("<b>2. Alta al Vuelo por Audio o Contacto</b><br/>Don Carlos le tira un audio: <i>'Sofi, agendá a Roberto de la Bulonera al 343...'</i> o le comparte la tarjeta de contacto de WhatsApp. Sofía lo vincula al instante para futuros pedidos.", body_style)
        ],
        [
            Paragraph("<b>3. Cierre 'Just-In-Time' (Al Despachar)</b><br/>Si Don Carlos anotó faltantes pero nunca pasó el teléfono del proveedor, al pedir <i>'mandale el pedido a...'</i>, Sofía pregunta: <i>'Tengo el remito listo, ¿a qué WhatsApp se lo mando?'</i>. Lo envía y lo guarda.", body_style),
            Paragraph("<b>4. Canastas Independientes e Informes</b><br/>Sofía mantiene hasta 20 carritos separados. Don Carlos consulta cuando quiera: <i>'Sofi, pedidos pendientes a proveedores'</i> o <i>'Sofi, qué tengo para pedirle a Pinturas Litoral'</i>.", body_style)
        ]
    ]
    t_supp = Table(supplier_data, colWidths=[9.2*cm, 9.2*cm])
    t_supp.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_supp)
    story.append(Spacer(1, 6))

    # 6. Bloque 3: Plantillas Oficiales Meta
    story.append(Paragraph("<b>📱 BLOQUE 3: PLANTILLAS OFICIALES META CLOUD API (REGLA 24 HS)</b>", h2_style))
    meta_data = [
        [
            Paragraph("<b>🟢 Plantilla A: Demo a Comercio Chico (Sofía ➔ Ricardo)</b><br/><i>'¡Hola {{1}}! Te escribo de parte de Javier de Sofía. Te envío la demostración solicitada para {{2}}:<br/>• 4x Martillos<br/>• 2x Alicates<br/>Total estimado: A cotizar<br/>Respondé este mensaje para ver cómo cotizo y proceso pedidos en tiempo real.'</i><br/><b>Vars:</b> {{1}}=Ricardo | {{2}}=Ferretería Nogoyá", code_style),
            Paragraph("<b>🔵 Plantilla B: Caballo de Troya (Comercio ➔ Mayorista)</b><br/><i>'ORDEN DE COMPRA FORMAL<br/>Hola {{1}}! Te escribo de parte de {{2}}. Te paso el pedido formal para el reparto:<br/>{{3}}<br/>Total estimado: {{4}}<br/>Por favor confirme recepcion o envie listas de precios a este chat. Muchas gracias!'</i><br/><b>Vars:</b> {{1}}=Distribuidora Alem | {{2}}=Ferretería Nogoyá | {{3}}=Faltantes | {{4}}=A cotizar", code_style)
        ]
    ]
    t_meta = Table(meta_data, colWidths=[9.2*cm, 9.2*cm])
    t_meta.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#EFF6FF')),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#ECFDF5')),
        ('BOX', (0,0), (0,0), 0.5, colors.HexColor('#3B82F6')),
        ('BOX', (1,0), (1,0), 0.5, colors.HexColor('#10B981')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 6))

    # 7. Bloque 4: Objeciones de Mostrador
    story.append(Paragraph("<b>🛡️ BLOQUE 4: OBJECIONES FRECUENTES DEL MOSTRADOR</b>", h2_style))
    obj_data = [
        [
            Paragraph("<b>'Yo me manejo con libretita y papelitos de siempre.'</b>", bold_label),
            Paragraph("<i>'Don Carlos, la libreta no le avisa si la Bulonera aumentó hoy ni le cotiza a un cliente un sábado cuando usted descansa. Sofía se la pasa en limpio y le evita perder plata cobrando precios viejos.'</i>", body_style)
        ],
        [
            Paragraph("<b>'Mis listas son un lío, ninguna viene igual.'</b>", bold_label),
            Paragraph("<i>'Sofía lee cualquier Excel o PDF aunque venga desordenado o con logos. Usted solo reenvía el archivo al WhatsApp y Sofía lo acomoda y actualiza sola.'</i>", body_style)
        ],
        [
            Paragraph("<b>'¿Cuánto me va a costar esto?'</b>", bold_label),
            Paragraph("<i>'Son $35.000 al mes ($1.160 por día). Con un solo alicate o un rollo de cable que Sofía le venda fuera de hora, el sistema ya se pagó todo el mes.'</i>", body_style)
        ]
    ]
    t_obj = Table(obj_data, colWidths=[6.2*cm, 12.4*cm])
    t_obj.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FFFFFF')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_obj)

    doc.build(story)
    print(f"✅ PDF generado exitosamente en: {filename}")

if __name__ == "__main__":
    build_pdf()
