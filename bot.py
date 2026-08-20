import os
import json
import html
import time
import logging
import requests
import threading
from datetime import datetime, timedelta
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
    """
    Consulta la API de Google en tiempo real para obtener únicamente los modelos
    Flash de producción verdaderamente activos.
    """
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

def obtener_fecha_proximo_dia(nombre_dia: str, hora_programada: int = 9) -> str:
    """Calcula la fecha ISO 8601 del próximo día especificado a las 09:00 AM UTC."""
    hoy = datetime.utcnow()
    dia_target = DIAS_MAPA.get(nombre_dia.upper(), 0)
    dias_diferencia = (dia_target - hoy.weekday()) % 7
    if dias_diferencia == 0:
        dias_diferencia = 7  # Programar para la próxima semana si cae hoy
    fecha_target = hoy + timedelta(days=dias_diferencia)
    fecha_target = fecha_target.replace(hour=hora_programada, minute=0, second=0, microsecond=0)
    return fecha_target.strftime("%Y-%m-%dT%H:%M:%SZ")

def generar_con_respaldo(prompt: str, json_mode: bool = False):
    """
    Genera contenido recorriendo la lista de modelos candidatos con reintentos automáticos ante 503.
    """
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
        "mode": "customScheduled" if fecha_iso else "queue",
        "schedulingType": "customScheduled" if fecha_iso else "queue"
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
    """Elimina los encabezados decorativos del mensaje de Telegram antes de enviarlo a Buffer."""
    lineas = texto_mensaje.strip().split("\n")
    if len(lineas) > 1 and ("📌" in lineas[0] or "Aprobado" in lineas[0]):
        return "\n".join(lineas[1:]).strip()
    return texto_mensaje.strip()

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
            await query.edit_message_text(f"✅ <b>APROBADO Y PROGRAMADO EN BUFFER ({nombre_dia})</b>\n\n{texto_actual_html}", parse_mode="HTML")
        else:
            texto_actual_html = html.escape(texto_pantalla)
            await query.edit_message_text(f"❌ <b>ERROR BUFFER:</b> {html.escape(str(res))}\n\n{texto_actual_html}", parse_mode="HTML")

    elif accion == "regenerar":
        dia = partes[2] if len(partes) > 2 else "DÍA"
        tema = partes[3] if len(partes) > 3 else "DATOS"

        await query.edit_message_text(f"🔄 <b>Regenerando opción para {html.escape(dia)} ({html.escape(tema)})...</b>", parse_mode="HTML")
        prompt = f"Actúa como Especialista Senior en Datos. Genera un post alternativo para LinkedIn sobre {dia} enfocado en {tema}. Devuelve SOLO el texto plano del post."
        
        try:
            response, modelo_usado = generar_con_respaldo(prompt, json_mode=False)
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
    threading.Thread(target=iniciar_servidor_salud, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("generar", comando_generar))
    app.add_handler(CallbackQueryHandler(manejar_botones))
    
    print("🤖 Bot listo...")
    app.run_polling()
