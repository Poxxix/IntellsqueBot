import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_, or_
from models.database import db_session
from models.user import User
from models.leave import LeaveRequest
from models.audit import AuditLog

# Helper to validate YYYY-MM-DD
def is_valid_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return True
    except ValueError:
        return False

# Helper to format leave type in Vietnamese
def format_leave_type(lt: str) -> str:
    types = {
        "sang": "Nghỉ buổi sáng",
        "chieu": "Nghỉ buổi chiều",
        "ngay": "Nghỉ cả ngày",
        "nhieu_ngay": "Nghỉ nhiều ngày"
    }
    return types.get(lt, lt)

# Send request to all Admins and Approvers
async def send_to_approvers(context: ContextTypes.DEFAULT_TYPE, req: LeaveRequest, applicant_name: str):
    async with db_session() as session:
        stmt = select(User).where(User.role.in_(['admin', 'approver']))
        res = await session.execute(stmt)
        approvers = res.scalars().all()
        
    date_str = req.start_date if req.start_date == req.end_date else f"từ {req.start_date} đến {req.end_date}"
    type_str = format_leave_type(req.leave_type)
    
    text = (
        f"🔔 **ĐƠN XIN NGHỈ PHÉP MỚI** (Mã đơn: #{req.id})\n\n"
        f"👤 **Thành viên:** {applicant_name}\n"
        f"🏖 **Loại nghỉ:** {type_str}\n"
        f"📅 **Thời gian:** {date_str}\n"
        f"📝 **Lý do:** {req.reason or 'Không có lý do'}\n\n"
        f"Vui lòng phê duyệt:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Duyệt", callback_data=f"leave_approve:{req.id}"),
            InlineKeyboardButton("❌ Từ chối", callback_data=f"leave_reject:{req.id}")
        ]
    ]
    
    sent_count = 0
    for appr in approvers:
        try:
            await context.bot.send_message(
                chat_id=appr.telegram_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            sent_count += 1
        except Exception:
            # Approver might not have started DM with bot
            pass
    return sent_count

async def handle_xinnghi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a leave request via command or quick menu."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user = update.effective_user
    user_id = user.id
    args = context.args

    # Check if user exists in database
    async with db_session() as session:
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
        if not db_user:
            # Auto-register as member
            db_user = User(
                telegram_id=user_id,
                display_name=user.full_name,
                username=user.username,
                role='member'
            )
            session.add(db_user)
            await session.flush()
            
    if not args:
        # Show Quick Reply Menu
        today_str = datetime.now().strftime("%Y-%m-%d")
        tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        text = (
            f"🏖 **ĐĂNG KÝ XIN NGHỈ PHÉP**\n\n"
            f"Bạn có thể xin nghỉ nhanh bằng cách gõ lệnh kèm các tham số:\n"
            f"• `/xinnghi sang YYYY-MM-DD [lý do]` (Nghỉ sáng)\n"
            f"• `/xinnghi chieu YYYY-MM-DD [lý do]` (Nghỉ chiều)\n"
            f"• `/xinnghi ngay YYYY-MM-DD [lý do]` (Nghỉ cả ngày)\n"
            f"• `/xinnghi tu YYYY-MM-DD den YYYY-MM-DD [lý do]` (Nghỉ nhiều ngày)\n\n"
            f"Hoặc chọn các nút bấm bên dưới để gửi đơn xin nghỉ nhanh hôm nay/ngày mai:"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("🏖 Sáng nay", callback_data=f"leave_quick:sang:{today_str}"),
                InlineKeyboardButton("🏖 Chiều nay", callback_data=f"leave_quick:chieu:{today_str}"),
                InlineKeyboardButton("🏖 Cả ngày nay", callback_data=f"leave_quick:ngay:{today_str}")
            ],
            [
                InlineKeyboardButton("🏖 Sáng mai", callback_data=f"leave_quick:sang:{tomorrow_str}"),
                InlineKeyboardButton("🏖 Chiều mai", callback_data=f"leave_quick:chieu:{tomorrow_str}"),
                InlineKeyboardButton("🏖 Cả ngày mai", callback_data=f"leave_quick:ngay:{tomorrow_str}")
            ]
        ]
        
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # Parse args
    first_arg = args[0].lower()
    leave_type = "ngay"
    start_date = ""
    end_date = ""
    reason = ""

    if first_arg == "tu":
        # tu YYYY-MM-DD den YYYY-MM-DD [reason]
        if len(args) < 4 or args[2].lower() != "den":
            await update.message.reply_text("❌ Cú pháp sai. Hãy dùng: `/xinnghi tu YYYY-MM-DD den YYYY-MM-DD [lý do]`")
            return
        start_date = args[1]
        end_date = args[3]
        leave_type = "nhieu_ngay"
        reason = " ".join(args[4:])
    elif first_arg in ["sang", "chieu", "ngay"]:
        if len(args) < 2:
            await update.message.reply_text(f"❌ Cú pháp sai. Hãy dùng: `/xinnghi {first_arg} YYYY-MM-DD [lý do]`")
            return
        start_date = args[1]
        end_date = args[1]
        leave_type = first_arg
        reason = " ".join(args[2:])
    else:
        await update.message.reply_text("❌ Loại nghỉ không hợp lệ. Hãy dùng `sang`, `chieu`, `ngay`, hoặc `tu`.")
        return

    # Validate dates
    if not is_valid_date(start_date) or not is_valid_date(end_date):
        await update.message.reply_text("❌ Định dạng ngày không hợp lệ. Vui lòng điền dạng YYYY-MM-DD (Ví dụ: 2026-06-06).")
        return

    if start_date > end_date:
        await update.message.reply_text("❌ Ngày bắt đầu không được lớn hơn ngày kết thúc.")
        return

    async with db_session() as session:
        # Check overlaps
        stmt = select(LeaveRequest).where(
            and_(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status.in_(['pending', 'approved']),
                or_(
                    and_(LeaveRequest.start_date <= start_date, LeaveRequest.end_date >= start_date),
                    and_(LeaveRequest.start_date <= end_date, LeaveRequest.end_date >= end_date),
                    and_(LeaveRequest.start_date >= start_date, LeaveRequest.end_date <= end_date)
                )
            )
        )
        res = await session.execute(stmt)
        overlap = res.scalar_one_or_none()
        if overlap:
            await update.message.reply_text("❌ Bạn đã có một đơn nghỉ phép trùng lặp trong thời gian này.")
            return

        # Create leave request
        req = LeaveRequest(
            user_id=user_id,
            user_name=db_user.display_name,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason or None,
            chat_id=chat_id,
            status='pending'
        )
        session.add(req)
        await session.flush() # get ID

        # Audit Log
        session.add(AuditLog(
            actor_id=user_id,
            action="submit_leave",
            entity_type="leave_requests",
            entity_id=req.id
        ))
        
        # Notify approvers
        sent_count = await send_to_approvers(context, req, db_user.display_name)
        
        ack = (
            f"✅ **Đã gửi đơn xin nghỉ phép mã #{req.id}!**\n\n"
            f"• Loại nghỉ: `{format_leave_type(leave_type)}`\n"
            f"• Thời gian: `{start_date if start_date == end_date else f'{start_date} đến {end_date}'}`\n"
        )
        if reason:
            ack += f"• Lý do: _{reason}_\n"
            
        if sent_count > 0:
            ack += f"\n✉️ Đã gửi thông báo đến `{sent_count}` cấp quản lý. Đang chờ phê duyệt..."
        else:
            ack += f"\n⚠️ Admin/Approver chưa chat với Bot. Vui lòng báo trực tiếp cho Admin."
            
        await update.message.reply_text(ack, parse_mode="Markdown")

