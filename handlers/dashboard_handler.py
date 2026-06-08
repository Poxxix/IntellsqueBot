import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, func, and_
from models.database import db_session
from models.user import User
from models.leave import LeaveRequest
from handlers.admin_handler import check_is_admin
from handlers.leave_handler import format_leave_type

async def get_dashboard_metrics():
    """Helper to query dashboard statistics from DB."""
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Calculate start and end of current week
    today = datetime.datetime.now()
    start_of_week = (today - datetime.timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    end_of_week = (today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(days=6)).strftime("%Y-%m-%d")
    start_of_month = today.strftime("%Y-%m-01")
    
    async with db_session() as session:
        # Active users count
        stmt_users = select(func.count(User.id)).where(User.active == True)
        res_users = await session.execute(stmt_users)
        active_users = res_users.scalar() or 0
        
        # Pending leave requests
        stmt_pending = select(func.count(LeaveRequest.id)).where(LeaveRequest.status == 'pending')
        res_pending = await session.execute(stmt_pending)
        pending_count = res_pending.scalar() or 0
        
        # Leaves today
        stmt_today = select(func.count(LeaveRequest.id)).where(
            and_(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= today_str,
                LeaveRequest.end_date >= today_str
            )
        )
        res_today = await session.execute(stmt_today)
        leaves_today = res_today.scalar() or 0
        
        # Leaves this week
        stmt_week = select(func.count(LeaveRequest.id)).where(
            and_(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date >= start_of_week,
                LeaveRequest.start_date <= end_of_week
            )
        )
        res_week = await session.execute(stmt_week)
        leaves_week = res_week.scalar() or 0
        
        # Leaves this month
        stmt_month = select(func.count(LeaveRequest.id)).where(
            and_(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date >= start_of_month
            )
        )
        res_month = await session.execute(stmt_month)
        leaves_month = res_month.scalar() or 0
        
    return {
        "active_users": active_users,
        "pending_count": pending_count,
        "leaves_today": leaves_today,
        "leaves_week": leaves_week,
        "leaves_month": leaves_month
    }

def get_dashboard_keyboard():
    """Generates the inline keyboard for dashboard navigation."""
    keyboard = [
        [
            InlineKeyboardButton("⏳ Duyệt Đơn Chờ", callback_data="dash_pending"),
            InlineKeyboardButton("📁 Xuất CSV", callback_data="dash_export")
        ],
        [
            InlineKeyboardButton("👥 Thành Viên", callback_data="dash_members"),
            InlineKeyboardButton("⚙️ Welcome Config", callback_data="dash_settings")
        ],
        [
            InlineKeyboardButton("📝 Tóm tắt Feedback (AI)", callback_data="dash_feedback_ai"),
            InlineKeyboardButton("🔄 Làm Mới", callback_data="dash_refresh")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def handle_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renders the admin dashboard (Private DM only)."""
    if not update.message or not update.effective_chat:
        return
        
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Lệnh này chỉ sử dụng được trong chat riêng tư (DM) với Bot.")
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        is_admin = await check_is_admin(session, user_id)
        if not is_admin:
            await update.message.reply_text("❌ Bạn không có quyền truy cập bảng điều hành.")
            return
            
    metrics = await get_dashboard_metrics()
    
    text = (
        f"📊 **BẢNG ĐIỀU HÀNH ADMIN (DASHBOARD)**\n\n"
        f"👥 **Nhân sự hoạt động:** `{metrics['active_users']}` thành viên\n"
        f"⏳ **Đơn nghỉ chờ duyệt:** `{metrics['pending_count']}` đơn\n"
        f"🏖 **Nghỉ phép hôm nay:** `{metrics['leaves_today']}` người\n"
        f"📅 **Đã duyệt tuần này:** `{metrics['leaves_week']}` lượt\n"
        f"📅 **Đã duyệt tháng này:** `{metrics['leaves_month']}` lượt\n\n"
        f"--- \n"
        f"Chọn một tùy chọn bên dưới để thực hiện quản trị:"
    )
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=get_dashboard_keyboard()
    )

async def handle_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists all pending leave requests (Admin/Approver DM only)."""
    if not update.message or not update.effective_chat:
        return
        
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Lệnh này chỉ sử dụng được trong chat riêng (DM) với Bot.")
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        # Check permissions
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
        if not db_user or db_user.role not in ['admin', 'approver']:
            await update.message.reply_text("❌ Bạn không có quyền phê duyệt đơn nghỉ phép.")
            return
            
        # Get pending requests
        stmt = select(LeaveRequest).where(LeaveRequest.status == 'pending').order_by(LeaveRequest.id.asc())
        res = await session.execute(stmt)
        requests = res.scalars().all()
        
    if not requests:
        await update.message.reply_text("🟢 Hiện không có đơn xin nghỉ phép nào đang chờ duyệt.")
        return
        
    await update.message.reply_text(f"⏳ Tìm thấy `{len(requests)}` đơn xin nghỉ phép đang chờ xử lý:")
    
    for r in requests:
        date_str = r.start_date if r.start_date == r.end_date else f"từ {r.start_date} đến {r.end_date}"
        type_str = format_leave_type(r.leave_type)
        
        text = (
            f"📋 **ĐƠN XIN NGHỈ PHÉP** (Mã đơn: #{r.id})\n\n"
            f"👤 **Nhân viên:** {r.user_name}\n"
            f"🏖 **Loại nghỉ:** {type_str}\n"
            f"📅 **Thời gian:** {date_str}\n"
            f"📝 **Lý do:** {r.reason or 'Không có lý do'}\n"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Duyệt", callback_data=f"leave_approve:{r.id}"),
                InlineKeyboardButton("❌ Từ chối", callback_data=f"leave_reject:{r.id}")
            ]
        ]
        
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes callback queries starting with 'dash_' from the admin dashboard."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    async with db_session() as session:
        is_admin = await check_is_admin(session, user_id)
        if not is_admin:
            await context.bot.send_message(chat_id=user_id, text="❌ Bạn không có quyền sử dụng chức năng này.")
            return
            
    if data == "dash_refresh" or data == "dash_main":
        metrics = await get_dashboard_metrics()
        text = (
            f"📊 **BẢNG ĐIỀU HÀNH ADMIN (DASHBOARD)**\n\n"
            f"👥 **Nhân sự hoạt động:** `{metrics['active_users']}` thành viên\n"
            f"⏳ **Đơn nghỉ chờ duyệt:** `{metrics['pending_count']}` đơn\n"
            f"🏖 **Nghỉ phép hôm nay:** `{metrics['leaves_today']}` người\n"
            f"📅 **Đã duyệt tuần này:** `{metrics['leaves_week']}` lượt\n"
            f"📅 **Đã duyệt tháng này:** `{metrics['leaves_month']}` lượt\n\n"
            f"--- \n"
            f"Chọn một tùy chọn bên dưới để thực hiện quản trị:"
        )
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_dashboard_keyboard())
        
    elif data == "dash_feedback_ai":
        from models.feedback import Feedback
        from config import AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
        
        async with db_session() as session:
            stmt = select(Feedback).order_by(Feedback.id.desc()).limit(15)
            res = await session.execute(stmt)
            feedbacks = res.scalars().all()
            
        if not feedbacks:
            keyboard = [[InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")]]
            await query.edit_message_text(
                "🟢 **Chưa có góp ý ẩn danh nào trong cơ sở dữ liệu để tóm tắt.**",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            keyboard = [[InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")]]
            await query.edit_message_text(
                "🔌 **Trợ lý AI chưa được kích hoạt. Vui lòng thiết lập AWS_ACCESS_KEY_ID và AWS_SECRET_ACCESS_KEY trên Railway để sử dụng tính năng này.**",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        fb_texts = []
        for fb in feedbacks:
            fb_texts.append(f"- [{fb.created_at}] Mã #{fb.id}: {fb.content}")
        fb_context = "\n".join(fb_texts)
        
        prompt = (
            "Dưới đây là danh sách các góp ý ẩn danh mới nhất của nhân viên trong tuần/tháng. "
            "Hãy đóng vai Trợ lý Cây Hài Văn Phòng để viết một bản tóm tắt gửi riêng cho Sếp/Admin. "
            "Yêu cầu bản tóm tắt phải cực kỳ vui nhộn, có phần 'Giải mã thái độ' (dịch ngôn ngữ văn phòng sang ý nghĩa thực tế một cách hài hước) "
            "và phân loại độ giận dữ/độ khịa của nhân viên một cách lầy lội. Đừng làm lộ thông tin nhạy cảm của người gửi nếu có, và giữ đúng tinh thần của góp ý.\n\n"
            "Danh sách góp ý:\n"
            f"{fb_context}"
        )
        
        await query.edit_message_text("🤖 Trợ lý AI đang nghiên cứu thái độ nhân viên và viết báo cáo cho Sếp...")
        
        from services.ai import generate_ai_response
        response = await generate_ai_response(prompt)
        
        keyboard = [[InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")]]
        await query.message.reply_text(response, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "dash_pending":
        async with db_session() as session:
            stmt = select(LeaveRequest).where(LeaveRequest.status == 'pending').order_by(LeaveRequest.id.asc())
            res = await session.execute(stmt)
            requests = res.scalars().all()
            
        if not requests:
            keyboard = [[InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")]]
            await query.edit_message_text(
                "🟢 **Không có đơn chờ duyệt nào.**",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
            
        await query.edit_message_text("Các đơn xin nghỉ đang chờ duyệt đã được tải bên dưới. Vui lòng kiểm tra chat.")
        for r in requests:
            date_str = r.start_date if r.start_date == r.end_date else f"từ {r.start_date} đến {r.end_date}"
            type_str = format_leave_type(r.leave_type)
            
            text = (
                f"📋 **ĐƠN XIN NGHỈ PHÉP** (Mã đơn: #{r.id})\n\n"
                f"👤 **Nhân viên:** {r.user_name}\n"
                f"🏖 **Loại nghỉ:** {type_str}\n"
                f"📅 **Thời gian:** {date_str}\n"
                f"📝 **Lý do:** {r.reason or 'Không có lý do'}\n"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Duyệt", callback_data=f"leave_approve:{r.id}"),
                    InlineKeyboardButton("❌ Từ chối", callback_data=f"leave_reject:{r.id}")
                ]
            ]
            
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    elif data == "dash_export":
        text = (
            "📁 **XUẤT DỮ LIỆU NGHỈ PHÉP (CSV UTF-8 BOM)**\n\n"
            "Chọn khoảng thời gian cần xuất báo cáo nghỉ phép của nhân viên:"
        )
        keyboard = [
            [
                InlineKeyboardButton("📁 Báo cáo tuần này", callback_data="leave_csv_weekly"),
                InlineKeyboardButton("📁 Báo cáo tháng này", callback_data="leave_csv_monthly")
            ],
            [
                InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")
            ]
        ]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "dash_members":
        async with db_session() as session:
            stmt = select(User).order_by(User.display_name.asc())
            res = await session.execute(stmt)
            users = res.scalars().all()
            
        text = "⚙️ **DANH SÁCH THÀNH VIÊN VĂN PHÒNG**\n\n"
        for idx, u in enumerate(users):
            username_str = f"(@{u.username})" if u.username else ""
            active_str = "Active" if u.active else "Inactive"
            role_str = u.role.upper()
            status_emoji = "🟢" if u.status == "available" else "🔴"
            text += f"{idx+1}. **{u.display_name}** {username_str}\n"
            text += f"   • Trạng thái: {status_emoji} `{u.status}`\n"
            text += f"   • ID: `{u.telegram_id}` | Quyền: `{role_str}` | `{active_str}`\n\n"
            
        keyboard = [[InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "dash_settings":
        text = (
            "⚙️ **CÀI ĐẶT CHÀO MỪNG THÀNH VIÊN MỚI**\n\n"
            "Sử dụng các lệnh sau trong group chat để cấu hình tin nhắn chào mừng:\n"
            "• `/welcome active on|off` - Bật/Tắt chào mừng\n"
            "• `/welcome message <nội dung>` - Cập nhật nội dung tin nhắn chào mừng.\n\n"
            "Ví dụ:\n"
            "`/welcome message Chào mừng {name} gia nhập văn phòng!`"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Quay lại", callback_data="dash_main")]]
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
