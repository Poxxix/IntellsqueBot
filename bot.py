import os
import sys
import datetime
from telegram import Update, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)
from sqlalchemy import select, func

# Import configurations and db
from config import BOT_TOKEN, TZ, ADMIN_IDS
from models.database import init_db, db_session
from models.user import User

# Import handlers
from handlers.commands import handle_start, handle_help
from handlers.random_handler import (
    handle_random,
    handle_random_role,
    handle_random_team,
    handle_spin_history,
    handle_spin_callback
)
from handlers.leave_handler import (
    handle_xinnghi,
    handle_nghihomnay,
    handle_cancel_leave,
    handle_leave_callback,
    handle_phep,
    handle_admin_phep
)
from handlers.poll_handler import (
    handle_vote,
    handle_react,
    handle_vote_callback,
    handle_react_callback
)
from handlers.remind_handler import (
    handle_remind,
    handle_reminders,
    handle_rem_callback
)
from handlers.welcome_handler import handle_welcome_config, handle_new_member
from handlers.digest_handler import handle_digest, daily_digest_scheduler_job
from handlers.admin_handler import handle_admin
from handlers.report_handler import handle_report, handle_export
from handlers.status_handler import handle_status, handle_team_status
from handlers.info_handler import handle_info
from handlers.feedback_handler import handle_feedback
from handlers.dashboard_handler import (
    handle_dashboard,
    handle_pending,
    handle_dashboard_callback
)
from handlers.ai_handler import handle_ai_message

# Import background jobs
from services.scheduler import check_and_trigger_reminders_job

