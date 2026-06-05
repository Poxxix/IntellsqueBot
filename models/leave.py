from sqlalchemy import Column, Integer, String, BigInteger, func
from models.database import Base

class LeaveRequest(Base):
    __tablename__ = 'leave_requests'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String, nullable=False)
    leave_type = Column(String, nullable=False)  # Buổi sáng | Buổi chiều | Cả ngày | Nhiều ngày
    start_date = Column(String, nullable=False)  # YYYY-MM-DD
    end_date = Column(String, nullable=False)    # YYYY-MM-DD
    reason = Column(String, nullable=True)
    status = Column(String, default='pending')   # pending | approved | rejected | cancelled
    approved_by = Column(String, nullable=True)  # Name of the approver
    chat_id = Column(BigInteger, nullable=True)  # Group chat ID where request was submitted
    created_at = Column(String, default=func.datetime('now', 'localtime'))

    def __repr__(self):
        return f"<LeaveRequest(user_name='{self.user_name}', type='{self.leave_type}', status='{self.status}')>"
