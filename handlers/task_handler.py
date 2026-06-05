import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, or_
from models.database import db_session
from models.user import User
from models.task import Task
from models.audit import AuditLog

# Helper to format task listing
def format_task(t: Task, assignee_name: str) -> str:
    created_date = t.created_at.split()[0] if t.created_at else ""
    assignee_str = f"👤 Giao cho: **{assignee_name}**" if assignee_name else "👤 Giao cho: **Chưa phân công**"
    deadline_str = f"📅 Hạn chót: `{t.deadline}`" if t.deadline else "📅 Hạn chót: **Không có**"
    return f"📌 **[Task #{t.id}] {t.title}**\n   • {assignee_str} | {deadline_str} | Trạng thái: `{t.status.upper()}`"

async def handle_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for all /task commands."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    args = context.args
    message_text = update.message.text
    
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp Quản lý Task nhẹ (v2.0):**\n\n"
            "1️⃣ **Tạo Task mới:**\n"
            "• `/task add \"Tên task\" [@assignee]` - Giao việc cho thành viên (Hạn chót mặc định 7 ngày).\n\n"
            "2️⃣ **Xem danh sách Task:**\n"
            "• `/task list` - Danh sách các task đang mở trong nhóm.\n"
            "• `/mytask` - Danh sách các task được giao cho bản thân.\n"
            "• `/task overdue` - Các task đã quá hạn chót.\n\n"
            "3️⃣ **Hoàn thành / Xóa Task:**\n"
            "• `/task done <ID>` - Đánh dấu hoàn thành task.\n"
            "• `/task del <ID>` - Xóa task (Chỉ người tạo hoặc Admin mới xóa được).",
            parse_mode="Markdown"
        )
        return

    subcommand = args[0].lower()

    # 1. ADD TASK: /task add "Tên task" [@assignee]
    if subcommand == "add":
        # Extract quoted text
        quoted = re.findall(r'"([^"]*)"', message_text)
        title = quoted[0] if quoted else ""
        
        # If no quote, reconstruct title from remaining args except assignee
        assignee_username = None
        
        # Find mention in args
        for arg in args[1:]:
            if arg.startswith("@"):
                assignee_username = arg[1:].lower()
                break
                
        if not title:
            # Reconstruct title from arguments (excluding subcmd and mentions)
            title_parts = [a for a in args[1:] if not a.startswith("@") and not a.startswith('"')]
            title = " ".join(title_parts)
            
        if not title:
            await update.message.reply_text("❌ Tên task không được để trống. Ví dụ: `/task add \"Thiết kế UI\" @nguyena`")
            return
            
        # Default deadline: 7 days
        deadline_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        
        async with db_session() as session:
            assignee_id = None
            assignee_name = ""
            
            if assignee_username:
                stmt = select(User).where(User.username == assignee_username)
                res = await session.execute(stmt)
                assignee_user = res.scalar_one_or_none()
                if assignee_user:
                    assignee_id = assignee_user.telegram_id
                    assignee_name = assignee_user.display_name
                else:
                    assignee_name = f"@{assignee_username}"
                    
            task = Task(
                title=title,
                assignee_id=assignee_id,
                created_by=user_id,
                deadline=deadline_date,
                status='open',
                chat_id=chat_id
            )
            session.add(task)
            await session.flush()
            
            # Audit
            session.add(AuditLog(
                actor_id=user_id,
                action="add_task",
                entity_type="tasks",
                entity_id=task.id
            ))
            
        assignee_notify = f"giao cho {assignee_name}" if assignee_name else "chưa phân công"
        await update.message.reply_text(
            f"✅ **Đã tạo Task thành công!** (ID: #{task.id})\n"
            f"• Nội dung: **{title}**\n"
            f"• Giao cho: **{assignee_name or 'Chưa phân công'}**\n"
            f"• Hạn chót (7 ngày): `{deadline_date}`"
        )

    # 2. LIST TASKS: /task list
    elif subcommand == "list":
        async with db_session() as session:
            stmt = select(Task).where(
                and_(
                    Task.chat_id == chat_id,
                    Task.status == 'open'
                )
            ).order_by(Task.id.asc())
            res = await session.execute(stmt)
            tasks = res.scalars().all()
            
            if not tasks:
                await update.message.reply_text("🟢 Nhóm này hiện không có task nào đang mở.")
                return
                
            text = f"📋 **DANH SÁCH TASK ĐANG MỞ ({len(tasks)} tasks)** 📋\n\n"
            for t in tasks:
                assignee_name = "Chưa phân công"
                if t.assignee_id:
                    stmt_u = select(User).where(User.telegram_id == t.assignee_id)
                    res_u = await session.execute(stmt_u)
                    u = res_u.scalar_one_or_none()
                    if u:
                        assignee_name = u.display_name
                        
                text += format_task(t, assignee_name) + "\n\n"
                
            await update.message.reply_text(text, parse_mode="Markdown")

    # 3. TASK DONE: /task done <ID>
    elif subcommand == "done":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("💡 Cú pháp: `/task done <ID>` (Ví dụ: `/task done 3`).")
            return
            
        task_id = int(args[1])
        async with db_session() as session:
            task = await session.get(Task, task_id)
            if not task:
                await update.message.reply_text(f"❌ Không tìm thấy task #{task_id}.")
                return
                
            # Check permissions (creator, assignee, or admin)
            stmt_u = select(User).where(User.telegram_id == user_id)
            res_u = await session.execute(stmt_u)
            db_user = res_u.scalar_one_or_none()
            
            is_admin = db_user is not None and db_user.role == 'admin'
            if task.created_by != user_id and task.assignee_id != user_id and not is_admin:
                await update.message.reply_text("❌ Bạn không có quyền đánh dấu hoàn thành task này (chỉ người tạo, người nhận hoặc Admin mới được phép).")
                return
                
            if task.status != 'open':
                await update.message.reply_text(f"❌ Task này đã ở trạng thái `{task.status}`.")
                return
                
            task.status = 'done'
            
            session.add(AuditLog(
                actor_id=user_id,
                action="complete_task",
                entity_type="tasks",
                entity_id=task_id
            ))
            
            await update.message.reply_text(f"🎉 Đã hoàn thành Task: **\"{task.title}\"** (ID: #{task.id})! Chúc mừng cả nhà! 👏")

    # 4. DELETE TASK: /task del <ID>
    elif subcommand == "del":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("💡 Cú pháp: `/task del <ID>` (Ví dụ: `/task del 3`).")
            return
            
        task_id = int(args[1])
        async with db_session() as session:
            task = await session.get(Task, task_id)
            if not task:
                await update.message.reply_text(f"❌ Không tìm thấy task #{task_id}.")
                return
                
            # Check permissions (creator or admin)
            stmt_u = select(User).where(User.telegram_id == user_id)
            res_u = await session.execute(stmt_u)
            db_user = res_u.scalar_one_or_none()
            
            is_admin = db_user is not None and db_user.role == 'admin'
            if task.created_by != user_id and not is_admin:
                await update.message.reply_text("❌ Bạn không có quyền xóa task này (chỉ người tạo hoặc Admin mới được phép).")
                return
                
            task.status = 'cancelled' # Soft delete
            
            session.add(AuditLog(
                actor_id=user_id,
                action="delete_task",
                entity_type="tasks",
                entity_id=task_id
            ))
            
            await update.message.reply_text(f"🗑 Đã xóa Task: **\"{task.title}\"** (ID: #{task.id}) thành công.")

    # 5. OVERDUE TASKS: /task overdue
    elif subcommand == "overdue":
        today_str = datetime.now().strftime("%Y-%m-%d")
        async with db_session() as session:
            stmt = select(Task).where(
                and_(
                    Task.chat_id == chat_id,
                    Task.status == 'open',
                    Task.deadline < today_str
                )
            ).order_by(Task.deadline.asc())
            res = await session.execute(stmt)
            tasks = res.scalars().all()
            
            if not tasks:
                await update.message.reply_text("🟢 Tuyệt vời! Hiện tại không có task nào bị quá hạn trong nhóm.")
                return
                
            text = f"🚨 **DANH SÁCH TASK QUÁ HẠN ({len(tasks)} tasks)** 🚨\n\n"
            for t in tasks:
                assignee_name = "Chưa phân công"
                if t.assignee_id:
                    stmt_u = select(User).where(User.telegram_id == t.assignee_id)
                    res_u = await session.execute(stmt_u)
                    u = res_u.scalar_one_or_none()
                    if u:
                        assignee_name = u.display_name
                        
                text += format_task(t, assignee_name) + "\n\n"
                
            await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Lệnh không hợp lệ. Hãy chọn `add`, `list`, `done`, `del`, hoặc `overdue`.")

async def handle_mytask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays tasks assigned to the current user."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        stmt = select(Task).where(
            and_(
                Task.assignee_id == user_id,
                Task.status == 'open'
            )
        ).order_by(Task.deadline.asc())
        res = await session.execute(stmt)
        tasks = res.scalars().all()
        
    if not tasks:
        await update.message.reply_text("🟢 Chúc mừng! Bạn không có task nào được giao đang mở.")
        return
        
    text = f"📋 **DANH SÁCH TASK ĐƯỢC GIAO CỦA BẠN ({len(tasks)} tasks)** 📋\n\n"
    for t in tasks:
        # User display name is their own name
        text += format_task(t, update.effective_user.full_name) + "\n\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")
