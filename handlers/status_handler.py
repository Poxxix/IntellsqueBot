from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.leave import LeaveRequest
from models.spin import SpinHistory
from models.reminder import Reminder
from models.task import Task
from handlers.leave_handler import format_leave_type

async def handle_status_homnay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Summarizes the current day's status for the group."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    async with db_session() as session:
        # 1. Leaves
        stmt_leave = select(LeaveRequest).where(
            and_(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= today_str,
                LeaveRequest.end_date >= today_str
            )
        )
        res_leave = await session.execute(stmt_leave)
        leaves = res_leave.scalars().all()
        
        # 2. Lunch Draw today
        # Check if the last random member spin was today
        stmt_lunch = select(SpinHistory).where(
            SpinHistory.spin_type == 'random_member'
        ).order_by(SpinHistory.id.desc()).limit(1)
        res_lunch = await session.execute(stmt_lunch)
        last_lunch = res_lunch.scalar_one_or_none()
        
        lunch_text = "🔴 Chưa chọn"
        if last_lunch:
            spin_date = last_lunch.created_at.split()[0] if last_lunch.created_at else ""
            if spin_date == today_str:
                lunch_text = f"🍱 **{last_lunch.result}**"
                
        # 3. Active Reminders today
        stmt_remind = select(Reminder).where(
            and_(
                Reminder.chat_id == chat_id,
                Reminder.active == True
            )
        )
        res_remind = await session.execute(stmt_remind)
        reminders = res_remind.scalars().all()
        
        today_reminders = []
        dt = datetime.now()
        day_name = dt.strftime("%A").lower()
        is_weekend = dt.weekday() >= 5
        
        for r in reminders:
            rule = r.schedule_rule
            if rule.startswith("once_time:"):
                parts = rule.split(":")
                time_str = f"{parts[1]}:{parts[2]}"
                today_reminders.append(f"⏰ `{time_str}` — **{r.title}** (Một lần)")
            elif rule.startswith("once_date:"):
                try:
                    iso_str = rule.split(":", 1)[1]
                    target_dt = datetime.fromisoformat(iso_str)
                    if target_dt.strftime("%Y-%m-%d") == today_str:
                        today_reminders.append(f"⏰ `{target_dt.strftime('%H:%M')}` — **{r.title}** (Một lần)")
                except Exception:
                    pass
            elif rule.startswith("recurring:"):
                parts = rule.split(":")
                freq = parts[1]
                time_str = f"{parts[2]}:{parts[3]}"
                if freq == "daily" or (freq == "weekdays" and not is_weekend) or freq == day_name:
                    today_reminders.append(f"📅 `{time_str}` — **{r.title}** (Định kỳ)")
            elif rule.startswith("task_interval:"):
                parts = rule.split(":")
                time_str = f"{parts[2]}:{parts[3]}"
                today_reminders.append(f"🧹 `{time_str}` — **{r.title}** (Định kỳ)")
                
        # 4. Open Tasks
        stmt_task = select(Task).where(
            and_(
                Task.chat_id == chat_id,
                Task.status == 'open'
            )
        )
        res_task = await session.execute(stmt_task)
        tasks = res_task.scalars().all()

    # Formatting
    leave_desc = ""
    if leaves:
        leave_desc = "\n".join([f"• **{l.user_name}** — {format_leave_type(l.leave_type)}" for l in leaves])
    else:
        leave_desc = "🟢 Hôm nay không có ai nghỉ phép."

    reminder_desc = ""
    if today_reminders:
        today_reminders.sort()
        reminder_desc = "\n".join(today_reminders)
    else:
        reminder_desc = "🟢 Không có nhắc nhở nào lên lịch hôm nay."

    text = (
        f"📊 **TRẠNG THÁI VĂN PHÒNG HÔM NAY** ({today_str})\n\n"
        f"🏖 **Nghỉ phép hôm nay:**\n"
        f"{leave_desc}\n\n"
        f"🍱 **Phân công lấy cơm hôm nay:**\n"
        f"👉 {lunch_text}\n\n"
        f"🔔 **Lịch nhắc nhở hôm nay:**\n"
        f"{reminder_desc}\n\n"
        f"✅ **Task đang mở:** `{len(tasks)}` việc chờ xử lý."
    )
    
    await update.message.reply_text(text, parse_mode="Markdown")
