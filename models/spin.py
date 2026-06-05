from sqlalchemy import Column, Integer, String, BigInteger, Text, func
from models.database import Base

class SpinHistory(Base):
    __tablename__ = 'spin_history'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    spin_type = Column(String, nullable=False)      # random_member | random_role | random_team
    result = Column(String, nullable=False)
    pool_snapshot = Column(Text, nullable=True)     # JSON string of candidates
    created_by = Column(BigInteger, nullable=True)
    created_at = Column(String, default=func.datetime('now', 'localtime'))

class Reaction(Base):
    __tablename__ = 'reactions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    user_name = Column(String, nullable=False)
    reaction_type = Column(String, nullable=False)  # emoji | vote
    value = Column(String, nullable=False)          # 👍, 👎, 🤔 or option index (0, 1, 2...)
    created_at = Column(String, default=func.datetime('now', 'localtime'))
