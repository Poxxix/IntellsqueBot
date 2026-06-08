from datetime import datetime
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.reminder import Reminder

def get_ordinal(n: int) -> str:
    """Helper to convert number to ordinal string (e.g., 1 -> '1st')."""
    return str(n) + ("th" if 4 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))

async def check_and_trigger_reminders_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job running every minute to trigger active reminders."""
    now = datetime.now()
    current_time_str = now.strftime("%H:%M") # HH:MM
    today_str = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A").lower() # e.g., monday
    is_weekend = now.weekday() >= 5
    day_ordinal = get_ordinal(now.day) # e.g., '1st'
    
    async with db_session() as session:
        stmt = select(Reminder).where(Reminder.active == True)
        res = await session.execute(stmt)
        active_reminders = res.scalars().all()
        
        for rem in active_reminders:
            should_trigger = False
            deactivate = False
            rule = rem.schedule_rule
            
            if rule.startswith("once_time:"):
                # once_time:HH:MM
                parts = rule.split(":")
                time_part = f"{parts[1]}:{parts[2]}"
                if time_part == current_time_str:
                    should_trigger = True
                    deactivate = True
                    
            elif rule.startswith("once_date:"):
                # once_date:ISOString
                try:
                    iso_str = rule.split(":", 1)[1]
                    target_dt = datetime.fromisoformat(iso_str)
                    if now >= target_dt:
                        should_trigger = True
                        deactivate = True
                except Exception:
                    pass
                    
            elif rule.startswith("recurring:"):
                # recurring:freq:HH:MM
                parts = rule.split(":")
                freq = parts[1]
                time_part = f"{parts[2]}:{parts[3]}"
                
                if time_part == current_time_str:
                    if freq == "day":
                        should_trigger = True
                    elif freq == day_name:
                        should_trigger = True
                    elif freq == day_ordinal:
                        should_trigger = True
                        
            if should_trigger:
                try:
                    print(f"Triggering reminder #{rem.id}: \"{rem.title}\" to chat {rem.chat_id}")
                    await context.bot.send_message(
                        chat_id=rem.chat_id,
                        text=f"⏰ **NHẮC NHỞ:** {rem.title}",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Failed to send reminder #{rem.id} to chat {rem.chat_id}: {e}")
                    
                if deactivate:
                    rem.active = False
                    
        # AI Auto Roast at 11:30 (Lunch check) and 14:00 (Status check)
        from config import GEMINI_API_KEY
        if GEMINI_API_KEY:
            if current_time_str == "11:30":
                from models.spin import SpinHistory
                from models.user import Setting
                stmt_spin = select(SpinHistory).where(
                    and_(
                        SpinHistory.spin_type == 'random_member',
                        SpinHistory.created_at.like(f"{today_str}%")
                    )
                )
                res_spin = await session.execute(stmt_spin)
                spin_today = res_spin.scalars().first()
                
                if not spin_today:
                    prompt = (
                        "Đã 11:30 trưa rồi mà chưa có ai quay số đi lấy cơm hôm nay bằng lệnh /random cả. "
                        "Hãy viết một tin nhắn nhắc nhở lịch sự và nghiêm túc để nhắc mọi người trong văn phòng quay số đi lấy cơm. "
                        "Tuyệt đối không pha trò, không dùng từ lóng, xưng là 'mình' và gọi người nhận là 'bạn'. Trả lời ngắn gọn dưới 2 câu."
                    )
                    from services.ai import generate_ai_response
                    roast_msg = await generate_ai_response(prompt)
                    
                    stmt_chats = select(Setting.chat_id).distinct()
                    res_chats = await session.execute(stmt_chats)
                    chat_ids = [c for c in res_chats.scalars().all() if c < 0]
                    for cid in chat_ids:
                        try:
                            await context.bot.send_message(chat_id=cid, text=f"🍱 {roast_msg}")
                        except Exception:
                            pass
                            
            elif current_time_str == "14:00":
                from models.user import User, Setting
                stmt_users = select(User).where(User.active == True)
                res_users = await session.execute(stmt_users)
                users = res_users.scalars().all()
                
                if users:
                    not_available_users = [u for u in users if u.status == 'no available']
                    pct = len(not_available_users) / len(users)
                    if pct >= 0.5 or len(not_available_users) >= 3:
                        prompt = (
                            f"Hiện tại là 14:00 chiều. Có {len(not_available_users)} trên tổng số {len(users)} nhân sự "
                            "đang để trạng thái 'no available' (vắng mặt/bận). Hãy viết một tin nhắn thông báo lịch sự, nghiêm túc "
                            "để nhắc nhở mọi người cập nhật lại trạng thái làm việc khi rảnh. Tuyệt đối không pha trò, không dùng từ lóng, xưng là 'mình' và gọi người nhận là 'bạn'. Trả lời ngắn gọn dưới 2 câu."
                        )
                        from services.ai import generate_ai_response
                        roast_msg = await generate_ai_response(prompt)
                        
                        stmt_chats = select(Setting.chat_id).distinct()
                        res_chats = await session.execute(stmt_chats)
                        chat_ids = [c for c in res_chats.scalars().all() if c < 0]
                        for cid in chat_ids:
                            try:
                                await context.bot.send_message(chat_id=cid, text=f"💤 {roast_msg}")
                            except Exception:
                                pass
