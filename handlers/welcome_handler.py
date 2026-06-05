from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.user import User, Setting
from models.audit import AuditLog

DEFAULT_WELCOME_MESSAGE = (
    "👋 Chào mừng {name} gia nhập nhóm!\n\n"
    "Mình là Office Bot — trợ lý nội bộ của team.\n"
    "Gõ /help để xem các lệnh mình có thể giúp.\n\n"
    "🎲 Random phân công — /random\n"
    "🏖 Xin nghỉ phép — /xinnghi\n"
    "📊 Vote nhanh — /vote\n"
    "👏 Tặng kudos — /kudos"
)

async def handle_welcome_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures the welcome message for this group."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args
    message_text = update.message.text
    
    # Check permissions (must be admin/approver in db, or chat admin)
    async with db_session() as session:
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
    is_admin = db_user is not None and db_user.role == 'admin'
    
    # Check if they are a chat administrator in Telegram
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ['administrator', 'creator']:
            is_admin = True
    except Exception:
        pass
        
    if not is_admin:
        await update.message.reply_text("❌ Chỉ Admin mới có quyền cấu hình tính năng chào mừng.")
        return
        
    if not args:
        await update.message.reply_text(
            "💡 **Cấu hình Welcome thành viên mới:**\n"
            "• `/welcome on` - Bật chào mừng thành viên mới.\n"
            "• `/welcome off` - Tắt chào mừng thành viên mới.\n"
            "• `/welcome message <Nội dung>` - Đổi nội dung tin nhắn chào mừng (Dùng `{name}` để chèn tên người mới).\n\n"
            "*Ví dụ:* `/welcome message Chào mừng {name} đến với ngôi nhà chung! 🎉`",
            parse_mode="Markdown"
        )
        return

    subcmd = args[0].lower()
    
    async with db_session() as session:
        if subcmd == "on" or subcmd == "off":
            active_val = "1" if subcmd == "on" else "0"
            stmt = select(Setting).where(and_(Setting.chat_id == chat_id, Setting.key == 'welcome_active'))
            res = await session.execute(stmt)
            setting = res.scalar_one_or_none()
            
            if setting:
                setting.value = active_val
            else:
                session.add(Setting(chat_id=chat_id, key='welcome_active', value=active_val))
                
            session.add(AuditLog(
                actor_id=user_id,
                action=f"welcome_toggle_{subcmd}",
                entity_type="settings",
                entity_id=chat_id
            ))
            
            status_str = "BẬT" if subcmd == "on" else "TẮT"
            await update.message.reply_text(f"✅ Đã **{status_str}** tin nhắn chào mừng thành viên mới cho nhóm này.")
            
        elif subcmd == "message":
            if len(args) < 2:
                await update.message.reply_text("❌ Vui lòng điền nội dung tin nhắn chào mừng.")
                return
                
            # Extract content after "/welcome message "
            content = message_text.split("message", 1)[1].strip()
            
            stmt = select(Setting).where(and_(Setting.chat_id == chat_id, Setting.key == 'welcome_message'))
            res = await session.execute(stmt)
            setting = res.scalar_one_or_none()
            
            if setting:
                setting.value = content
            else:
                session.add(Setting(chat_id=chat_id, key='welcome_message', value=content))
                
            session.add(AuditLog(
                actor_id=user_id,
                action="welcome_message_change",
                entity_type="settings",
                entity_id=chat_id
            ))
            
            await update.message.reply_text("✅ Đã cập nhật nội dung chào mừng thành viên mới thành công.")

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcomes new members when they join the group."""
    if not update.chat_member or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    
    # Check if a user has joined (transition from not a member to member)
    status_before = update.chat_member.old_chat_member.status
    status_after = update.chat_member.new_chat_member.status
    
    was_member = status_before in ['member', 'administrator', 'creator']
    is_member = status_after in ['member', 'administrator', 'creator']
    
    if not was_member and is_member:
        new_user = update.chat_member.new_chat_member.user
        if new_user.is_bot:
            return # Skip bots
            
        # Get settings
        async with db_session() as session:
            stmt_active = select(Setting).where(and_(Setting.chat_id == chat_id, Setting.key == 'welcome_active'))
            res_active = await session.execute(stmt_active)
            active_setting = res_active.scalar_one_or_none()
            
            # Default is active (1) unless explicitly disabled (0)
            is_active = active_setting is None or active_setting.value == "1"
            
            if not is_active:
                return
                
            stmt_msg = select(Setting).where(and_(Setting.chat_id == chat_id, Setting.key == 'welcome_message'))
            res_msg = await session.execute(stmt_msg)
            msg_setting = res_msg.scalar_one_or_none()
            
            welcome_tpl = msg_setting.value if msg_setting else DEFAULT_WELCOME_MESSAGE
            
            # Auto-register new member in user DB
            stmt_u = select(User).where(User.telegram_id == new_user.id)
            res_u = await session.execute(stmt_u)
            db_user = res_u.scalar_one_or_none()
            if not db_user:
                db_user = User(
                    telegram_id=new_user.id,
                    display_name=new_user.full_name,
                    username=new_user.username,
                    role='member'
                )
                session.add(db_user)
                
        # Send welcome message
        mention = f"@{new_user.username}" if new_user.username else new_user.full_name
        welcome_text = welcome_tpl.replace("{name}", mention)
        
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            parse_mode="Markdown"
        )
