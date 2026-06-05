import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.reminder import Reminder
from models.user import User
from models.audit import AuditLog

# Helper to check if user is admin/approver
async def is_admin_or_approver(session, user_id: int) -> bool:
    stmt = select(User).where(User.telegram_id == user_id)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()
    return user is not None and user.role in ['admin', 'approver']

async def handle_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all variations of the /remind command."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args
    message_text = update.message.text
    
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp đặt nhắc nhở:**\n\n"
            "1️⃣ **Nhắc việc tức thì (Broadcast):**\n"
            "• `/remind review` - Nhắc review PR ngay lập tức.\n"
            "• `/remind timesheet` - Nhắc nộp timesheet ngay lập tức.\n\n"
            "2️⃣ **Nhắc một lần (One-time):**\n"
            "• `/remind HH:MM [nội dung]` - Nhắc vào giờ cố định.\n"
            "• `/remind [Số][s|m|h] [nội dung]` - Nhắc sau khoảng thời gian.\n\n"
            "3️⃣ **Nhắc lặp lại (Recurring - v2.0):**\n"
            "• `/remind every day 17:30 [nội dung]` - Mỗi ngày.\n"
            "• `/remind every monday 09:00 [nội dung]` - Mỗi Thứ 2.\n"
            "• `/remind every 1st 10:00 [nội dung]` - Ngày 1 hàng tháng.\n\n"
            "4️⃣ **Hủy nhắc nhở:**\n"
            "• `/remind cancel <ID>` - Hủy nhắc nhở theo ID.",
            parse_mode="Markdown"
        )
        return

    # Check Cancel
    if args[0].lower() == "cancel":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("❌ Vui lòng điền mã ID nhắc nhở cần hủy (Ví dụ: `/remind cancel 5`).")
            return
            
        rem_id = int(args[1])
        async with db_session() as session:
            rem = await session.get(Reminder, rem_id)
            if not rem:
                await update.message.reply_text(f"❌ Không tìm thấy nhắc nhở mã #{rem_id}.")
                return
                
            # Verify permission: creator or admin
            is_admin = await is_admin_or_approver(session, user_id)
            if rem.created_by != user_id and not is_admin:
                await update.message.reply_text("❌ Bạn không có quyền hủy nhắc nhở này.")
                return
                
            rem.active = False
            session.add(AuditLog(
                actor_id=user_id,
                action="cancel_reminder",
                entity_type="reminders",
                entity_id=rem_id
            ))
            await update.message.reply_text(f"🗑 Đã hủy nhắc nhở **\"{rem.title}\"** (ID: #{rem_id}) thành công.")
        return

    # Check Broadcast instant reminders
    if len(args) == 1:
        keyword = args[0].lower()
        if keyword == "review":
            await update.message.reply_text("🔔 **Mọi người nhớ review PR giúp đồng nghiệp nhé!** 💻👀")
            return
        elif keyword == "timesheet":
            await update.message.reply_text("🔔 **Mọi người nhớ nộp timesheet đúng giờ nhé!** ⏱📝")
            return

    # Check Recurring: every [day|monday|1st] HH:MM [title]
    if args[0].lower() == "every":
        if len(args) < 4:
            await update.message.reply_text("❌ Cú pháp sai. Ví dụ: `/remind every monday 09:00 Họp weekly`")
            return
            
        freq = args[1].lower() # day, monday, 1st...
        time_str = args[2] # HH:MM
        title = " ".join(args[3:])
        
        # Validate HH:MM
        if not re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', time_str):
            await update.message.reply_text("❌ Giờ nhắc nhở không đúng định dạng HH:MM.")
            return
            
        # Validate freq
        valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        valid_ordinals = [f"{i}st" for i in [1, 21, 31]] + [f"{i}nd" for i in [2, 22]] + [f"{i}rd" for i in [3, 23]] + [f"{i}th" for i in range(4, 21)] + [f"{i}th" for i in range(24, 31)]
        
        if freq not in ["day"] + valid_days + valid_ordinals:
            await update.message.reply_text("❌ Tần suất lặp không hợp lệ. Hãy chọn `day`, thứ trong tuần (e.g. `monday`), hoặc ngày trong tháng (e.g. `1st`, `15th`).")
            return
            
        rule = f"recurring:{freq}:{time_str}"
        async with db_session() as session:
            rem = Reminder(
                chat_id=chat_id,
                title=title,
                schedule_rule=rule,
                is_recurring=True,
                created_by=user_id
            )
            session.add(rem)
            await session.flush()
            
            session.add(AuditLog(
                actor_id=user_id,
                action="create_recurring_reminder",
                entity_type="reminders",
                entity_id=rem.id
            ))
            
        freq_vi = "mỗi ngày" if freq == "day" else f"Thứ {valid_days.index(freq)+2}" if freq in valid_days else f"ngày {freq} hàng tháng"
        if freq == "sunday":
            freq_vi = "Chủ Nhật hàng tuần"
            
        await update.message.reply_text(
            f"📅 **Đã lên lịch nhắc nhở lặp lại!** (ID: #{rem.id})\n"
            f"• Nội dung: **{title}**\n"
            f"• Lặp: `{freq_vi}` lúc `{time_str}`"
        )
        return

    # Check HH:MM or duration
    time_arg = args[0]
    title = " ".join(args[1:])
    
    time_reg = re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', time_arg)
    duration_reg = re.match(r'^(\d+)([smh])$', time_arg)
    
    rule = ""
    ack = ""
    
    if time_reg:
        rule = f"once_time:{time_arg}"
        ack = f"🔔 Đã hẹn giờ nhắc nhở **\"{title}\"** vào lúc **{time_arg}** hôm nay (hoặc ngày mai nếu giờ này đã qua)."
    elif duration_reg:
        val = int(duration_reg.group(1))
        unit = duration_reg.group(2)
        
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
        ack = f"🔔 Đã hẹn nhắc nhở **\"{title}\"** sau **{val} {unit_vi}** (vào lúc `{target_time.strftime('%H:%M:%S')}`)."
    else:
        await update.message.reply_text("❌ Không hiểu định dạng thời gian. Vui lòng điền dạng HH:MM hoặc 10m, 30s.")
        return

    async with db_session() as session:
        rem = Reminder(
            chat_id=chat_id,
            title=title,
            schedule_rule=rule,
            is_recurring=False,
            created_by=user_id
        )
        session.add(rem)
        await session.flush()
        
        session.add(AuditLog(
            actor_id=user_id,
            action="create_reminder",
            entity_type="reminders",
            entity_id=rem.id
        ))
        
    await update.message.reply_text(f"{ack} (ID: #{rem.id})")

