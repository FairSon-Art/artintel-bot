import os
import logging
import threading
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from google import genai

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 8080))

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """Tu es curateur associé et analyste du marché primaire/secondaire (post-émergence, 5-15k€). 
Analyse l'artiste soumis pour identifier s'il coche la case "blue-chip accessible en devenir".
Réponds UNIQUEMENT un JSON valide avec ces clés exactes :
{
  "score": "X/10",
  "tiers": "Spéculatif pur / Candidat Blue-Chip / Déjà verrouillé hors budget",
  "red_flag": "1 phrase max",
  "plafond_primaire": "X €"
}"""

def call_gemini_resilient(prompt_text):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return gemini_client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_text,
                config=genai.types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    max_output_tokens=400,
                    temperature=0.1
                )
            )
        except Exception as e:
            err_str = str(e).lower()
            is_overloaded = any(k in err_str for k in ['503', '429', 'unavailable', 'resource_exhausted', 'overloaded'])
            if is_overloaded and attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            raise e

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ArtIntel VIP actif (JSON mode). Envoie /bluehunt [Artiste / Œuvre + prix]")

async def bluehunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /bluehunt [Nom Artiste - Prix demandé ex: 8000€]")
        return
    
    await update.message.reply_text(f"Scan institutionnel : {query}...")
    
    try:
        response = call_gemini_resilient(f"Évalue : {query}")
        raw_text = getattr(response, 'text', '')
        
        # Parse JSON et formatage propre client-side
        data = json.loads(raw_text)
        formatted_message = (
            f"🎯 Score : {data.get('score', 'N/A')}\n"
            f"🏷️ Tiers : {data.get('tiers', 'N/A')}\n"
            f"🚩 Red Flag : {data.get('red_flag', 'N/A')}\n"
            f"💰 Plafond : {data.get('plafond_primaire', 'N/A')}"
        )
        await update.message.reply_text(formatted_message)
        
    except json.JSONDecodeError:
        # Fallback si le JSON est malformé ou brut
        await update.message.reply_text(raw_text or "Erreur de format de réponse.")
    except Exception as e:
        err_str = str(e)
        if any(k in err_str.lower() for k in ['503', 'unavailable', 'high demand', '429']):
            await update.message.reply_text("⚠️ Google AI Studio sature. Réessaie dans 30 secondes !")
        else:
            await update.message.reply_text(f"Erreur API Gemini : {e}")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        return

def run_http_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthHandler)
    server.serve_forever()

def main():
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("ERREUR : Il manque une clé secrète !")
        return
    
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bluehunt", bluehunt))
    print("Le bot est réveillé (JSON)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()