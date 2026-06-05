from sqlalchemy import Column, Integer, String, BigInteger, Text, func
from models.database import Base

class AuditLog(Base):
    __tablename__ = 'audit_logs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(BigInteger, nullable=False)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    meta_data = Column(Text, nullable=True)              # JSON string
    created_at = Column(String, default=func.datetime('now', 'localtime'))
