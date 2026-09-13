from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config.settings import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def run_auto_migrations(db_engine):
    """
    Ensures that existing databases (PostgreSQL and SQLite) seamlessly upgrade schema:
    - Adds merchant_phone column to prospects if missing.
    - Drops unique constraint on prospects.phone so multiple merchants can share suppliers.
    """
    try:
        from sqlalchemy import text
        with db_engine.connect() as conn:
            if str(db_engine.url).startswith("sqlite"):
                res = conn.execute(text("PRAGMA table_info(prospects)")).fetchall()
                col_names = [r[1] for r in res]
                if col_names and "merchant_phone" not in col_names:
                    conn.execute(text("ALTER TABLE prospects ADD COLUMN merchant_phone VARCHAR"))
                    conn.commit()
                conn.execute(text("DROP INDEX IF EXISTS ix_prospects_phone"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_phone ON prospects (phone)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_merchant_phone ON prospects (merchant_phone)"))
                conn.commit()
            else:
                conn.execute(text("ALTER TABLE prospects ADD COLUMN IF NOT EXISTS merchant_phone VARCHAR;"))
                conn.execute(text("DROP INDEX IF EXISTS ix_prospects_phone;"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_phone ON prospects (phone);"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_merchant_phone ON prospects (merchant_phone);"))
                conn.commit()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Error in run_auto_migrations: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

__all__ = ["engine", "SessionLocal", "Base", "get_db", "run_auto_migrations"]

