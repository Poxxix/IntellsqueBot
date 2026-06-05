from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from models.database import db_session
from models.user import User
from config import ADMIN_IDS

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets the user and gives an introduction to the bot."""
    if not update.message:
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        db_user = res.scalar_one_or_none()
        
    name = db_user.display_name if db_user else update.effective_user.full_name
    
    text = (
        f"👋 **Chào mừng {name} đến với Office Bot v2.0!**\n\n"
        f"Tôi là Trợ lý số hóa hoạt động nội bộ văn phòng viết bằng Python.\n\n"
        f"🚀 **Các tính năng chính:**\n"
        f"1. 🎲 **Quay số ngẫu nhiên:** `/random`, `/random_role`, `/random_team`\n"
        f"2. 🏖 **Xin nghỉ phép:** `/xinnghi`, `/nghihomnay`\n"
        f"3. 📊 **Bình chọn & Phản hồi:** `/vote`, `/react`\n"
        f"4. 👏 **Ghi nhận Kudos:** `/kudos`, `/kudos_board`\n"
        f"5. 🔔 **Nhắc nhở công việc:** `/remind`, `/reminders`\n"
        f"6. 📋 **Quản lý Task:** `/task`, `/mytask`\n\n"
        f"Gõ `/help` để xem chi tiết hướng dẫn và tất cả các lệnh!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Provides a detailed list of available commands based on user role."""
    if not update.message:
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        db_user = res.scalar_one_or_none()
        
    role = db_user.role if db_user else 'member'
    is_config_admin = user_id in ADMIN_IDS
    
    text = (
        "📖 **HƯỚNG DẪN SỬ DỤNG OFFICE BOT v2.0**\n\n"
        "🎲 **1. Module Random phân công:**\n"
        "• `/random` - Quay ngẫu nhiên 1 người đi làm hôm nay.\n"
        "• `/random_role` - Chia vai trò họp (Presenter, Note, Timekeeper).\n"
        "• `/random_team <N>` - Chia thành viên làm N đội.\n"
        "• `/spin_history` - Xem lịch sử quay số.\n\n"
        "🏖 **2. Module Nghỉ phép:**\n"
        "• `/xinnghi [sang|chieu|ngay|tu...]` - Đăng ký nghỉ phép.\n"
        "• `/nghihomnay` - Xem ai nghỉ phép hôm nay.\n"
        "• `/huy_nghi <ID>` - Hủy đơn xin nghỉ phép.\n\n"
        "📊 **3. Module Vote & Reaction:**\n"
        "• `/vote \"Tiêu đề\" \"Phương án 1\" ...` - Tạo bình chọn.\n"
        "• `/react` - Reply tin nhắn để tạo bảng 👍👎🤔.\n\n"
        "👏 **4. Module Kudos:**\n"
        "• `/kudos @username [Lý do]` - Ghi nhận đóng góp.\n"
        "• `/kudos_board` - Bảng vàng xếp hạng kudos tháng.\n\n"
        "🔔 **5. Module Nhắc nhở:**\n"
        "• `/remind HH:MM [nội dung]` - Nhắc nhở một lần.\n"
        "• `/remind [số][s|m|h] [nội dung]` - Hẹn giờ đếm ngược.\n"
        "• `/remind every [day|monday|1st] HH:MM [nội dung]` - Lặp định kỳ.\n"
        "• `/reminders` - Quản lý danh sách nhắc nhở.\n\n"
        "📋 **6. Module Task:**\n"
        "• `/task add \"Tên\" @username` - Giao việc.\n"
        "• `/task list` / `/mytask` - Xem danh sách task.\n"
        "• `/task done <ID>` / `/task del <ID>` - Hoàn thành / Xóa.\n\n"
        "🎂 **7. Sinh nhật & Ngày gia nhập:**\n"
        "• `/birthday set DD/MM` / `/birthday list` - Cài đặt sinh nhật.\n"
        "• `/joined set DD/MM/YYYY` - Cài đặt ngày vào công ty.\n"
        "• `/digest preview` - Preview bản tin buổi sáng."
    )
    
    if role in ['admin', 'approver'] or is_config_admin:
        text += (
            "\n\n💼 **Lệnh cho Approver/Admin:**\n"
            "• Phê duyệt nghỉ phép trực tiếp qua nút bấm Bot gửi riêng.\n"
            "• `/digest on|off` / `/digest time HH:MM` - Bản tin sáng.\n"
            "• `/welcome on|off` / `/welcome message <text>` - Welcome người mới."
        )
        
    if role == 'admin' or is_config_admin:
        text += (
            "\n\n⚙️ **Lệnh cho Admin:**\n"
            "• `/admin` - Bảng điều khiển admin.\n"
            "• `/export [nghi|kudos]` - Xuất file CSV UTF-8 BOM."
        )
        
    await update.message.reply_text(text, parse_mode="Markdown")
