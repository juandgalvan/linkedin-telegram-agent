# ==============================================================================
# BOT DE LINKEDIN & TELEGRAM VIA BUFFER - VERSIÓN 1.2.2 (NON-BLOCKING ASYNC)
# ==============================================================================
# Descripción: Genera matrices de contenido bilingües (Español e Inglés 🇺🇸) 
# para LinkedIn usando Gemini, permite aprobación/regeneración/descarte
# desde Telegram y programa las publicaciones en Buffer.
# Arquitectura: Webhooks nativos + Comando de activación de Cold Start (/despierta).
# Parche v1.2.2: Desacoplamiento asíncrono vía asyncio.to_thread para llamadas LLM.
# Hora de publicación: 09:15 AM CST (15:15 UTC)
# ==============================================================================

import os
import re
import json
import html
import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from google import genai
from google.genai import types

# Configuración de logs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Carga de variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_LINKEDIN") or os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BUFFER_TOKEN = os.environ.get("BUFFER_TOKEN")
BUFFER_CHANNEL_ID = os.environ.get("BUFFER_CHANNEL_ID")
RENDER_URL = os.environ.get("RENDER_URL") or os.environ.get("RENDER_EXTERNAL_URL")
PORT = int(os.environ.get("PORT", 8080))

client = genai.Client(api_key=GEMINI_API_KEY)

DIAS_MAPA = {
    "LUNES": 0,
    "MARTES": 1,
    "MIÉRCOLES": 2,
    "MIERCOLES": 2,
    "JUEVES": 3,
    "VIERNES": 4,
    "SÁBADO": 5,
    "SABADO": 5
}

def obtener_modelos_candidatos() -> list[str]:
    """Consulta la API de Google en tiempo real para obtener modelos Flash activos."""
    candidatos = []
    try:
        for m in client.models.list():
            nombre = m.name.replace("models/", "") if hasattr(m, "name") else str(m)
            nombre_lower = nombre.lower()
            
            if "flash" in nombre_lower and not any(x in nombre_lower for x in ["omni", "experimental", "exp", "preview", "thinking", "lite"]):
                candidatos.append(nombre)
                
        candidatos.sort(reverse=True)
    except Exception as e:
        logging.warning(f"No se pudo listar modelos dinámicamente: {e}")

    if not candidatos:
        candidatos = ["gemini-1.5-flash"]
        
    logging.info(f"Modelos Flash activos detectados: {candidatos}")
    return candidatos

def obtener_fecha_proximo_dia(nombre_dia: str, hora_programada: int = 15, minuto_programado: int = 15) -> str:
    """
    Calcula la fecha ISO 8601 del próximo día especificado.
    Por defecto programa a las 15:15 UTC, que corresponde exactamente a las 09:15 AM hora Centro de México (CST).
    """
    hoy = datetime.now(timezone.utc)
    dia_target = DIAS_MAPA.get(nombre_dia.upper(), 0)
    dias_diferencia = (dia_target - hoy.weekday()) % 7
    if dias_diferencia == 0:
        dias_diferencia = 7  # Programar para la próxima semana si cae hoy
    fecha_target = hoy + timedelta(days=dias_diferencia)
    fecha_target = fecha_target.replace(hour=hora_programada, minute=minuto_programado, second=0, microsecond=0)
    return fecha_target.strftime("%Y-%m-%dT%H:%M:%SZ")

def generar_con_respaldo(prompt: str, json_mode: bool = False):
    """Genera contenido recorriendo los modelos candidatos con reintentos."""
    candidatos = obtener_modelos_candidatos()
    config = types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None
    
    ultimo_error = None

    for modelo in candidatos:
        for intento in range(2):
            try:
                logging.info(f"Intentando generar con modelo: {modelo} (intento {intento+1})")
                if config:
                    res = client.models.generate_content(model=modelo, contents=prompt, config=config)
                else:
                    res = client.models.generate_content(model=modelo, contents=prompt)
                return res, modelo
            except Exception as e:
                ultimo_error = e
                logging.warning(f"Error con modelo {modelo} en intento {intento+1}: {e}")
                time.sleep(2)

    raise ultimo_error

