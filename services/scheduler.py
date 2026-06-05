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
