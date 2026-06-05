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
        f"👋 **Chào mừng {name} đến với Office Bot v3.0!**\n\n"
        f"Tôi là Trợ lý số hóa hoạt động nội bộ văn phòng viết bằng Python.\n\n"
        f"🚀 **Các tính năng chính:**\n"
        f"1. 🎲 **Quay số ngẫu nhiên:** `/random`, `/random_role`, `/random_team`\n"
        f"2. 🏖 **Nghỉ phép bảo mật:** `/xinnghi`, `/nghihomnay` (Ẩn lý do trong group)\n"
        f"3. 🟢 **Trạng thái làm việc:** `/status` (Toggle available / no available), `/team_status`\n"
        f"4. ℹ️ **Tra cứu nội bộ:** `/info <tên_khóa>`\n"
        f"5. 📩 **Góp ý ẩn danh:** `/feedback <nội dung>` (Chỉ dùng trong DM)\n"
        f"6. 🔔 **Nhắc nhở:** `/remind`, `/reminders`\n"
        f"7. 📊 **Bình chọn nhanh:** `/vote`, `/react`\n\n"
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
        "📖 **HƯỚNG DẪN SỬ DỤNG OFFICE BOT v3.0**\n\n"
        "🎲 **1. Quay số phân công:**\n"
        "• `/random` - Chọn ngẫu nhiên 1 người đi làm hôm nay.\n"
        "• `/random_role` - Chia vai trò họp (Presenter, Note, Timekeeper).\n"
        "• `/random_team <N>` - Chia thành viên thành N đội.\n"
        "• `/spin_history` - Xem lịch sử quay số.\n\n"
        "🏖 **2. Nghỉ phép (Bảo mật):**\n"
        "• `/xinnghi` - Hiện menu xin nghỉ phép nhanh trong DM.\n"
        "• `/xinnghi sang|chieu|ngay YYYY-MM-DD [lý do]` - Đăng ký nghỉ ngày cụ thể.\n"
        "• `/xinnghi tu YYYY-MM-DD den YYYY-MM-DD [lý do]` - Đăng ký nghỉ nhiều ngày.\n"
        "• `/nghihomnay` - Danh sách người nghỉ phép hôm nay (Lý do được ẩn).\n"
        "• `/huy_nghi` - Hủy đơn nghỉ phép đang chờ duyệt (DM chỉ định).\n\n"
        "🟢 **3. Trạng thái hoạt động (Team Status):**\n"
        "• `/status` - Chuyển đổi qua lại giữa `available` và `no available`.\n"
        "• `/status available|no available` - Đặt trạng thái cụ thể.\n"
        "• `/team_status` - Xem bảng trạng thái làm việc của toàn nhóm.\n\n"
        "ℹ️ **4. Kho thông tin nội bộ:**\n"
        "• `/info` - Liệt kê danh sách các khóa thông tin khả dụng.\n"
        "• `/info <tên_khóa>` - Tra cứu thông tin cụ thể (Ví dụ: `/info wifi`).\n\n"
        "📩 **5. Góp ý ẩn danh (DM Bot):**\n"
        "• `/feedback <nội dung>` - Gửi góp ý ẩn danh đến Ban quản trị (Không lưu thông tin tài khoản của bạn).\n\n"
        "🔔 **6. Nhắc nhở:**\n"
        "• `/remind HH:MM [nội dung]` - Hẹn giờ nhắc nhở hôm nay.\n"
        "• `/remind [số][s|m|h] [nội dung]` - Hẹn giờ đếm ngược (s: giây, m: phút, h: giờ).\n"
        "• `/remind every [day|monday|1st] HH:MM [nội dung]` - Thiết lập nhắc nhở lặp lại.\n"
        "• `/reminders` - Quản lý danh sách nhắc nhở của nhóm.\n\n"
        "📊 **7. Bình chọn & Reaction:**\n"
        "• `/vote \"Tiêu đề\" \"P.Án 1\" \"P.Án 2\" ...` - Tạo cuộc bình chọn nhanh.\n"
        "• `/react` (Reply tin nhắn) - Gắn bảng 👍, 👎, 🤔 vào tin nhắn được reply."
    )
    
    if role in ['admin', 'approver'] or is_config_admin:
        text += (
            "\n\n💼 **Lệnh cho Quản lý / Approver:**\n"
            "• Phê duyệt nghỉ phép trực tiếp qua nút bấm Bot gửi riêng.\n"
            "• `/pending` - Xem danh sách đơn xin nghỉ phép đang chờ duyệt.\n"
            "• `/digest on|off` / `/digest time HH:MM` - Cấu hình bản tin sáng.\n"
            "• `/welcome active on|off` - Bật/tắt lời chào người mới."
        )
        
    if role == 'admin' or is_config_admin:
        text += (
            "\n\n⚙️ **Lệnh cho Admin:**\n"
            "• `/admin` - Bảng điều khiển admin qua dòng lệnh.\n"
            "• `/dashboard` - Bảng điều khiển Admin Dashboard dạng phím bấm trong DM.\n"
            "• `/export nghi` - Xuất toàn bộ đơn nghỉ phép thành file CSV (DM Admin)."
        )
        
    await update.message.reply_text(text, parse_mode="Markdown")
