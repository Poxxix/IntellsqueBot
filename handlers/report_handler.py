import io
import calendar
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, or_, func
from models.database import db_session
from models.leave import LeaveRequest
from models.spin import SpinHistory, Kudos
from models.task import Task
from models.user import User
from services.export import generate_csv_with_bom
from handlers.leave_handler import format_leave_type

async def handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates various text-based reports for the group."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp lệnh /report (v2.0):**\n\n"
            "• `/report nghi tuan` - Báo cáo nghỉ phép tuần này.\n"
            "• `/report nghi thang` - Báo cáo nghỉ phép tháng này.\n"
            "• `/report kudos thang` - Thống kê Kudos tháng này.\n"
            "• `/report task` - Báo cáo trạng thái công việc trong nhóm.\n"
            "• `/report com thang` - Thống kê ai đi lấy cơm nhiều nhất tháng.",
            parse_mode="Markdown"
        )
        return

    report_type = args[0].lower()
    now = datetime.now()

    # 1. LEAVE REPORT
    if report_type == "nghi":
        if len(args) < 2:
            await update.message.reply_text("❌ Vui lòng chọn phạm vi: `/report nghi tuan` hoặc `/report nghi thang`.")
            return
            
        scope = args[1].lower()
        
        if scope == "tuan":
            start_week = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            end_week = (now + timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d")
            
            async with db_session() as session:
                stmt = select(LeaveRequest).where(
                    and_(
                        LeaveRequest.status == 'approved',
                        LeaveRequest.start_date <= end_week,
                        LeaveRequest.end_date >= start_week
                    )
                ).order_by(LeaveRequest.start_date.asc())
                res = await session.execute(stmt)
                leaves = res.scalars().all()
                
            text = f"📊 **BÁO CÁO NGHỈ PHÉP TUẦN NÀY** ({start_week} đến {end_week})\n\n"
            if not leaves:
                text += "🟢 Không có ai nghỉ phép trong tuần này."
            else:
                for idx, l in enumerate(leaves):
                    type_str = format_leave_type(l.leave_type)
                    date_str = f"từ {l.start_date} đến {l.end_date}" if l.start_date != l.end_date else l.start_date
                    text += f"{idx+1}. **{l.user_name}** — {type_str} ({date_str})\n"
            await update.message.reply_text(text, parse_mode="Markdown")

        elif scope == "thang":
            start_month = now.strftime("%Y-%m-01")
            last_day = calendar.monthrange(now.year, now.month)[1]
            end_month = now.strftime(f"%Y-%m-{last_day}")
            
            async with db_session() as session:
                stmt = select(LeaveRequest).where(
                    and_(
                        LeaveRequest.status == 'approved',
                        LeaveRequest.start_date <= end_month,
                        LeaveRequest.end_date >= start_month
                    )
                ).order_by(LeaveRequest.start_date.asc())
                res = await session.execute(stmt)
                leaves = res.scalars().all()
                
            text = f"📊 **BÁO CÁO NGHỈ PHÉP THÁNG NÀY** ({now.strftime('%m/%Y')})\n\n"
            if not leaves:
                text += "🟢 Không có ai nghỉ phép trong tháng này."
            else:
                for idx, l in enumerate(leaves):
                    type_str = format_leave_type(l.leave_type)
                    date_str = f"từ {l.start_date} đến {l.end_date}" if l.start_date != l.end_date else l.start_date
                    text += f"{idx+1}. **{l.user_name}** — {type_str} ({date_str})\n"
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Phạm vi không hợp lệ. Hãy chọn `tuan` hoặc `thang`.")

    # 2. KUDOS REPORT: /report kudos thang
    elif report_type == "kudos":
        current_month = now.strftime("%Y-%m")
        async with db_session() as session:
            stmt = (
                select(Kudos.receiver_name, func.count(Kudos.id).label('count'))
                .where(Kudos.month == current_month)
                .group_by(Kudos.receiver_name)
                .order_by(func.count(Kudos.id).desc())
            )
            res = await session.execute(stmt)
            rows = res.all()
            
        text = f"🏆 **BÁO CÁO KUDOS THÁNG {now.strftime('%m/%Y')}** 🏆\n\n"
        if not rows:
            text += "👏 Chưa có ai nhận Kudos nào trong tháng này."
        else:
            for idx, (name, count) in enumerate(rows):
                text += f"{idx+1}. **{name}** — `{count}` kudos 👏\n"
        await update.message.reply_text(text, parse_mode="Markdown")

    # 3. TASK REPORT: /report task
    elif report_type == "task":
        today_str = now.strftime("%Y-%m-%d")
        async with db_session() as session:
            # Open tasks
            stmt_open = select(func.count(Task.id)).where(and_(Task.chat_id == chat_id, Task.status == 'open'))
            res_open = await session.execute(stmt_open)
            open_count = res_open.scalar() or 0
            
            # Done tasks
            stmt_done = select(func.count(Task.id)).where(and_(Task.chat_id == chat_id, Task.status == 'done'))
            res_done = await session.execute(stmt_done)
            done_count = res_done.scalar() or 0
            
            # Overdue tasks
            stmt_overdue = select(func.count(Task.id)).where(
                and_(
                    Task.chat_id == chat_id,
                    Task.status == 'open',
                    Task.deadline < today_str
                )
            )
            res_overdue = await session.execute(stmt_overdue)
            overdue_count = res_overdue.scalar() or 0
            
        text = (
            f"📋 **BÁO CÁO CÔNG VIỆC NHÓM** 📋\n\n"
            f"• Task đang mở (Pending): `{open_count}`\n"
            f"• Task đã xong (Done): `{done_count}`\n"
            f"• Task trễ hạn (Overdue): `{overdue_count}` 🚨\n\n"
            f"💡 Gõ `/task list` để xem chi tiết danh sách task đang mở."
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    # 4. LUNCH DRAW REPORT: /report com thang
    elif report_type == "com":
        current_month = now.strftime("%Y-%m")
        async with db_session() as session:
            # Query draw count from spin history where result is the display name
            # We match using spin_type = 'random_member'
            stmt = (
                select(SpinHistory.result, func.count(SpinHistory.id).label('count'))
                .where(
                    and_(
                        SpinHistory.spin_type == 'random_member',
                        SpinHistory.created_at.like(f"{current_month}%")
                    )
                )
                .group_by(SpinHistory.result)
                .order_by(func.count(SpinHistory.id).desc())
            )
            res = await session.execute(stmt)
            rows = res.all()
            
        text = f"🍱 **THỐNG KÊ LẤY CƠM THÁNG {now.strftime('%m/%Y')}** 🍱\n\n"
        if not rows:
            text += "🟢 Chưa có ai đi lấy cơm qua bot trong tháng này."
        else:
            for idx, (name, count) in enumerate(rows):
                text += f"{idx+1}. **{name}** — `{count}` lần lấy cơm\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Loại báo cáo không hợp lệ. Hãy gõ `/report` để xem các lệnh.")

async def handle_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exports database tables to CSV format with UTF-8 BOM."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp Xuất dữ liệu (CSV):**\n"
            "• `/export nghi` - Xuất tất cả đơn xin nghỉ phép.\n"
            "• `/export kudos` - Xuất tất cả thông tin ghi nhận Kudos.",
            parse_mode="Markdown"
        )
        return

    export_type = args[0].lower()

    if export_type == "nghi":
        async with db_session() as session:
            stmt = select(LeaveRequest).order_by(LeaveRequest.id.asc())
            res = await session.execute(stmt)
            requests = res.scalars().all()
            
        if not requests:
            await update.message.reply_text("🫙 Chưa có dữ liệu nghỉ phép nào để xuất.")
            return
            
        headers = ["Mã đơn", "ID người xin", "Tên người xin", "Loại nghỉ", "Ngày bắt đầu", "Ngày kết thúc", "Trạng thái", "Người duyệt", "Lý do", "Ngày tạo"]
        rows = [
            [
                r.id, r.user_id, r.user_name, r.leave_type,
                r.start_date, r.end_date, r.status, r.approved_by or "",
                r.reason or "", r.created_at
            ]
            for r in requests
        ]
        
        csv_bytes = generate_csv_with_bom(headers, rows)
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(csv_bytes),
            filename=f"leave_requests_{datetime.now().strftime('%Y%m%d')}.csv",
            caption="📊 Gửi bạn file xuất dữ liệu nghỉ phép."
        )

    elif export_type == "kudos":
        async with db_session() as session:
            stmt = select(Kudos).order_by(Kudos.id.asc())
            res = await session.execute(stmt)
            kudos_list = res.scalars().all()
            
        if not kudos_list:
            await update.message.reply_text("🫙 Chưa có dữ liệu Kudos nào để xuất.")
            return
            
        headers = ["Mã Kudos", "ID người gửi", "ID người nhận", "Tên người nhận", "Lý do", "Tháng", "Ngày tạo"]
        rows = [
            [
                k.id, k.giver_id, k.receiver_id or "",
                k.receiver_name, k.reason or "", k.month, k.created_at
            ]
            for k in kudos_list
        ]
        
        csv_bytes = generate_csv_with_bom(headers, rows)
        await context.bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(csv_bytes),
            filename=f"kudos_list_{datetime.now().strftime('%Y%m%d')}.csv",
            caption="🏆 Gửi bạn file xuất dữ liệu ghi nhận Kudos."
        )
    else:
        await update.message.reply_text("❌ Loại xuất dữ liệu không hợp lệ. Vui lòng chọn `nghi` hoặc `kudos`.")
