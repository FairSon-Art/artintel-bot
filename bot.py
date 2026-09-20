import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
import anthropic

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PORT = int(os.getenv("PORT", 8080))

claude_client = anthropic.Client(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Tu es curateur associé et analyste du marché primaire/secondaire (post-émergence, 5-15k€). 
Analyse l'artiste soumis pour identifier s'il coche la case "blue-chip accessible en devenir".
Critères stricts de notation (sur 10) :
1. Ancrage institutionnel précoce (prix, centre d'art, résidence reconnue : /3)
2. Densité et constance du marché primaire (galeries mid-tier reconnues : /3)
3. Résistance du second marché ou absence de dumping spéculatif : /2
4. Rareté/maturité du corpus : /2

Format de réponse obligatoire :
- Score global (ex: 7.5/10)
- Tiers actuel (Spéculatif pur / Candidat Blue-Chip / Déjà verrouillé hors budget)
- Le "Red Flag" majeur
- Le prix plafond conseillé pour de l'achat primaire sécurisé."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("ArtIntel VIP actif. Envoie /bluehunt [Artiste / Œuvre + prix] pour scanner la trajectoire.")

async def bluehunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: /bluehunt [Nom Artiste - Prix demandé ex: 8000€]")
        return
    
    await update.message.reply_text(f"Analyse institutionnelle et de marché en cours pour : {query}...")
    
    try:
        response = claude_client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Évalue cet artiste/œuvre : {query}"}]
        )
        text_reply = ""
        for block in response.content:
            if hasattr(block, 'text'):
                text_reply += block.text
        if not text_reply:
            text_reply = str(response.content)
        await update.message.reply_text(text_reply)
    except Exception as e:
        await update.message.reply_text(f"Erreur API : {e}")

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
        print("ERREUR : Il manque une clé secrète !")
        return
    
    t = threading.Thread(target=run_http_server, daemon=True)
    t.start()
        
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bluehunt", bluehunt))
    print("Le bot est réveillé et écoute sur Telegram...")
    app.run_polling()

if __name__ == '__main__':
    main()