from sqlalchemy import Column, Integer, String, BigInteger, Boolean, func
from models.database import Base

class Reminder(Base):
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    title = Column(String, nullable=False)
    schedule_rule = Column(String, nullable=False)      # cron string or YYYY-MM-DD HH:MM:SS or HH:MM
    is_recurring = Column(Boolean, default=False)
    active = Column(Boolean, default=True)
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(String, default=func.datetime('now', 'localtime'))
