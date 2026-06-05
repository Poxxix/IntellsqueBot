from sqlalchemy import Column, Integer, String, Text, func
from models.database import Base

class InfoHub(Base):
    __tablename__ = 'info_hub'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text, nullable=False)
    created_at = Column(String, default=func.datetime('now', 'localtime'))

    def __repr__(self):
        return f"<InfoHub(key='{self.key}')>"
