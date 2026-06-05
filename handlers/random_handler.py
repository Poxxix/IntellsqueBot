import random
import json
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select, and_
from models.database import db_session
from models.user import User
from models.spin import SpinHistory
from models.leave import LeaveRequest
from models.audit import AuditLog

# Helper to get active members who are not on leave today
async def get_active_candidates(session, today_str: str, exclude_ids=None) -> list[User]:
    if exclude_ids is None:
        exclude_ids = []
        
    # Query approved leaves today
    stmt_leave = select(LeaveRequest.user_id).where(
        and_(
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today_str,
            LeaveRequest.end_date >= today_str
        )
    )
    res_leave = await session.execute(stmt_leave)
    leave_user_ids = res_leave.scalars().all()
    
    # Query active users not on leave and not in exclude_ids
    stmt_users = select(User).where(
        and_(
            User.active == True,
            User.telegram_id.notin_(leave_user_ids),
            User.telegram_id.notin_(exclude_ids)
        )
    )
    res_users = await session.execute(stmt_users)
    return list(res_users.scalars().all())

async def handle_random(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Picks a random member with spin animation."""
    if not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    async with db_session() as session:
        candidates = await get_active_candidates(session, today_str)
        
        if not candidates:
            await update.message.reply_text("❌ Không có thành viên nào khả dụng (mọi người đều nghỉ phép hoặc nhóm trống).")
            return
            
        # Send initial spin message
        msg = await update.message.reply_text("🎲 **Đang khởi động vòng quay...**", parse_mode="Markdown")
        
        # Spin animation: show random names with delay
        animation_steps = min(5, len(candidates) * 2)
        if animation_steps > 1:
            for i in range(animation_steps):
                temp_name = random.choice(candidates).display_name
                await msg.edit_text(f"🎲 **Đang quay:** `{temp_name}`...", parse_mode="Markdown")
                await asyncio.sleep(0.4)
                
        # Draw final winner
        winner = random.choice(candidates)
        
        # Save to spin history
        pool_snap = [{"id": u.telegram_id, "name": u.display_name} for u in candidates]
        history = SpinHistory(
            spin_type="random_member",
            result=winner.display_name,
            pool_snapshot=json.dumps(pool_snap),
            created_by=user_id
        )
        session.add(history)
        await session.flush() # get ID
        
        # Log to Audit
        audit = AuditLog(
            actor_id=user_id,
            action="spin_member",
            entity_type="spin_history",
            entity_id=history.id,
            meta_data=json.dumps({"winner_id": winner.telegram_id, "winner_name": winner.display_name})
        )
        session.add(audit)
        
        # Reply text with Reroll button
        mention = f"@{winner.username}" if winner.username else f"[{winner.display_name}](tg://user?id={winner.telegram_id})"
        text = (
            f"🎉 **VÒNG QUAY NGẪU NHIÊN** 🎉\n\n"
            f"👉 Người được chọn: **{winner.display_name}** ({mention})\n"
            f"📊 Pool: `{len(candidates)}` thành viên đi làm hôm nay.\n\n"
            f"Vui lòng xác nhận:"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("🔄 Reroll", callback_data=f"spin_reroll:member:{winner.telegram_id}"),
                InlineKeyboardButton("✅ Xác nhận", callback_data=f"spin_confirm:{history.id}")
            ]
        ]
        
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_random_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Assigns random roles for a daily meeting."""
    if not update.effective_chat:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    async with db_session() as session:
        candidates = await get_active_candidates(session, today_str)
        
        if len(candidates) < 2:
            await update.message.reply_text("❌ Cần ít nhất 2 thành viên đi làm để phân chia vai trò.")
            return
            
        msg = await update.message.reply_text("🎲 **Đang phân chia vai trò...**", parse_mode="Markdown")
        await asyncio.sleep(1.0)
        
        roles = ["Presenter (Thuyết trình)", "Note Taker (Ghi chép)", "Time Keeper (Giữ giờ)"]
        # Limit roles based on candidate count
        meeting_roles = roles[:len(candidates)]
        
        chosen_members = random.sample(candidates, len(meeting_roles))
        
        result_lines = []
        result_dict = {}
        for r, member in zip(meeting_roles, chosen_members):
            mention = f"@{member.username}" if member.username else member.display_name
            result_lines.append(f"• **{r}**: {member.display_name} ({mention})")
            result_dict[r] = member.display_name
            
        result_text = "\n".join(result_lines)
        
        # Save to history
        history = SpinHistory(
            spin_type="random_role",
            result=json.dumps(result_dict, ensure_ascii=False),
            pool_snapshot=json.dumps([{"id": u.telegram_id, "name": u.display_name} for u in candidates]),
            created_by=user_id
        )
        session.add(history)
        await session.flush()
        
        session.add(AuditLog(
            actor_id=user_id,
            action="spin_roles",
            entity_type="spin_history",
            entity_id=history.id
        ))
        
        text = (
            f"💼 **PHÂN VAI TRÒ HỌP HÔM NAY** 💼\n\n"
            f"{result_text}\n\n"
            f"Chúc cả nhà họp hiệu quả! 🚀"
        )
        
        await msg.edit_text(text, parse_mode="Markdown")

async def handle_random_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Splits active members into N teams."""
    if not update.effective_chat or not update.message:
        return
        
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Parse N from args
    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("💡 Cú pháp: `/random_team <số_đội>`\nVí dụ: `/random_team 2`")
        return
        
    num_teams = int(args[0])
    if num_teams <= 1:
        await update.message.reply_text("❌ Số đội phải lớn hơn 1.")
        return
        
    async with db_session() as session:
        candidates = await get_active_candidates(session, today_str)
        
        if len(candidates) < num_teams:
            await update.message.reply_text(f"❌ Số người đi làm hiện tại ({len(candidates)}) không đủ để chia làm {num_teams} đội.")
            return
            
        msg = await update.message.reply_text("🎲 **Đang xáo trộn và chia đội...**", parse_mode="Markdown")
        await asyncio.sleep(1.0)
        
        # Shuffle candidates
        shuffled = list(candidates)
        random.shuffle(shuffled)
        
        teams = [[] for _ in range(num_teams)]
        for idx, member in enumerate(shuffled):
            teams[idx % num_teams].append(member)
            
        # Format output
        result_text = f"👥 **KẾT QUẢ CHIA {num_teams} ĐỘI** 👥\n\n"
        history_dict = {}
        
        for i, team in enumerate(teams):
            names = [f"• {m.display_name}" for m in team]
            result_text += f"🅰️ **Team {i+1}:**\n" + "\n".join(names) + "\n\n"
            history_dict[f"Team {i+1}"] = [m.display_name for m in team]
            
        # Save to history
        history = SpinHistory(
            spin_type="random_team",
            result=json.dumps(history_dict, ensure_ascii=False),
            pool_snapshot=json.dumps([{"id": u.telegram_id, "name": u.display_name} for u in candidates]),
            created_by=user_id
        )
        session.add(history)
        await session.flush()
        
        session.add(AuditLog(
            actor_id=user_id,
            action="spin_teams",
            entity_type="spin_history",
            entity_id=history.id
        ))
        
        await msg.edit_text(result_text, parse_mode="Markdown")

async def handle_spin_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays recent spin results."""
    if not update.message:
        return
        
    async with db_session() as session:
        stmt = select(SpinHistory).order_by(SpinHistory.id.desc()).limit(7)
        res = await session.execute(stmt)
        history = res.scalars().all()
        
        if not history:
            await update.message.reply_text("📅 Chưa có lịch sử vòng quay nào được ghi nhận.")
            return
            
        text = "📅 **LỊCH SỬ VÒNG QUAY (7 LẦN GẦN NHẤT)** 📅\n\n"
        for idx, h in enumerate(history):
            date_part = h.created_at.split()[0] if h.created_at else ""
            time_part = h.created_at.split()[1][:5] if h.created_at and len(h.created_at.split()) > 1 else ""
            datetime_str = f"{date_part} {time_part}"
            
            if h.spin_type == "random_member":
                text += f"{idx+1}. **Quay thành viên** - Winner: **{h.result}** ({datetime_str})\n"
            elif h.spin_type == "random_role":
                try:
                    res_dict = json.loads(h.result)
                    desc = ", ".join([f"{r}: {name}" for r, name in res_dict.items()])
                    text += f"{idx+1}. **Chia vai trò họp** ({datetime_str}):\n   _{desc}_\n"
                except Exception:
                    text += f"{idx+1}. **Chia vai trò họp** - {h.result} ({datetime_str})\n"
            elif h.spin_type == "random_team":
                try:
                    teams_dict = json.loads(h.result)
                    desc = " | ".join([f"{team}: {', '.join(names)}" for team, names in teams_dict.items()])
                    text += f"{idx+1}. **Chia đội** ({datetime_str}):\n   _{desc}_\n"
                except Exception:
                    text += f"{idx+1}. **Chia đội** - {h.result} ({datetime_str})\n"
                    
        await update.message.reply_text(text, parse_mode="Markdown")

async def handle_spin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles callback buttons for random member draw."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    parts = data.split(":")
    action = parts[0]
    
    if action == "spin_confirm":
        history_id = int(parts[1])
        async with db_session() as session:
            h = await session.get(SpinHistory, history_id)
            if h:
                # Remove buttons and update text
                original_text = query.message.text if query.message else ""
                confirmed_text = original_text + "\n\n✅ **Đã xác nhận!**"
                await query.edit_message_text(confirmed_text, parse_mode="Markdown")
                
                # Log audit
                user_id = query.from_user.id
                session.add(AuditLog(
                    actor_id=user_id,
                    action="spin_confirm",
                    entity_type="spin_history",
                    entity_id=history_id
                ))
                
    elif action == "spin_reroll":
        exclude_id = int(parts[2])
        user_id = query.from_user.id
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        async with db_session() as session:
            # Reroll picks another candidate
            candidates = await get_active_candidates(session, today_str, exclude_ids=[exclude_id])
            
            if not candidates:
                await query.edit_message_text("❌ Không còn thành viên nào khác khả dụng để reroll.")
                return
                
            winner = random.choice(candidates)
            
            # Save to history
            pool_snap = [{"id": u.telegram_id, "name": u.display_name} for u in candidates]
            history = SpinHistory(
                spin_type="random_member",
                result=winner.display_name,
                pool_snapshot=json.dumps(pool_snap),
                created_by=user_id
            )
            session.add(history)
            await session.flush()
            
            session.add(AuditLog(
                actor_id=user_id,
                action="spin_reroll",
                entity_type="spin_history",
                entity_id=history.id,
                meta_data=json.dumps({"winner_id": winner.telegram_id, "winner_name": winner.display_name})
            ))
            
            # Reply text with Reroll button
            mention = f"@{winner.username}" if winner.username else f"[{winner.display_name}](tg://user?id=${winner.telegram_id})"
            text = (
                f"🎉 **VÒNG QUAY NGẪU NHIÊN (REROLL)** 🎉\n\n"
                f"👉 Người được chọn: **{winner.display_name}** ({mention})\n"
                f"📊 Pool: `{len(candidates)}` thành viên đi làm hôm nay.\n\n"
                f"Vui lòng xác nhận:"
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Reroll", callback_data=f"spin_reroll:member:{winner.telegram_id}"),
                    InlineKeyboardButton("✅ Xác nhận", callback_data=f"spin_confirm:{history.id}")
                ]
            ]
            
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
