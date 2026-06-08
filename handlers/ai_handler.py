import re
import json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select
from models.database import db_session
from models.info import InfoHub
from models.user import User
from models.reminder import Reminder
from models.audit import AuditLog
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

async def parse_ai_reminder(prompt: str) -> dict:
    """Uses Gemini to parse a natural language reminder delegation request."""
    now = datetime.now()
    current_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    day_name = now.strftime("%A")
    
    system_instruction = (
        "Bạn là Trợ lý phân tích cú pháp hẹn giờ nhắc nhở văn phòng. "
        "Nhiệm vụ của bạn là phân tích câu nói của người dùng và trích xuất các thông tin hẹn giờ thành định dạng JSON chuẩn. "
        "Tuyệt đối không trả về bất kỳ văn bản giải thích nào khác ngoài chuỗi JSON hợp lệ. "
        "Định dạng JSON cần có chính xác các trường sau:\n"
        "- \"target_username\": Username của người cần nhắc nhở (bỏ ký tự @, ví dụ: 'nam', 'lan'). Nếu nhắc chính người nói hoặc không nhắc ai cụ thể thì trả về null.\n"
        "- \"reminder_content\": Nội dung nhắc nhở cần gửi (ngắn gọn, xúc tích).\n"
        "- \"time_type\": Kiểu thời gian, chọn một trong các giá trị: 'time' (giờ cụ thể trong ngày), 'duration' (khoảng thời gian từ lúc nói), 'datetime' (ngày giờ cụ thể), 'recurring' (lặp định kỳ), hoặc 'unknown' nếu không rõ.\n"
        "- \"time_value\": Giá trị tương ứng với time_type:\n"
        "  + Nếu 'time': định dạng 'HH:MM' (ví dụ: '15:30').\n"
        "  + Nếu 'duration': số kèm đơn vị s/m/h (ví dụ: '10m' là 10 phút, '2h' là 2 giờ, '30s' là 30 giây).\n"
        "  + Nếu 'datetime': định dạng 'YYYY-MM-DD HH:MM:SS' (ví dụ: '2026-06-09 15:00:00').\n"
        "  + Nếu 'recurring': định dạng 'tần_suất:HH:MM' (ví dụ: 'monday:09:00', 'day:17:30', '1st:10:00').\n"
    )
    
    analysis_prompt = (
        f"Thời gian hiện tại của hệ thống: {current_time_str} (Thứ: {day_name}).\n"
        f"Hãy phân tích câu chat đặt nhắc nhở sau:\n"
        f"\"{prompt}\"\n\n"
        "Hãy trả về JSON hợp lệ:"
    )
    
    try:
        response_text = await generate_ai_response(analysis_prompt, system_instruction=system_instruction)
        # Clean response in case of markdown wrapping
        cleaned_response = response_text.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()
        
        parsed = json.loads(cleaned_response)
        if isinstance(parsed, dict):
            return parsed
        return None
    except Exception as e:
        print(f"Error parsing AI reminder: {e}")
        return None

async def handle_normal_ai_mention(update: Update, context: ContextTypes.DEFAULT_TYPE, clean_prompt: str):
    """Answers user query using Info Hub context (RAG)."""
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
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    response = await generate_ai_response(full_prompt)
    await update.message.reply_text(response, parse_mode="Markdown")

