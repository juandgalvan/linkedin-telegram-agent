import os
import json
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from google import genai
from google.genai import types

# Configuración de logs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Carga de variables de entorno (Render)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_LINKEDIN") or os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BUFFER_TOKEN = os.environ.get("BUFFER_TOKEN")
BUFFER_CHANNEL_ID = os.environ.get("BUFFER_CHANNEL_ID")

# Cliente Gemini
client = genai.Client(api_key=GEMINI_API_KEY)

def enviar_a_buffer(texto: str) -> dict:
    """Envía la publicación aprobada a la cola de Buffer."""
    url = "https://api.bufferapp.com/1/updates/create.json"
    payload = {
        "access_token": BUFFER_TOKEN,
        "profile_ids[]": BUFFER_CHANNEL_ID,
        "text": texto,
        "now": False
    }
    res = requests.post(url, data=payload)
    return res.json()

async def comando_generar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera la parrilla semanal y envía los posts con botones interactivos."""
    chat_id = str(update.effective_chat.id)
    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        await update.message.reply_text("⛔ No tienes autorización para usar este bot.")
        return

    await update.message.reply_text("🧠 *Generando la matriz semanal de LinkedIn con Gemini... Espere un momento.*", parse_mode="Markdown")

    prompt = """
    Actúa como un Especialista Senior en Datos. Genera 6 publicaciones profesionales para LinkedIn (Lunes a Sábado).
    Estructura temática:
    - Lunes: SQL / Optimización.
    - Martes: Power BI / DAX.
    - Miércoles: ETL / Modelado Dimensional.
    - Jueves: Microsoft Fabric / Azure.
    - Viernes: Automatización Python.
    - Sábado: Sábado Geek (Cultura pop, cómics, cine de culto, tecnología o lógica).

    Devuelve STRICTAMENTE un JSON con este formato:
    [
      {"dia": "Lunes", "tema": "SQL", "post": "Contenido completo..."},
      {"dia": "Martes", "tema": "Power BI", "post": "Contenido completo..."},
      {"dia": "Miércoles", "tema": "ETL", "post": "Contenido completo..."},
      {"dia": "Jueves", "tema": "Microsoft Fabric", "post": "Contenido completo..."},
      {"dia": "Viernes", "tema": "Python", "post": "Contenido completo..."},
      {"dia": "Sábado", "tema": "Sábado Geek", "post": "Contenido completo..."}
    ]
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        posts = json.loads(response.text)
        context.user_data['posts'] = {i: p for i, p in enumerate(posts)}

        for index, item in enumerate(posts):
            mensaje = f"📌 *{item['dia'].upper()}* ({item['tema']})\n\n{item['post']}"
            keyboard = [
                [
                    InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar_{index}"),
                    InlineKeyboardButton("❌ Descartar", callback_data=f"descartar_{index}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(mensaje, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"❌ Error al generar la matriz: {str(e)}")

async def manejar_botones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja los clics en los botones de Aprobar o Descartar."""
    query = update.callback_query
    await query.answer()

    accion, index_str = query.data.split("_")
    index = int(index_str)
    posts = context.user_data.get('posts', {})
    post_item = posts.get(index)

    if accion == "aprobar":
        if post_item:
            res = enviar_a_buffer(post_item['post'])
            if 'errors' not in res:
                await query.edit_message_text(f"✅ *APROBADO Y ENVIADO A BUFFER*\n\n{query.message.text}", parse_mode="Markdown")
            else:
                await query.edit_message_text(f"❌ *ERROR BUFFER:* {res}\n\n{query.message.text}")
        else:
            await query.edit_message_text("⚠️ No se encontró la información del post.")

    elif accion == "descartar":
        await query.edit_message_text(f"🗑️ *POST DESCARTADO*\n\n~{query.message.text}~", parse_mode="Markdown")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("generar", comando_generar))
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    print("🤖 Bot de LinkedIn escuchando peticiones en Telegram...")
    app.run_polling()
