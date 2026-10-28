# 🛡️ Guía de Instalación y Puesta en Marcha: Sofía Centinela Desktop

El **Centinela** es el puente invisible que conecta la planilla de Excel local de una clínica o consultorio con la Inteligencia Artificial de Sofía en la nube (Render). 

Su gran ventaja comercial: **La secretaria sigue trabajando en su Excel de siempre y no tiene que aprender ningún sistema nuevo.**

---

## 📦 ¿Qué contiene el paquete para la clínica?

Una vez compilado, el paquete que llevás a la clínica en un pendrive (o mandás comprimido en `.zip`) tiene solo estos 4 archivos:

| Archivo | Función |
| :--- | :--- |
| **`Sofia_Centinela.exe`** | El motor silencioso que vigila el Excel y envía los cambios. |
| **`centinela_config.json`** | Archivo de configuración simple (nombre de la clínica y del Excel). |
| **`instalar_en_inicio_windows.bat`** | Instalador de 1 doble clic para que arranque solo al prender la PC. |
| **`desinstalar_de_inicio_windows.bat`** | Desinstalador limpio por si algún día se desea remover. |

---

## 🚀 Paso a Paso: Desde la Compilación hasta la Clínica

### Fase 1: Compilar el `.exe` en tu PC con Windows (Solo se hace una vez)

1. En tu computadora con Windows, abrí la carpeta del proyecto.
2. Andá a la carpeta `scripts/` y hacé **doble clic** sobre:
   ```text
   build_centinela_exe.bat
   ```
3. El script automáticamente:
   * Instala `pyinstaller` y `openpyxl` si no los tenías.
   * Compila `sofia_desktop_sync.py` en un único archivo ejecutable.
   * Crea la carpeta `dist/` con todo el paquete listo para usar.
4. **Listo.** Copiá la carpeta `dist/` a tu pendrive o subila a Google Drive.

---

### Fase 2: Configurar los datos de la clínica (30 segundos)

Abrí el archivo `centinela_config.json` con el Bloc de Notas. Vas a ver esto:

```json
{
    "tenant_slug": "clinica_alvear",
    "excel_file": "Turnos.xlsx",
    "server_url": "https://sofia-ai-agency.onrender.com",
    "check_interval_seconds": 2
}
```

Solo tenés que verificar 2 datos:
1. **`tenant_slug`**: El identificador de la clínica en Sofía (ej: `clinica_alvear`, `consultorio_dr_garcia`, etc.).
2. **`excel_file`**: El nombre o la ruta completa del Excel donde la secretaria anota los turnos.
   * Si ponés `"Turnos.xlsx"`, buscará el archivo en la misma carpeta.
   * Si la secretaria lo tiene guardado en el Escritorio o Documentos, podés poner la ruta completa:
     `"C:\\Users\\Secretaria\\Desktop\\Turnos_2026.xlsx"`

Guardás los cambios en el archivo (`Ctrl + G`).

---

### Fase 3: Instalación en la computadora de la clínica

En la computadora de la recepción de la clínica:

1. Creá una carpetita fija para el sistema, por ejemplo en:
   `C:\Sofia_Centinela\`
2. Pegá allí los archivos de la carpeta `dist/`.
3. Hacé **doble clic** en:
   ```text
   instalar_en_inicio_windows.bat
   ```
   * El script creará automáticamente el acceso directo en la carpeta de inicio de Windows.
   * Te preguntará si querés iniciar el Centinela ahora mismo. Presionás **S** (Sí).

#### 💡 Alternativa Manual (si la computadora tiene bloqueado PowerShell):
1. Clic derecho en `Sofia_Centinela.exe` ➡️ **"Crear acceso directo"**.
2. Presionás las teclas **`Windows + R`**.
3. En la ventanita escribís: **`shell:startup`** y presionás Enter.
4. Pegás el acceso directo allí adentro.

---

## 🧪 Cómo probar que está funcionando en vivo

1. Abrí el Excel de la clínica y agregá un turno de prueba:
   * **Paciente:** Tu Nombre
   * **Teléfono:** Tu número real de celular (ej: `3434123456`)
   * **Fecha:** La fecha de mañana
   * **Hora:** `10:00`
   * **Profesional:** Nombre del médico
2. Guardá el archivo en Excel (`Ctrl + G`).
3. En la ventanita del Centinela vas a ver:
   ```text
   ⚡ [14:15:22] Cambio detectado en Turnos.xlsx. Leyendo filas...
   ✅ [14:15:23] Sincronización Exitosa: 1 creados, 0 actualizados.
   ```
4. **¡Listo!** En ese instante el turno ya está en la nube de Sofía y programado para los recordatorios automáticos de WhatsApp.

---

## ❓ Preguntas Frecuentes y Situaciones Reales

* **¿La secretaria tiene que abrir la ventana del Centinela todos los días?**
  No. Como quedó configurado en el Inicio de Windows, cada vez que ella prende la PC a la mañana, el Centinela arranca solo y queda trabajando en segundo plano.
* **¿Qué pasa si la secretaria renombra o mueve de lugar el archivo de Excel?**
  El Centinela mostrará un aviso: *"Esperando a que el archivo sea colocado en la ruta..."*. En cuanto ella vuelva a guardarlo en la ruta indicada en `centinela_config.json`, el Centinela lo retoma de inmediato.
* **¿Qué pasa si se corta la conexión a internet?**
  La secretaria sigue trabajando normalmente en su Excel. Cuando el servicio de internet se restablece y ella vuelve a guardar, el Centinela envía todas las filas acumuladas en un solo paquete.
* **¿Cómo se desinstala si la clínica se da de baja?**
  Simplemente se hace doble clic en `desinstalar_de_inicio_windows.bat` y se borra la carpeta `C:\Sofia_Centinela\`. No deja ningún residuo en el sistema.
