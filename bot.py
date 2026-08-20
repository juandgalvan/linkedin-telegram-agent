import os
import requests
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from google import genai

# Configuración de Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Variables de entorno exactas según tu configuración en Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_LINKEDIN") or os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BUFFER_TOKEN = os.environ.get("BUFFER_TOKEN")
BUFFER_CHANNEL_ID = os.environ.get("BUFFER_CHANNEL_ID")

# Configurar cliente de Gemini
client_gemini = genai.Client(api_key=GEMINI_API_KEY)

# Estructura temporal para almacenar los posts pendientes
POSTS_PENDIENTES = {}

# Días de publicación
DIAS_PUBLICACION = {
    0: "LUNES (SQL)",
    1: "MARTES (PYTHON)",
    2: "MIÉRCOLES (POWER BI / DAX)",
    3: "JUEVES (SQL)",
    4: "VIERNES (PYTHON)"
}

def obtener_siguiente_fecha():
    tz = ZoneInfo('America/Mexico_City')
    ahora = datetime.now(tz)
    
    dias_para_sumar = 1
    siguiente_dt = ahora
    
    while True:
        siguiente_dt = ahora.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=dias_para_sumar)
        if siguiente_dt.weekday() in DIAS_PUBLICACION:
            break
        dias_para_sumar += 1
        
    tema = DIAS_PUBLICACION[siguiente_dt.weekday()]
    fecha_formateada = siguiente_dt.strftime("%Y-%m-%d %H:%M:%S")
    return fecha_formateada, tema

def generar_contenido_gemini(tema: str) -> str:
    prompt = f"""
    Eres un experto creador de contenido técnico y Data Analyst.
    Genera una publicación atractiva para LinkedIn enfocada en el tema del día: {tema}.
    
    Reglas:
    1. Debe ser técnica, profesional pero cercana.
    2. Incluye un ejemplo práctico de código, consulta o buenas prácticas si aplica.
    3. Incluye hashtags relevantes al final (#DataAnalytics #PowerBI #Python #SQL #DataEngineering).
    4. Usa un tono narrativo fluido, profesional y conciso.
    """
    response = client_gemini.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )
    return response.text.strip()

def enviar_a_buffer(texto: str, fecha_formateada: str = None) -> dict:
    url = "https://api.buffer.com"
    headers = {
        "Authorization": f"Bearer {BUFFER_TOKEN}",
        "Content-Type": "application/json"
    }
    
    query = """
    mutation CreatePost($channelId: String!, $text: String!, $scheduledAt: String) {
      createPost(input: {
        channelId: $channelId,
        text: $text,
        scheduledAt: $scheduledAt,
        mode: customScheduled
      }) {
        ... on PostActionSuccess {
          post {
            id
            text
          }
        }
        ... on PostActionError {
          message
        }
      }
    }
    """
    
    variables = {
        "channelId": BUFFER_CHANNEL_ID,
        "text": texto
    }
    
    if fecha_formateada:
        fecha_iso = fecha_formateada.replace(" ", "T") + "Z"
        variables["scheduledAt"] = fecha_iso

    try:
        res = requests.post(url, headers=headers, json={"query": query, "variables": variables})
        logging.info(f"Respuesta Buffer GraphQL: Status {res.status_code} - Body: {res.text}")
        data = res.json()
        
        if "errors" in data or "message" in data.get("data", {}).get("createPost", {}):
            return {"success": False, "error": data}
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def cmd_generar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id=chat_id, text="🧠 Generando matriz de contenidos... Espere un momento.")
    
    fecha, tema = obtener_siguiente_fecha()
    contenido = generar_contenido_gemini(tema)
    
    POSTS_PENDIENTES[chat_id] = {
        "texto": contenido,
        "fecha": fecha,
        "tema": tema
    }
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Aprobar y Programar", callback_data="aprobar_post"),
            InlineKeyboardButton("🔄 Regenerar", callback_data="regenerar_post")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    mensaje = f"📌 **{tema}**\n📅 Programación sugerida: `{fecha}`\n\n---\n\n{contenido}"
    await context.bot.send_message(chat_id=chat_id, text=mensaje, parse_mode="Markdown", reply_markup=reply_markup)

async def manejar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat.id
    data = query.data
    
    if data == "aprobar_post":
        post_info = POSTS_PENDIENTES.get(chat_id)
        if not post_info:
            await query.edit_message_text("❌ No hay ninguna propuesta activa para aprobar.")
            return
            
        await query.edit_message_text("🚀 Enviando propuesta a Buffer vía GraphQL...")
        
        resultado = enviar_a_buffer(post_info["texto"], post_info["fecha"])
        
        if resultado["success"]:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ **¡Publicación programada exitosamente en Buffer!**\n📅 Fecha: `{post_info['fecha']}`",
                parse_mode="Markdown"
            )
            POSTS_PENDIENTES.pop(chat_id, None)
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ **ERROR BUFFER:** `{resultado['error']}`",
                parse_mode="Markdown"
            )
            
    elif data == "regenerar_post":
        await query.edit_message_text("🔄 Regenerando propuesta de contenido...")
        await cmd_generar(update, context)

def main():
    if not TELEGRAM_TOKEN:
        raise ValueError("TELEGRAM_TOKEN o TELEGRAM_BOT_TOKEN_LINKEDIN no está configurado.")
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("generar", cmd_generar))
    app.add_handler(CallbackQueryHandler(manejar_callback))
    
    logging.info("Bot iniciando polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
