from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func, and_
from models.database import db_session
from models.user import User
from models.spin import Kudos
from models.audit import AuditLog

async def handle_kudos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends kudos to a team member."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    giver = update.effective_user
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp gửi Kudos:**\n"
            "`/kudos @username [lý do ghi nhận]`\n\n"
            "*Ví dụ:* `/kudos @nguyena Cảm ơn vì đã giúp mình review pull request gấp!`",
            parse_mode="Markdown"
        )
        return
        
    target_mention = args[0]
    reason = " ".join(args[1:])
    
    if not target_mention.startswith("@"):
        await update.message.reply_text("❌ Hãy mention chính xác thành viên nhận (bắt đầu bằng dấu `@`).")
        return
        
    target_username = target_mention[1:].lower()
    
    # Giver cannot give kudos to themselves
    if giver.username and giver.username.lower() == target_username:
        await update.message.reply_text("❌ Bạn không thể tự gửi kudos cho chính mình!")
        return
        
    async with db_session() as session:
        # Check if receiver is in our database
        stmt = select(User).where(func.lower(User.username) == target_username)
        res = await session.execute(stmt)
        receiver = res.scalar_one_or_none()
        
        receiver_name = receiver.display_name if receiver else f"@{target_username}"
        receiver_id = receiver.telegram_id if receiver else None
        
        current_month = datetime.now().strftime("%Y-%m-%d")[:7] # YYYY-MM
        
        # Save kudos
        kudos_entry = Kudos(
            giver_id=giver.id,
            receiver_id=receiver_id,
            receiver_name=receiver_name,
            reason=reason or "Ghi nhận đóng góp",
            month=current_month
        )
        session.add(kudos_entry)
        await session.flush()
        
        # Audit Log
        session.add(AuditLog(
            actor_id=giver.id,
            action="give_kudos",
            entity_type="kudos",
            entity_id=kudos_entry.id
        ))
        
    giver_mention = f"@{giver.username}" if giver.username else giver.full_name
    text = (
        f"👏 **KUDOS RECEIVED!** 👏\n\n"
        f"👤 **Người gửi:** {giver.full_name} ({giver_mention})\n"
        f"🎯 **Người nhận:** {receiver_name} ({target_mention})\n"
        f"📝 **Lý do:** _\"{reason or 'Ghi nhận đóng góp xuất sắc!'}\"_\n\n"
        f"Cảm ơn bạn đã đóng góp cho team! 🌟"
    )
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_kudos_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the kudos monthly leaderboard."""
    if not update.message:
        return
        
    current_month = datetime.now().strftime("%Y-%m-%d")[:7] # YYYY-MM
    
    async with db_session() as session:
        # Query kudos count grouped by receiver name
        stmt = (
            select(Kudos.receiver_name, func.count(Kudos.id).label('kudos_count'))
            .where(Kudos.month == current_month)
            .group_by(Kudos.receiver_name)
            .order_by(func.count(Kudos.id).desc())
        )
        res = await session.execute(stmt)
        rows = res.all()
        
    if not rows:
        await update.message.reply_text(f"🏆 Chưa có Kudos nào được gửi trong tháng {current_month[-2:]}/{current_month[:4]}.")
        return
        
    text = f"🏆 **BẢNG VÀNG KUDOS (Tháng {current_month[-2:]}/{current_month[:4]})** 🏆\n\n"
    for idx, (name, count) in enumerate(rows):
        emoji = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else "✨"
        text += f"{emoji} {idx+1}. **{name}** — `{count}` kudos 👏\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")
