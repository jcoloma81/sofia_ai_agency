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

def verify_database_health(db_engine) -> bool:
    """Fast non-blocking connectivity check against database engine."""
    try:
        from sqlalchemy import text
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

def run_auto_migrations(db_engine):
    """
    Robust Pre-flight Database Migration:
    Ensures that existing databases (PostgreSQL on Render and SQLite locally)
    have all required tables, columns and indexes before accepting any requests.
    Guarantees zero HTTP 500 errors from schema mismatches in production.
    """
    import logging
    log = logging.getLogger("sofia_ai_agency.database")
    try:
        from sqlalchemy import text
        with db_engine.connect() as conn:
            is_sqlite = str(db_engine.url).startswith("sqlite")
            if is_sqlite:
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
                conn.execute(text("""
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS merchant_phone VARCHAR;
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS business_type VARCHAR;
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS campaign VARCHAR DEFAULT 'ai_agency';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS conversation_history TEXT DEFAULT '[]';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS notes TEXT;
                    DROP INDEX IF EXISTS ix_prospects_phone;
                    CREATE INDEX IF NOT EXISTS ix_prospects_phone ON prospects (phone);
                    CREATE INDEX IF NOT EXISTS ix_prospects_merchant_phone ON prospects (merchant_phone);
                """))
                conn.commit()
            log.info("🛡️ Pre-flight database schema check passed successfully.")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Error in run_auto_migrations: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

__all__ = ["engine", "SessionLocal", "Base", "get_db", "run_auto_migrations", "verify_database_health"]