def enviar_a_buffer(texto: str, fecha_iso: str = None) -> dict:
    url = "https://api.buffer.com"
    headers = {
        "Authorization": f"Bearer {BUFFER_TOKEN}",
        "Content-Type": "application/json"
    }
    
    query = """
    mutation CreatePost($channelId: ChannelId!, $text: String!, $dueAt: DateTime, $mode: ShareMode!, $schedulingType: SchedulingType!) {
      createPost(input: {
        channelId: $channelId,
        text: $text,
        dueAt: $dueAt,
        mode: $mode,
        schedulingType: $schedulingType
      }) {
        ... on PostActionSuccess {
          post {
            id
            text
          }
        }
      }
    }
    """
    
    variables = {
        "channelId": BUFFER_CHANNEL_ID,
        "text": texto,
        "schedulingType": "automatic",
        "mode": "customScheduled" if fecha_iso else "addToQueue"
    }
    
    if fecha_iso:
        variables["dueAt"] = fecha_iso

    try:
        res = requests.post(url, headers=headers, json={"query": query, "variables": variables})
        logging.info(f"Respuesta Buffer GraphQL: Status {res.status_code} - Body: {res.text}")
        data = res.json()
        
        if "errors" in data or "message" in data.get("data", {}).get("createPost", {}):
            return {"errors": data}
        return data
    except Exception as e:
        return {"errors": str(e)}

def extraer_dia_de_texto(texto_mensaje: str) -> str:
    """Extrae el nombre del día del encabezado del mensaje de Telegram."""
    for dia in DIAS_MAPA.keys():
        if dia in texto_mensaje.upper():
            return dia
    return "LUNES"

def limpiar_texto_para_buffer(texto_mensaje: str) -> str:
    """Elimina los encabezados decorativos del mensaje de Telegram y limpia HTML antes de enviarlo a Buffer."""
    lineas = texto_mensaje.strip().split("\n")
    if len(lineas) > 1 and ("📌" in lineas[0] or "APROBADO" in lineas[0].upper()):
        texto_limpio = "\n".join(lineas[1:]).strip()
    else:
        texto_limpio = texto_mensaje.strip()
    
    # Sanitización de etiquetas HTML de Telegram para Buffer
    return re.sub(r'<[^>]+>', '', texto_limpio)

