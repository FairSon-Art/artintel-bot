import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from telegram.constants import ParseMode
import anthropic

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PORT = int(os.getenv("PORT", 8080))

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Tu es curateur associé et analyste principal du marché de l'art (primaire/secondaire, tranche 5-15k€).
Fournis une analyse dense, percutante et structurée en Markdown propre :
- **Verdict / Score** (/10)
- **Trajectoire institutionnelle** (expositions, galerie, foires)
- **Risque spéculatif & Liquidité**
- **Plafond d'achat conseillé**"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ArtIntel VIP (Claude Engine) actif. Envoie /bluehunt [Artiste / Œuvre + prix]")

async def bluehunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /bluehunt [Nom Artiste - Prix demandé ex: 8000€]")
        return
    
    await update.message.reply_text(f"🔍 Analyse institutionnelle approfondie : {query}...")
    
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Évalue cette opportunité : {query}"}
            ]
        )
        text_reply = response.content[0].text
        await update.message.reply_text(text_reply.strip(), parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erreur Claude : {e}")

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
    if not TELEGRAM_TOKEN or not ANTHROPIC_API_KEY:
        print("ERREUR : Il manque une clé secrète (TELEGRAM_TOKEN ou ANTHROPIC_API_KEY) !")
        return
    
    # Lancement du serveur HTTP pour le health check Render
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bluehunt", bluehunt))
    print("Le bot Claude est réveillé et à l'écoute...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()