async def handle_nghihomnay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all approved leave requests for today (hides reasons)."""
    if not update.message:
        return
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    async with db_session() as session:
        stmt = select(LeaveRequest).where(
            and_(
                LeaveRequest.status == 'approved',
                LeaveRequest.start_date <= today_str,
                LeaveRequest.end_date >= today_str
            )
        )
        res = await session.execute(stmt)
        leaves = res.scalars().all()
        
    if not leaves:
        await update.message.reply_text(f"🟢 Hôm nay ({today_str}) không có ai nghỉ phép.")
        return
        
    text = f"🏖 **DANH SÁCH THÀNH VIÊN NGHỈ PHÉP HÔM NAY** ({today_str})\n\n"
    for idx, l in enumerate(leaves):
        type_str = format_leave_type(l.leave_type)
        date_str = f" (từ {l.start_date} đến {l.end_date})" if l.start_date != l.end_date else ""
        text += f"{idx+1}. **{l.user_name}** — {type_str}{date_str}\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_huy_nghi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels/deletes a leave request."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    args = context.args
    
    if not args or not args[0].isdigit():
        await update.message.reply_text("💡 Cú pháp: `/huy_nghi <mã_đơn>`\nVí dụ: `/huy_nghi 5`")
        return
        
    req_id = int(args[0])
    
    async with db_session() as session:
        # Check permissions (applicant or admin)
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
        req = await session.get(LeaveRequest, req_id)
        
        if not req:
            await update.message.reply_text(f"❌ Không tìm thấy đơn xin nghỉ mã #{req_id}.")
            return
            
        if req.user_id != user_id and (not db_user or db_user.role != 'admin'):
            await update.message.reply_text("❌ Bạn không có quyền hủy đơn xin nghỉ này (chỉ chủ đơn hoặc Admin mới được phép).")
            return
            
        if req.status in ['cancelled', 'rejected']:
            await update.message.reply_text(f"❌ Đơn này đã ở trạng thái `{req.status}` từ trước.")
            return
            
        req.status = 'cancelled'
        
        session.add(AuditLog(
            actor_id=user_id,
            action="cancel_leave",
            entity_type="leave_requests",
            entity_id=req_id
        ))
        
        await update.message.reply_text(f"✅ Đã hủy thành công đơn xin nghỉ mã #{req_id}.")

async def handle_leave_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callback queries for leave approval/rejection and quick submits."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    action = parts[0]
    
    user_id = query.from_user.id
    
    if action == "leave_quick":
        # leave_quick:type:date
        leave_type = parts[1]
        date_str = parts[2]
        chat_id = query.message.chat.id if query.message else 0
        
        async with db_session() as session:
            stmt_u = select(User).where(User.telegram_id == user_id)
            res_u = await session.execute(stmt_u)
            db_user = res_u.scalar_one_or_none()
            
            if not db_user:
                db_user = User(
                    telegram_id=user_id,
                    display_name=query.from_user.full_name,
                    username=query.from_user.username,
                    role='member'
                )
                session.add(db_user)
                await session.flush()
                
            # Overlap check
            stmt = select(LeaveRequest).where(
                and_(
                    LeaveRequest.user_id == user_id,
                    LeaveRequest.status.in_(['pending', 'approved']),
                    LeaveRequest.start_date <= date_str,
                    LeaveRequest.end_date >= date_str
                )
            )
            res = await session.execute(stmt)
            if res.scalar_one_or_none():
                await query.edit_message_text("❌ Bạn đã có đơn xin nghỉ trùng ngày này.")
                return
                
            req = LeaveRequest(
                user_id=user_id,
                user_name=db_user.display_name,
                leave_type=leave_type,
                start_date=date_str,
                end_date=date_str,
                reason="Gửi nhanh bằng nút bấm",
                chat_id=chat_id,
                status='pending'
            )
            session.add(req)
            await session.flush()
            
            session.add(AuditLog(
                actor_id=user_id,
                action="submit_leave",
                entity_type="leave_requests",
                entity_id=req.id
            ))
            
            sent_count = await send_to_approvers(context, req, db_user.display_name)
            
            text = (
                f"✅ **Đã gửi đơn xin nghỉ phép nhanh mã #{req.id}!**\n\n"
                f"• Loại nghỉ: `{format_leave_type(leave_type)}`\n"
                f"• Ngày nghỉ: `{date_str}`\n"
            )
            if sent_count > 0:
                text += f"✉️ Chờ duyệt bởi `{sent_count}` quản lý..."
            else:
                text += f"⚠️ Admin/Approver chưa bắt đầu chat riêng với Bot."
                
            await query.edit_message_text(text, parse_mode="Markdown")

    elif action in ["leave_approve", "leave_reject"]:
        req_id = int(parts[1])
        approved = action == "leave_approve"
        
        async with db_session() as session:
            # Check permissions
            stmt_u = select(User).where(User.telegram_id == user_id)
            res_u = await session.execute(stmt_u)
            db_user = res_u.scalar_one_or_none()
            
            if not db_user or db_user.role not in ['admin', 'approver']:
                await context.bot.answer_callback_query(
                    callback_query_id=query.id,
                    text="❌ Bạn không có quyền phê duyệt đơn này.",
                    show_alert=True
                )
                return
                
            req = await session.get(LeaveRequest, req_id)
            if not req:
                await query.edit_message_text("❌ Không tìm thấy đơn này.")
                return
                
            if req.status != 'pending':
                await query.edit_message_text(f"⚠️ Đơn này đã được xử lý trước đó. Trạng thái: {req.status}")
                return
                
            req.status = 'approved' if approved else 'rejected'
            req.approved_by = db_user.display_name
            
            session.add(AuditLog(
                actor_id=user_id,
                action="approve_leave" if approved else "reject_leave",
                entity_type="leave_requests",
                entity_id=req_id
            ))
            
            # Edit manager's DM
            status_symbol = "✅" if approved else "❌"
            status_word = "ĐÃ DUYỆT" if approved else "BỊ TỪ CHỐI"
            
            date_str = req.start_date if req.start_date == req.end_date else f"từ {req.start_date} đến {req.end_date}"
            type_str = format_leave_type(req.leave_type)
            
            text = (
                f"{status_symbol} **ĐƠN XIN NGHỈ PHÉP {status_word}**\n\n"
                f"👤 **Thành viên:** {req.user_name}\n"
                f"🏖 **Loại nghỉ:** {type_str}\n"
                f"📅 **Thời gian:** {date_str}\n"
                f"👤 **Người duyệt:** {db_user.display_name}\n"
            )
            await query.edit_message_text(text, parse_mode="Markdown")
            
            # Notify Applicant
            try:
                msg = f"{status_symbol} Đơn xin nghỉ phép #{req.id} ({type_str} - {date_str}) của bạn đã được **{status_word.lower()}** bởi {db_user.display_name}."
                await context.bot.send_message(chat_id=req.user_id, text=msg, parse_mode="Markdown")
            except Exception:
                pass
                
            # Broadcast to group chat (hiding the reason!)
            if approved and req.chat_id and req.chat_id < 0:
                try:
                    announce = f"📢 **Thông báo:** **{req.user_name}** sẽ **{type_str.lower()}** vào ngày `{date_str}` (đã được duyệt)."
                    await context.bot.send_message(chat_id=req.chat_id, text=announce, parse_mode="Markdown")
                except Exception:
                    pass