async def handle_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all active reminders in the current chat."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    
    async with db_session() as session:
        stmt = select(Reminder).where(
            and_(
                Reminder.chat_id == chat_id,
                Reminder.active == True
            )
        )
        res = await session.execute(stmt)
        rems = res.scalars().all()
        
    if not rems:
        await update.message.reply_text("🔔 Hiện tại không có nhắc nhở nào đang hoạt động trong nhóm này.")
        return
        
    text = "🔔 **DANH SÁCH NHẮC NHỞ ĐANG HOẠT ĐỘNG** 🔔\n\n"
    
    keyboard = []
    for idx, r in enumerate(rems):
        rule_desc = ""
        rule = r.schedule_rule
        
        if rule.startswith("once_time:"):
            time_part = rule.split(":")[1] + ":" + rule.split(":")[2]
            rule_desc = f"Một lần lúc `{time_part}`"
        elif rule.startswith("once_date:"):
            iso_str = rule.split(":", 1)[1]
            dt = datetime.fromisoformat(iso_str)
            rule_desc = f"Một lần lúc `{dt.strftime('%d/%m/%Y %H:%M')}`"
        elif rule.startswith("recurring:"):
            parts = rule.split(":")
            freq = parts[1]
            time_str = parts[2] + ":" + parts[3]
            
            freq_str = "Hàng ngày" if freq == "day" else f"Thứ {freq.capitalize()}" if freq != "sunday" else "Chủ Nhật"
            if freq.endswith("st") or freq.endswith("nd") or freq.endswith("rd") or freq.endswith("th"):
                freq_str = f"Ngày {freq} hàng tháng"
            rule_desc = f"Định kỳ: `{freq_str}` lúc `{time_str}`"
            
        text += f"• **#{r.id}**: {r.title} — {rule_desc}\n"
        keyboard.append(InlineKeyboardButton(f"🗑 Xóa #{r.id}", callback_data=f"rem_del:{r.id}"))
        
    # Chunk buttons
    button_rows = [keyboard[i:i+3] for i in range(0, len(keyboard), 3)]
    
    await update.message.reply_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(button_rows)
    )

async def handle_rem_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes callback clicks to delete reminders."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    rem_id = int(parts[1])
    user_id = query.from_user.id
    
    async with db_session() as session:
        rem = await session.get(Reminder, rem_id)
        if not rem:
            await query.edit_message_text("❌ Không tìm thấy nhắc nhở này.")
            return
            
        # Verify permissions
        is_admin = await is_admin_or_approver(session, user_id)
        if rem.created_by != user_id and not is_admin:
            await context.bot.answer_callback_query(
                callback_query_id=query.id,
                text="❌ Bạn không có quyền xóa nhắc nhở này.",
                show_alert=True
            )
            return
            
        rem.active = False
        session.add(AuditLog(
            actor_id=user_id,
            action="cancel_reminder_callback",
            entity_type="reminders",
            entity_id=rem_id
        ))
        
    await query.edit_message_text(f"🗑 Đã xóa nhắc nhở **\"{rem.title}\"** thành công.")
