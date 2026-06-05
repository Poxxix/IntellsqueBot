from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from config import DATABASE_URL

# Create engine
engine = create_async_engine(DATABASE_URL, echo=False)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()

async def init_db():
    # Import all models to ensure they register on Base.metadata
    from models.user import User, Setting
    from models.leave import LeaveRequest
    from models.spin import SpinHistory, Reaction
    from models.reminder import Reminder
    from models.info import InfoHub
    from models.feedback import Feedback
    from models.audit import AuditLog
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables initialized successfully.")

class db_session:
    """Async context manager to get db session easily in handlers."""
    async def __aenter__(self) -> AsyncSession:
        self.session = AsyncSessionLocal()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.session.rollback()
        else:
            await self.session.commit()
        await self.session.close()
