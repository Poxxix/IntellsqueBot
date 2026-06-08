from sqlalchemy import Column, Integer, String, Boolean, DateTime, BigInteger, Float, func
from models.database import Base

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    display_name = Column(String, nullable=False)
    username = Column(String, nullable=True)
    role = Column(String, default='member')       # member | approver | admin | hr
    team = Column(String, nullable=True)
    status = Column(String, default='available')   # available | no available
    status_updated_at = Column(String, nullable=True)
    lunch_opt_in = Column(Boolean, default=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    joined_date = Column(DateTime, nullable=True)
    leave_balance = Column(Float, default=0.0)
    total_accrued = Column(Integer, default=0)

    def __repr__(self):
        return f"<User(display_name='{self.display_name}', role='{self.role}', status='{self.status}')>"

class Setting(Base):
    __tablename__ = 'settings'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    key = Column(String, nullable=False)            # e.g., 'welcome_active', 'welcome_message', 'digest_active'
    value = Column(String, nullable=False)
    
    def __repr__(self):
        return f"<Setting(chat_id={self.chat_id}, key='{self.key}', value='{self.value}')>"
