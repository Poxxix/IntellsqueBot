import json
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from config import ADMIN_IDS
from models.database import db_session
from models.user import User, Setting
from models.spin import Kudos
from models.audit import AuditLog

# Helper to check if caller is admin
async def check_is_admin(session, user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    stmt = select(User).where(User.telegram_id == user_id)
    res = await session.execute(stmt)
    u = res.scalar_one_or_none()
    return u is not None and u.role == 'admin'

async def handle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for admin panel commands."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    args = context.args
    
    async with db_session() as session:
        is_admin = await check_is_admin(session, user_id)
        if not is_admin:
            await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh admin này.")
            return
            
        if not args:
            await update.message.reply_text(
                "⚙️ **BẢNG ĐIỀU KHIỂN ADMIN (v2.0):**\n\n"
                "• `/admin members` - Xem danh sách và trạng thái thành viên.\n"
                "• `/admin add_member @username display_name` - Thêm thủ công thành viên.\n"
                "• `/admin remove_member @username` - Xóa thành viên khỏi pool random.\n"
                "• `/admin set_approver @username` - Gán quyền duyệt nghỉ phép.\n"
                "• `/admin reset kudos` - Xóa sạch kudos tháng hiện tại.\n"
                "• `/admin broadcast <Nội dung>` - Gửi thông báo đến mọi group chat.",
                parse_mode="Markdown"
            )
            return

        subcmd = args[0].lower()

        # 1. VIEW MEMBERS: /admin members
        if subcmd == "members":
            stmt = select(User).order_by(User.display_name.asc())
            res = await session.execute(stmt)
            users = res.scalars().all()
            
            text = "⚙️ **DANH SÁCH THÀNH VIÊN HỆ THỐNG** ⚙️\n\n"
            for idx, u in enumerate(users):
                username_str = f"(@{u.username})" if u.username else ""
                lunch_str = "🍱 Cơm" if u.lunch_opt_in else "❌ Cơm"
                active_str = "🟢 Active" if u.active else "🔴 Inactive"
                text += f"{idx+1}. **{u.display_name}** {username_str}\n"
                text += f"   • Quyền: `{u.role.upper()}` | {active_str} | {lunch_str}\n"
                text += f"   • Telegram ID: `{u.telegram_id}`\n\n"
            await update.message.reply_text(text, parse_mode="Markdown")

        # 2. ADD MEMBER: /admin add_member @username display_name
        elif subcommand := subcmd == "add_member":
            if len(args) < 3 or not args[1].startswith("@"):
                await update.message.reply_text("❌ Cú pháp sai. Hãy dùng: `/admin add_member @username Tên hiển thị` (Ví dụ: `/admin add_member @nguyena Nguyễn Văn A`).")
                return
            username = args[1][1:].lower()
            display_name = " ".join(args[2:])
            
            # Since we don't have their telegram_id yet, we create a placeholder ID
            # Let's generate a temporary unique negative ID or ask them to start the bot
            # To be safe, we let them know it's a placeholder till they start the bot
            # Let's use a random unique big int
            import random as rand
            placeholder_id = -rand.randint(100000000, 999999999)
            
            # Check if username exists
            stmt = select(User).where(User.username == username)
            res = await session.execute(stmt)
            if res.scalar_one_or_none():
                await update.message.reply_text("❌ Thành viên này đã tồn tại trong hệ thống.")
                return
                
            user = User(
                telegram_id=placeholder_id,
                display_name=display_name,
                username=username,
                role='member'
            )
            session.add(user)
            await session.flush()
            
            session.add(AuditLog(
                actor_id=user_id,
                action="admin_add_member",
                entity_type="users",
                entity_id=user.id,
                meta_data=json.dumps({"username": username, "name": display_name})
            ))
            await update.message.reply_text(f"✅ Đã thêm thành viên **{display_name}** (@{username}) vào hệ thống.")

        # 3. REMOVE MEMBER: /admin remove_member @username
        elif subcmd == "remove_member":
            if len(args) < 2 or not args[1].startswith("@"):
                await update.message.reply_text("❌ Hãy điền đúng username. Ví dụ: `/admin remove_member @nguyena`.")
                return
            username = args[1][1:].lower()
            
            stmt = select(User).where(User.username == username)
            res = await session.execute(stmt)
            user = res.scalar_one_or_none()
            if not user:
                await update.message.reply_text(f"❌ Không tìm thấy thành viên @{username} trong hệ thống.")
                return
                
            user.active = False
            
            session.add(AuditLog(
                actor_id=user_id,
                action="admin_remove_member",
                entity_type="users",
                entity_id=user.id
            ))
            await update.message.reply_text(f"✅ Đã hủy kích hoạt (Inactivate) thành viên **{user.display_name}** (@{username}).")

        # 4. SET APPROVER: /admin set_approver @username
        elif subcmd == "set_approver":
            if len(args) < 2 or not args[1].startswith("@"):
                await update.message.reply_text("❌ Hãy điền đúng username. Ví dụ: `/admin set_approver @nguyena`.")
                return
            username = args[1][1:].lower()
            
            stmt = select(User).where(User.username == username)
            res = await session.execute(stmt)
            user = res.scalar_one_or_none()
            if not user:
                await update.message.reply_text(f"❌ Không tìm thấy thành viên @{username} trong hệ thống.")
                return
                
            user.role = 'approver'
            
            session.add(AuditLog(
                actor_id=user_id,
                action="admin_set_approver",
                entity_type="users",
                entity_id=user.id
            ))
            await update.message.reply_text(f"✅ Đã gán quyền duyệt nghỉ phép (`APPROVER`) cho **{user.display_name}** (@{username}).")

        # 5. RESET KUDOS: /admin reset kudos
        elif subcmd == "reset" and len(args) > 1 and args[1].lower() == "kudos":
            import datetime as dt
            current_month = dt.datetime.now().strftime("%Y-%m")
            
            # Delete all kudos in the current month
            from sqlalchemy import delete
            stmt_del = delete(Kudos).where(Kudos.month == current_month)
            await session.execute(stmt_del)
            
            session.add(AuditLog(
                actor_id=user_id,
                action="admin_reset_kudos",
                meta_data=json.dumps({"month": current_month})
            ))
            await update.message.reply_text(f"✅ Đã reset bảng vàng Kudos tháng hiện tại ({current_month}) thành công.")

        # 6. BROADCAST: /admin broadcast <Nội dung>
        elif subcmd == "broadcast":
            if len(args) < 2:
                await update.message.reply_text("❌ Hãy điền nội dung tin nhắn cần phát.")
                return
            content = update.message.text.split("broadcast", 1)[1].strip()
            
            # Query all group chats
            stmt_chats = select(Setting.chat_id).distinct()
            res_chats = await session.execute(stmt_chats)
            chat_ids = [c for c in res_chats.scalars().all() if c < 0] # only group chats
            
            if not chat_ids:
                await update.message.reply_text("⚠️ Hiện tại chưa có nhóm nào được lưu trữ trong DB để broadcast.")
                return
                
            broadcast_msg = f"📢 **THÔNG BÁO TỪ BAN QUẢN TRỊ** 📢\n\n{content}"
            sent_count = 0
            for cid in chat_ids:
                try:
                    await context.bot.send_message(
                        chat_id=cid,
                        text=broadcast_msg,
                        parse_mode="Markdown"
                    )
                    sent_count += 1
                except Exception:
                    pass
                    
            await update.message.reply_text(f"✅ Đã broadcast tin nhắn đến `{sent_count}` group chats.")
        else:
            await update.message.reply_text("❌ Lệnh admin phụ trợ không hợp lệ.")
