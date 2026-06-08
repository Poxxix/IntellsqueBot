import re
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from models.database import db_session
from models.info import InfoHub
from services.ai import generate_ai_response

async def build_info_context() -> str:
    """Helper to retrieve all Info Hub entries as context for AWS Bedrock."""
    async with db_session() as session:
        stmt = select(InfoHub)
        res = await session.execute(stmt)
        infos = res.scalars().all()
        
    if not infos:
        return "Hiện chưa có thông tin nội bộ nào được thiết lập."
        
    context_lines = []
    for info in infos:
        context_lines.append(f"- {info.key}: {info.value}")
    return "\n".join(context_lines)

async def handle_ai_mention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles messages in group chats where the bot is mentioned/tagged."""
    if not update.message or not update.message.text:
        return
        
    message_text = update.message.text
    bot_username = context.bot.username
    
    # Check if the bot was mentioned
    if f"@{bot_username}" not in message_text:
        return
        
    # Clean the prompt by removing the bot mention
    clean_prompt = re.sub(rf"@{bot_username}", "", message_text, flags=re.IGNORECASE).strip()
    if not clean_prompt:
        await update.message.reply_text("🤡 Tag em làm gì đấy sếp ơi? Gõ gì đó đi em mới trả lời được chứ! 🧐")
        return
        
    # Build prompt with Info Hub context
    info_context = await build_info_context()
    
    full_prompt = (
        "Hãy đóng vai Trợ lý Cây Hài Văn Phòng. "
        "Sử dụng thông tin nội bộ của văn phòng dưới đây (nếu có liên quan) để trả lời câu hỏi của người dùng. "
        "Nếu câu hỏi không liên quan đến thông tin nội bộ, hãy trả lời tự do theo phong cách hài hước và cà khịa thường ngày.\n\n"
        "--- THÔNG TIN NỘI BỘ VĂN PHÒNG ---\n"
        f"{info_context}\n"
        "------------------------------------\n\n"
        f"Câu hỏi của người dùng: \"{clean_prompt}\"\n"
    )
    
    # Send typing action to make it feel responsive
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # Generate and send response
    response = await generate_ai_response(full_prompt)
    await update.message.reply_text(response, parse_mode="Markdown")

async def handle_ai_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text chat in private DM with the bot (non-command text)."""
    if not update.message or not update.message.text or update.effective_chat.type != 'private':
        return
        
    # Skip if it's a command
    if update.message.text.startswith('/'):
        return
        
    user_prompt = update.message.text.strip()
    info_context = await build_info_context()
    
    full_prompt = (
        "Hãy đóng vai Trợ lý Cây Hài Văn Phòng. "
        "Người dùng đang chat riêng (DM) với bạn. Sử dụng thông tin nội bộ của văn phòng dưới đây (nếu có liên quan) để trả lời. "
        "Nếu không liên quan, trả lời tự do theo cách lầy lội, hài hước.\n\n"
        "--- THÔNG TIN NỘI BỘ VĂN PHÒNG ---\n"
        f"{info_context}\n"
        "------------------------------------\n\n"
        f"Tin nhắn của người dùng: \"{user_prompt}\"\n"
    )
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await generate_ai_response(full_prompt)
    await update.message.reply_text(response, parse_mode="Markdown")

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes incoming text messages to either DM chat or Group mention handlers."""
    if not update.effective_chat:
        return
    if update.effective_chat.type == 'private':
        await handle_ai_dm(update, context)
    else:
        await handle_ai_mention(update, context)
