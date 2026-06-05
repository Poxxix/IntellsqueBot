from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, delete
from models.database import db_session
from models.info import InfoHub
from models.audit import AuditLog
from handlers.admin_handler import check_is_admin

async def handle_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles lookups or listing keys in the Info Hub."""
    if not update.message:
        return
        
    args = context.args
    
    async with db_session() as session:
        if not args:
            # List all available keys
            stmt = select(InfoHub.key).order_by(InfoHub.key.asc())
            res = await session.execute(stmt)
            keys = res.scalars().all()
            
            if not keys:
                await update.message.reply_text(
                    "ℹ️ **Kho thông tin nội bộ hiện đang trống.**\n\n"
                    "Admin có thể thêm thông tin bằng lệnh:\n"
                    "`/admin info add <tên_khóa> <nội dung>`",
                    parse_mode="Markdown"
                )
                return
                
            text = "ℹ️ **KHO THÔNG TIN NỘI BỘ VĂN PHÒNG**\n\n"
            text += "Sử dụng lệnh `/info <tên_khóa>` để tra cứu nhanh:\n"
            for k in keys:
                text += f"• `{k}`\n"
                
            text += "\n---\n⚙️ _Admin có thể cập nhật thông tin bằng lệnh `/admin info add/del`._"
            await update.message.reply_text(text, parse_mode="Markdown")
            return
            
        # Lookup key
        lookup_key = args[0].strip().lower()
        stmt = select(InfoHub).where(InfoHub.key == lookup_key)
        res = await session.execute(stmt)
        info = res.scalar_one_or_none()
        
        if not info:
            await update.message.reply_text(
                f"❌ Không tìm thấy thông tin cho khóa `{lookup_key}`.\n"
                "Gõ `/info` để xem danh sách các khóa có sẵn.",
                parse_mode="Markdown"
            )
            return
            
        text = f"ℹ️ **THÔNG TIN: {info.key.upper()}**\n\n{info.value}"
        await update.message.reply_text(text, parse_mode="Markdown")

async def handle_admin_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sub-router for '/admin info' commands (add, del). Called from admin router."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    args = context.args # e.g. ['info', 'add', 'wifi', 'pass123']
    
    if len(args) < 2:
        await update.message.reply_text(
            "⚙️ **CÚ PHÁP QUẢN TRỊ KHO THÔNG TIN:**\n\n"
            "• `/admin info add <tên_khóa> <nội dung>`\n"
            "• `/admin info del <tên_khóa>`",
            parse_mode="Markdown"
        )
        return
        
    action = args[1].lower()
    
    async with db_session() as session:
        # Check permission (redundant but safe)
        is_admin = await check_is_admin(session, user_id)
        if not is_admin:
            await update.message.reply_text("❌ Bạn không có quyền quản trị thông tin.")
            return
            
        if action == "add":
            if len(args) < 4:
                await update.message.reply_text("❌ Cú pháp sai. Hãy dùng: `/admin info add <tên_khóa> <nội dung>`.")
                return
                
            info_key = args[2].strip().lower()
            info_val = " ".join(args[3:]).strip()
            
            # Upsert logic
            stmt = select(InfoHub).where(InfoHub.key == info_key)
            res = await session.execute(stmt)
            info = res.scalar_one_or_none()
            
            if info:
                info.value = info_val
                act = "update_info"
            else:
                info = InfoHub(key=info_key, value=info_val)
                session.add(info)
                act = "add_info"
                
            await session.flush()
            
            session.add(AuditLog(
                actor_id=user_id,
                action=act,
                entity_type="info_hub",
                entity_id=info.id
            ))
            
            await update.message.reply_text(f"✅ Đã lưu thông tin cho khóa `{info_key}` thành công.")
            
        elif action == "del":
            if len(args) < 3:
                await update.message.reply_text("❌ Cú pháp sai. Hãy dùng: `/admin info del <tên_khóa>`.")
                return
                
            info_key = args[2].strip().lower()
            
            stmt = select(InfoHub).where(InfoHub.key == info_key)
            res = await session.execute(stmt)
            info = res.scalar_one_or_none()
            
            if not info:
                await update.message.reply_text(f"❌ Không tìm thấy thông tin cho khóa `{info_key}`.")
                return
                
            info_id = info.id
            await session.delete(info)
            
            session.add(AuditLog(
                actor_id=user_id,
                action="delete_info",
                entity_type="info_hub",
                entity_id=info_id
            ))
            
            await update.message.reply_text(f"✅ Đã xóa thông tin cho khóa `{info_key}`.")
            
        else:
            await update.message.reply_text("❌ Thao tác không hợp lệ. Chỉ chấp nhận `add` hoặc `del`.")
