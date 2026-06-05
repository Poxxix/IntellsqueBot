import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    # We will log it, but let's allow it to not crash import if creating schema
    BOT_TOKEN = ""

admin_ids_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = []
for x in admin_ids_raw.split(","):
    x_clean = x.strip()
    if x_clean.isdigit():
        ADMIN_IDS.append(int(x_clean))

# Database connection conversion for async SQLAlchemy
database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///office_bot.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif database_url.startswith("sqlite://"):
    database_url = database_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
elif "://" not in database_url:
    # Handle pure paths
    database_url = f"sqlite+aiosqlite:///{database_url}"

DATABASE_URL = database_url
TZ = os.getenv("TZ", "Asia/Ho_Chi_Minh")

# Set system timezone
if os.name != 'nt': # Unix/Mac only
    try:
        import time
        os.environ['TZ'] = TZ
        time.tzset()
    except Exception:
        pass

DIGEST_TIME = os.getenv("DIGEST_TIME", "08:30")
