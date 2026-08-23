# linkedin-telegram-agent (v1.2.0 - Bilingual Edition)

Agente interactivo de marca personal en LinkedIn impulsado por **Python**, **Google Gemini API**, **Telegram** y **Buffer GraphQL API**.

---

## 🚀 Descripción del Proyecto

Este agente automatiza el flujo completo de creación, revisión y publicación de contenidos técnicos en LinkedIn. Genera matrices semanales bilingües (Español + 🇺🇸 Inglés), permite la aprobación o regeneración en tiempo real desde Telegram y programa automáticamente las publicaciones en Buffer respetando los horarios óptimos de audiencia.

---

## 🏗️ Arquitectura y Flujo de Trabajo

1. **Cold Start & Despertador (`/despierta`):** Comando ultra ligero que levanta la instancia en Render deshabilitando el estado de reposo (*cold start*) sin consumir llamadas a la API de Inteligencia Artificial.
2. **Generación Bilingüe (`/generar`):** Un motor dinámico evalúa los modelos activos de Google Gemini (priorizando la serie *Flash*) y genera 6 publicaciones adaptadas en formato JSON bilingüe (Español + 🇺🇸 English Version).
3. **Validación Interactiva en Telegram:** Muestra una vista previa en Telegram con botones interactivos (*Inline Keyboards*) para **Aprobar**, **Regenerar** opción por opción o **Descartar**.
4. **Programación en Buffer:** Al pulsar **Aprobar**, el bot calcula la fecha exacta del día objetivo a las **09:15 AM CST** (15:15 UTC) y la envía mediante una mutación GraphQL a la API v2 de Buffer.
5. **Webhooks Nativos en la Nube:** Servidor HTTP integrado que registra Webhooks nativos con Telegram, eliminando la necesidad de navegadores o ejecuciones locales.

---

## 🛠️ Variables de Entorno Requeridas

Configura las siguientes variables en Render (o tu entorno `.env` local):

| Variable | Descripción |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN_LINKEDIN` | Token de acceso otorgado por `@BotFather`. |
| `TELEGRAM_CHAT_ID` | ID único de tu usuario para restringir el uso exclusivo del bot. |
| `GEMINI_API_KEY` | API Key otorgada por Google AI Studio. |
| `BUFFER_TOKEN` | Bearer Access Token para autenticación en la API de Buffer. |
| `BUFFER_CHANNEL_ID` | ID del canal de LinkedIn vinculado en Buffer. |
| `RENDER_URL` | URL pública externa de la app en Render (ej. `https://tu-app.onrender.com`). |
| `PORT` | Puerto asignado automáticamente por el entorno de Render (por defecto `8080`). |

---

## 📅 Estructura Temática Semanal

* 📌 **Lunes:** SQL & Optimización de Consultas (SARGability, Planes de Ejecución).
* 📌 **Martes:** Power BI & DAX (Transición de Contexto, Optimización de Modelos).
* 📌 **Miércoles:** ETL & Modelado Dimensional (Star Schema, Surrogate Keys).
* 📌 **Jueves:** Microsoft Fabric & Azure Data Architecture.
* 📌 **Viernes:** Automatización con Python (Pandas, Scripts de Productividad).
* 📌 **Sábado:** Sábado Geek (Cultura pop, cine de culto, lógica o cómics aplicados a datos).

---

## 📝 Formato Bilingüe de Salida

Cada post individual programado en Buffer y LinkedIn sigue una estructura limpia en un solo bloque de publicación:

```text
🚀 [Título y Contenido Técnico en Español]
...
#HashtagsEnEspañol #HashtagsTécnicos

──────────────────────────────
🇺🇸 ENGLISH VERSION
──────────────────────────────

🚀 [Technical Title & Adapted Content in English]
...
#HashtagsInEnglish #TechnicalHashtags
