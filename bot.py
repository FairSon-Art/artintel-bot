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
# Suivi du dernier mode actif par chat_id ('art' ou 'tcg') pour contextualiser les messages libres
active_mode = {}

SYSTEM_PROMPT_ART = """Tu es curateur associé et analyste principal du marché de l'art (tranche cible globale 5-15k€, plafond absolu 15 000 €).
Adopte un ton direct, élégant, dense et percutant, sans gros titres ##, utilise des emojis et du gras.

Règle absolue : si une pièce ou une estimation dépasse 15 000 €, commence par un avertissement 🚨 **HORS PLAFOND VIP (>15k€)**.

Structure type de ton analyse :
🎯 **Score & Verdict (Art)** : [X/10] — [Achat recommandé / Vigilance / Passe ton tour]
🏛️ **Trajectoire** : [Institutions / Galeries / Foires majeures]
⚡ **Risque & Liquidité** : [Niveau de liquidité secondaire]

🏷️ **Grille de prix cible (par support/format)** :
- Édition / Gravure / Petit multiple : [Fourchette €]
- Œuvre papier / Petit original : [Fourchette €]
- Toile / Œuvre majeure / Signature : [Fourchette € max, bloqué à 15k€ max]

Si un prix précis est donné par l'utilisateur, commente sa pertinence. Sinon, donne la grille de référence. Sois concis et direct. Pose 2 questions ciblées si des manques bloquent l'affinage."""

SYSTEM_PROMPT_TCG = """Tu es expert en investissement et grading TCG (One Piece JAP, Pokémon JAP/FR, arbitrage PSA/BGS).
Adopte un ton direct, élégant, dense et percutant, sans gros titres ##, utilise des emojis et du gras.

Règle absolue : alerte si le risque d'illiquidité ou de surcote post-hype est critique.

Structure type de ton analyse :
🎯 **Score & Verdict (TCG)** : [X/10] — [Achat brut recommandé / Grading only / Passe ton tour]
📈 **Potentiel Liquide** : [eBay / Cardmarket / Vinted / Sortie de set]
⚡ **Risque & Grading** : [Sensibilité centrage/blanchiment edge, ROI PSA 10 vs PSA 9]

🏷️ **Grille de prix cible (par état / grade)** :
- Raw / Brut (Near Mint irréprochable) : [Fourchette €]
- Potentiel Grading PSA 10 estimé (coût grading inclus) : [Fourchette € cible d'achat brut]
- Valeur marché PSA 10 validée : [Fourchette €]

Si un prix précis est donné par l'utilisateur, commente sa pertinence par rapport au grading. Sinon, donne la grille de référence. Sois concis et direct. Pose 2 questions ciblées si des manques (centrage, état back, extension) bloquent l'affinage."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    active_mode[chat_id] = 'art'
    await update.message.reply_text(
        "⚡ *Art & TCG Intel VIP* actif.\n\n"
        "🎨 `/bluehunt [Artiste / Œuvre]` (Plafond 15k€)\n"
        "🃏 `/tcghunt [Carte One Piece / Pokémon + prix opt.]`", 
        parse_mode=ParseMode.MARKDOWN
    )

async def bluehunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    query = " ".join(context.args)
    active_mode[chat_id] = 'art'
    
    if not query:
        await update.message.reply_text("💡 Usage : `/bluehunt Wolfgang Tillmans - 10000€`", parse_mode=ParseMode.MARKDOWN)
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await update.message.reply_text(f"🔍 *Scan Art Matrice 5-15k€* : {query}...", parse_mode=ParseMode.MARKDOWN)
    
    user_prompt = f"[MODE ART] Évalue cette cible / grille d'acquisition : {query}"
    conversation_history[chat_id] = [{"role": "user", "content": user_prompt}]
    await get_and_send_claude_response(update, chat_id, mode='art')

async def tcghunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    query = " ".join(context.args)
    active_mode[chat_id] = 'tcg'
    
    if not query:
        await update.message.reply_text("💡 Usage : `/tcghunt Silvers Rayleigh Manga OP01 - 450€`", parse_mode=ParseMode.MARKDOWN)
        return
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await update.message.reply_text(f"🔍 *Scan TCG / Grading* : {query}...", parse_mode=ParseMode.MARKDOWN)
    
    user_prompt = f"[MODE TCG] Évalue cette carte / grille brut-PSA : {query}"
    conversation_history[chat_id] = [{"role": "user", "content": user_prompt}]
    await get_and_send_claude_response(update, chat_id, mode='tcg')

async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
        active_mode[chat_id] = 'art'
        
    mode = active_mode.get(chat_id, 'art')
    prefixed_text = f"[SUITE MODE {mode.upper()}] {text}"
    conversation_history[chat_id].append({"role": "user", "content": prefixed_text})
    
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    await get_and_send_claude_response(update, chat_id, mode=mode)

async def send_long_message(update: Update, text: str):
    max_length = 4000
    if len(text) <= max_length:
        await update.message.reply_text(text.strip(), parse_mode=ParseMode.MARKDOWN)
        return
    
    parts = [text[i:i+max_length] for i in range(0, len(text), max_length)]
    for part in parts:
        await update.message.reply_text(part.strip(), parse_mode=ParseMode.MARKDOWN)

async def get_and_send_claude_response(update: Update, chat_id: int, mode: str):
    try:
        sys_prompt = SYSTEM_PROMPT_TCG if mode == 'tcg' else SYSTEM_PROMPT_ART
        
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,
            system=sys_prompt,
            messages=conversation_history[chat_id]
        )
        
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
    app.add_handler(CommandHandler("tcghunt", tcghunt))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_chat_message))
    
    print("Le bot fusionné Art (15k) + TCG (One Piece/Pokémon) est opérationnel...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()