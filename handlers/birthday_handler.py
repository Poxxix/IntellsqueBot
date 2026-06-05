import re
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.user import User, Setting
from models.audit import AuditLog

async def handle_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for /birthday commands."""
    if not update.message:
        return
        
    args = context.args
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp lệnh /birthday:**\n"
            "• `/birthday set DD/MM` - Đặt ngày sinh nhật của bạn (Ví dụ: `/birthday set 06/06`)\n"
            "• `/birthday list` - Xem danh sách sinh nhật thành viên sắp tới.",
            parse_mode="Markdown"
        )
        return
        
    subcmd = args[0].lower()
    if subcmd == "set":
        context.args = args[1:]
        await handle_birthday_set(update, context)
    elif subcmd == "list":
        await handle_birthday_list(update, context)
    else:
        await update.message.reply_text("❌ Lệnh không hợp lệ. Vui lòng chọn `set` hoặc `list`.")

async def handle_birthday_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the user's birthday."""
    user_id = update.effective_user.id
    args = context.args
    
    if not args or not re.match(r'^\d{2}/\d{2}$', args[0]):
        await update.message.reply_text("💡 Cú pháp: `/birthday set DD/MM` (Ví dụ: `/birthday set 06/06`).")
        return
        
    birthday_str = args[0]
    day, month = map(int, birthday_str.split("/"))
    
    if month < 1 or month > 12 or day < 1 or day > 31:
        await update.message.reply_text("❌ Ngày hoặc tháng sinh không hợp lệ.")
        return
        
    async with db_session() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=user_id,
                display_name=update.effective_user.full_name,
                username=update.effective_user.username,
                role='member'
            )
            session.add(user)
            
        user.birthday = birthday_str
        
        session.add(AuditLog(
            actor_id=user_id,
            action="set_birthday",
            entity_type="users",
            entity_id=user.id
        ))
        
    await update.message.reply_text(f"🎂 Đã cập nhật ngày sinh nhật của bạn thành: `{birthday_str}`.")

async def handle_birthday_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all upcoming birthdays in the database."""
    async with db_session() as session:
        stmt = select(User).where(User.birthday.isnot(None)).order_by(User.birthday.asc())
        res = await session.execute(stmt)
        users = res.scalars().all()
        
    if not users:
        await update.message.reply_text("🎂 Chưa có thành viên nào cập nhật sinh nhật.")
        return
        
    def sort_key(u):
        d, m = map(int, u.birthday.split("/"))
        return (m, d)
        
    sorted_users = sorted(users, key=sort_key)
    
    text = "🎂 **DANH SÁCH SINH NHẬT THÀNH VIÊN** 🎂\n\n"
    for idx, u in enumerate(sorted_users):
        mention = f"@{u.username}" if u.username else u.display_name
        text += f"{idx+1}. **{u.display_name}** ({mention}) — `{u.birthday}`\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_joined_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets the user's joined date."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    args = context.args
    
    # Allow `/joined set DD/MM/YYYY` or `/joined DD/MM/YYYY`
    joined_arg = ""
    if args:
        if args[0].lower() == "set":
            joined_arg = args[1] if len(args) > 1 else ""
        else:
            joined_arg = args[0]
            
    if not joined_arg or not re.match(r'^\d{2}/\d{2}/\d{4}$', joined_arg):
        await update.message.reply_text("💡 Cú pháp: `/joined set DD/MM/YYYY` (Ví dụ: `/joined set 06/06/2023`).")
        return
        
    joined_str = joined_arg
    try:
        datetime.strptime(joined_str, "%d/%m/%Y")
    except ValueError:
        await update.message.reply_text("❌ Định dạng ngày không hợp lệ. Vui lòng nhập đúng định dạng DD/MM/YYYY.")
        return
        
    async with db_session() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            user = User(
                telegram_id=user_id,
                display_name=update.effective_user.full_name,
                username=update.effective_user.username,
                role='member'
            )
            session.add(user)
            
        user.joined_date = joined_str
        
        session.add(AuditLog(
            actor_id=user_id,
            action="set_joined_date",
            entity_type="users",
            entity_id=user.id
        ))
        
    await update.message.reply_text(f"💼 Đã cập nhật ngày gia nhập công ty của bạn thành: `{joined_str}`.")

async def daily_birthday_greeting_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to run daily to check birthdays and work anniversaries and greet them."""
    now = datetime.now()
    today_dm = now.strftime("%d/%m") # DD/MM
    current_year = now.year
    
    async with db_session() as session:
        # Get users with birthday today
        stmt_bday = select(User).where(User.birthday == today_dm)
        res_bday = await session.execute(stmt_bday)
        birthday_users = res_bday.scalars().all()
        
        # Get users with work anniversary today
        stmt_all_users = select(User).where(User.joined_date.isnot(None))
        res_all_users = await session.execute(stmt_all_users)
        anniv_users = []
        for u in res_all_users.scalars().all():
            if u.joined_date.startswith(today_dm):
                anniv_users.append(u)
                
        if not birthday_users and not anniv_users:
            return
            
        # Get active group chats in Setting
        stmt_chats = select(Setting.chat_id).distinct()
        res_chats = await session.execute(stmt_chats)
        chat_ids = [c for c in res_chats.scalars().all() if c < 0] # only groups
        
    if not chat_ids:
        return
        
    greetings = []
    
    # 1. Birthday greetings
    for u in birthday_users:
        mention = f"@{u.username}" if u.username else f"[{u.display_name}](tg://user?id={u.telegram_id})"
        greetings.append(
            f"🎉 🎂 **CHÚC MỪNG SINH NHẬT** 🎂 🎉\n\n"
            f"Hôm nay là sinh nhật của **{u.display_name}** ({mention})! "
            f"Chúc bạn tuổi mới luôn ngập tràn niềm vui, dồi dào sức khỏe, hạnh phúc ngọt ngào "
            f"và gặt hái được nhiều thành công rực rỡ trong công việc cũng như cuộc sống! 🥳✨🎈"
        )
        
    # 2. Anniversary greetings
    for u in anniv_users:
        joined_year = int(u.joined_date.split("/")[-1])
        years = current_year - joined_year
        if years > 0:
            mention = f"@{u.username}" if u.username else f"[{u.display_name}](tg://user?id={u.telegram_id})"
            greetings.append(
                f"🎉 💼 **KỶ NIỆM NGÀY GIA NHẬP** 💼 🎉\n\n"
                f"Chúc mừng **{u.display_name}** ({mention}) đã tròn `{years} năm` đồng hành và cống hiến cùng team! "
                f"Cảm ơn những nỗ lực bền bỉ và nguồn năng lượng tích cực mà bạn đã mang lại cho đại gia đình chúng ta! 🚀🌟"
            )
            
    # Send all greetings to all group chats
    for chat_id in chat_ids:
        for greet in greetings:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=greet,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
