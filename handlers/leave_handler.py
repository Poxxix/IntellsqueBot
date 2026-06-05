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

# Send request to all Admins and Approvers (in their DM only)
async def send_to_approvers(context: ContextTypes.DEFAULT_TYPE, req: LeaveRequest, applicant_name: str):
    async with db_session() as session:
        stmt = select(User).where(User.role.in_(['admin', 'approver']))
        res = await session.execute(stmt)
        approvers = res.scalars().all()
        
    date_str = req.start_date if req.start_date == req.end_date else f"từ {req.start_date} đến {req.end_date}"
    type_str = format_leave_type(req.leave_type)
    
    text = (
        f"📋 **ĐƠN XIN NGHỈ PHÉP MỚI** (Mã đơn: #{req.id})\n\n"
        f"👤 **Nhân viên:** {applicant_name}\n"
        f"🏖 **Loại nghỉ:** {type_str}\n"
        f"📅 **Ngày:** {date_str}\n"
        f"📝 **Lý do:** {req.reason or 'Không có lý do'}\n"
        f"⏳ **Trạng thái:** Chờ duyệt\n\n"
        f"Vui lòng phê duyệt:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Duyệt", callback_data=f"leave_approve:{req.id}"),
            InlineKeyboardButton("❌ Từ chối", callback_data=f"leave_reject:{req.id}")
        ],
        [
            InlineKeyboardButton("📁 Xuất CSV", callback_data=f"leave_csv_single:{req.id}")
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
            pass
    return sent_count

async def handle_xinnghi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Creates a leave request. Safe for group and private chats."""
    if not update.message or not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    is_group = update.effective_chat.type in ['group', 'supergroup']
    user = update.effective_user
    user_id = user.id
    args = context.args
    message_text = update.message.text

    # Auto-register member
    async with db_session() as session:
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
        if not db_user:
            db_user = User(
                telegram_id=user_id,
                display_name=user.full_name,
                username=user.username,
                role='member'
            )
            session.add(db_user)
            await session.flush()
            
    if not args:
        if is_group:
            # If in group, send instruction and ask them to check DM
            await update.message.reply_text("🏖 Vui lòng kiểm tra tin nhắn riêng (DM) với Bot để gửi đơn xin nghỉ nhanh.")
            
            # Send the menu to DM
            try:
                await send_quick_menu(context.bot, user_id)
            except Exception:
                await update.message.reply_text("⚠️ Bot không thể nhắn tin riêng cho bạn. Vui lòng mở chat với Bot và gõ `/start` trước.")
        else:
            # If in private chat, send the quick menu directly
            await send_quick_menu(context.bot, user_id)
        return

    # Parse arguments: sang|chieu|ngay|tu
    first_arg = args[0].lower()
    leave_type = "ngay"
    start_date = ""
    end_date = ""
    reason = ""

    if first_arg == "tu":
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
        await session.flush()

        session.add(AuditLog(
            actor_id=user_id,
            action="submit_leave",
            entity_type="leave_requests",
            entity_id=req.id
        ))
        
        # Notify approvers
        sent_count = await send_to_approvers(context, req, db_user.display_name)
        
    if is_group:
        # Hiding reason and sensitive info in group
        await update.message.reply_text("✅ Đã nhận yêu cầu, kiểm tra DM.")
    else:
        ack = (
            f"✅ **Đã gửi đơn xin nghỉ phép mã #{req.id}!**\n\n"
            f"• Loại nghỉ: `{format_leave_type(leave_type)}`\n"
            f"• Thời gian: `{start_date if start_date == end_date else f'{start_date} đến {end_date}'}`\n"
        )
        if reason:
            ack += f"• Lý do: _{reason}_\n"
        if sent_count > 0:
            ack += f"\n✉️ Đang chờ `{sent_count}` cấp quản lý phê duyệt..."
        else:
            ack += f"\n⚠️ Admin/Approver chưa kết nối bot. Vui lòng báo trực tiếp cho Admin."
        await update.message.reply_text(ack, parse_mode="Markdown")

async def send_quick_menu(bot, chat_id: int):
    """Sends the quick leave menu to private DM."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    text = (
        f"🏖 **ĐĂNG KÝ XIN NGHỈ PHÉP NHANH**\n\n"
        f"Chọn một trong các nút bấm dưới đây để tạo đơn nghỉ nhanh hôm nay/ngày mai:"
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
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_nghihomnay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows all approved leave requests today (strictly hides reasons)."""
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
        
    # Strictly hide reasons!
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_my_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lists leave requests for the caller (Private DM only)."""
    if not update.message or update.effective_chat.type != 'private':
        if update.message:
            await update.message.reply_text("❌ Lệnh này chỉ sử dụng được trong chat riêng tư (DM) với Bot.")
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        stmt = select(LeaveRequest).where(
            LeaveRequest.user_id == user_id
        ).order_by(LeaveRequest.id.desc()).limit(10)
        res = await session.execute(stmt)
        requests = res.scalars().all()
        
    if not requests:
        await update.message.reply_text("🏖 Bạn chưa tạo đơn xin nghỉ phép nào.")
        return
        
    text = "🏖 **ĐƠN XIN NGHỈ PHÉP CỦA BẠN (10 đơn gần nhất)**\n\n"
    for r in requests:
        type_str = format_leave_type(r.leave_type)
        date_str = r.start_date if r.start_date == r.end_date else f"từ {r.start_date} đến {r.end_date}"
        
        status_emoji = "⏳" if r.status == "pending" else "✅" if r.status == "approved" else "❌"
        cancel_txt = f" /cancel_leave {r.id}" if r.status == "pending" else ""
        
        text += f"• **Đơn #{r.id}** — {type_str} ({date_str})\n"
        text += f"   • Trạng thái: {status_emoji} `{r.status.upper()}`{cancel_txt}\n"
        if r.reason:
            text += f"   • Lý do: _{r.reason}_\n"
        text += "\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_cancel_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancels a pending leave request (Private DM only)."""
    if not update.message or update.effective_chat.type != 'private':
        if update.message:
            await update.message.reply_text("❌ Lệnh này chỉ sử dụng được trong chat riêng tư (DM) với Bot.")
        return
        
    user_id = update.effective_user.id
    args = context.args
    
    if not args or not args[0].isdigit():
        await update.message.reply_text("💡 Cú pháp: `/cancel_leave <mã_đơn>`\nVí dụ: `/cancel_leave 5`")
        return
        
    req_id = int(args[0])
    
    async with db_session() as session:
        req = await session.get(LeaveRequest, req_id)
        
        if not req:
            await update.message.reply_text(f"❌ Không tìm thấy đơn xin nghỉ mã #{req_id}.")
            return
            
        if req.user_id != user_id:
            await update.message.reply_text("❌ Bạn không có quyền hủy đơn xin nghỉ này.")
            return
            
        if req.status != 'pending':
            await update.message.reply_text(f"❌ Đơn này đã được xử lý (trạng thái: `{req.status}`). Bạn không thể tự hủy.")
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
    """Handles callbacks for leave approvals, rejections, and quick submits."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    action = parts[0]
    user_id = query.from_user.id
    
    if action in ["leave_csv_weekly", "leave_csv_monthly", "leave_csv_single"]:
        from handlers.report_handler import handle_leave_csv_callback
        await handle_leave_csv_callback(query, context)
        return

    if action == "leave_quick":
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
            
        # Update Admin's view in DM (still show reason, but add export snapshot buttons)
        status_symbol = "✅" if approved else "❌"
        status_word = "ĐÃ DUYỆT" if approved else "BỊ TỪ CHỐI"
        
        date_str = req.start_date if req.start_date == req.end_date else f"từ {req.start_date} đến {req.end_date}"
        type_str = format_leave_type(req.leave_type)
        
        text = (
            f"{status_symbol} **ĐƠN XIN NGHỈ PHÉP {status_word}**\n\n"
            f"👤 **Nhân viên:** {req.user_name}\n"
            f"🏖 **Loại nghỉ:** {type_str}\n"
            f"📅 **Thời gian:** {date_str}\n"
            f"📝 **Lý do:** {req.reason or 'Không có lý do'}\n"
            f"👤 **Người duyệt:** {db_user.display_name}\n"
        )
        
        # Add automated snapshot export options
        keyboard = [
            [
                InlineKeyboardButton("📁 Xuất CSV tuần này", callback_data="leave_csv_weekly"),
                InlineKeyboardButton("📁 Xuất CSV tháng này", callback_data="leave_csv_monthly")
            ]
        ]
        
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        
        # Notify Applicant
        try:
            msg = f"{status_symbol} Đơn xin nghỉ phép #{req.id} ({type_str} - {date_str}) của bạn đã được **{status_word.lower()}** bởi {db_user.display_name}."
            await context.bot.send_message(chat_id=req.user_id, text=msg, parse_mode="Markdown")
        except Exception:
            pass
            
        # Broadcast short operational summary to group chat (hiding the reason!)
        if approved and req.chat_id and req.chat_id < 0:
            try:
                announce = f"📅 **{req.user_name}** nghỉ **{type_str.lower()}** ngày `{date_str}` — Đã duyệt ✅"
                await context.bot.send_message(chat_id=req.chat_id, text=announce, parse_mode="Markdown")
            except Exception:
                pass
