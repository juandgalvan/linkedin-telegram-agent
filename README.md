# linkedin-telegram-agent
Agente interactivo para generación y aprobación de contenido en LinkedIn con Telegram y Gemini API

# Agente Automático de LinkedIn (Telegram + Gemini + Buffer)

Bot de Telegram desarrollado en Python para la generación, revisión y programación automatizada de contenidos profesionales de datos para LinkedIn.

## 🚀 Arquitectura y Flujo de Trabajo

1. **Telegram Interface**: El usuario ejecuta `/generar` para solicitar la matriz semanal de contenidos.
2. **Generación IA (Google Gemini)**: Un cliente dinámico evalúa los modelos disponibles (ej. `gemini-2.0-flash`, `gemini-1.5-flash`) y retorna 6 posts temáticos estructurados en formato JSON.
3. **Validación Interactiva**: Telegram despliega Inline Keyboards con opciones para **Aprobar**, **Regenerar** o **Descartar** cada publicación individualmente.
4. **Programación Automatizada**: Al aprobar, el bot calcula la fecha del próximo día correspondiente (Lunes a Sábado a las 09:00 AM UTC) y la envía a la **API GraphQL v2 de Buffer**.
5. **Despliegue Continuo**: Alojado en Render con un servidor de salud HTTP integrado para garantizar el estado activo en instancias Free.

## 🛠️ Variables de Entorno Requeridas

| Variable | Descripción |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN_LINKEDIN` | Token de acceso del Bot en Telegram. |
| `TELEGRAM_CHAT_ID` | ID de chat permitido para restringir el uso del bot. |
| `GEMINI_API_KEY` | API Key de Google Gemini AI Studio. |
| `BUFFER_TOKEN` | Access Token de la API GraphQL de Buffer. |
| `BUFFER_CHANNEL_ID` | ID del canal de LinkedIn configurado en Buffer. |
| `PORT` | Puerto asignado automáticamente por Render para el Health Check. |

## 📅 Estructura Temática Semanal

* **Lunes**: SQL / Optimización de Consultas.
* **Martes**: Power BI / DAX.
* **Miércoles**: ETL / Modelado Dimensional.
* **Jueves**: Microsoft Fabric / Azure.
* **Viernes**: Automatización con Python.
* **Sábado**: Sábado Geek (Cultura pop, cómics, cine de culto o lógica).
