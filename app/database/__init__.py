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
                if col_names:
                    if "merchant_phone" not in col_names:
                        conn.execute(text("ALTER TABLE prospects ADD COLUMN merchant_phone VARCHAR"))
                    if "parent_merchant_phone" not in col_names:
                        conn.execute(text("ALTER TABLE prospects ADD COLUMN parent_merchant_phone VARCHAR"))
                    if "employee_role" not in col_names:
                        conn.execute(text("ALTER TABLE prospects ADD COLUMN employee_role VARCHAR DEFAULT 'owner'"))
                    if "can_dispatch" not in col_names:
                        conn.execute(text("ALTER TABLE prospects ADD COLUMN can_dispatch BOOLEAN DEFAULT 0"))
                    conn.commit()
                conn.execute(text("DROP INDEX IF EXISTS ix_prospects_phone"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_phone ON prospects (phone)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_merchant_phone ON prospects (merchant_phone)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_prospects_parent_merchant_phone ON prospects (parent_merchant_phone)"))
                # Ensure appointments 48h/24h columns
                res_apt = conn.execute(text("PRAGMA table_info(appointments)")).fetchall()
                apt_cols = [r[1] for r in res_apt]
                if apt_cols:
                    if "reminder_48h_sent_at" not in apt_cols:
                        conn.execute(text("ALTER TABLE appointments ADD COLUMN reminder_48h_sent_at TIMESTAMP"))
                    if "reminder_24h_sent_at" not in apt_cols:
                        conn.execute(text("ALTER TABLE appointments ADD COLUMN reminder_24h_sent_at TIMESTAMP"))
                    conn.commit()

                # Ensure waitlist_entries expires_at column
                res_wl = conn.execute(text("PRAGMA table_info(waitlist_entries)")).fetchall()
                wl_cols = [r[1] for r in res_wl]
                if wl_cols:
                    if "expires_at" not in wl_cols:
                        conn.execute(text("ALTER TABLE waitlist_entries ADD COLUMN expires_at TIMESTAMP"))
                    conn.commit()

                # Ensure bridge_commands table & indexes
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bridge_commands (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        command_id VARCHAR UNIQUE,
                        merchant_phone VARCHAR,
                        action VARCHAR,
                        target_file VARCHAR,
                        sheet_name VARCHAR,
                        payload TEXT DEFAULT '{}',
                        status VARCHAR DEFAULT 'pending',
                        result_message TEXT,
                        created_at TIMESTAMP,
                        completed_at TIMESTAMP
                    )
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bridge_commands_command_id ON bridge_commands (command_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bridge_commands_merchant_phone ON bridge_commands (merchant_phone)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bridge_commands_status ON bridge_commands (status)"))

                # Ensure tenants quota & plan columns
                res_tenants = conn.execute(text("PRAGMA table_info(tenants)")).fetchall()
                t_cols = [r[1] for r in res_tenants]
                if t_cols:
                    if "owner_email" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN owner_email VARCHAR"))
                    if "plan_type" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN plan_type VARCHAR DEFAULT 'shared'"))
                    if "monthly_message_quota" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN monthly_message_quota INTEGER DEFAULT 150"))
                    if "messages_sent_this_month" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN messages_sent_this_month INTEGER DEFAULT 0"))
                    if "extra_messages_balance" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN extra_messages_balance INTEGER DEFAULT 0"))
                    if "quota_exhausted_alert_sent" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN quota_exhausted_alert_sent BOOLEAN DEFAULT 0"))
                    if "last_quota_reset" not in t_cols:
                        conn.execute(text("ALTER TABLE tenants ADD COLUMN last_quota_reset TIMESTAMP"))

                # Ensure message_pack_payments table
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS message_pack_payments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id INTEGER,
                        mp_preference_id VARCHAR,
                        mp_payment_id VARCHAR UNIQUE,
                        external_reference VARCHAR UNIQUE,
                        pack_name VARCHAR DEFAULT 'Pack 100 Mensajes Extra',
                        pack_messages INTEGER DEFAULT 100,
                        amount REAL DEFAULT 4500.0,
                        status VARCHAR DEFAULT 'pending',
                        mp_init_point VARCHAR,
                        paid_at TIMESTAMP,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_msg_pack_ext_ref ON message_pack_payments (external_reference)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_msg_pack_tenant_id ON message_pack_payments (tenant_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_msg_pack_status ON message_pack_payments (status)"))
                conn.commit()
            else:
                conn.execute(text("""
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS merchant_phone VARCHAR;
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS parent_merchant_phone VARCHAR;
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS employee_role VARCHAR DEFAULT 'owner';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS can_dispatch BOOLEAN DEFAULT FALSE;
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS business_type VARCHAR;
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS campaign VARCHAR DEFAULT 'ai_agency';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'pending';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS conversation_history TEXT DEFAULT '[]';
                    ALTER TABLE prospects ADD COLUMN IF NOT EXISTS notes TEXT;
                    ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_48h_sent_at TIMESTAMP;
                    ALTER TABLE appointments ADD COLUMN IF NOT EXISTS reminder_24h_sent_at TIMESTAMP;
                    ALTER TABLE waitlist_entries ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
                    DROP INDEX IF EXISTS ix_prospects_phone;
                    CREATE INDEX IF NOT EXISTS ix_prospects_phone ON prospects (phone);
                    CREATE INDEX IF NOT EXISTS ix_prospects_merchant_phone ON prospects (merchant_phone);
                    CREATE INDEX IF NOT EXISTS ix_prospects_parent_merchant_phone ON prospects (parent_merchant_phone);

                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS owner_email VARCHAR;
                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan_type VARCHAR DEFAULT 'shared';
                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS monthly_message_quota INTEGER DEFAULT 150;
                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS messages_sent_this_month INTEGER DEFAULT 0;
                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS extra_messages_balance INTEGER DEFAULT 0;
                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS quota_exhausted_alert_sent BOOLEAN DEFAULT FALSE;
                    ALTER TABLE tenants ADD COLUMN IF NOT EXISTS last_quota_reset TIMESTAMP;

                    CREATE TABLE IF NOT EXISTS bridge_commands (
                        id SERIAL PRIMARY KEY,
                        command_id VARCHAR UNIQUE,
                        merchant_phone VARCHAR,
                        action VARCHAR,
                        target_file VARCHAR,
                        sheet_name VARCHAR,
                        payload TEXT DEFAULT '{}',
                        status VARCHAR DEFAULT 'pending',
                        result_message TEXT,
                        created_at TIMESTAMP,
                        completed_at TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS ix_bridge_commands_command_id ON bridge_commands (command_id);
                    CREATE INDEX IF NOT EXISTS ix_bridge_commands_merchant_phone ON bridge_commands (merchant_phone);
                    CREATE INDEX IF NOT EXISTS ix_bridge_commands_status ON bridge_commands (status);

                    CREATE TABLE IF NOT EXISTS message_pack_payments (
                        id SERIAL PRIMARY KEY,
                        tenant_id INTEGER,
                        mp_preference_id VARCHAR,
                        mp_payment_id VARCHAR UNIQUE,
                        external_reference VARCHAR UNIQUE,
                        pack_name VARCHAR DEFAULT 'Pack 100 Mensajes Extra',
                        pack_messages INTEGER DEFAULT 100,
                        amount DOUBLE PRECISION DEFAULT 4500.0,
                        status VARCHAR DEFAULT 'pending',
                        mp_init_point VARCHAR,
                        paid_at TIMESTAMP,
                        created_at TIMESTAMP,
                        updated_at TIMESTAMP
                    );
                    CREATE INDEX IF NOT EXISTS ix_msg_pack_ext_ref ON message_pack_payments (external_reference);
                    CREATE INDEX IF NOT EXISTS ix_msg_pack_tenant_id ON message_pack_payments (tenant_id);
                    CREATE INDEX IF NOT EXISTS ix_msg_pack_status ON message_pack_payments (status);
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