async def handle_track_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-track and register members when they post messages in the group or DMs."""
    if not update.effective_user or update.effective_user.is_bot:
        return
        
    user_id = update.effective_user.id
    username = update.effective_user.username
    display_name = update.effective_user.full_name
    
    async with db_session() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user:
            # First user in DB or ID in config.ADMIN_IDS gets admin role
            stmt_count = select(func.count(User.id))
            res_count = await session.execute(stmt_count)
            count = res_count.scalar() or 0
            
            role = 'admin' if (count == 0 or user_id in ADMIN_IDS) else 'member'
            
            new_user = User(
                telegram_id=user_id,
                display_name=display_name,
                username=username,
                role=role
            )
            session.add(new_user)
            print(f"Auto-tracked and registered new user: {display_name} ({user_id}) as {role}")
        else:
            # Sync display name and username if they changed
            if user.display_name != display_name or user.username != username:
                user.display_name = display_name
                user.username = username

async def post_init(application) -> None:
    """Post initialization for DB tables and suggested commands configuration."""
    await init_db()
    
    # Configure command suggestion menu for Telegram UI
    commands = [
        BotCommand("start", "Khởi động và giới thiệu bot"),
        BotCommand("help", "Xem hướng dẫn và danh sách tất cả các lệnh"),
        BotCommand("status", "Cập nhật trạng thái (available / no available)"),
        BotCommand("team_status", "Xem bảng trạng thái hoạt động cả nhóm"),
        BotCommand("xinnghi", "Đăng ký xin nghỉ phép (bảo mật lý do)"),
        BotCommand("nghihomnay", "Xem danh sách người nghỉ hôm nay"),
        BotCommand("huy_nghi", "Huỷ đơn xin nghỉ phép đang chờ duyệt"),
        BotCommand("phep", "Xem ngày nghỉ phép còn lại của bạn"),
        BotCommand("admin_phep", "Quản lý ngày nghỉ phép nhân viên (Admin only)"),
        BotCommand("info", "Tra cứu thông tin nội bộ (ví dụ: /info wifi)"),
        BotCommand("feedback", "Gửi góp ý ẩn danh đến Ban Quản trị (chỉ dùng trong DM)"),
        BotCommand("random", "Chọn ngẫu nhiên 1 người đi lấy cơm/phân công"),
        BotCommand("random_role", "Chia vai trò họp ngẫu nhiên"),
        BotCommand("random_team", "Chia nhóm ngẫu nhiên"),
        BotCommand("spin_history", "Xem lịch sử quay số phân công"),
        BotCommand("vote", "Tạo cuộc bình chọn nhanh"),
        BotCommand("react", "Tạo bảng 👍👎🤔 gắn vào tin nhắn được reply"),
        BotCommand("remind", "Hẹn giờ nhắc việc"),
        BotCommand("reminders", "Quản lý danh sách nhắc nhở"),
        BotCommand("admin", "Lệnh quản trị hệ thống (Admin only)"),
        BotCommand("dashboard", "Mở Admin Dashboard phím bấm (Admin DM)"),
        BotCommand("pending", "Xem đơn nghỉ chờ duyệt (Admin/Approver DM)"),
    ]
    await application.bot.set_my_commands(commands)
    print("Bot commands suggestion list configured successfully (v4.0 clean commands).")

def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not defined in environment variables or .env file.")
        sys.exit(1)
        
    print("Initializing Python Office Telegram Bot v4.0 (AI Edition)...")
    
    # Build Telegram Bot application
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    # 1. Register Message Handler for auto-tracking members
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_track_member), group=-1)
    
    # 2. Register Core Commands
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("admin", handle_admin))
    
    # 3. Register Module Commands
    # Random
    app.add_handler(CommandHandler("random", handle_random))
    app.add_handler(CommandHandler("random_role", handle_random_role))
    app.add_handler(CommandHandler("random_team", handle_random_team))
    app.add_handler(CommandHandler("spin_history", handle_spin_history))
    
    # Leaves
    app.add_handler(CommandHandler("xinnghi", handle_xinnghi))
    app.add_handler(CommandHandler("nghihomnay", handle_nghihomnay))
    app.add_handler(CommandHandler("huy_nghi", handle_cancel_leave))
    app.add_handler(CommandHandler("phep", handle_phep))
    app.add_handler(CommandHandler("admin_phep", handle_admin_phep))
    
    # Vote & React
    app.add_handler(CommandHandler("vote", handle_vote))
    app.add_handler(CommandHandler("react", handle_react))
    
    # Reminders
    app.add_handler(CommandHandler("remind", handle_remind))
    app.add_handler(CommandHandler("reminders", handle_reminders))
    
    # Welcome config
    app.add_handler(CommandHandler("welcome", handle_welcome_config))
    
    # Daily Digest
    app.add_handler(CommandHandler("digest", handle_digest))
    
    # Advanced Reports & Exports
    app.add_handler(CommandHandler("report", handle_report))
    app.add_handler(CommandHandler("export", handle_export))

    # Team Status
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(CommandHandler("team_status", handle_team_status))

    # Info Hub
    app.add_handler(CommandHandler("info", handle_info))

    # Feedback
    app.add_handler(CommandHandler("feedback", handle_feedback))

    # Admin Dashboard
    app.add_handler(CommandHandler("dashboard", handle_dashboard))
    app.add_handler(CommandHandler("pending", handle_pending))

    # 4. Callback Query Handlers (Buttons click)
    app.add_handler(CallbackQueryHandler(handle_spin_callback, pattern="^spin_"))
    app.add_handler(CallbackQueryHandler(handle_leave_callback, pattern="^leave_"))
    app.add_handler(CallbackQueryHandler(handle_vote_callback, pattern="^vote_"))
    app.add_handler(CallbackQueryHandler(handle_react_callback, pattern="^react_"))
    app.add_handler(CallbackQueryHandler(handle_rem_callback, pattern="^rem_"))
    app.add_handler(CallbackQueryHandler(handle_dashboard_callback, pattern="^dash_"))

    # 5. Welcoming New Members Handler
    app.add_handler(ChatMemberHandler(handle_new_member, ChatMemberHandler.CHAT_MEMBER))

    # 6. AI text conversation (mentions in group / text in DMs)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message))

    # 7. Configure JobQueue Scheduler
    jq = app.job_queue
    if jq:
        # Run every 60 seconds (check reminders and daily digests)
        jq.run_repeating(check_and_trigger_reminders_job, interval=60, first=10)
        jq.run_repeating(daily_digest_scheduler_job, interval=60, first=15)
        print("Background jobs and schedulers initialized successfully.")
    else:
        print("WARNING: JobQueue is disabled. Background reminders and digests will not function.")

    # 8. Start polling bot
    print("🚀 Python Office Bot v4.0 (AI Edition) is starting... Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == '__main__':
    main()
