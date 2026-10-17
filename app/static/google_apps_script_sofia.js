/**
 * =====================================================================
 * 🤖 SOFÍA AI AGENCY - CONECTOR AUTÓNOMO PARA GOOGLE SHEETS
 * =====================================================================
 * Instrucciones de instalación para la secretaria / clínica:
 * 1. Abrí tu planilla de Google Sheets.
 * 2. En el menú superior, andá a: Extensiones > Apps Script.
 * 3. Borrá cualquier código que aparezca y pegá este archivo completo.
 * 4. Cambiá la variable TENANT_SLUG con el identificador de tu negocio (ej. 'clinica_alvear').
 * 5. Hacé clic en Guardar (icono de disquete) y recargá la planilla.
 * ¡Listo! Aparecerá un menú arriba llamado "🤖 Sofía AI" y se sincronizará automáticamente.
 * =====================================================================
 */

// ⚙️ CONFIGURACIÓN DE TU NEGOCIO:
const TENANT_SLUG = "clinica_alvear"; // Reemplazar con el slug de tu negocio
const SOFIA_SERVER_URL = "https://sofia-ai-agency.onrender.com"; // Servidor oficial de Sofía

/**
 * Crea el menú en Google Sheets al abrir la planilla
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu("🤖 Sofía AI")
    .addItem("⚡ Sincronizar Ahora con Sofía", "sincronizarConSofia")
    .addItem("❓ Ver Estado de Conexión", "verEstadoConexion")
    .addToUi();
}

/**
 * Función principal que lee las filas de la planilla y las envía a Sofía
 */
function sincronizarConSofia() {
  const sheet = SpreadsheetApp.getActiveSheet();
  const data = sheet.getDataRange().getDisplayValues();

  if (data.length < 2) {
    SpreadsheetApp.getUi().alert("⚠️ La planilla no tiene datos suficientes para sincronizar.");
    return;
  }

  // Primera fila como encabezados
  const headers = data[0].map(h => String(h).toLowerCase().trim());
  const rows = [];

  for (let i = 1; i < data.length; i++) {
    const row = data[i];
    // Ignorar filas totalmente vacías
    if (!row.some(cell => String(cell).trim() !== "")) continue;

    const rowObj = {};
    headers.forEach((h, idx) => {
      rowObj[h] = row[idx];
    });
    rows.push(rowObj);
  }

  if (rows.length === 0) {
    SpreadsheetApp.getUi().alert("⚠️ No se encontraron filas con datos.");
    return;
  }

  const endpoint = SOFIA_SERVER_URL + "/api/v1/sync/" + TENANT_SLUG;
  const payload = {
    source: "google_sheets",
    rows: rows
  };

  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(endpoint, options);
    const code = response.getResponseCode();
    const result = JSON.parse(response.getContentText());

    if (code === 200 && result.status === "success") {
      const msg = "✅ Sincronización Exitosa con Sofía!\n\n" +
                  "• Registros leídos: " + result.records_received + "\n" +
                  "• Creados: " + result.created_count + "\n" +
                  "• Actualizados: " + result.updated_count + "\n\n" +
                  "Sofía ya tiene la agenda al día con recordatorios programados.";
      SpreadsheetApp.getUi().alert(msg);
    } else {
      SpreadsheetApp.getUi().alert("❌ Error al sincronizar: " + (result.detail || response.getContentText()));
    }
  } catch (err) {
    SpreadsheetApp.getUi().alert("❌ Error de conexión con el servidor de Sofía:\n" + err.toString());
  }
}

/**
 * Verifica si el servidor de Sofía está en línea
 */
function verEstadoConexion() {
  try {
    const response = UrlFetchApp.fetch(SOFIA_SERVER_URL + "/health", { muteHttpExceptions: true });
    if (response.getResponseCode() === 200) {
      SpreadsheetApp.getUi().alert("🟢 Servidor de Sofía Online y operando correctamente.");
    } else {
      SpreadsheetApp.getUi().alert("🟡 Servidor respondió con código: " + response.getResponseCode());
    }
  } catch (err) {
    SpreadsheetApp.getUi().alert("🔴 No se pudo conectar al servidor de Sofía: " + err.toString());
  }
}
