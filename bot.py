import os
import json
import html
import time
import logging
import requests
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from google import genai
from google.genai import types

# Servidor de salud para plan Free de Render
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def iniciar_servidor_salud():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# Configuración de logs
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# Carga de variables de entorno
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_LINKEDIN") or os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BUFFER_TOKEN = os.environ.get("BUFFER_TOKEN")
BUFFER_CHANNEL_ID = os.environ.get("BUFFER_CHANNEL_ID")

client = genai.Client(api_key=GEMINI_API_KEY)

def obtener_modelos_candidatos() -> list:
    """Obtiene una lista ordenada de modelos Flash estables para usar como respaldos en caso de error 503."""
    candidatos_base = ["gemini-2.5-flash", "gemini-1.5-flash"]
    try:
        modelos = [m.name.replace("models/", "") for m in client.models.list() if "flash" in m.name.lower() and "gemini" in m.name.lower()]
        estables = [m for m in modelos if not any(x in m for x in ["preview", "exp", "thinking", "lite"])]
        ordenados = sorted(estables, reverse=True)
        if ordenados:
            return ordenados + [m for m in candidatos_base if m not in ordenados]
    except Exception as e:
        logging.warning(f"Error detectando modelos dinámicos: {e}")
    return candidatos_base

def generar_con_respaldo(prompt: str, json_mode: bool = False):
    """Llama a Gemini reintentando con modelos de respaldo si ocurre un error 503 por alta demanda."""
    modelos = obtener_modelos_candidatos()
    config = types.GenerateContentConfig(response_mime_type="application/json") if json_mode else None

    ultimo_error = None
    for modelo in modelos:
        for intento in range(2):  # Reintento rápido por modelo
            try:
                if config:
                    return client.models.generate_content(model=modelo, contents=prompt, config=config), modelo
                else:
                    return client.models.generate_content(model=modelo, contents=prompt), modelo
            except Exception as e:
                ultimo_error = e
                logging.warning(f"Error con modelo {modelo} (intento {intento+1}): {e}")
                time.sleep(1)  # Pausa breve antes de reintentar
    raise ultimo_error

def enviar_a_buffer(texto: str) -> dict:
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
    chat_id = str(update.effective_chat.id)
    if ALLOWED_CHAT_ID and chat_id != str(ALLOWED_CHAT_ID):
        await update.message.reply_text("⛔ No tienes autorización para usar este bot.")
        return

    await update.message.reply_text("🧠 <b>Generando matriz de contenidos... Espere un momento.</b>", parse_mode="HTML")

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
        response, modelo_usado = generar_con_respaldo(prompt, json_mode=True)
        posts = json.loads(response.text)
        if 'posts' not in context.user_data:
            context.user_data['posts'] = {}

        for index, item in enumerate(posts):
            context.user_data['posts'][index] = item
            dia_limpio = html.escape(str(item['dia']).upper())
            tema_limpio = html.escape(str(item['tema']))
            post_limpio = html.escape(str(item['post']))

            mensaje = f"📌 <b>{dia_limpio}</b> ({tema_limpio})\n\n{post_limpio}"
            keyboard = [
                [
                    InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar_{index}"),
                    InlineKeyboardButton("🔄 Regenerar", callback_data=f"regenerar_{index}"),
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

    accion, index_str = query.data.split("_")
    index = int(index_str)
    posts = context.user_data.get('posts', {})
    post_item = posts.get(index)

    if accion == "aprobar":
        if post_item:
            res = enviar_a_buffer(post_item['post'])
            if 'errors' not in res:
                texto_actual = html.escape(query.message.text)
                await query.edit_message_text(f"✅ <b>APROBADO Y ENVIADO A BUFFER</b>\n\n{texto_actual}", parse_mode="HTML")
            else:
                texto_actual = html.escape(query.message.text)
                await query.edit_message_text(f"❌ <b>ERROR BUFFER:</b> {html.escape(str(res))}\n\n{texto_actual}", parse_mode="HTML")
        else:
            await query.edit_message_text("⚠️ No se encontró la información del post.")

    elif accion == "regenerar":
        if post_item:
            await query.edit_message_text(f"🔄 <b>Regenerando opción para {html.escape(post_item['dia'])} ({html.escape(post_item['tema'])})...</b>", parse_mode="HTML")
            prompt = f"Actúa como Especialista Senior en Datos. Genera un post alternativo para LinkedIn sobre el día {post_item['dia']} enfocado en {post_item['tema']}. Devuelve SOLO el texto plano del post."
            
            try:
                response, modelo_usado = generar_con_respaldo(prompt, json_mode=False)
                nuevo_post = response.text.strip()
                post_item['post'] = nuevo_post
                context.user_data['posts'][index] = post_item

                dia_limpio = html.escape(str(post_item['dia']).upper())
                tema_limpio = html.escape(str(post_item['tema']))
                post_limpio = html.escape(nuevo_post)

                mensaje = f"📌 <b>{dia_limpio}</b> ({tema_limpio})\n\n{post_limpio}"
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar_{index}"),
                        InlineKeyboardButton("🔄 Regenerar", callback_data=f"regenerar_{index}"),
                        InlineKeyboardButton("❌ Descartar", callback_data=f"descartar_{index}")
                    ]
                ]
                await query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
            except Exception as e:
                await query.edit_message_text(f"❌ Error al regenerar: {html.escape(str(e))}", parse_mode="HTML")

    elif accion == "descartar":
        texto_actual = html.escape(query.message.text)
        await query.edit_message_text(f"🗑️ <b>POST DESCARTADO</b>\n\n<s>{texto_actual}</s>", parse_mode="HTML")

if __name__ == '__main__':
    threading.Thread(target=iniciar_servidor_salud, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("generar", comando_generar))
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    print("🤖 Bot de LinkedIn escuchando peticiones en Telegram con tolerancia a fallos 503...")
    app.run_polling()
