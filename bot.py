import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from telegram.constants import ParseMode, ChatAction
anthropic_pkg = __import__('anthropic')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PORT = int(os.getenv("PORT", 8080))

client = anthropic_pkg.Anthropic(api_key=ANTHROPIC_API_KEY)

# Mémoire simple par chat_id : { chat_id: [ {role, content}, ... ] }
conversation_history = {}

SYSTEM_PROMPT = """Tu es curateur associé et analyste principal du marché de l'art (tranche cible globale 5-15k€, plafond absolu 15 000 €).
Adopte un ton direct, élégant, dense et percutant, sans gros titres ##, utilise des emojis et du gras.

Règle absolue : si une pièce ou une estimation dépasse 15 000 €, commence par un avertissement 🚨 **HORS PLAFOND VIP (>15k€)**.

Structure type de ton analyse :
🎯 **Score & Verdict** : [X/10] — [Achat recommandé / Vigilance / Passe ton tour]
🏛️ **Trajectoire** : [Institutions / Galeries / Foires majeures]
⚡ **Risque & Liquidité** : [Niveau de liquidité secondaire]

🏷️ **Grille de prix cible (par support/format)** :
- Édition / Gravure / Petit multiple : [Fourchette €]
- Œuvre papier / Petit original : [Fourchette €]
- Toile / Œuvre majeure / Signature : [Fourchette € max, bloqué à 15k€ max]

Si un prix précis est donné par l'utilisateur, commente sa pertinence. Sinon, donne la grille de référence. Sois concis et direct pour éviter toute coupe de texte. Pose 2 questions ciblées si des manques bloquent l'affinage."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text(
        "🎨 *ArtIntel VIP* actif (Plafond strict : 15k€).\n\nEnvoie `/bluehunt [Nom Artiste ou Œuvre (+ prix optionnel)]`."
    , parse_mode=ParseMode.MARKDOWN)

async def bluehunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    query = " ".join(context.args)
    
    if not query:
        await update.message.reply_text(
            "💡 Usage : `/bluehunt Wolfgang Tillmans` (ou avec prix : `/bluehunt Wolfgang Tillmans - 10000€`)", 
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await update.message.reply_text(f"🔍 *Scan & Matrice 5-15k€* : {query}...", parse_mode=ParseMode.MARKDOWN)
    
    user_prompt = f"Évalue cette cible / donne le score / la grille de prix d'acquisition (rappel plafond strict 15k€) : {query}"
    
    conversation_history[chat_id] = [
        {"role": "user", "content": user_prompt}
    ]
    
    await get_and_send_claude_response(update, chat_id)

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
        
    conversation_history[chat_id].append({"role": "user", "content": text})
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await get_and_send_claude_response(update, chat_id)

async def send_long_message(update: Update, text: str):
    """Découpe et envoie les messages trop longs pour Telegram (limite ~4096 caractères)."""
    max_length = 4000
    if len(text) <= max_length:
        await update.message.reply_text(text.strip(), parse_mode=ParseMode.MARKDOWN)
        return
    
    parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    for part in parts:
        await update.message.reply_text(part.strip(), parse_mode=ParseMode.MARKDOWN)

async def get_and_send_claude_response(update: Update, chat_id: int):
    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,  # Réduit pour éviter les réponses trop longues qui coupent
            system=SYSTEM_PROMPT,
            messages=conversation_history[chat_id]
        )
        
        # Extrait uniquement le bloc texte, ignore les blocs de réflexion (thinking)
        text_reply = ""
        for block in response.content:
            if hasattr(block, 'text'):
                text_reply += block.text
            elif isinstance(block, dict) and block.get('type') == 'text':
                text_reply += block.get('text', '')
                
        if not text_reply and response.content:
            text_reply = str(response.content[-1])
        
        conversation_history[chat_id].append({"role": "assistant", "content": text_reply})
        
        if len(conversation_history[chat_id]) > 10:
            conversation_history[chat_id] = conversation_history[chat_id][-10:]
            
        await send_long_message(update, text_reply)
        
    except Exception as e:
        await update.message.reply_text(f"⚠️ Erreur Claude : `{e}`", parse_mode=ParseMode.MARKDOWN)

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
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_chat_message))
    
    print("Le bot Claude avec score /10, anti-coupure et mémoire est opérationnel...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()