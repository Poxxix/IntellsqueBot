import datetime
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from models.database import db_session
from models.user import User
from models.audit import AuditLog

async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Updates the user's operational status to either 'available' or 'no available'."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    display_name = update.effective_user.full_name
    username = update.effective_user.username
    args = context.args
    
    # Parse requested status
    requested_status = None
    if args:
        joined_args = " ".join(args).strip().lower()
        if joined_args in ["available"]:
            requested_status = "available"
        elif joined_args in ["no available", "no_available", "not_available", "no", "not"]:
            requested_status = "no available"
        else:
            await update.message.reply_text(
                "❌ Trạng thái không hợp lệ.\n"
                "Vui lòng sử dụng:\n"
                "• `/status available` để sẵn sàng làm việc\n"
                "• `/status no available` để báo vắng mặt\n"
                "• Hoặc chỉ gõ `/status` để tự động đổi qua lại.",
                parse_mode="Markdown"
            )
            return

    now_str = datetime.datetime.now().strftime("%H:%M %d/%m")
    
    async with db_session() as session:
        # Get or create user
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            # Register user
            user = User(
                telegram_id=user_id,
                display_name=display_name,
                username=username,
                role='member',
                status='available',
                status_updated_at=now_str
            )
            session.add(user)
            await session.flush()
            
        # Determine final status
        if requested_status is None:
            # Toggle logic
            if user.status == "available":
                final_status = "no available"
            else:
                final_status = "available"
        else:
            final_status = requested_status
            
        user.status = final_status
        user.status_updated_at = now_str
        
        # Log action
        session.add(AuditLog(
            actor_id=user_id,
            action=f"update_status_{final_status.replace(' ', '_')}",
            entity_type="users",
            entity_id=user.id
        ))
        
    status_emoji = "🟢" if final_status == "available" else "🔴"
    await update.message.reply_text(
        f"{status_emoji} Bạn đã cập nhật trạng thái hoạt động: **{final_status}** lúc `{now_str}`.",
        parse_mode="Markdown"
    )

async def handle_team_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays a list of all group members and their operational statuses."""
    if not update.message:
        return
        
    async with db_session() as session:
        stmt = select(User).where(User.active == True).order_by(User.display_name.asc())
        res = await session.execute(stmt)
        users = res.scalars().all()
        
    if not users:
        await update.message.reply_text("⚠️ Chưa có thành viên nào được lưu trong hệ thống.")
        return
        
    available_list = []
    not_available_list = []
    
    for u in users:
        time_info = f" _(Cập nhật: {u.status_updated_at})_" if u.status_updated_at else ""
        user_line = f"• **{u.display_name}**{time_info}"
        
        if u.status == "available":
            available_list.append(user_line)
        else:
            not_available_list.append(user_line)
            
    text = "👥 **BẢNG TRẠNG THÁI THÀNH VIÊN VĂN PHÒNG**\n\n"
    
    text += "🟢 **Sẵn sàng (available):**\n"
    if available_list:
        text += "\n".join(available_list)
    else:
        text += "_Không có ai_"
        
    text += "\n\n🔴 **Vắng mặt (no available):**\n"
    if not_available_list:
        text += "\n".join(not_available_list)
    else:
        text += "_Không có ai_"
        
    text += "\n\n---\n💡 _Dùng lệnh `/status` hoặc `/status [available|no available]` để cập nhật trạng thái của bạn._"
    
    await update.message.reply_text(text, parse_mode="Markdown")
