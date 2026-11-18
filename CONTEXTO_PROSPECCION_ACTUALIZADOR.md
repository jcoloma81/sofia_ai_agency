# 🚀 DOSSIER DE CONTEXTO Y MISIÓN: PROSPECCIÓN B2B SÚPER ACTUALIZADOR PRO

## 📌 1. Visión General del Proyecto
- **Propietario / Fundador:** Javier Coloma.
- **Agencia:** Sofía AI Agency (desplegada en Render: `https://sofia-ai-agency.onrender.com`).
- **Producto:** **Súper Actualizador PRO v2.0** (Software de escritorio en Python para comercios minoristas y mayoristas: cruce masivo de listas de proveedores con IVA/márgenes en 3 segundos + comparador inteligente de compras para detectar el precio más bajo entre distribuidores).

---

## 🛠️ 2. Estado Técnico Actual (100% Verificado y en Producción)
1. **Paquete Portable para Windows:**
   - Ubicación en servidor: `app/static/packages/PAQUETE_INSTALADOR_CLIENTE_SAP_v2.0.zip` (48.8 MB).
   - Validado en máquinas externas sin Python instalado (arranca con `INICIAR_WINDOWS.bat` mediante `motor_windows` Python 3.11 embebido).
   - Errores de sintaxis y compatibilidad con Python 3.11 completamente resueltos y desplegados en Render.
2. **Sistema de Licenciamiento RSA-2048:**
   - La clave privada (`sap_license_private.pem`) vive segura en el servidor de Render.
   - Activación de prueba de 7 días en 1 clic (sin formularios obligatorios).
   - Emisión de licencias PRO definitivas desde el panel móvil.
3. **Centro de Control Móvil para Javier:**
   - Ruta: `https://sofia-ai-agency.onrender.com/generador-movil` (PIN: 9981).
   - Métricas en tiempo real: Descargas del ZIP, Demos activas, Leads de WhatsApp, Licencias PRO vendidas.
   - Botón de emisión y envío de licencia PRO por WhatsApp en 1 toque.
4. **Landing Page Pública:**
   - URL: `https://sofia-ai-agency.onrender.com/actualizador`
   - Descarga directa: `/descargar-actualizador`
   - Formulario opcional de captura de leads para calibración técnica gratuita.
5. **Material Publicitario Generado:**
   - 3 Reels en formato vertical 9:16 (1080x1920) listos en `Descargas/VIDEOS_REELS_ACTUALIZADOR/`:
     - `REEL_1_ACTUALIZADOR_MASIVO.mp4` (27s)
     - `REEL_2_COMPARADOR_PROVEEDORES.mp4` (26s)
     - `REEL_3_COMBO_COMERCIO_PRO.mp4` (30s)

---

## 🎯 3. La Misión de Sofía: La Máquina de Prospección Comercial
Separamos los roles:
- `actualizador_precios_pro` es el **taller de ingeniería del software**.
- `sofia_ai_agency` es la **fuerza comercial automatizada** (Sofía).

### El Embudo de Ventas que Sofía debe ejecutar:
1. **Scraping de Comercios en Google Maps (`prospector/scraper.py`):**
   - Nichos: Ferreterías, buloneras, repuesteras del automotor, pinturerías, casas de sanitarios y distribuidores mayoristas.
   - Mercados:
     - Local: Ciudades de Argentina (Paraná, Santa Fe, Rosario, Córdoba, Buenos Aires, etc.).
     - Internacional: México (Guadalajara, Monterrey, CDMX), Colombia (Bogotá, Medellín), Chile (Santiago), España (Madrid, Barcelona).
   - Datos capturados: Nombre del negocio, WhatsApp/Teléfono (E.164), Email, Dirección.

2. **Prospección por WhatsApp (Estrategia de Máxima Conversión):**
   - **Paso 1: NOTA DE VOZ REAL DE JAVIER:** Enviada como Push-to-Talk (PTT con micrófono verde). Sin frialdad robótica, tono humano y cercano.
   - **Paso 2: VIDEO DEMO:** Enviar el micro-video de 20 segundos del comparador (`REEL_2_COMPARADOR_PROVEEDORES.mp4`) mostrando el ahorro real de dinero.
   - **Paso 3: LLAMADO A LA ACCIÓN:** Enlace directo a la landing page para descargar la prueba gratis de 7 días.

3. **Email Outreach (Canal Secundario):**
   - Correos formales al responsable de compras de los comercios que tengan email público.

4. **Atención y Cierre con IA de Sofía:**
   - Respuestas inteligentes ante dudas técnicas sobre el instalador o los formatos de Excel.
   - Derivación a la pasarela de compra (Mercado Pago para Argentina / Whop o Gumroad en USD para el exterior).
   - Emisión de la licencia PRO permanente.

---

## 🚀 4. Próximos Pasos Inmediatos al Iniciar la Sesión en Sofía:
1. Integrar el archivo de audio real grabado por Javier en el módulo de envíos de WhatsApp.
2. Probar una corrida piloto del scraper de Google Maps en un nicho y ciudad seleccionada.
3. Testear el envío de la secuencia (Audio PTT + Video + Enlace) a un número de prueba antes de lanzar la prospección masiva.