async def handle_ai_reminder_intent(update: Update, context: ContextTypes.DEFAULT_TYPE, clean_prompt: str) -> bool:
    """Checks if the user's intent is to create a reminder and handles it. Returns True if handled."""
    reminder_keywords = ["nhắc", "nhac", "hẹn giờ", "hen gio", "remind"]
    if not any(kw in clean_prompt.lower() for kw in reminder_keywords):
        return False
        
    # Attempt to parse
    parsed = await parse_ai_reminder(clean_prompt)
    if not parsed or parsed.get("time_type") == "unknown":
        return False
        
    target_username = parsed.get("target_username")
    reminder_content = parsed.get("reminder_content")
    time_type = parsed.get("time_type")
    time_value = parsed.get("time_value")
    
    if not reminder_content:
        return False
        
    # Determine target Telegram ID
    target_user_id = None
    target_display_name = ""
    
    async with db_session() as session:
        if target_username:
            stmt = select(User).where(User.username == target_username.lower())
            res = await session.execute(stmt)
            t_user = res.scalar_one_or_none()
            if t_user:
                target_user_id = t_user.telegram_id
                target_display_name = t_user.display_name
            else:
                await update.message.reply_text(
                    f"❌ Mình không tìm thấy tài khoản @{target_username} trong hệ thống của bot. "
                    f"Người nhận cần mở chat với bot và gõ `/start` để kích hoạt nhận tin nhắn riêng."
                )
                return True
        else:
            # Default to the sender
            target_user_id = update.effective_user.id
            target_display_name = update.effective_user.full_name
            
    # Calculate schedule rule
    rule = ""
    is_recurring = False
    ack_time = ""
    
    if time_type == "time":
        rule = f"once_time:{time_value}"
        ack_time = f"lúc `{time_value}` hôm nay (hoặc ngày mai nếu giờ này đã qua)"
    elif time_type == "duration":
        val_match = re.match(r'^(\d+)([smh])$', time_value)
        if val_match:
            val = int(val_match.group(1))
            unit = val_match.group(2)
            
            delta = timedelta()
            unit_vi = ""
            if unit == 's':
                delta = timedelta(seconds=val)
                unit_vi = "giây"
            elif unit == 'm':
                delta = timedelta(minutes=val)
                unit_vi = "phút"
            elif unit == 'h':
                delta = timedelta(hours=val)
                unit_vi = "giờ"
                
            target_time = datetime.now() + delta
            rule = f"once_date:{target_time.isoformat()}"
            ack_time = f"sau `{val} {unit_vi}` (vào lúc `{target_time.strftime('%H:%M:%S')}`)"
        else:
            return False
    elif time_type == "datetime":
        try:
            target_time = datetime.strptime(time_value, "%Y-%m-%d %H:%M:%S")
            rule = f"once_date:{target_time.isoformat()}"
            ack_time = f"lúc `{target_time.strftime('%d/%m/%Y %H:%M:%S')}`"
        except Exception:
            return False
    elif time_type == "recurring":
        is_recurring = True
        rule = f"recurring:{time_value}"
        parts = time_value.split(":")
        freq = parts[0]
        time_part = parts[1] + ":" + parts[2]
        
        valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        freq_vi = "mỗi ngày" if freq == "day" else f"Thứ {valid_days.index(freq)+2}" if freq in valid_days else f"ngày {freq} hàng tháng"
        if freq == "sunday":
            freq_vi = "Chủ Nhật hàng tuần"
        ack_time = f"định kỳ `{freq_vi}` lúc `{time_part}`"
    else:
        return False
        
    # Create reminder
    creator_username = update.effective_user.username
    creator_name = f"@{creator_username}" if creator_username else update.effective_user.full_name
    reminder_title = f"Có lời nhắc từ {creator_name}: {reminder_content}"
    
    async with db_session() as session:
        rem = Reminder(
            chat_id=target_user_id,
            title=reminder_title,
            schedule_rule=rule,
            is_recurring=is_recurring,
            created_by=update.effective_user.id
        )
        session.add(rem)
        await session.flush()
        
        session.add(AuditLog(
            actor_id=update.effective_user.id,
            action="create_delegated_reminder",
            entity_type="reminders",
            entity_id=rem.id
        ))
        
    # Send confirmation response
    if target_user_id == update.effective_user.id:
        await update.message.reply_text(
            f"📅 **Đã lên lịch nhắc nhở cho bạn!**\n"
            f"• Nội dung: **{reminder_content}**\n"
            f"• Thời gian: {ack_time}\n"
            f"• Phương thức: Mình sẽ gửi tin nhắn riêng (DM) cho bạn khi đến hạn."
        )
    else:
        await update.message.reply_text(
            f"📅 **Đã lên lịch nhắc nhở ủy thác thành công!**\n"
            f"• Người nhận: **{target_display_name}** (@{target_username})\n"
            f"• Nội dung: **{reminder_content}**\n"
            f"• Thời gian: {ack_time}\n"
            f"• Phương thức: Mình sẽ gửi tin nhắn riêng (DM) cho bạn ấy khi đến hạn."
        )
    return True

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
            
    is_mentioned = False
    if bot_username and f"@{bot_username.lower()}" in message_text.lower():
        is_mentioned = True
    elif update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id:
        is_mentioned = True
        
    if not is_mentioned:
        return
        
    clean_prompt = message_text
    if bot_username:
        clean_prompt = re.sub(rf"@{bot_username}", "", clean_prompt, flags=re.IGNORECASE).strip()
        
    if not clean_prompt:
        await update.message.reply_text("💼 Xin chào, mình có thể hỗ trợ gì cho bạn? Bạn vui lòng nhập nội dung câu hỏi nhé.")
        return
        
    # 1. Try to handle as a reminder intent
    is_handled = await handle_ai_reminder_intent(update, context, clean_prompt)
    if is_handled:
        return
        
    # 2. Fallback to normal RAG QA
    await handle_normal_ai_mention(update, context, clean_prompt)

async def handle_ai_dm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text chat in private DM with the bot (non-command text)."""
    if not update.message or not update.message.text or update.effective_chat.type != 'private':
        return
        
    if update.message.text.startswith('/'):
        return
        
    # Check if there is a pending leave request waiting for a reason
    pending = context.user_data.get('pending_leave_req')
    if pending and 'reason' not in pending:
        reason_text = update.message.text.strip()
        if not reason_text:
            await update.message.reply_text("❌ Lý do không được để trống. Vui lòng nhập lý do xin nghỉ:")
            return
        pending['reason'] = reason_text
        context.user_data['pending_leave_req'] = pending
        from handlers.leave_handler import send_leave_confirm_menu
        await send_leave_confirm_menu(context.bot, update.effective_user.id, pending, context)
        return
        
    user_prompt = update.message.text.strip()
    
    # 1. Try to handle as a reminder intent
    is_handled = await handle_ai_reminder_intent(update, context, user_prompt)
    if is_handled:
        return
        
    # 2. Fallback to normal RAG QA
    await handle_normal_ai_mention(update, context, user_prompt)

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes incoming text messages to either DM chat or Group mention handlers."""
    if not update.effective_chat:
        return
    if update.effective_chat.type == 'private':
        await handle_ai_dm(update, context)
    else:
        await handle_ai_mention(update, context)
