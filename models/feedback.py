from sqlalchemy import Column, Integer, String, Text, func
from models.database import Base

class Feedback(Base):
    __tablename__ = 'feedbacks'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content = Column(Text, nullable=False)
    created_at = Column(String, default=func.datetime('now', 'localtime'))

    def __repr__(self):
        return f"<Feedback(id={self.id})>"
