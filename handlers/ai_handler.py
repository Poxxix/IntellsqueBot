import re
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from models.database import db_session
from models.info import InfoHub
from services.ai import generate_ai_response

async def build_info_context() -> str:
    """Helper to retrieve all Info Hub entries as context for Gemini."""
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
    """Handles messages in group chats where the bot is mentioned/tagged or replied to."""
    if not update.message or not update.message.text:
        return
        
    message_text = update.message.text
    
    bot_username = context.bot.username
    if not bot_username:
        try:
            bot_info = await context.bot.get_me()
            bot_username = bot_info.username
        except Exception as e:
            print(f"Error fetching bot username: {e}")
            return
            
    # Check if the bot was mentioned (case-insensitive) or if it's a reply to the bot
    is_mentioned = False
    if bot_username and f"@{bot_username.lower()}" in message_text.lower():
        is_mentioned = True
    elif update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        is_mentioned = True
        
    if not is_mentioned:
        return
        
    # Clean the prompt by removing the bot mention
    clean_prompt = message_text
    if bot_username:
        clean_prompt = re.sub(rf"@{bot_username}", "", clean_prompt, flags=re.IGNORECASE).strip()
        
    if not clean_prompt:
        await update.message.reply_text("💼 Xin chào, mình có thể hỗ trợ gì cho bạn? Bạn vui lòng nhập nội dung câu hỏi nhé.")
        return
        
    # Build prompt with Info Hub context
    info_context = await build_info_context()
    
    full_prompt = (
        "Hãy đóng vai Trợ lý Văn phòng chuyên nghiệp và nghiêm túc. "
        "Sử dụng thông tin nội bộ của văn phòng dưới đây (nếu có liên quan) để trả lời câu hỏi của người dùng. "
        "Hãy trả lời một cách lịch sự, nghiêm túc, chính xác và trực diện. Không pha trò, không đùa cợt, không dùng từ lóng. Xưng hô là 'mình' và gọi người dùng là 'bạn'.\n\n"
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
        "Hãy đóng vai Trợ lý Văn phòng chuyên nghiệp và nghiêm túc. "
        "Người dùng đang chat riêng (DM) với bạn. Sử dụng thông tin nội bộ của văn phòng dưới đây (nếu có liên quan) để trả lời. "
        "Hãy trả lời một cách lịch sự, nghiêm túc, chính xác và trực diện. Không pha trò, không đùa cợt, không dùng từ lóng. Xưng hô là 'mình' và gọi người dùng là 'bạn'.\n\n"
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
