import re
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.user import User, Setting
from models.audit import AuditLog
from services.digest import build_daily_digest
from config import DIGEST_TIME

async def handle_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures or previews the daily morning digest."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args
    message_text = update.message.text
    
    # Check permissions
    async with db_session() as session:
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
    is_admin = db_user is not None and db_user.role in ['admin', 'approver']
    
    # Check if they are a chat administrator in Telegram
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            is_admin = True
    except Exception:
        pass
        
    if not args:
        await update.message.reply_text(
            "💡 **Cấu hình Daily Digest (v2.0):**\n"
            "• `/digest on` - Bật bản tin tóm tắt buổi sáng cho nhóm này.\n"
            "• `/digest off` - Tắt bản tin tóm tắt buổi sáng.\n"
            "• `/digest time HH:MM` - Thay đổi giờ gửi bản tin tự động (Admin).\n"
            "• `/digest preview` - Xem trước nội dung tóm tắt ngay bây giờ.",
            parse_mode="Markdown"
        )
        return

    subcmd = args[0].lower()

    if subcmd == "preview":
        today_str = datetime.now().strftime("%Y-%m-%d")
        async with db_session() as session:
            digest_text = await build_daily_digest(session, chat_id, today_str)
        await update.message.reply_text(digest_text, parse_mode="Markdown")
        return

    if not is_admin:
        await update.message.reply_text("❌ Chỉ Admin hoặc Quản trị viên mới được phép thay đổi cấu hình Daily Digest.")
        return

    async with db_session() as session:
        if subcmd == "on" or subcmd == "off":
            active_val = "1" if subcmd == "on" else "0"
            stmt = select(Setting).where(and_(Setting.chat_id == chat_id, Setting.key == 'digest_active'))
            res = await session.execute(stmt)
            setting = res.scalar_one_or_none()
            
            if setting:
                setting.value = active_val
            else:
                session.add(Setting(chat_id=chat_id, key='digest_active', value=active_val))
                
            session.add(AuditLog(
                actor_id=user_id,
                action=f"digest_toggle_{subcmd}",
                entity_type="settings",
                entity_id=chat_id
            ))
            
            status_str = "BẬT" if subcmd == "on" else "TẮT"
            await update.message.reply_text(f"✅ Đã **{status_str}** bản tin tóm tắt buổi sáng cho nhóm này.")
            
        elif subcmd == "time":
            if len(args) < 2 or not re.match(r'^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$', args[1]):
                await update.message.reply_text("❌ Định dạng giờ không hợp lệ. Vui lòng điền dạng HH:MM (Ví dụ: `/digest time 08:30`).")
                return
                
            time_str = args[1]
            stmt = select(Setting).where(and_(Setting.chat_id == chat_id, Setting.key == 'digest_time'))
            res = await session.execute(stmt)
            setting = res.scalar_one_or_none()
            
            if setting:
                setting.value = time_str
            else:
                session.add(Setting(chat_id=chat_id, key='digest_time', value=time_str))
                
            session.add(AuditLog(
                actor_id=user_id,
                action="digest_time_change",
                entity_type="settings",
                entity_id=chat_id,
                meta_data=time_str
            ))
            
            await update.message.reply_text(f"✅ Đã cập nhật thời gian gửi bản tin tóm tắt hàng ngày thành: `{time_str}`.")
        else:
            await update.message.reply_text("❌ Lệnh digest không hợp lệ.")

async def daily_digest_scheduler_job(context: ContextTypes.DEFAULT_TYPE):
    """Background job running every minute to trigger digests for active groups."""
    now = datetime.now()
    current_time_str = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    
    async with db_session() as session:
        # Find all active digest settings
        stmt = select(Setting).where(and_(Setting.key == 'digest_active', Setting.value == '1'))
        res = await session.execute(stmt)
        active_digests = res.scalars().all()
        
        for dig in active_digests:
            # Check custom time for this chat, default to config DIGEST_TIME
            stmt_time = select(Setting).where(and_(Setting.chat_id == dig.chat_id, Setting.key == 'digest_time'))
            res_time = await session.execute(stmt_time)
            time_setting = res_time.scalar_one_or_none()
            
            target_time = time_setting.value if time_setting else DIGEST_TIME
            
            if target_time == current_time_str:
                # Build and send digest
                try:
                    digest_text = await build_daily_digest(session, dig.chat_id, today_str)
                    await context.bot.send_message(
                        chat_id=dig.chat_id,
                        text=digest_text,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Error sending daily digest to chat {dig.chat_id}: {e}")
