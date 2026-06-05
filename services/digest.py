from datetime import datetime
from sqlalchemy import select, and_
from models.leave import LeaveRequest
from models.reminder import Reminder
from models.task import Task

async def build_daily_digest(session, chat_id: int, today_str: str) -> str:
    """Builds a daily summary message for a specific group chat."""
    # 1. Fetch approved leave requests for today
    stmt_leave = select(LeaveRequest).where(
        and_(
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today_str,
            LeaveRequest.end_date >= today_str
        )
    )
    res_leave = await session.execute(stmt_leave)
    leaves = res_leave.scalars().all()
    
    # 2. Fetch active reminders for today
    stmt_remind = select(Reminder).where(
        and_(
            Reminder.chat_id == chat_id,
            Reminder.active == True
        )
    )
    res_remind = await session.execute(stmt_remind)
    reminders = res_remind.scalars().all()
    
    # Filter reminders that trigger today
    today_reminders = []
    dt = datetime.strptime(today_str, "%Y-%m-%d")
    day_name = dt.strftime("%A").lower()  # e.g., monday
    is_weekend = dt.weekday() >= 5
    
    for r in reminders:
        rule = r.schedule_rule
        if rule.startswith("once_time:"):
            parts = rule.split(":")
            time_str = f"{parts[1]}:{parts[2]}"
            today_reminders.append((time_str, r.title))
        elif rule.startswith("once_date:"):
            # If date is today, list it
            # Format: once_date:ISOString
            try:
                target_iso = rule.substring(10) if hasattr(rule, 'substring') else rule[10:]
                target_dt = datetime.fromisoformat(target_iso.replace("Z", "+00:00"))
                # If target date matches today (local date)
                if target_dt.strftime("%Y-%m-%d") == today_str:
                    time_str = target_dt.strftime("%H:%M")
                    today_reminders.append((time_str, r.title))
            except Exception:
                pass
        elif rule.startswith("recurring:"):
            parts = rule.split(":")
            freq = parts[1]
            time_str = f"{parts[2]}:{parts[3]}"
            if freq == "daily" or (freq == "weekdays" and not is_weekend):
                today_reminders.append((time_str, r.title))
        elif rule.startswith("task_interval:"):
            parts = rule.split(":")
            time_str = f"{parts[2]}:{parts[3]}"
            today_reminders.append((time_str, r.title))
            
    # Sort reminders by time
    today_reminders.sort(key=lambda x: x[0])
    
    # 3. Fetch open tasks
    stmt_task = select(Task).where(
        and_(
            Task.chat_id == chat_id,
            Task.status == 'open'
        )
    )
    res_task = await session.execute(stmt_task)
    tasks = res_task.scalars().all()
    
    # Format weekday in Vietnamese
    days_vi = {
        "monday": "Thứ 2",
        "tuesday": "Thứ 3",
        "wednesday": "Thứ 4",
        "thursday": "Thứ 5",
        "friday": "Thứ 6",
        "saturday": "Thứ 7",
        "sunday": "Chủ Nhật"
    }
    day_vi = days_vi.get(day_name, day_name.capitalize())
    date_formatted = dt.strftime("%d/%m/%Y")
    
    digest = f"🌅 **Good morning! Tóm tắt hôm nay:**\n\n"
    digest += f"📅 **Hôm nay:** {day_vi}, {date_formatted}\n\n"
    
    # Leaves
    digest += "🏖 **Nghỉ phép:**\n"
    if leaves:
        for l in leaves:
            digest += f"• {l.user_name} — {l.leave_type}\n"
    else:
        digest += "• Không có ai nghỉ phép hôm nay\n"
        
    # Reminders
    digest += "\n🔔 **Nhắc việc hôm nay:**\n"
    if today_reminders:
        for time_str, title in today_reminders:
            digest += f"• {time_str} — {title}\n"
    else:
        digest += "• Không có lịch nhắc nhở nào\n"
        
    # Tasks count
    digest += f"\n✅ **Task đang mở:** {len(tasks)} việc chờ xử lý\n"
    
    return digest
