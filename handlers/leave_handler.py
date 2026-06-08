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

async def update_user_leave_accrual(session, user: User) -> bool:
    """Calculates and updates leave balance based on joined_date.
    Probation (first 2 months): 0 leave days.
    After 2 months: 1 day per month.
    """
    if not user.joined_date:
        return False
        
    today = datetime.now()
    joined = user.joined_date
    
    # Calculate completed months
    completed_months = (today.year - joined.year) * 12 + today.month - joined.month
    if today.day < joined.day:
        completed_months -= 1
        
    expected_accrued = max(0, completed_months - 2)
    if expected_accrued > user.total_accrued:
        diff = expected_accrued - user.total_accrued
        user.leave_balance += diff
        user.total_accrued = expected_accrued
        session.add(user)
        return True
    return False

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
        f"🏖 **Số ngày phép sử dụng:** {req.used_leave_days or 0.0} ngày\n"
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

async def send_leave_confirm_menu(bot, user_id: int, details: dict, context: ContextTypes.DEFAULT_TYPE, query=None):
    context.user_data['pending_leave_req'] = details
    
    async with db_session() as session:
        stmt = select(User).where(User.telegram_id == user_id)
        res = await session.execute(stmt)
        db_user = res.scalar_one_or_none()
        if db_user:
            await update_user_leave_accrual(session, db_user)
            balance = db_user.leave_balance
        else:
            balance = 0.0
            
    type_str = format_leave_type(details['leave_type'])
    date_str = details['start_date'] if details['start_date'] == details['end_date'] else f"từ {details['start_date']} đến {details['end_date']}"
    
    text = (
        f"🏖 **XÁC NHẬN ĐƠN XIN NGHỈ PHÉP**\n\n"
        f"• Loại nghỉ: `{type_str}`\n"
        f"• Thời gian: `{date_str}`\n"
        f"• Lý do: `{details['reason'] or 'Không có lý do'}`\n"
        f"• Số ngày phép hiện tại: `{balance} ngày`\n\n"
        f"Bạn có muốn sử dụng ngày nghỉ phép cho đơn này không?"
    )
    
    keyboard = []
    if details['leave_type'] in ['sang', 'chieu']:
        keyboard.append([
            InlineKeyboardButton("🏖 Dùng 0.5 ngày phép", callback_data="leave_confirm:0.5"),
            InlineKeyboardButton("💸 Không dùng phép", callback_data="leave_confirm:0.0")
        ])
    else:
        keyboard.append([
            InlineKeyboardButton("🏖 Dùng 1.0 ngày phép", callback_data="leave_confirm:1.0"),
            InlineKeyboardButton("💸 Không dùng phép", callback_data="leave_confirm:0.0")
        ])
        
    keyboard.append([
        InlineKeyboardButton("❌ Hủy bỏ đơn này", callback_data="leave_confirm:cancel")
    ])
    
    if query:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

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

    details = {
        'leave_type': leave_type,
        'start_date': start_date,
        'end_date': end_date,
        'reason': reason or None,
        'chat_id': chat_id
    }
    
    if is_group:
        try:
            await send_leave_confirm_menu(context.bot, user_id, details, context)
            await update.message.reply_text("🏖 Mình đã gửi yêu cầu xác nhận sử dụng ngày phép vào DM của bạn. Vui lòng kiểm tra và xác nhận.")
        except Exception:
            await update.message.reply_text("⚠️ Mình không thể gửi tin nhắn riêng cho bạn. Vui lòng mở chat với Bot và gõ `/start` trước.")
    else:
        await send_leave_confirm_menu(context.bot, user_id, details, context)

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

    if action == "leave_confirm":
        option = parts[1] # "0.5", "1.0", "0.0" or "cancel"
        
        if option == "cancel":
            context.user_data.pop('pending_leave_req', None)
            await query.edit_message_text("❌ Đã hủy bỏ yêu cầu xin nghỉ phép.")
            return
            
        used_days = float(option)
        details = context.user_data.pop('pending_leave_req', None)
        if not details:
            await query.edit_message_text("❌ Không tìm thấy thông tin đơn nghỉ phép đang chờ xác nhận hoặc đơn đã hết hạn.")
            return
            
        chat_id = details['chat_id']
        
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
                
            await update_user_leave_accrual(session, db_user)
            
            if used_days > 0.0 and db_user.leave_balance < used_days:
                await query.edit_message_text(f"❌ Số ngày nghỉ phép của bạn không đủ (Hiện có: {db_user.leave_balance} ngày, yêu cầu: {used_days} ngày).")
                return
                
            # Create leave request
            req = LeaveRequest(
                user_id=user_id,
                user_name=db_user.display_name,
                leave_type=details['leave_type'],
                start_date=details['start_date'],
                end_date=details['end_date'],
                reason=details['reason'] or None,
                chat_id=chat_id,
                used_leave_days=used_days,
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
            
        type_str = format_leave_type(details['leave_type'])
        date_str = details['start_date'] if details['start_date'] == details['end_date'] else f"từ {details['start_date']} đến {details['end_date']}"
        
        text = (
            f"✅ **Đã gửi đơn xin nghỉ phép mã #{req.id}!**\n\n"
            f"• Loại nghỉ: `{type_str}`\n"
            f"• Thời gian: `{date_str}`\n"
            f"• Số ngày phép sử dụng: `{used_days} ngày`\n"
        )
        if details['reason']:
            text += f"• Lý do: _{details['reason']}_\n"
            
        if sent_count > 0:
            text += f"\n✉️ Đang chờ `{sent_count}` cấp quản lý phê duyệt..."
        else:
            text += f"\n⚠️ Admin/Approver chưa kết nối bot. Vui lòng báo trực tiếp cho Admin."
            
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if action == "leave_quick":
        leave_type = parts[1]
        date_str = parts[2]
        chat_id = query.message.chat.id if query.message else 0
        
        async with db_session() as session:
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
                
        details = {
            'leave_type': leave_type,
            'start_date': date_str,
            'end_date': date_str,
            'reason': "Gửi nhanh bằng nút bấm",
            'chat_id': chat_id
        }
        
        await send_leave_confirm_menu(context.bot, user_id, details, context, query=query)
        return

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
            
            if approved:
                stmt_applicant = select(User).where(User.telegram_id == req.user_id)
                res_applicant = await session.execute(stmt_applicant)
                applicant = res_applicant.scalar_one_or_none()
                if applicant:
                    await update_user_leave_accrual(session, applicant)
                    applicant.leave_balance = max(0.0, applicant.leave_balance - req.used_leave_days)
                    session.add(applicant)
            
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

async def handle_phep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Checks the user's leave balance (DM only)."""
    if not update.message or not update.effective_chat:
        return
        
    if update.effective_chat.type != 'private':
        await update.message.reply_text("❌ Bạn chỉ có thể sử dụng lệnh này trong chat riêng tư (DM) với Bot để bảo mật thông tin.")
        return
        
    user_id = update.effective_user.id
    
    async with db_session() as session:
        stmt_u = select(User).where(User.telegram_id == user_id)
        res_u = await session.execute(stmt_u)
        db_user = res_u.scalar_one_or_none()
        
        if not db_user:
            await update.message.reply_text("❌ Tài khoản của bạn chưa được khởi tạo trong hệ thống.")
            return
            
        await update_user_leave_accrual(session, db_user)
        balance = db_user.leave_balance
        joined = db_user.joined_date
        
    joined_str = joined.strftime("%Y-%m-%d") if joined else "Chưa thiết lập"
    
    # Calculate months since joined
    if joined:
        today = datetime.now()
        completed_months = (today.year - joined.year) * 12 + today.month - joined.month
        if today.day < joined.day:
            completed_months -= 1
            
        if completed_months < 2:
            status_str = f"Thử việc ({completed_months}/2 tháng)"
        else:
            status_str = f"Chính thức (Thâm niên: {completed_months} tháng)"
    else:
        status_str = "Chưa thiết lập ngày gia nhập"
        
    text = (
        f"🏖 **THÔNG TIN NGÀY NGHỈ PHÉP CỦA BẠN**\n\n"
        f"• **Họ tên:** {db_user.display_name}\n"
        f"• **Ngày bắt đầu làm việc:** `{joined_str}`\n"
        f"• **Trạng thái:** {status_str}\n"
        f"• **Số ngày phép khả dụng:** `{balance} ngày`\n\n"
        f"💡 *Lưu ý: Nhân viên thử việc (2 tháng đầu) không có ngày phép. Sau 2 tháng, bạn tự động tích lũy thêm 1 ngày phép mỗi tháng.*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_admin_phep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin tool to manage employee leave balances and joined dates."""
    if not update.message or not update.effective_user:
        return
        
    user_id = update.effective_user.id
    args = context.args
    
    from config import ADMIN_IDS
    
    async with db_session() as session:
        # Check permissions
        is_admin = False
        if user_id in ADMIN_IDS:
            is_admin = True
        else:
            stmt = select(User).where(User.telegram_id == user_id)
            res = await session.execute(stmt)
            u = res.scalar_one_or_none()
            is_admin = u is not None and u.role == 'admin'
            
        if not is_admin:
            await update.message.reply_text("❌ Bạn không có quyền sử dụng lệnh admin này.")
            return
            
        if not args:
            # List all active users leave balances
            stmt = select(User).where(User.active == True).order_by(User.display_name.asc())
            res = await session.execute(stmt)
            users = res.scalars().all()
            
            text = "⚙️ **QUẢN LÝ NGÀY NGHỈ PHÉP NHÂN VIÊN** ⚙️\n\n"
            for idx, u in enumerate(users):
                joined_str = u.joined_date.strftime("%Y-%m-%d") if u.joined_date else "Chưa cài đặt"
                text += f"{idx+1}. **{u.display_name}** (@{u.username or 'Không có username'})\n"
                text += f"   • Ngày phép khả dụng: `{u.leave_balance} ngày` (Đã tích lũy tự động: {u.total_accrued})\n"
                text += f"   • Ngày bắt đầu: `{joined_str}`\n\n"
            text += (
                "💡 **Cú pháp lệnh quản trị:**\n"
                "• `/admin_phep @username joined YYYY-MM-DD` - Đặt ngày bắt đầu làm việc để kích hoạt tích lũy tự động.\n"
                "• `/admin_phep @username set <số>` - Đặt trực tiếp số ngày phép.\n"
                "• `/admin_phep @username add <số>` - Cộng thêm (hoặc trừ đi nếu số âm) số ngày phép."
            )
            await update.message.reply_text(text, parse_mode="Markdown")
            return
            
        if len(args) < 3 or not args[0].startswith("@"):
            await update.message.reply_text("❌ Cú pháp không chính xác. Vui lòng gõ `/admin_phep` không kèm đối số để xem hướng dẫn.")
            return
            
        username = args[0][1:].lower()
        subcmd = args[1].lower()
        value_str = args[2]
        
        stmt = select(User).where(User.username == username)
        res = await session.execute(stmt)
        target_user = res.scalar_one_or_none()
        
        if not target_user:
            await update.message.reply_text(f"❌ Không tìm thấy thành viên @{username} trong hệ thống.")
            return
            
        if subcmd == "joined":
            if not is_valid_date(value_str):
                await update.message.reply_text("❌ Định dạng ngày không hợp lệ. Vui lòng điền dạng YYYY-MM-DD.")
                return
            joined_dt = datetime.strptime(value_str, "%Y-%m-%d")
            
            target_user.joined_date = joined_dt
            target_user.total_accrued = 0
            await update_user_leave_accrual(session, target_user)
            session.add(target_user)
            await update.message.reply_text(f"✅ Đã đặt ngày bắt đầu của **{target_user.display_name}** là `{value_str}`. Số ngày phép hiện tại: `{target_user.leave_balance} ngày` (Đã tích lũy tự động: {target_user.total_accrued}).")
            
        elif subcmd == "set":
            try:
                balance = float(value_str)
            except ValueError:
                await update.message.reply_text("❌ Số ngày phép phải là số hợp lệ (ví dụ: 12 hoặc 10.5).")
                return
            target_user.leave_balance = max(0.0, balance)
            session.add(target_user)
            await update.message.reply_text(f"✅ Đã đặt số ngày phép của **{target_user.display_name}** thành `{target_user.leave_balance} ngày`.")
            
        elif subcmd == "add":
            try:
                amount = float(value_str)
            except ValueError:
                await update.message.reply_text("❌ Số ngày phép cộng thêm phải là số hợp lệ.")
                return
            target_user.leave_balance = max(0.0, target_user.leave_balance + amount)
            session.add(target_user)
            await update.message.reply_text(f"✅ Đã cộng `{amount}` ngày phép cho **{target_user.display_name}**. Số ngày phép hiện tại: `{target_user.leave_balance} ngày`.")
            
        else:
            await update.message.reply_text("❌ Lệnh phụ không hợp lệ. Hãy dùng `joined`, `set`, hoặc `add`.")
