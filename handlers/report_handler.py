import io
import calendar
import datetime
from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.leave import LeaveRequest
from models.spin import SpinHistory
from models.user import User
from services.export import generate_csv_with_bom
from handlers.leave_handler import format_leave_type
from handlers.admin_handler import check_is_admin

async def handle_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates various text-based reports for the group (Leaves and Lunch only)."""
    if not update.message or not update.effective_chat:
        return
        
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "💡 **Cú pháp lệnh /report (v3.0):**\n\n"
            "• `/report nghi tuan` - Báo cáo nghỉ phép tuần này.\n"
            "• `/report nghi thang` - Báo cáo nghỉ phép tháng này.\n"
            "• `/report com thang` - Thống kê tần suất lấy cơm trong tháng.",
            parse_mode="Markdown"
        )
        return

    report_type = args[0].lower()
    now = datetime.datetime.now()

    # 1. LEAVE REPORT
    if report_type == "nghi":
        if len(args) < 2:
            await update.message.reply_text("❌ Vui lòng chọn phạm vi: `/report nghi tuan` hoặc `/report nghi thang`Scope.")
            return
            
        scope = args[1].lower()
        
        if scope == "tuan":
            start_week = (now - datetime.timedelta(days=now.weekday())).strftime("%Y-%m-%d")
            end_week = (now + datetime.timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d")
            
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

    # 2. LUNCH DRAW REPORT: /report com thang
    elif report_type == "com":
        current_month = now.strftime("%Y-%m")
        async with db_session() as session:
            # Query draw count from spin history where result is the display name
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
    """Exports database leaves to CSV format (Admin DM only)."""
    if not update.message or not update.effective_chat:
        return
        
    chat_type = update.effective_chat.type
    if chat_type != 'private':
        await update.message.reply_text("❌ Lệnh xuất dữ liệu (CSV) chỉ dùng được trong chat riêng (DM) với Bot để bảo vệ thông tin.")
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        is_admin = await check_is_admin(session, user_id)
        if not is_admin:
            await update.message.reply_text("❌ Bạn không có quyền xuất dữ liệu.")
            return
            
    args = context.args
    if not args or args[0].lower() != "nghi":
        await update.message.reply_text(
            "💡 **Cú pháp Xuất dữ liệu (CSV):**\n"
            "• `/export nghi` - Xuất toàn bộ danh sách đơn nghỉ phép.",
            parse_mode="Markdown"
        )
        return

    # Export all leaves
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
        chat_id=user_id,
        document=io.BytesIO(csv_bytes),
        filename=f"all_leave_requests_{datetime.datetime.now().strftime('%Y%m%d')}.csv",
        caption="📊 Gửi Admin file xuất toàn bộ dữ liệu nghỉ phép."
    )

async def handle_leave_csv_callback(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE):
    """Processes callback queries related to exporting CSVs from approval menus."""
    user_id = query.from_user.id
    data = query.data
    
    async with db_session() as session:
        # Check permissions (admins and approvers only)
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
        if not db_user or db_user.role not in ['admin', 'approver']:
            await query.answer("❌ Bạn không có quyền xuất báo cáo CSV.", show_alert=True)
            return
            
    now = datetime.datetime.now()
    
    # Header format
    headers = ["Mã đơn", "ID người xin", "Tên người xin", "Loại nghỉ", "Ngày bắt đầu", "Ngày kết thúc", "Trạng thái", "Người duyệt", "Lý do", "Ngày tạo"]
    
    if data == "leave_csv_weekly":
        start_week = (now - datetime.timedelta(days=now.weekday())).strftime("%Y-%m-%d")
        end_week = (now + datetime.timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d")
        
        async with db_session() as session:
            stmt = select(LeaveRequest).where(
                and_(
                    LeaveRequest.status == 'approved',
                    LeaveRequest.start_date <= end_week,
                    LeaveRequest.end_date >= start_week
                )
            ).order_by(LeaveRequest.start_date.asc())
            res = await session.execute(stmt)
            requests = res.scalars().all()
            
        if not requests:
            await query.answer("🫙 Không có dữ liệu nghỉ phép được duyệt trong tuần này.", show_alert=True)
            return
            
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
            chat_id=user_id,
            document=io.BytesIO(csv_bytes),
            filename=f"leave_weekly_{start_week}_to_{end_week}.csv",
            caption=f"📊 Báo cáo nghỉ phép tuần này ({start_week} đến {end_week})."
        )
        await query.answer("✅ Đã gửi file CSV tuần này qua DM.")
        
    elif data == "leave_csv_monthly":
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
            requests = res.scalars().all()
            
        if not requests:
            await query.answer("🫙 Không có dữ liệu nghỉ phép được duyệt trong tháng này.", show_alert=True)
            return
            
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
            chat_id=user_id,
            document=io.BytesIO(csv_bytes),
            filename=f"leave_monthly_{now.strftime('%Y%m')}.csv",
            caption=f"📊 Báo cáo nghỉ phép tháng {now.strftime('%m/%Y')}."
        )
        await query.answer("✅ Đã gửi file CSV tháng này qua DM.")
        
    elif data.startswith("leave_csv_single:"):
        req_id = int(data.split(":")[1])
        
        async with db_session() as session:
            req = await session.get(LeaveRequest, req_id)
            
        if not req:
            await query.answer("❌ Không tìm thấy thông tin đơn nghỉ phép.", show_alert=True)
            return
            
        rows = [
            [
                req.id, req.user_id, req.user_name, req.leave_type,
                req.start_date, req.end_date, req.status, req.approved_by or "",
                req.reason or "", req.created_at
            ]
        ]
        
        csv_bytes = generate_csv_with_bom(headers, rows)
        await context.bot.send_document(
            chat_id=user_id,
            document=io.BytesIO(csv_bytes),
            filename=f"leave_request_{req_id}_{req.user_name}.csv",
            caption=f"📄 Thông tin đơn nghỉ phép #{req_id} của {req.user_name}."
        )
        await query.answer("✅ Đã gửi file CSV đơn qua DM.")
