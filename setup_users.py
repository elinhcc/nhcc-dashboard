"""One-time setup: creates the `users` table in Supabase and inserts the default admin.

Run ONCE from your local machine before first deployment:

    pip install psycopg2-binary
    python setup_users.py

Requires SUPABASE_DB_URL in .streamlit/secrets.toml  (NOT in requirements.txt —
psycopg2 is only needed here, not by the cloud app).

Get the URL from:
  Supabase Dashboard → Settings → Database → Connection string
  Choose the "Transaction pooler" URI tab (port 6543).

Add to .streamlit/secrets.toml:
  SUPABASE_DB_URL = "postgresql://postgres.[ref]:[password]@[host]:6543/postgres"
"""
import os
import re
import sys


def _get_db_url():
    url = os.environ.get("SUPABASE_DB_URL")
    if url:
        return url
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        try:
            text = open(secrets_path, encoding="utf-8").read()
            m = re.search(r'SUPABASE_DB_URL\s*=\s*["\']([^"\']+)["\']', text)
            if m:
                return m.group(1)
        except Exception as e:
            print(f"  Warning: could not parse secrets.toml: {e}")
    return None


def main():
    db_url = _get_db_url()
    if not db_url:
        print("ERROR: SUPABASE_DB_URL not found.")
        print()
        print("Add this to .streamlit/secrets.toml:")
        print('  SUPABASE_DB_URL = "postgresql://postgres.[ref]:[pass]@[host]:6543/postgres"')
        print()
        print("Get it from: Supabase Dashboard → Settings → Database → Connection string")
        print("             → Transaction pooler tab (port 6543)")
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed.")
        print("  Run:  pip install psycopg2-binary")
        sys.exit(1)

    try:
        import bcrypt
    except ImportError:
        print("ERROR: bcrypt not installed.")
        print("  Run:  pip install bcrypt")
        sys.exit(1)

    print(f"Connecting to Supabase PostgreSQL...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    # ── Create users table ────────────────────────────────────────────
    print("Creating users table (if not exists)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id          BIGSERIAL PRIMARY KEY,
            username    TEXT      NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            full_name   TEXT,
            role        TEXT      NOT NULL DEFAULT 'staff'
                        CHECK (role IN ('admin', 'staff')),
            is_active   BOOLEAN   NOT NULL DEFAULT TRUE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_login  TIMESTAMPTZ
        )
    """)
    print("  ✓ users table ready")

    # ── Create tasks table ────────────────────────────────────────────
    print("Creating tasks table (if not exists)...")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          BIGSERIAL PRIMARY KEY,
            practice_id BIGINT    NOT NULL REFERENCES practices(id),
            task_type   TEXT      NOT NULL,
            description TEXT,
            due_date    DATE,
            assigned_to TEXT,
            is_complete BOOLEAN   NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
    """)
    print("  ✓ tasks table ready")

    # ── Upsert default admin ──────────────────────────────────────────
    default_password = "Admin1234!"
    pw_hash = bcrypt.hashpw(default_password.encode(), bcrypt.gensalt()).decode()

    cur.execute("""
        INSERT INTO users (username, password_hash, full_name, role, is_active)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (username) DO UPDATE
            SET full_name  = EXCLUDED.full_name,
                role       = EXCLUDED.role,
                is_active  = EXCLUDED.is_active
    """, ("admin", pw_hash, "Administrator", "admin", True))
    print("  ✓ Admin user ready (username: admin)")

    cur.close()
    conn.close()

    print()
    print("=" * 50)
    print("Setup complete!")
    print("  Username: admin")
    print(f"  Password: {default_password}")
    print("  ⚠  Change the password after your first login!")
    print("=" * 50)


if __name__ == "__main__":
    main()
