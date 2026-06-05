from sqlalchemy import Column, Integer, String, BigInteger, func
from models.database import Base

class Task(Base):
    __tablename__ = 'tasks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, nullable=False)
    assignee_id = Column(BigInteger, nullable=True)     # Telegram ID of assignee
    created_by = Column(BigInteger, nullable=False)
    deadline = Column(String, nullable=True)            # YYYY-MM-DD
    status = Column(String, default='open')            # open | done | cancelled
    chat_id = Column(BigInteger, nullable=False)
    created_at = Column(String, default=func.datetime('now', 'localtime'))
