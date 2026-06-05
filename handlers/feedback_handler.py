import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from models.database import db_session
from models.user import User
from models.feedback import Feedback
from config import ADMIN_IDS

async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles submission of anonymous feedback from users via private DM."""
    if not update.message or not update.effective_chat:
        return
        
    chat_type = update.effective_chat.type
    if chat_type != 'private':
        # Delete message if in group to protect user privacy (if bot has admin permissions)
        try:
            await update.message.delete()
        except Exception:
            pass
            
        await update.message.reply_text(
            "❌ Để bảo vệ quyền riêng tư và ẩn danh, lệnh `/feedback` chỉ hoạt động trong chat riêng (DM) với Bot.\n"
            "Vui lòng nhấn vào Bot và gửi tin nhắn tại đó."
        )
        return
        
    args = context.args
    if not args:
        await update.message.reply_text(
            "💡 **CÚ PHÁP GỬI GÓP Ý ẨN DANH:**\n"
            "`/feedback <nội dung góp ý>`\n\n"
            "Ví dụ: `/feedback Đề xuất mua thêm đồ ăn nhẹ cho tủ lạnh văn phòng.`",
            parse_mode="Markdown"
        )
        return
        
    feedback_content = " ".join(args).strip()
    now_str = datetime.datetime.now().strftime("%H:%M %d/%m")
    
    async with db_session() as session:
        # Create anonymous feedback (no user_id stored)
        new_feedback = Feedback(
            content=feedback_content,
            created_at=now_str
        )
        session.add(new_feedback)
        await session.flush()
        
        # Get all Admins
        stmt = select(User).where(User.role == 'admin')
        res = await session.execute(stmt)
        admins = res.scalars().all()
        
    # Send notification to admins
    admin_text = (
        f"📩 **GÓP Ý ẨN DANH MỚI** (Mã: #{new_feedback.id})\n\n"
        f"\"{feedback_content}\"\n\n"
        f"📅 _Nhận lúc: {now_str}_"
    )
    
    # Notify hardcoded admins as well just in case they are not in User table
    admin_chat_ids = set([adm.telegram_id for adm in admins if adm.active])
    for aid in ADMIN_IDS:
        admin_chat_ids.add(aid)
        
    sent_count = 0
    for ac_id in admin_chat_ids:
        try:
            await context.bot.send_message(
                chat_id=ac_id,
                text=admin_text,
                parse_mode="Markdown"
            )
            sent_count += 1
        except Exception:
            pass
            
    await update.message.reply_text(
        "✅ **Đã gửi góp ý thành công!**\n"
        "Góp ý của bạn đã được chuyển đến Ban Quản trị ẩn danh hoàn toàn. Cảm ơn sự đóng góp của bạn.",
        parse_mode="Markdown"
    )