async def comando_despierta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando ultra ligero para encender el servidor desde reposo sin consumir API de IA."""
    chat_id = str(update.effective_chat.id)
    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        return
    await update.message.reply_text("🟢 <b>Servidor en línea y preparado. Puedes enviar /generar.</b>", parse_mode="HTML")

async def comando_generar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        await update.message.reply_text("⛔ No tienes autorización para usar este bot.")
        return

    await update.message.reply_text("🧠 <b>Generando matriz de contenidos bilingüe... Espere un momento.</b>", parse_mode="HTML")

    prompt = """
    Actúa como un Especialista Senior en Datos. Genera 6 publicaciones profesionales para LinkedIn (Lunes a Sábado).
    Estructura temática:
    - Lunes: SQL / Optimización.
    - Martes: Power BI / DAX.
    - Miércoles: ETL / Modelado Dimensional.
    - Jueves: Microsoft Fabric / Azure.
    - Viernes: Automatización Python.
    - Sábado: Sábado Geek (Cultura pop, cómics, cine de culto, tecnología o lógica).

    REQUISITO OBLIGATORIO DE FORMATO PARA EL CAMPO "post":
    Cada publicación DEBE ser strictly bilingüe (Español primero, seguido de la versión en Inglés con bandera de EE. UU.), estructurada exactamente así:

    [Título con emoji y tema en Español]

    [Contenido técnico claro y al grano en Español: problema, solución práctica con tips o código breve, y pregunta para generar debate]

    #HashtagsEnEspañol #HashtagsTécnicos

    ──────────────────────────────
    🇺🇸 ENGLISH VERSION
    ──────────────────────────────

    [Título adaptado con emoji en Inglés]

    [Contenido técnico adaptado en Inglés técnico natural, sin traducciones literales, con tips o código y pregunta final]

    #HashtagsInEnglish #TechnicalHashtags

    Devuelve STRICTAMENTE un JSON con este formato:
    [
      {"dia": "Lunes", "tema": "SQL", "post": "Contenido bilingüe completo..."},
      {"dia": "Martes", "tema": "Power BI", "post": "Contenido bilingüe completo..."},
      {"dia": "Miércoles", "tema": "ETL", "post": "Contenido bilingüe completo..."},
      {"dia": "Jueves", "tema": "Microsoft Fabric", "post": "Contenido bilingüe completo..."},
      {"dia": "Viernes", "tema": "Python", "post": "Contenido bilingüe completo..."},
      {"dia": "Sábado", "tema": "Sábado Geek", "post": "Contenido bilingüe completo..."}
    ]
    """

    try:
        # Ejecución no bloqueante en hilo secundario
        response, modelo_usado = await asyncio.to_thread(generar_con_respaldo, prompt, json_mode=True)
        posts = json.loads(response.text)

        for index, item in enumerate(posts):
            dia_limpio = html.escape(str(item['dia']).upper())
            tema_limpio = html.escape(str(item['tema']))
            post_limpio = html.escape(str(item['post']))

            mensaje = f"📌 <b>{dia_limpio}</b> ({tema_limpio})\n\n{post_limpio}"
            keyboard = [
                [
                    InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar_{index}"),
                    InlineKeyboardButton("🔄 Regenerar", callback_data=f"regenerar_{index}_{dia_limpio}_{tema_limpio}"),
                    InlineKeyboardButton("❌ Descartar", callback_data=f"descartar_{index}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(mensaje, reply_markup=reply_markup, parse_mode="HTML")

    except Exception as e:
        await update.message.reply_text(f"❌ Error al generar la matriz: {html.escape(str(e))}", parse_mode="HTML")

async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes = query.data.split("_")
    accion = partes[0]

    if accion == "aprobar":
        texto_pantalla = query.message.text
        texto_final = limpiar_texto_para_buffer(texto_pantalla)
        nombre_dia = extraer_dia_de_texto(texto_pantalla)
        fecha_programada = obtener_fecha_proximo_dia(nombre_dia)

        res = enviar_a_buffer(texto_final, fecha_iso=fecha_programada)
        if 'errors' not in res:
            texto_actual_html = html.escape(texto_pantalla)
            await query.edit_message_text(f"✅ <b>APROBADO Y PROGRAMADO EN BUFFER ({nombre_dia} - 09:15 AM)</b>\n\n{texto_actual_html}", parse_mode="HTML")
        else:
            texto_actual_html = html.escape(texto_pantalla)
            await query.edit_message_text(f"❌ <b>ERROR BUFFER:</b> {html.escape(str(res))}\n\n{texto_actual_html}", parse_mode="HTML")

    elif accion == "regenerar":
        dia = partes[2] if len(partes) > 2 else "DÍA"
        tema = partes[3] if len(partes) > 3 else "DATOS"

        await query.edit_message_text(f"🔄 <b>Regenerando opción bilingüe para {html.escape(dia)} ({html.escape(tema)})...</b>", parse_mode="HTML")
        
        prompt = f"""
        Actúa como Especialista Senior en Datos. Genera un post alternativo profesional para LinkedIn para el día {dia} enfocado en {tema}.

        REQUISITO OBLIGATORIO DE FORMATO:
        El post DEBE ser estrictamente bilingüe estructurado exactamente así:

        [Título con emoji y tema en Español]

        [Contenido técnico en Español: problema, solución práctica con tips o código y pregunta para debate]

        #HashtagsEnEspañol #HashtagsTécnicos

        ──────────────────────────────
        🇺🇸 ENGLISH VERSION
        ──────────────────────────────

        [Título adaptado con emoji en Inglés]

        [Contenido técnico adaptado en Inglés técnico natural, sin traducciones literales]

        #HashtagsInEnglish #TechnicalHashtags

        Devuelve SOLO el texto plano del post bilingüe sin comillas ni JSON adicionales.
        """
        
        try:
            # Ejecución no bloqueante en hilo secundario
            response, modelo_usado = await asyncio.to_thread(generar_con_respaldo, prompt, json_mode=False)
            nuevo_post = response.text.strip()

            dia_limpio = html.escape(str(dia).upper())
            tema_limpio = html.escape(str(tema))
            post_limpio = html.escape(nuevo_post)

            mensaje = f"📌 <b>{dia_limpio}</b> ({tema_limpio})\n\n{post_limpio}"
            keyboard = [
                [
                    InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar_0"),
                    InlineKeyboardButton("🔄 Regenerar", callback_data=f"regenerar_0_{dia_limpio}_{tema_limpio}"),
                    InlineKeyboardButton("❌ Descartar", callback_data=f"descartar_0")
                ]
            ]
            await query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ Error al regenerar: {html.escape(str(e))}", parse_mode="HTML")

    elif accion == "descartar":
        texto_actual_html = html.escape(query.message.text)
        await query.edit_message_text(f"🗑️ <b>POST DESCARTADO</b>\n\n<s>{texto_actual_html}</s>", parse_mode="HTML")

if __name__ == '__main__':
    if not RENDER_URL:
        raise ValueError("Error: Debe configurar la variable de entorno RENDER_URL")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Manejadores de Comandos
    app.add_handler(CommandHandler("despierta", comando_despierta))
    app.add_handler(CommandHandler("generar", comando_generar))
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    # Configuración de ruta segura para Webhook
    webhook_path = f"/telegram/{TELEGRAM_TOKEN}"
    full_webhook_url = f"{RENDER_URL.rstrip('/')}{webhook_path}"
    
    logging.info(f"🤖 Iniciando Bot en modo Webhook en: {full_webhook_url}")
    
    # Arranca el servidor HTTP en el puerto dinámico de Render y registra la URL en Telegram
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=full_webhook_url,
        allowed_updates=Update.ALL_TYPES
    )
