"""Database abstraction: Supabase (cloud) with SQLite fallback (local dev).

On Streamlit Cloud the SUPABASE_URL and SUPABASE_KEY secrets are set in the
Streamlit secrets dashboard.  Locally, .streamlit/secrets.toml is used.
If neither is available, all operations fall back to the local providers.db
SQLite file.
"""
import sqlite3
import os
import re
from collections import defaultdict
from datetime import datetime, date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.db")

# ── Supabase lazy-init ────────────────────────────────────────────────────────

_supa_client = None
_supa_initialized = False


def _supa():
    """Return Supabase client (lazy-init), or None if not configured."""
    global _supa_client, _supa_initialized
    if _supa_initialized:
        return _supa_client
    _supa_initialized = True
    try:
        import streamlit as st
        url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase", {}).get("url")
        key = st.secrets.get("SUPABASE_KEY") or st.secrets.get("supabase", {}).get("key")
        if url and key:
            from supabase import create_client
            _supa_client = create_client(url, key)
    except Exception:
        pass
    return _supa_client


def _sqlite():
    """Return a configured SQLite connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Utilities ─────────────────────────────────────────────────────────────────

def _ym_to_range(ym: str):
    """'YYYY-MM' → (start_iso, end_iso) covering the full calendar month."""
    year, month = int(ym[:4]), int(ym[5:7])
    start = f"{year}-{month:02d}-01"
    end = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
    return start, end


def _pop_embed(row: dict, embed_key: str, flat_key: str):
    """Flatten a PostgREST embedded-resource dict into a top-level field."""
    embedded = row.pop(embed_key, None)
    row[flat_key] = embedded.get("name") if isinstance(embedded, dict) else None
    return row


# ── Core helpers ──────────────────────────────────────────────────────────────

def db_exists() -> bool:
    """Return True if the database has at least one practice row."""
    supa = _supa()
    if supa:
        try:
            result = supa.table("practices").select("id", count="exact").limit(1).execute()
            return (result.count or 0) > 0
        except Exception:
            return False
    if not os.path.exists(DB_PATH):
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def get_connection():
    """SQLite connection — kept for backward-compat with admin/diagnostic code.
    On Supabase deployments, prefer the typed helper functions below.
    """
    return _sqlite()


def init_db():
    """Create SQLite schema (no-op when using Supabase — tables live in Postgres)."""
    if _supa():
        return  # Schema is managed in Supabase SQL editor
    conn = _sqlite()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS practices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        zip_code TEXT,
        location_category TEXT DEFAULT 'Other',
        website TEXT,
        specialty TEXT,
        contact_person TEXT,
        phone TEXT,
        fax TEXT,
        fax_vonage_email TEXT,
        email TEXT,
        status TEXT DEFAULT 'Active',
        referral_volume INTEGER DEFAULT 0,
        notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS providers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        practice_id INTEGER,
        status TEXT DEFAULT 'Active',
        inactive_reason TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS provider_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER NOT NULL,
        old_practice_id INTEGER,
        new_practice_id INTEGER,
        move_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        notes TEXT,
        FOREIGN KEY (provider_id) REFERENCES providers(id),
        FOREIGN KEY (old_practice_id) REFERENCES practices(id),
        FOREIGN KEY (new_practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS contact_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        contact_type TEXT NOT NULL,
        contact_date DATETIME,
        team_member TEXT,
        person_contacted TEXT,
        outcome TEXT,
        purpose TEXT,
        call_attempt_number INTEGER,
        notes TEXT,
        contact_method TEXT,
        email_subject TEXT,
        fax_document TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS lunch_tracking (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        status TEXT DEFAULT 'Not Contacted',
        scheduled_date DATETIME,
        scheduled_time TEXT,
        staff_count INTEGER,
        dietary_notes TEXT,
        restaurant TEXT,
        confirmed_with TEXT,
        completed_date DATETIME,
        actual_attendees INTEGER,
        visit_notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS call_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lunch_id INTEGER,
        practice_id INTEGER NOT NULL,
        call_date DATETIME,
        call_time TEXT,
        person_contacted TEXT,
        outcome TEXT,
        notes TEXT,
        FOREIGN KEY (lunch_id) REFERENCES lunch_tracking(id),
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS thank_you_letters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER,
        practice_id INTEGER NOT NULL,
        lunch_id INTEGER,
        reason TEXT DEFAULT 'Post-Lunch',
        status TEXT DEFAULT 'Pending',
        date_mailed DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (provider_id) REFERENCES providers(id),
        FOREIGN KEY (practice_id) REFERENCES practices(id),
        FOREIGN KEY (lunch_id) REFERENCES lunch_tracking(id)
    );
    CREATE TABLE IF NOT EXISTS cookie_visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        visit_date DATETIME,
        items_delivered TEXT,
        delivered_by TEXT,
        notes TEXT,
        status TEXT DEFAULT 'Logged',
        next_visit_date DATETIME,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS flyer_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sent_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        flyer_name TEXT,
        sent_by TEXT
    );
    CREATE TABLE IF NOT EXISTS flyer_recipients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id INTEGER NOT NULL,
        practice_id INTEGER NOT NULL,
        vonage_email TEXT,
        status TEXT DEFAULT 'Sent',
        error_message TEXT,
        FOREIGN KEY (campaign_id) REFERENCES flyer_campaigns(id),
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER,
        provider_id INTEGER,
        event_type TEXT,
        label TEXT,
        scheduled_date DATETIME,
        scheduled_time TEXT,
        status TEXT DEFAULT 'Scheduled',
        notes TEXT,
        created_by TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        followup_interval TEXT,
        next_event_id INTEGER,
        FOREIGN KEY (practice_id) REFERENCES practices(id),
        FOREIGN KEY (provider_id) REFERENCES providers(id),
        FOREIGN KEY (next_event_id) REFERENCES events(id)
    );
    CREATE TABLE IF NOT EXISTS recurring_reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        day_of_month INTEGER NOT NULL DEFAULT 1,
        active INTEGER NOT NULL DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS follow_ups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        follow_up_type TEXT NOT NULL,
        follow_up_date DATETIME,
        interval TEXT,
        status TEXT DEFAULT 'Scheduled',
        notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        task_type TEXT NOT NULL,
        description TEXT,
        due_date DATE,
        assigned_to TEXT,
        is_complete INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        role TEXT DEFAULT 'staff',
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_login DATETIME
    );
    CREATE TABLE IF NOT EXISTS outreach_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL UNIQUE,
        lunch_status TEXT DEFAULT 'Not Started',
        lunch_status_date DATE,
        lunch_note TEXT,
        last_lunch_date DATE,
        next_lunch_due DATE,
        lunch_amount_spent REAL,
        cookie_status TEXT DEFAULT 'Not Started',
        cookie_status_date DATE,
        cookie_note TEXT,
        last_cookie_date DATE,
        next_cookie_due DATE,
        cookie_amount_spent REAL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS outreach_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        outreach_type TEXT NOT NULL,
        status TEXT NOT NULL,
        status_date DATE,
        note TEXT,
        amount_spent REAL,
        updated_by TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS provider_referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_id INTEGER NOT NULL,
        practice_id INTEGER NOT NULL,
        referral_date DATE NOT NULL,
        patient_initials TEXT,
        notes TEXT,
        logged_by TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (provider_id) REFERENCES providers(id),
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    CREATE TABLE IF NOT EXISTS referral_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        week_ending_date DATE NOT NULL,
        referral_count INTEGER NOT NULL DEFAULT 0,
        service_line TEXT,
        notes TEXT,
        logged_by TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (practice_id) REFERENCES practices(id)
    );
    """)
    _migrate_column(c, "contact_log", "purpose", "TEXT")
    _migrate_column(c, "contact_log", "call_attempt_number", "INTEGER")
    _migrate_column(c, "contact_log", "contact_method", "TEXT")
    _migrate_column(c, "contact_log", "email_subject", "TEXT")
    _migrate_column(c, "contact_log", "fax_document", "TEXT")
    _migrate_column(c, "cookie_visits", "status", "TEXT DEFAULT 'Logged'")
    _migrate_column(c, "cookie_visits", "next_visit_date", "DATETIME")
    _migrate_column(c, "practices", "specialty", "TEXT")
    _migrate_column(c, "tasks", "notes", "TEXT")
    _migrate_column(c, "tasks", "task_type", "TEXT")
    _migrate_column(c, "tasks", "is_complete", "INTEGER DEFAULT 0")
    _migrate_column(c, "providers", "is_new_referrer", "INTEGER DEFAULT 0")
    _migrate_column(c, "providers", "specialty", "TEXT")
    _migrate_column(c, "providers", "first_referral_date", "DATE")
    _migrate_column(c, "providers", "last_referral_date", "DATE")
    _migrate_column(c, "providers", "total_referrals", "INTEGER DEFAULT 0")
    _migrate_column(c, "providers", "welcome_package_sent", "INTEGER DEFAULT 0")
    _migrate_column(c, "providers", "welcome_package_sent_date", "DATE")
    _migrate_column(c, "providers", "thank_you_sent", "INTEGER DEFAULT 0")
    _migrate_column(c, "providers", "intro_folder_sent", "INTEGER DEFAULT 0")
    _migrate_column(c, "providers", "business_card_sent", "INTEGER DEFAULT 0")
    _migrate_column(c, "practices", "pipeline_stage", "TEXT DEFAULT 'New Lead'")
    _migrate_column(c, "practices", "first_referral_date", "DATE")
    _migrate_column(c, "practices", "last_referral_date", "DATE")
    _migrate_column(c, "practices", "total_referrals", "INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def _migrate_column(cursor, table, column, col_type):
    try:
        cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass


# ── Practice CRUD ─────────────────────────────────────────────────────────────

def get_all_practices(status_filter=None):
    supa = _supa()
    if supa:
        q = supa.table("practices").select("*").order("name")
        if status_filter:
            q = q.eq("status", status_filter)
        return q.execute().data or []
    conn = _sqlite()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM practices WHERE status=? ORDER BY name", (status_filter,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM practices ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_practice(practice_id):
    supa = _supa()
    if supa:
        result = supa.table("practices").select("*").eq("id", practice_id).limit(1).execute()
        return result.data[0] if result.data else None
    conn = _sqlite()
    row = conn.execute("SELECT * FROM practices WHERE id=?", (practice_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_practice(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("practices").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO practices ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_practice(practice_id: int, data: dict):
    supa = _supa()
    data["updated_at"] = datetime.now().isoformat()
    if supa:
        supa.table("practices").update(data).eq("id", practice_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE practices SET {sets} WHERE id=?", list(data.values()) + [practice_id])
    conn.commit()
    conn.close()


def search_practices(query: str):
    supa = _supa()
    if supa:
        q = f"%{query}%"
        result = supa.table("practices").select("*").or_(
            f"name.ilike.{q},address.ilike.{q},phone.ilike.{q},fax.ilike.{q}"
        ).order("name").execute()
        return result.data or []
    conn = _sqlite()
    q = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM practices WHERE name LIKE ? OR address LIKE ? OR phone LIKE ? OR fax LIKE ? ORDER BY name",
        (q, q, q, q),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Provider CRUD ─────────────────────────────────────────────────────────────

def get_providers_for_practice(practice_id):
    supa = _supa()
    if supa:
        result = supa.table("providers").select("*").eq("practice_id", practice_id).order("name").execute()
        return result.data or []
    conn = _sqlite()
    rows = conn.execute(
        "SELECT * FROM providers WHERE practice_id=? ORDER BY name", (practice_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_providers():
    supa = _supa()
    if supa:
        result = supa.table("providers").select("*, practices(name)").order("name").execute()
        rows = result.data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    rows = conn.execute(
        "SELECT p.*, pr.name as practice_name FROM providers p "
        "LEFT JOIN practices pr ON p.practice_id=pr.id ORDER BY p.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_provider(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("providers").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO providers ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_provider(provider_id: int, data: dict):
    supa = _supa()
    data["updated_at"] = datetime.now().isoformat()
    if supa:
        supa.table("providers").update(data).eq("id", provider_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE providers SET {sets} WHERE id=?", list(data.values()) + [provider_id])
    conn.commit()
    conn.close()


def get_provider(provider_id: int):
    supa = _supa()
    if supa:
        result = supa.table("providers").select("*").eq("id", provider_id).limit(1).execute()
        return result.data[0] if result.data else None
    conn = _sqlite()
    row = conn.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_provider(provider_id: int):
    supa = _supa()
    if supa:
        supa.table("provider_history").delete().eq("provider_id", provider_id).execute()
        supa.table("thank_you_letters").update({"provider_id": None}).eq("provider_id", provider_id).execute()
        supa.table("providers").delete().eq("id", provider_id).execute()
        return
    conn = _sqlite()
    conn.execute("DELETE FROM provider_history WHERE provider_id=?", (provider_id,))
    conn.execute("UPDATE thank_you_letters SET provider_id=NULL WHERE provider_id=?", (provider_id,))
    conn.execute("DELETE FROM providers WHERE id=?", (provider_id,))
    conn.commit()
    conn.close()


def move_provider(provider_id: int, new_practice_id: int, notes: str = ""):
    old_id = None
    supa = _supa()
    if supa:
        existing = supa.table("providers").select("practice_id").eq("id", provider_id).limit(1).execute()
        if existing.data:
            old_id = existing.data[0].get("practice_id")
        supa.table("providers").update({
            "practice_id": new_practice_id,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", provider_id).execute()
        supa.table("provider_history").insert({
            "provider_id": provider_id,
            "old_practice_id": old_id,
            "new_practice_id": new_practice_id,
            "notes": notes,
        }).execute()
        return
    conn = _sqlite()
    old = conn.execute("SELECT practice_id FROM providers WHERE id=?", (provider_id,)).fetchone()
    old_id = old["practice_id"] if old else None
    conn.execute(
        "UPDATE providers SET practice_id=?, updated_at=? WHERE id=?",
        (new_practice_id, datetime.now().isoformat(), provider_id),
    )
    conn.execute(
        "INSERT INTO provider_history (provider_id, old_practice_id, new_practice_id, notes) VALUES (?,?,?,?)",
        (provider_id, old_id, new_practice_id, notes),
    )
    conn.commit()
    conn.close()


# ── Contact Log ───────────────────────────────────────────────────────────────

def add_contact_log(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("contact_log").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO contact_log ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def get_contact_log(practice_id=None, limit=50):
    supa = _supa()
    if supa:
        q = supa.table("contact_log").select("*, practices(name)").order("contact_date", desc=True).limit(limit)
        if practice_id:
            q = q.eq("practice_id", practice_id)
        rows = q.execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    if practice_id:
        rows = conn.execute(
            "SELECT cl.*, pr.name as practice_name FROM contact_log cl "
            "JOIN practices pr ON cl.practice_id=pr.id "
            "WHERE cl.practice_id=? ORDER BY cl.contact_date DESC LIMIT ?",
            (practice_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT cl.*, pr.name as practice_name FROM contact_log cl "
            "JOIN practices pr ON cl.practice_id=pr.id "
            "ORDER BY cl.contact_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_contact_log_by_date(start_date: str, end_date: str, limit: int = 2000):
    """Return contact log rows between start_date and end_date (inclusive, YYYY-MM-DD).
    Joins practices for practice_name. Ordered by team_member then contact_date.
    """
    supa = _supa()
    if supa:
        rows = (
            supa.table("contact_log")
            .select("*, practices(name)")
            .gte("contact_date", start_date)
            .lte("contact_date", end_date + "T23:59:59")
            .order("team_member")
            .order("contact_date")
            .limit(limit)
            .execute()
            .data or []
        )
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    rows = conn.execute(
        "SELECT cl.*, pr.name as practice_name FROM contact_log cl "
        "JOIN practices pr ON cl.practice_id=pr.id "
        "WHERE cl.contact_date >= ? AND cl.contact_date <= ? "
        "ORDER BY cl.team_member, cl.contact_date LIMIT ?",
        (start_date, end_date + " 23:59:59", limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Referral Log (practice-level weekly counts) ────────────────────────────────

def add_referral_log(data: dict) -> int:
    """Insert a referral_log entry and refresh the practice's referral summary.

    On the practice's first-ever referral: auto-updates pipeline_stage to 'Referring'
    and creates thank-you / intro-package / schedule-lunch tasks.
    Returns the new row id.
    """
    data = dict(data)
    data.setdefault("created_at", datetime.now().isoformat())
    practice_id = data.get("practice_id")

    supa = _supa()
    if supa:
        try:
            result = supa.table("referral_log").insert(data).execute()
            rid = result.data[0]["id"]
        except Exception:
            rid = 0
    else:
        conn = _sqlite()
        try:
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            cur = conn.execute(
                f"INSERT INTO referral_log ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
            conn.commit()
            rid = cur.lastrowid
        except Exception:
            rid = 0
        finally:
            conn.close()

    if practice_id:
        _refresh_practice_referral_stats(practice_id, data.get("logged_by", ""))
    return rid


def _refresh_practice_referral_stats(practice_id: int, logged_by: str = ""):
    """Recompute practice total_referrals, first/last dates; advance stage on first referral."""
    supa = _supa()
    if supa:
        try:
            rows = (supa.table("referral_log")
                    .select("week_ending_date,referral_count")
                    .eq("practice_id", practice_id)
                    .order("week_ending_date")
                    .execute().data or [])
        except Exception:
            return
    else:
        conn = _sqlite()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT week_ending_date, referral_count FROM referral_log "
                "WHERE practice_id=? ORDER BY week_ending_date",
                (practice_id,),
            ).fetchall()]
        except Exception:
            rows = []
        finally:
            conn.close()

    if not rows:
        return

    total      = sum(r.get("referral_count") or 0 for r in rows)
    first_date = rows[0].get("week_ending_date") if rows else None
    last_date  = rows[-1].get("week_ending_date") if rows else None
    is_first   = len(rows) == 1

    update_data: dict = {
        "total_referrals":     total,
        "first_referral_date": first_date,
        "last_referral_date":  last_date,
    }
    if is_first:
        update_data["pipeline_stage"] = "Referring"

    supa = _supa()
    if supa:
        try:
            supa.table("practices").update(update_data).eq("id", practice_id).execute()
        except Exception:
            pass
    else:
        conn = _sqlite()
        try:
            sets = ", ".join(f"{k}=?" for k in update_data)
            conn.execute(
                f"UPDATE practices SET {sets} WHERE id=?",
                list(update_data.values()) + [practice_id],
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    if is_first:
        try:
            from datetime import date as _d, timedelta as _td
            today = _d.today()
            for task_type, desc in [
                ("Send Thank You Letter",  f"Send thank you letter to new referring practice (#{practice_id})"),
                ("Send Intro Package",     f"Send introductory folder to new referring practice (#{practice_id})"),
                ("Schedule Lunch",         f"Schedule lunch with new referring practice (#{practice_id})"),
            ]:
                add_task({
                    "practice_id": practice_id,
                    "task_type":   task_type,
                    "description": desc,
                    "due_date":    (today + _td(days=3)).isoformat(),
                    "assigned_to": logged_by or "",
                    "is_complete": 0,
                    "created_at":  datetime.now().isoformat(),
                })
        except Exception:
            pass


def get_referral_log(practice_id=None, start_date=None, end_date=None, limit=1000):
    """Fetch referral_log rows, optionally filtered by practice and/or date range."""
    supa = _supa()
    if supa:
        try:
            q = (supa.table("referral_log")
                 .select("*, practices(name)")
                 .order("week_ending_date", desc=True)
                 .limit(limit))
            if practice_id:
                q = q.eq("practice_id", practice_id)
            if start_date:
                q = q.gte("week_ending_date", start_date)
            if end_date:
                q = q.lte("week_ending_date", end_date)
            rows = q.execute().data or []
            for row in rows:
                _pop_embed(row, "practices", "practice_name")
            return rows
        except Exception:
            return []

    conn = _sqlite()
    try:
        clauses, params = [], []
        if practice_id:
            clauses.append("rl.practice_id=?"); params.append(practice_id)
        if start_date:
            clauses.append("rl.week_ending_date>=?"); params.append(start_date)
        if end_date:
            clauses.append("rl.week_ending_date<=?"); params.append(end_date)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT rl.*, pr.name AS practice_name FROM referral_log rl "
            f"JOIN practices pr ON rl.practice_id=pr.id "
            f"{where} ORDER BY rl.week_ending_date DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def get_pipeline_overview() -> dict:
    """Return {stage: count} for all Active practices."""
    supa = _supa()
    if supa:
        try:
            rows = (supa.table("practices")
                    .select("pipeline_stage")
                    .eq("status", "Active")
                    .execute().data or [])
            counts: dict = {}
            for r in rows:
                s = r.get("pipeline_stage") or "New Lead"
                counts[s] = counts.get(s, 0) + 1
            return counts
        except Exception:
            return {}

    conn = _sqlite()
    try:
        rows = conn.execute(
            "SELECT COALESCE(pipeline_stage,'New Lead') AS stage, COUNT(*) AS cnt "
            "FROM practices WHERE status='Active' GROUP BY stage"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}
    finally:
        conn.close()


def get_referral_alerts() -> list:
    """Return list of alert dicts: new_referrer, referral_drop, six_month_lead."""
    import datetime as _dt
    today = _dt.date.today()
    d30   = (today - _dt.timedelta(days=30)).isoformat()
    d150  = (today - _dt.timedelta(days=150)).isoformat()

    supa = _supa()
    if supa:
        try:
            practices = (supa.table("practices")
                         .select("id,name,pipeline_stage,first_referral_date,"
                                 "last_referral_date,total_referrals,created_at")
                         .eq("status", "Active")
                         .execute().data or [])
        except Exception:
            return []
    else:
        conn = _sqlite()
        try:
            practices = [dict(r) for r in conn.execute(
                "SELECT id,name,pipeline_stage,first_referral_date,last_referral_date,"
                "total_referrals,created_at FROM practices WHERE status='Active'"
            ).fetchall()]
        except Exception:
            return []
        finally:
            conn.close()

    alerts = []
    for p in practices:
        stage     = p.get("pipeline_stage") or "New Lead"
        first_ref = (p.get("first_referral_date") or "")[:10]
        last_ref  = (p.get("last_referral_date")  or "")[:10]
        total     = p.get("total_referrals") or 0
        created   = (p.get("created_at") or "")[:10]

        if first_ref and first_ref >= d30:
            alerts.append({
                "type": "new_referrer", "color": "green",
                "practice": p["name"], "practice_id": p["id"],
                "detail": f"First referral logged {first_ref}",
                "action": "Send thank you letter + schedule lunch",
            })
        elif total > 0 and last_ref and last_ref < d30 and stage in ("Referring", "Routine Referring"):
            alerts.append({
                "type": "referral_drop", "color": "red",
                "practice": p["name"], "practice_id": p["id"],
                "detail": f"No referrals since {last_ref} ({total} total)",
                "action": "Schedule courtesy call — check in",
            })
        elif stage == "New Lead" and total == 0 and created and created <= d150:
            alerts.append({
                "type": "six_month_lead", "color": "yellow",
                "practice": p["name"], "practice_id": p["id"],
                "detail": f"In New Lead since ~{created[:7]}, no referrals logged",
                "action": "Evaluate: continue nurturing or move to Dropped",
            })

    return sorted(alerts, key=lambda a: ("green", "yellow", "red").index(a["color"])
                  if a["color"] in ("green", "yellow", "red") else 3)


def get_referral_monthly_totals(months: int = 12) -> list:
    """Return [{'month': 'YYYY-MM', 'total': N}, ...] for last N calendar months."""
    import datetime as _dt
    supa = _supa()
    if supa:
        try:
            rows = (supa.table("referral_log")
                    .select("week_ending_date,referral_count")
                    .execute().data or [])
        except Exception:
            rows = []
    else:
        conn = _sqlite()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT week_ending_date, referral_count FROM referral_log"
            ).fetchall()]
        except Exception:
            rows = []
        finally:
            conn.close()

    month_totals: dict = {}
    for r in rows:
        ym = (r.get("week_ending_date") or "")[:7]
        if ym:
            month_totals[ym] = month_totals.get(ym, 0) + (r.get("referral_count") or 0)

    today = _dt.date.today()
    result = []
    for i in range(months - 1, -1, -1):
        dt = (today.replace(day=1) - _dt.timedelta(days=i * 30)).replace(day=1)
        ym = dt.strftime("%Y-%m")
        result.append({"month": ym, "total": month_totals.get(ym, 0)})
    return result


def get_referral_dashboard_stats() -> dict:
    """Return referral KPIs for the main dashboard."""
    import datetime as _dt
    today      = _dt.date.today()
    this_month = today.strftime("%Y-%m")
    d30        = (today - _dt.timedelta(days=30)).isoformat()

    stats = {
        "referrals_this_month":    0,
        "new_referrers_this_month": 0,
        "referral_drops":          0,
        "pipeline_referring":      0,
    }

    supa = _supa()
    if supa:
        try:
            rows = (supa.table("referral_log")
                    .select("referral_count")
                    .gte("week_ending_date", f"{this_month}-01")
                    .execute().data or [])
            stats["referrals_this_month"] = sum(r.get("referral_count") or 0 for r in rows)
            nr = (supa.table("practices").select("id", count="exact")
                  .gte("first_referral_date", f"{this_month}-01")
                  .eq("status", "Active").execute())
            stats["new_referrers_this_month"] = nr.count or 0
            drops = (supa.table("practices").select("id", count="exact")
                     .in_("pipeline_stage", ["Referring", "Routine Referring"])
                     .lt("last_referral_date", d30)
                     .not_.is_("last_referral_date", "null")
                     .eq("status", "Active").execute())
            stats["referral_drops"] = drops.count or 0
            ref = (supa.table("practices").select("id", count="exact")
                   .in_("pipeline_stage", ["Referring", "Routine Referring"])
                   .eq("status", "Active").execute())
            stats["pipeline_referring"] = ref.count or 0
        except Exception:
            pass
        return stats

    conn = _sqlite()
    try:
        stats["referrals_this_month"] = conn.execute(
            "SELECT COALESCE(SUM(referral_count),0) FROM referral_log "
            "WHERE strftime('%Y-%m',week_ending_date)=?", (this_month,)
        ).fetchone()[0]
        stats["new_referrers_this_month"] = conn.execute(
            "SELECT COUNT(*) FROM practices WHERE status='Active' "
            "AND first_referral_date>=?", (f"{this_month}-01",)
        ).fetchone()[0]
        stats["referral_drops"] = conn.execute(
            "SELECT COUNT(*) FROM practices WHERE status='Active' "
            "AND pipeline_stage IN ('Referring','Routine Referring') "
            "AND last_referral_date IS NOT NULL AND last_referral_date<?", (d30,)
        ).fetchone()[0]
        stats["pipeline_referring"] = conn.execute(
            "SELECT COUNT(*) FROM practices WHERE status='Active' "
            "AND pipeline_stage IN ('Referring','Routine Referring')"
        ).fetchone()[0]
    except Exception:
        pass
    finally:
        conn.close()
    return stats


def get_call_attempt_count(practice_id: int) -> int:
    supa = _supa()
    if supa:
        result = supa.table("contact_log").select("id", count="exact").eq(
            "practice_id", practice_id
        ).eq("contact_type", "Phone Call").execute()
        return result.count or 0
    conn = _sqlite()
    count = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE practice_id=? AND contact_type='Phone Call'",
        (practice_id,),
    ).fetchone()[0]
    conn.close()
    return count


def get_last_contact(practice_id: int):
    supa = _supa()
    if supa:
        result = supa.table("contact_log").select("*").eq(
            "practice_id", practice_id
        ).order("contact_date", desc=True).limit(1).execute()
        return result.data[0] if result.data else None
    conn = _sqlite()
    row = conn.execute(
        "SELECT * FROM contact_log WHERE practice_id=? ORDER BY contact_date DESC LIMIT 1",
        (practice_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Lunch Tracking ────────────────────────────────────────────────────────────

def add_lunch(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("lunch_tracking").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO lunch_tracking ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def get_lunches(practice_id=None, status_filter=None):
    supa = _supa()
    if supa:
        q = supa.table("lunch_tracking").select("*, practices(name)").order("scheduled_date", desc=True)
        if practice_id:
            q = q.eq("practice_id", practice_id)
        if status_filter:
            q = q.eq("status", status_filter)
        rows = q.execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    query = "SELECT lt.*, pr.name as practice_name FROM lunch_tracking lt JOIN practices pr ON lt.practice_id=pr.id"
    params = []
    conditions = []
    if practice_id:
        conditions.append("lt.practice_id=?")
        params.append(practice_id)
    if status_filter:
        conditions.append("lt.status=?")
        params.append(status_filter)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY lt.scheduled_date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_lunch(lunch_id: int, data: dict):
    supa = _supa()
    if supa:
        supa.table("lunch_tracking").update(data).eq("id", lunch_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE lunch_tracking SET {sets} WHERE id=?", list(data.values()) + [lunch_id])
    conn.commit()
    conn.close()


# ── Call Attempts ─────────────────────────────────────────────────────────────

def add_call_attempt(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("call_attempts").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO call_attempts ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def get_call_attempts(lunch_id=None, practice_id=None):
    supa = _supa()
    if supa:
        q = supa.table("call_attempts").select("*").order("call_date", desc=True)
        if lunch_id:
            q = q.eq("lunch_id", lunch_id)
        elif practice_id:
            q = q.eq("practice_id", practice_id)
        return q.execute().data or []
    conn = _sqlite()
    if lunch_id:
        rows = conn.execute(
            "SELECT * FROM call_attempts WHERE lunch_id=? ORDER BY call_date DESC", (lunch_id,)
        ).fetchall()
    elif practice_id:
        rows = conn.execute(
            "SELECT * FROM call_attempts WHERE practice_id=? ORDER BY call_date DESC", (practice_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM call_attempts ORDER BY call_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Thank You Letters ─────────────────────────────────────────────────────────

def add_thank_you(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("thank_you_letters").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO thank_you_letters ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_thank_yous(practice_id=None, status_filter=None):
    supa = _supa()
    if supa:
        q = supa.table("thank_you_letters").select(
            "*, practices(name), providers(name)"
        ).order("created_at", desc=True)
        if practice_id:
            q = q.eq("practice_id", practice_id)
        if status_filter:
            q = q.eq("status", status_filter)
        rows = q.execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
            p = row.pop("providers", None)
            row["provider_name"] = p.get("name") if isinstance(p, dict) else None
        return rows
    conn = _sqlite()
    query = (
        "SELECT ty.*, pr.name as practice_name, prov.name as provider_name "
        "FROM thank_you_letters ty "
        "JOIN practices pr ON ty.practice_id=pr.id "
        "LEFT JOIN providers prov ON ty.provider_id=prov.id"
    )
    params = []
    conditions = []
    if practice_id:
        conditions.append("ty.practice_id=?")
        params.append(practice_id)
    if status_filter:
        conditions.append("ty.status=?")
        params.append(status_filter)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY ty.created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_thank_you(ty_id: int, data: dict):
    supa = _supa()
    if supa:
        supa.table("thank_you_letters").update(data).eq("id", ty_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE thank_you_letters SET {sets} WHERE id=?", list(data.values()) + [ty_id])
    conn.commit()
    conn.close()


# ── Cookie Visits ─────────────────────────────────────────────────────────────

def add_cookie_visit(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("cookie_visits").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO cookie_visits ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    vid = cur.lastrowid
    conn.close()
    return vid


def get_cookie_visits(practice_id=None):
    supa = _supa()
    if supa:
        q = supa.table("cookie_visits").select("*, practices(name)").order("visit_date", desc=True)
        if practice_id:
            q = q.eq("practice_id", practice_id)
        rows = q.execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    if practice_id:
        rows = conn.execute(
            "SELECT cv.*, pr.name as practice_name FROM cookie_visits cv "
            "JOIN practices pr ON cv.practice_id=pr.id "
            "WHERE cv.practice_id=? ORDER BY cv.visit_date DESC",
            (practice_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT cv.*, pr.name as practice_name FROM cookie_visits cv "
            "JOIN practices pr ON cv.practice_id=pr.id "
            "ORDER BY cv.visit_date DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Flyer Campaigns ───────────────────────────────────────────────────────────

def add_flyer_campaign(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("flyer_campaigns").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO flyer_campaigns ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def add_flyer_recipient(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("flyer_recipients").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO flyer_recipients ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_flyer_campaigns():
    supa = _supa()
    if supa:
        campaigns = supa.table("flyer_campaigns").select("*").order("sent_date", desc=True).execute().data or []
        recipients = supa.table("flyer_recipients").select("campaign_id,status").execute().data or []
        by_campaign = defaultdict(list)
        for r in recipients:
            by_campaign[r["campaign_id"]].append(r)
        for c in campaigns:
            recs = by_campaign[c["id"]]
            c["recipient_count"] = len(recs)
            c["sent_count"] = sum(1 for r in recs if r["status"] == "Sent")
            c["failed_count"] = sum(1 for r in recs if r["status"] == "Failed")
        return campaigns
    conn = _sqlite()
    rows = conn.execute(
        "SELECT fc.*, COUNT(fr.id) as recipient_count, "
        "SUM(CASE WHEN fr.status='Sent' THEN 1 ELSE 0 END) as sent_count, "
        "SUM(CASE WHEN fr.status='Failed' THEN 1 ELSE 0 END) as failed_count "
        "FROM flyer_campaigns fc "
        "LEFT JOIN flyer_recipients fr ON fc.id=fr.campaign_id "
        "GROUP BY fc.id ORDER BY fc.sent_date DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_flyer_recipients(campaign_id):
    supa = _supa()
    if supa:
        rows = supa.table("flyer_recipients").select(
            "*, practices(name)"
        ).eq("campaign_id", campaign_id).execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    rows = conn.execute(
        "SELECT fr.*, pr.name as practice_name FROM flyer_recipients fr "
        "JOIN practices pr ON fr.practice_id=pr.id "
        "WHERE fr.campaign_id=? ORDER BY pr.name",
        (campaign_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Follow-ups ────────────────────────────────────────────────────────────────

def add_follow_up(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("follow_ups").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO follow_ups ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def get_follow_ups(practice_id=None, status_filter=None):
    supa = _supa()
    if supa:
        q = supa.table("follow_ups").select("*, practices(name)").order("follow_up_date")
        if practice_id:
            q = q.eq("practice_id", practice_id)
        if status_filter:
            q = q.eq("status", status_filter)
        rows = q.execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
        return rows
    conn = _sqlite()
    query = ("SELECT f.*, pr.name as practice_name FROM follow_ups f "
             "JOIN practices pr ON f.practice_id=pr.id")
    conditions = []
    params = []
    if practice_id:
        conditions.append("f.practice_id=?")
        params.append(practice_id)
    if status_filter:
        conditions.append("f.status=?")
        params.append(status_filter)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY f.follow_up_date ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_follow_up(follow_up_id: int, data: dict):
    supa = _supa()
    if supa:
        supa.table("follow_ups").update(data).eq("id", follow_up_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE follow_ups SET {sets} WHERE id=?", list(data.values()) + [follow_up_id])
    conn.commit()
    conn.close()


# ── Tasks ─────────────────────────────────────────────────────────────────────

def _add_business_days(start_date, days: int):
    """Return a date N business days after start_date (Mon–Fri)."""
    from datetime import timedelta
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def add_task(data: dict) -> int:
    supa = _supa()
    if supa:
        d = dict(data)
        if "is_complete" in d:
            d["is_complete"] = bool(d["is_complete"])
        result = supa.table("tasks").insert(d).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_tasks(practice_id=None, is_complete=None, due_before=None, assigned_to=None):
    supa = _supa()
    if supa:
        try:
            q = supa.table("tasks").select("*, practices(name)").order("due_date")
            if practice_id:
                q = q.eq("practice_id", practice_id)
            if is_complete is not None:
                q = q.eq("is_complete", bool(is_complete))
            if due_before:
                q = q.lte("due_date", due_before)
            if assigned_to:
                q = q.eq("assigned_to", assigned_to)
            rows = q.execute().data or []
            for row in rows:
                _pop_embed(row, "practices", "practice_name")
            return rows
        except Exception:
            return []
    conn = _sqlite()
    try:
        query = ("SELECT t.*, pr.name as practice_name FROM tasks t "
                 "LEFT JOIN practices pr ON t.practice_id=pr.id")
        conditions, params = [], []
        if practice_id:
            conditions.append("t.practice_id=?")
            params.append(practice_id)
        if is_complete is not None:
            conditions.append("t.is_complete=?")
            params.append(1 if is_complete else 0)
        if due_before:
            conditions.append("t.due_date<=?")
            params.append(due_before)
        if assigned_to:
            conditions.append("t.assigned_to=?")
            params.append(assigned_to)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY t.due_date ASC"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        conn.close()
        return []


def update_task(task_id: int, data: dict):
    supa = _supa()
    if supa:
        d = dict(data)
        if "is_complete" in d:
            d["is_complete"] = bool(d["is_complete"])
        supa.table("tasks").update(d).eq("id", task_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", list(data.values()) + [task_id])
    conn.commit()
    conn.close()


# ── Dashboard Stats ───────────────────────────────────────────────────────────

def get_dashboard_stats() -> dict:
    supa = _supa()
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    month_start, month_end = _ym_to_range(ym)
    stats = {}

    if supa:
        def _count(table, **filters):
            q = supa.table(table).select("id", count="exact")
            for k, v in filters.items():
                q = q.eq(k, v)
            return q.execute().count or 0

        def _count_month(table, date_col, **filters):
            q = supa.table(table).select("id", count="exact").gte(date_col, month_start).lt(date_col, month_end)
            for k, v in filters.items():
                q = q.eq(k, v)
            return q.execute().count or 0

        stats["total_practices"] = _count("practices", status="Active")
        stats["total_providers"] = _count("providers", status="Active")
        stats["contacts_this_month"] = _count_month("contact_log", "contact_date")
        stats["lunches_scheduled"] = _count("lunch_tracking", status="Scheduled")
        stats["lunches_completed_month"] = _count_month("lunch_tracking", "completed_date", status="Completed")
        stats["lunches_completed_total"] = _count("lunch_tracking", status="Completed")
        stats["cookie_visits_this_month"] = _count_month("cookie_visits", "visit_date")
        stats["cookie_visits_total"] = _count("cookie_visits")
        stats["pending_thank_yous"] = _count("thank_you_letters", status="Pending")

        # Flyers this month
        camp_ids_this_month = [
            c["id"] for c in
            supa.table("flyer_campaigns").select("id").gte("sent_date", month_start).lt("sent_date", month_end).execute().data or []
        ]
        if camp_ids_this_month:
            r = supa.table("flyer_recipients").select("id", count="exact").in_(
                "campaign_id", camp_ids_this_month
            ).eq("status", "Sent").execute()
            stats["flyers_sent_this_month"] = r.count or 0
        else:
            stats["flyers_sent_this_month"] = 0

        stats["calls_this_month"] = _count_month("contact_log", "contact_date", contact_type="Phone Call")
        stats["emails_this_month"] = _count_month("contact_log", "contact_date", contact_type="Email Sent")
        stats["faxes_this_month"] = _count_month("contact_log", "contact_date", contact_type="Fax Sent")
        stats["huntsville_practices"] = _count("practices", location_category="Huntsville", status="Active")
        stats["woodlands_practices"] = _count("practices", location_category="Woodlands", status="Active")

        # Task stats
        today_str = date.today().isoformat()
        try:
            stats["tasks_due_today"] = (
                supa.table("tasks").select("id", count="exact")
                .eq("is_complete", False).lte("due_date", today_str).execute().count or 0
            )
            stats["tasks_overdue"] = (
                supa.table("tasks").select("id", count="exact")
                .eq("is_complete", False).lt("due_date", today_str).execute().count or 0
            )
        except Exception:
            stats["tasks_due_today"] = 0
            stats["tasks_overdue"] = 0

        # Needs attention: 3+ phone calls, no lunch scheduled
        try:
            from collections import Counter as _Counter
            phone_logs = (supa.table("contact_log").select("practice_id")
                          .eq("contact_type", "Phone Call").execute().data or [])
            phone_counts = _Counter(r["practice_id"] for r in phone_logs)
            high_attn = {pid for pid, cnt in phone_counts.items() if cnt >= 3}
            if high_attn:
                scheduled = (supa.table("lunch_tracking").select("practice_id")
                             .in_("status", ["Scheduled", "Completed"]).execute().data or [])
                scheduled_pids = {r["practice_id"] for r in scheduled}
                stats["needs_attention"] = len(high_attn - scheduled_pids)
            else:
                stats["needs_attention"] = 0
        except Exception:
            stats["needs_attention"] = 0

        return stats

    conn = _sqlite()
    stats["total_practices"] = conn.execute("SELECT COUNT(*) FROM practices WHERE status='Active'").fetchone()[0]
    stats["total_providers"] = conn.execute("SELECT COUNT(*) FROM providers WHERE status='Active'").fetchone()[0]
    stats["contacts_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE strftime('%Y-%m', contact_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["lunches_scheduled"] = conn.execute("SELECT COUNT(*) FROM lunch_tracking WHERE status='Scheduled'").fetchone()[0]
    stats["lunches_completed_month"] = conn.execute(
        "SELECT COUNT(*) FROM lunch_tracking WHERE status='Completed' AND strftime('%Y-%m', completed_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["lunches_completed_total"] = conn.execute("SELECT COUNT(*) FROM lunch_tracking WHERE status='Completed'").fetchone()[0]
    stats["cookie_visits_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM cookie_visits WHERE strftime('%Y-%m', visit_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["cookie_visits_total"] = conn.execute("SELECT COUNT(*) FROM cookie_visits").fetchone()[0]
    stats["pending_thank_yous"] = conn.execute("SELECT COUNT(*) FROM thank_you_letters WHERE status='Pending'").fetchone()[0]
    stats["flyers_sent_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM flyer_recipients WHERE status='Sent' "
        "AND campaign_id IN (SELECT id FROM flyer_campaigns WHERE strftime('%Y-%m', sent_date)=strftime('%Y-%m', 'now'))"
    ).fetchone()[0]
    stats["calls_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE contact_type='Phone Call' AND strftime('%Y-%m', contact_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["emails_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE contact_type='Email Sent' AND strftime('%Y-%m', contact_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["faxes_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE contact_type='Fax Sent' AND strftime('%Y-%m', contact_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["huntsville_practices"] = conn.execute(
        "SELECT COUNT(*) FROM practices WHERE location_category='Huntsville' AND status='Active'"
    ).fetchone()[0]
    stats["woodlands_practices"] = conn.execute(
        "SELECT COUNT(*) FROM practices WHERE location_category='Woodlands' AND status='Active'"
    ).fetchone()[0]

    today_str = date.today().isoformat()
    try:
        stats["tasks_due_today"] = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE is_complete=0 AND due_date<=?", (today_str,)
        ).fetchone()[0]
        stats["tasks_overdue"] = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE is_complete=0 AND due_date<?", (today_str,)
        ).fetchone()[0]
    except Exception:
        stats["tasks_due_today"] = 0
        stats["tasks_overdue"] = 0

    try:
        stats["needs_attention"] = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT practice_id FROM contact_log
                WHERE contact_type='Phone Call'
                GROUP BY practice_id HAVING COUNT(*) >= 3
            ) subq
            WHERE subq.practice_id NOT IN (
                SELECT practice_id FROM lunch_tracking
                WHERE status IN ('Scheduled', 'Completed')
            )
        """).fetchone()[0]
    except Exception:
        stats["needs_attention"] = 0

    conn.close()
    return stats


# ── Monthly Count Helper (for analytics page) ─────────────────────────────────

def get_month_count(table: str, date_col: str, ym: str, extra_where: str = "") -> int:
    """Count rows in table where date_col falls in month ym ('YYYY-MM').
    extra_where: optional simple equality clause like \"status='Completed'\".
    """
    supa = _supa()
    if supa:
        start, end = _ym_to_range(ym)
        q = supa.table(table).select("id", count="exact").gte(date_col, start).lt(date_col, end)
        if extra_where:
            m = re.match(r"(\w+)='([^']*)'", extra_where.strip())
            if m:
                q = q.eq(m.group(1), m.group(2))
        return q.execute().count or 0
    conn = _sqlite()
    sql = f"SELECT COUNT(*) FROM {table} WHERE strftime('%Y-%m', {date_col})=?"
    if extra_where:
        sql += f" AND {extra_where}"
    count = conn.execute(sql, (ym,)).fetchone()[0]
    conn.close()
    return count


# ── Events ────────────────────────────────────────────────────────────────────

def create_event(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("events").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO events ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_event(event_id: int):
    supa = _supa()
    if supa:
        result = supa.table("events").select("*").eq("id", event_id).limit(1).execute()
        return result.data[0] if result.data else None
    conn = _sqlite()
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_event(event_id: int, data: dict):
    supa = _supa()
    if supa:
        supa.table("events").update(data).eq("id", event_id).execute()
        return
    conn = _sqlite()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(f"UPDATE events SET {sets} WHERE id=?", list(data.values()) + [event_id])
    conn.commit()
    conn.close()


def delete_event(event_id: int):
    supa = _supa()
    if supa:
        supa.table("events").delete().eq("id", event_id).execute()
        return
    conn = _sqlite()
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()


def list_events(practice_id=None, event_type=None, month=None, year=None):
    supa = _supa()
    if supa:
        q = supa.table("events").select("*").order("scheduled_date", desc=True)
        if practice_id:
            q = q.eq("practice_id", practice_id)
        if event_type:
            q = q.eq("event_type", event_type)
        if year and month:
            start, end = _ym_to_range(f"{year}-{int(month):02d}")
            q = q.gte("scheduled_date", start).lt("scheduled_date", end)
        rows = q.execute().data or []
        return rows
    conn = _sqlite()
    query = "SELECT e.*, pr.name as practice_name FROM events e LEFT JOIN practices pr ON e.practice_id=pr.id"
    conditions = []
    params = []
    if practice_id:
        conditions.append("e.practice_id=?")
        params.append(practice_id)
    if event_type:
        conditions.append("e.event_type=?")
        params.append(event_type)
    if year and month:
        ym = f"{year}-{int(month):02d}"
        conditions.append("strftime('%Y-%m', e.scheduled_date)=?")
        params.append(ym)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY e.scheduled_date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_events_by_month(year: int, month: int):
    return list_events(month=month, year=year)


# ── Outreach Records ──────────────────────────────────────────────────────────

def get_outreach_record(practice_id: int):
    supa = _supa()
    if supa:
        try:
            result = supa.table("outreach_records").select("*").eq("practice_id", practice_id).limit(1).execute()
            return result.data[0] if result.data else None
        except Exception:
            return None
    conn = _sqlite()
    try:
        row = conn.execute("SELECT * FROM outreach_records WHERE practice_id=?", (practice_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        conn.close()
        return None


def get_all_outreach_records():
    """Return dict keyed by practice_id."""
    supa = _supa()
    if supa:
        try:
            result = supa.table("outreach_records").select("*").execute()
            return {r["practice_id"]: r for r in (result.data or [])}
        except Exception:
            return {}
    conn = _sqlite()
    try:
        rows = conn.execute("SELECT * FROM outreach_records").fetchall()
        conn.close()
        return {r["practice_id"]: dict(r) for r in rows}
    except Exception:
        conn.close()
        return {}


def upsert_outreach_record(practice_id: int, data: dict):
    data = dict(data)
    data["updated_at"] = datetime.now().isoformat()
    supa = _supa()
    if supa:
        try:
            payload = {"practice_id": practice_id, **data}
            supa.table("outreach_records").upsert(payload, on_conflict="practice_id").execute()
        except Exception:
            pass
        return
    conn = _sqlite()
    try:
        existing = conn.execute(
            "SELECT id FROM outreach_records WHERE practice_id=?", (practice_id,)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in data)
            conn.execute(
                f"UPDATE outreach_records SET {sets} WHERE practice_id=?",
                list(data.values()) + [practice_id],
            )
        else:
            full = {"practice_id": practice_id, **data}
            cols = ", ".join(full.keys())
            placeholders = ", ".join(["?"] * len(full))
            conn.execute(
                f"INSERT INTO outreach_records ({cols}) VALUES ({placeholders})",
                list(full.values()),
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def add_outreach_history(data: dict) -> int:
    data = dict(data)
    data.setdefault("created_at", datetime.now().isoformat())
    supa = _supa()
    if supa:
        try:
            result = supa.table("outreach_history").insert(data).execute()
            return result.data[0]["id"]
        except Exception:
            return 0
    conn = _sqlite()
    try:
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        cur = conn.execute(
            f"INSERT INTO outreach_history ({cols}) VALUES ({placeholders})",
            list(data.values()),
        )
        conn.commit()
        hid = cur.lastrowid
    except Exception:
        hid = 0
    finally:
        conn.close()
    return hid


def get_outreach_history(practice_id: int, outreach_type=None, limit=30):
    supa = _supa()
    if supa:
        try:
            q = (supa.table("outreach_history").select("*")
                 .eq("practice_id", practice_id)
                 .order("created_at", desc=True).limit(limit))
            if outreach_type:
                q = q.eq("outreach_type", outreach_type)
            return q.execute().data or []
        except Exception:
            return []
    conn = _sqlite()
    try:
        if outreach_type:
            rows = conn.execute(
                "SELECT * FROM outreach_history WHERE practice_id=? AND outreach_type=? "
                "ORDER BY created_at DESC LIMIT ?",
                (practice_id, outreach_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM outreach_history WHERE practice_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (practice_id, limit),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        conn.close()
        return []


def get_all_last_contacts() -> dict:
    """Return {practice_id: last_contact_dict} — one DB call for all practices."""
    supa = _supa()
    if supa:
        try:
            rows = (supa.table("contact_log").select("*")
                    .order("contact_date", desc=True).execute().data or [])
            seen: dict = {}
            for r in rows:
                pid = r.get("practice_id")
                if pid and pid not in seen:
                    seen[pid] = r
            return seen
        except Exception:
            return {}
    conn = _sqlite()
    try:
        rows = conn.execute(
            "SELECT * FROM contact_log ORDER BY contact_date DESC"
        ).fetchall()
        conn.close()
        seen = {}
        for r in rows:
            pid = r["practice_id"]
            if pid and pid not in seen:
                seen[pid] = dict(r)
        return seen
    except Exception:
        conn.close()
        return {}


def get_open_task_counts() -> dict:
    """Return {practice_id: open_task_count} — one DB call for all practices."""
    supa = _supa()
    if supa:
        try:
            rows = (supa.table("tasks").select("practice_id")
                    .eq("is_complete", False).execute().data or [])
            counts: dict = {}
            for r in rows:
                pid = r.get("practice_id")
                if pid:
                    counts[pid] = counts.get(pid, 0) + 1
            return counts
        except Exception:
            return {}
    conn = _sqlite()
    try:
        rows = conn.execute(
            "SELECT practice_id, COUNT(*) as cnt FROM tasks "
            "WHERE is_complete=0 GROUP BY practice_id"
        ).fetchall()
        conn.close()
        return {r["practice_id"]: r["cnt"] for r in rows}
    except Exception:
        conn.close()
        return {}


# ── Bulk Helpers (performance optimization) ───────────────────────────────────

def get_contact_queue_data():
    """Fetch all data needed for the contact queue in 3 bulk queries instead of 3×N.

    Returns:
        (practices, last_contact_by_pid, lunch_active_pids, phone_count_by_pid)
        - practices: list of Active practice dicts (id, name, phone, address)
        - last_contact_by_pid: {practice_id: last_contact_dict}
        - lunch_active_pids: set of practice_ids with Scheduled/Completed lunch
        - phone_count_by_pid: {practice_id: int}
    """
    from collections import defaultdict
    supa = _supa()
    if supa:
        try:
            practices = (supa.table("practices").select("id,name,phone,address")
                         .eq("status", "Active").order("name").execute().data or [])
            contacts = (supa.table("contact_log")
                        .select("practice_id,contact_type,contact_date,outcome")
                        .order("contact_date", desc=True).execute().data or [])
            lunches = (supa.table("lunch_tracking")
                       .select("practice_id,status").execute().data or [])
        except Exception:
            return [], {}, set(), {}
    else:
        conn = _sqlite()
        try:
            practices = [dict(r) for r in conn.execute(
                "SELECT id,name,phone,address FROM practices WHERE status='Active' ORDER BY name"
            ).fetchall()]
            contacts = [dict(r) for r in conn.execute(
                "SELECT practice_id,contact_type,contact_date,outcome FROM contact_log ORDER BY contact_date DESC"
            ).fetchall()]
            lunches = [dict(r) for r in conn.execute(
                "SELECT practice_id,status FROM lunch_tracking"
            ).fetchall()]
        except Exception:
            practices, contacts, lunches = [], [], []
        finally:
            conn.close()

    last_contact_by_pid = {}
    phone_count_by_pid = defaultdict(int)
    for c in contacts:
        pid = c.get("practice_id")
        if pid is None:
            continue
        if pid not in last_contact_by_pid:
            last_contact_by_pid[pid] = c
        if c.get("contact_type") == "Phone Call":
            phone_count_by_pid[pid] += 1

    lunch_active_pids = {
        l["practice_id"] for l in lunches
        if l.get("status") in ("Scheduled", "Completed")
    }

    return practices, last_contact_by_pid, lunch_active_pids, dict(phone_count_by_pid)


def get_relationship_bulk_data():
    """Fetch all data needed for relationship scoring in 3 bulk queries.

    Returns:
        (contacts_by_pid, lunches_by_pid, cookies_by_pid)
        Each is a defaultdict(list) keyed by practice_id.
    """
    from collections import defaultdict
    supa = _supa()
    if supa:
        try:
            contacts = (supa.table("contact_log")
                        .select("practice_id,contact_type,contact_date")
                        .order("contact_date", desc=True).execute().data or [])
            lunches = (supa.table("lunch_tracking")
                       .select("practice_id,status").execute().data or [])
            cookies = (supa.table("cookie_visits")
                       .select("practice_id,visit_date").execute().data or [])
        except Exception:
            contacts, lunches, cookies = [], [], []
    else:
        conn = _sqlite()
        try:
            contacts = [dict(r) for r in conn.execute(
                "SELECT practice_id,contact_type,contact_date FROM contact_log ORDER BY contact_date DESC"
            ).fetchall()]
            lunches = [dict(r) for r in conn.execute(
                "SELECT practice_id,status FROM lunch_tracking"
            ).fetchall()]
            cookies = [dict(r) for r in conn.execute(
                "SELECT practice_id,visit_date FROM cookie_visits"
            ).fetchall()]
        except Exception:
            contacts, lunches, cookies = [], [], []
        finally:
            conn.close()

    contacts_by_pid = defaultdict(list)
    for c in contacts:
        contacts_by_pid[c["practice_id"]].append(c)

    lunches_by_pid = defaultdict(list)
    for l in lunches:
        lunches_by_pid[l["practice_id"]].append(l)

    cookies_by_pid = defaultdict(list)
    for cv in cookies:
        cookies_by_pid[cv["practice_id"]].append(cv)

    return contacts_by_pid, lunches_by_pid, cookies_by_pid


def get_all_providers_by_practice():
    """Return {practice_id: [provider_dicts]} — one DB call for all practices."""
    from collections import defaultdict
    supa = _supa()
    if supa:
        try:
            rows = (supa.table("providers").select("id,practice_id,name,status")
                    .order("name").execute().data or [])
        except Exception:
            rows = []
    else:
        conn = _sqlite()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT id,practice_id,name,status FROM providers ORDER BY name"
            ).fetchall()]
        except Exception:
            rows = []
        finally:
            conn.close()

    by_practice = defaultdict(list)
    for p in rows:
        by_practice[p["practice_id"]].append(p)
    return dict(by_practice)


def get_practices_with_new_referrers():
    """Return set of practice_ids that have at least one provider with is_new_referrer=1."""
    supa = _supa()
    if supa:
        try:
            result = supa.table("providers").select("practice_id").eq("is_new_referrer", True).execute()
            return {r["practice_id"] for r in (result.data or [])}
        except Exception:
            return set()
    conn = _sqlite()
    try:
        rows = conn.execute(
            "SELECT DISTINCT practice_id FROM providers WHERE is_new_referrer=1"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}
    except Exception:
        conn.close()
        return set()


def set_provider_new_referrer(provider_id: int, value: bool):
    supa = _supa()
    if supa:
        try:
            supa.table("providers").update({"is_new_referrer": value}).eq("id", provider_id).execute()
        except Exception:
            pass
        return
    conn = _sqlite()
    try:
        conn.execute("UPDATE providers SET is_new_referrer=? WHERE id=?", (1 if value else 0, provider_id))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ── Provider Referrals ────────────────────────────────────────────────────────

def log_provider_referral(data: dict) -> int:
    """Insert a referral record and refresh the provider's summary stats."""
    data = dict(data)
    data.setdefault("created_at", datetime.now().isoformat())
    supa = _supa()
    if supa:
        try:
            result = supa.table("provider_referrals").insert(data).execute()
            rid = result.data[0]["id"]
        except Exception:
            rid = 0
    else:
        conn = _sqlite()
        try:
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            cur = conn.execute(
                f"INSERT INTO provider_referrals ({cols}) VALUES ({placeholders})",
                list(data.values()),
            )
            conn.commit()
            rid = cur.lastrowid
        except Exception:
            rid = 0
        finally:
            conn.close()

    provider_id = data.get("provider_id")
    if provider_id:
        _refresh_provider_referral_stats(provider_id)
    return rid


def _refresh_provider_referral_stats(provider_id: int):
    """Recompute first/last referral date, total, and is_new_referrer on the providers row."""
    refs = get_provider_referrals(provider_id, limit=5000)
    if not refs:
        return
    dates = sorted(
        [r["referral_date"] for r in refs if r.get("referral_date")],
    )
    total = len(refs)
    first_date = dates[0] if dates else None
    last_date  = dates[-1] if dates else None

    is_new = False
    if first_date:
        try:
            from datetime import date as _d
            fd = _d.fromisoformat(str(first_date)[:10])
            is_new = (_d.today() - fd).days <= 30 and total <= 3
        except Exception:
            pass

    update_data = {
        "total_referrals":    total,
        "first_referral_date": first_date,
        "last_referral_date":  last_date,
        "is_new_referrer":     1 if is_new else 0,
    }
    supa = _supa()
    if supa:
        try:
            d = dict(update_data)
            d["is_new_referrer"] = bool(d["is_new_referrer"])
            supa.table("providers").update(d).eq("id", provider_id).execute()
        except Exception:
            pass
        return
    conn = _sqlite()
    try:
        sets = ", ".join(f"{k}=?" for k in update_data)
        conn.execute(
            f"UPDATE providers SET {sets} WHERE id=?",
            list(update_data.values()) + [provider_id],
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_provider_referrals(provider_id: int, limit: int = 50):
    supa = _supa()
    if supa:
        try:
            result = (
                supa.table("provider_referrals").select("*")
                .eq("provider_id", provider_id)
                .order("referral_date", desc=True).limit(limit).execute()
            )
            return result.data or []
        except Exception:
            return []
    conn = _sqlite()
    try:
        rows = conn.execute(
            "SELECT * FROM provider_referrals WHERE provider_id=? ORDER BY referral_date DESC LIMIT ?",
            (provider_id, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        conn.close()
        return []


def get_provider_referral_stats(provider_id: int) -> dict:
    """Return {total, last_30, last_90, prior_90, last_180} for a provider."""
    today = date.today()
    d30   = (today - __import__("datetime").timedelta(days=30)).isoformat()
    d90   = (today - __import__("datetime").timedelta(days=90)).isoformat()
    d180  = (today - __import__("datetime").timedelta(days=180)).isoformat()
    pr_start = d180
    pr_end   = d90

    supa = _supa()
    if supa:
        try:
            rows = (
                supa.table("provider_referrals").select("referral_date")
                .eq("provider_id", provider_id).execute().data or []
            )
            dates = [r["referral_date"] for r in rows if r.get("referral_date")]
            return {
                "total":    len(dates),
                "last_30":  sum(1 for d in dates if d >= d30),
                "last_90":  sum(1 for d in dates if d >= d90),
                "prior_90": sum(1 for d in dates if pr_start <= d < pr_end),
                "last_180": sum(1 for d in dates if d >= d180),
            }
        except Exception:
            return {"total": 0, "last_30": 0, "last_90": 0, "prior_90": 0, "last_180": 0}

    conn = _sqlite()
    try:
        total    = conn.execute("SELECT COUNT(*) FROM provider_referrals WHERE provider_id=?",   (provider_id,)).fetchone()[0]
        last_30  = conn.execute("SELECT COUNT(*) FROM provider_referrals WHERE provider_id=? AND referral_date>=?", (provider_id, d30)).fetchone()[0]
        last_90  = conn.execute("SELECT COUNT(*) FROM provider_referrals WHERE provider_id=? AND referral_date>=?", (provider_id, d90)).fetchone()[0]
        prior_90 = conn.execute("SELECT COUNT(*) FROM provider_referrals WHERE provider_id=? AND referral_date>=? AND referral_date<?", (provider_id, pr_start, pr_end)).fetchone()[0]
        last_180 = conn.execute("SELECT COUNT(*) FROM provider_referrals WHERE provider_id=? AND referral_date>=?", (provider_id, d180)).fetchone()[0]
        conn.close()
        return {"total": total, "last_30": last_30, "last_90": last_90, "prior_90": prior_90, "last_180": last_180}
    except Exception:
        conn.close()
        return {"total": 0, "last_30": 0, "last_90": 0, "prior_90": 0, "last_180": 0}


# ── Vonage / Fax ──────────────────────────────────────────────────────────────

def validate_vonage_email(email: str) -> bool:
    if not email:
        return False
    return bool(re.match(r'^1\d{10}@fax\.vonagebusiness\.com$', email))


def fix_all_vonage_emails() -> dict:
    """Re-derive every practice's fax_vonage_email from its fax column."""
    from data_import import convert_fax_to_vonage_email
    supa = _supa()
    if supa:
        rows = supa.table("practices").select(
            "id,name,fax,fax_vonage_email"
        ).not_.is_("fax", "null").neq("fax", "").execute().data or []
        fixed = 0
        errors = []
        for r in rows:
            old_email = r.get("fax_vonage_email") or ""
            new_email = convert_fax_to_vonage_email(r["fax"])
            if new_email and new_email != old_email:
                supa.table("practices").update({"fax_vonage_email": new_email}).eq("id", r["id"]).execute()
                fixed += 1
            elif not new_email and old_email:
                supa.table("practices").update({"fax_vonage_email": ""}).eq("id", r["id"]).execute()
                errors.append(f"{r['name']}: could not parse fax '{r['fax']}'")
        return {"fixed": fixed, "errors": errors}

    conn = _sqlite()
    rows = conn.execute(
        "SELECT id, name, fax, fax_vonage_email FROM practices "
        "WHERE fax IS NOT NULL AND fax != ''"
    ).fetchall()
    fixed = 0
    errors = []
    for r in rows:
        old_email = r["fax_vonage_email"] or ""
        new_email = convert_fax_to_vonage_email(r["fax"])
        if new_email and new_email != old_email:
            conn.execute("UPDATE practices SET fax_vonage_email=? WHERE id=?", (new_email, r["id"]))
            fixed += 1
        elif not new_email and old_email:
            conn.execute("UPDATE practices SET fax_vonage_email='' WHERE id=?", (r["id"],))
            errors.append(f"{r['name']}: could not parse fax '{r['fax']}'")
    conn.commit()
    conn.close()
    return {"fixed": fixed, "errors": errors}


# ── Calendar Backfill Migration ───────────────────────────────────────────────

def migrate_lunches_cookies_to_events() -> dict:
    """Backfill events table from lunch_tracking / cookie_visits. Safe to re-run."""
    supa = _supa()
    created = {"lunches": 0, "cookies": 0}

    if supa:
        lunches = supa.table("lunch_tracking").select(
            "id,practice_id,scheduled_date,scheduled_time,status,practices(name)"
        ).not_.is_("scheduled_date", "null").execute().data or []

        existing_lunch = supa.table("events").select(
            "practice_id,scheduled_date"
        ).eq("event_type", "Lunch").execute().data or []
        exist_set = {
            (e["practice_id"], (e["scheduled_date"] or "")[:10])
            for e in existing_lunch
        }

        for l in lunches:
            pname = l.get("practices", {}).get("name", "") if isinstance(l.get("practices"), dict) else ""
            date_str = (l["scheduled_date"] or "")[:10]
            if (l["practice_id"], date_str) not in exist_set:
                supa.table("events").insert({
                    "practice_id": l["practice_id"],
                    "event_type": "Lunch",
                    "label": f"Lunch - {pname}",
                    "scheduled_date": l["scheduled_date"],
                    "scheduled_time": l.get("scheduled_time") or "12:00",
                    "status": l.get("status") or "Scheduled",
                    "created_by": "migration",
                }).execute()
                created["lunches"] += 1

        cookies = supa.table("cookie_visits").select(
            "id,practice_id,visit_date,status,practices(name)"
        ).not_.is_("visit_date", "null").execute().data or []

        existing_cookies = supa.table("events").select(
            "practice_id,scheduled_date"
        ).eq("event_type", "Cookie Visit").execute().data or []
        exist_set_c = {
            (e["practice_id"], (e["scheduled_date"] or "")[:10])
            for e in existing_cookies
        }

        for cv in cookies:
            pname = cv.get("practices", {}).get("name", "") if isinstance(cv.get("practices"), dict) else ""
            date_str = (cv["visit_date"] or "")[:10]
            if (cv["practice_id"], date_str) not in exist_set_c:
                supa.table("events").insert({
                    "practice_id": cv["practice_id"],
                    "event_type": "Cookie Visit",
                    "label": f"Cookies - {pname}",
                    "scheduled_date": cv["visit_date"],
                    "status": cv.get("status") or "Completed",
                    "created_by": "migration",
                }).execute()
                created["cookies"] += 1

        return created

    conn = _sqlite()
    lunches = conn.execute("""
        SELECT lt.id, lt.practice_id, lt.scheduled_date, lt.scheduled_time,
               lt.status, pr.name AS practice_name
        FROM lunch_tracking lt
        JOIN practices pr ON lt.practice_id = pr.id
        WHERE lt.scheduled_date IS NOT NULL
    """).fetchall()
    for l in lunches:
        exists = conn.execute("""
            SELECT id FROM events WHERE event_type='Lunch'
            AND practice_id=? AND date(scheduled_date)=date(?)
        """, (l["practice_id"], l["scheduled_date"])).fetchone()
        if not exists:
            conn.execute("""
                INSERT INTO events (practice_id, event_type, label, scheduled_date,
                                    scheduled_time, status, created_by)
                VALUES (?, 'Lunch', ?, ?, ?, ?, 'migration')
            """, (l["practice_id"], f"Lunch - {l['practice_name']}", l["scheduled_date"],
                  l["scheduled_time"] or "12:00", l["status"] or "Scheduled"))
            created["lunches"] += 1

    cookies = conn.execute("""
        SELECT cv.id, cv.practice_id, cv.visit_date, cv.status,
               pr.name AS practice_name
        FROM cookie_visits cv
        JOIN practices pr ON cv.practice_id = pr.id
        WHERE cv.visit_date IS NOT NULL
    """).fetchall()
    for cv in cookies:
        exists = conn.execute("""
            SELECT id FROM events WHERE event_type='Cookie Visit'
            AND practice_id=? AND date(scheduled_date)=date(?)
        """, (cv["practice_id"], cv["visit_date"])).fetchone()
        if not exists:
            conn.execute("""
                INSERT INTO events (practice_id, event_type, label, scheduled_date,
                                    status, created_by)
                VALUES (?, 'Cookie Visit', ?, ?, ?, 'migration')
            """, (cv["practice_id"], f"Cookies - {cv['practice_name']}", cv["visit_date"],
                  cv["status"] or "Completed"))
            created["cookies"] += 1

    conn.commit()
    conn.close()
    return created


# ── Recurring Reminders ───────────────────────────────────────────────────────

def create_recurring_reminder(data: dict) -> int:
    supa = _supa()
    if supa:
        result = supa.table("recurring_reminders").insert(data).execute()
        return result.data[0]["id"]
    conn = _sqlite()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(f"INSERT INTO recurring_reminders ({cols}) VALUES ({placeholders})", list(data.values()))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_recurring_reminders(active_only: bool = True) -> list:
    supa = _supa()
    if supa:
        q = supa.table("recurring_reminders").select("*").order("day_of_month").order("name")
        if active_only:
            q = q.eq("active", True)
        return q.execute().data or []
    conn = _sqlite()
    if active_only:
        rows = conn.execute(
            "SELECT * FROM recurring_reminders WHERE active=1 ORDER BY day_of_month, name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM recurring_reminders ORDER BY day_of_month, name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_recurring_reminder(reminder_id: int):
    supa = _supa()
    if supa:
        supa.table("recurring_reminders").delete().eq("id", reminder_id).execute()
        return
    conn = _sqlite()
    conn.execute("DELETE FROM recurring_reminders WHERE id=?", (reminder_id,))
    conn.commit()
    conn.close()


# ── Admin Helpers (used by settings.py) ──────────────────────────────────────

def get_table_counts() -> dict:
    """Return {practice_count, provider_count} for the DB status display."""
    supa = _supa()
    if supa:
        r1 = supa.table("practices").select("id", count="exact").execute()
        r2 = supa.table("providers").select("id", count="exact").execute()
        return {"practice_count": r1.count or 0, "provider_count": r2.count or 0}
    conn = _sqlite()
    p = conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0]
    pv = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
    conn.close()
    return {"practice_count": p, "provider_count": pv}


def delete_all_data(tables=None):
    """Delete all rows from the given tables (default: all data tables)."""
    default_tables = [
        "flyer_recipients", "flyer_campaigns",
        "cookie_visits", "thank_you_letters",
        "call_attempts", "lunch_tracking",
        "contact_log", "provider_history",
        "events", "follow_ups",
        "providers", "practices",
    ]
    tables = tables or default_tables
    supa = _supa()
    if supa:
        for t in tables:
            try:
                supa.table(t).delete().gte("id", 1).execute()
            except Exception:
                pass
        return
    conn = _sqlite()
    for t in tables:
        try:
            conn.execute(f"DELETE FROM {t}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def get_fax_diagnostic() -> dict:
    """Return fax/vonage email counts and sample rows for the diagnostic panel."""
    supa = _supa()
    if supa:
        total = supa.table("practices").select("id", count="exact").execute().count or 0
        with_fax = (
            supa.table("practices").select("id", count="exact")
            .not_.is_("fax", "null").neq("fax", "").execute().count or 0
        )
        with_vonage = (
            supa.table("practices").select("id", count="exact")
            .not_.is_("fax_vonage_email", "null").neq("fax_vonage_email", "").execute().count or 0
        )
        missing = (
            supa.table("practices").select("id", count="exact")
            .not_.is_("fax", "null").neq("fax", "")
            .or_("fax_vonage_email.is.null,fax_vonage_email.eq.").execute().count or 0
        )
        samples = (
            supa.table("practices").select("name,fax,fax_vonage_email").limit(10).execute().data or []
        )
        return {
            "total": total,
            "with_fax": with_fax,
            "with_vonage": with_vonage,
            "missing_vonage": missing,
            "samples": samples,
        }
    conn = _sqlite()
    total = conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0]
    with_fax = conn.execute(
        "SELECT COUNT(*) FROM practices WHERE fax IS NOT NULL AND fax != ''"
    ).fetchone()[0]
    with_vonage = conn.execute(
        "SELECT COUNT(*) FROM practices WHERE fax_vonage_email IS NOT NULL AND fax_vonage_email != ''"
    ).fetchone()[0]
    missing = conn.execute(
        "SELECT COUNT(*) FROM practices "
        "WHERE fax IS NOT NULL AND fax != '' "
        "AND (fax_vonage_email IS NULL OR fax_vonage_email = '')"
    ).fetchone()[0]
    samples = conn.execute(
        "SELECT name, fax, fax_vonage_email FROM practices LIMIT 10"
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "with_fax": with_fax,
        "with_vonage": with_vonage,
        "missing_vonage": missing,
        "samples": [dict(r) for r in samples],
    }


def cleanup_calendar_events(bad_types: tuple) -> dict:
    """Delete bad event types and matching contact_log entries. Returns counts."""
    bad_list = list(bad_types)
    supa = _supa()
    if supa:
        r1 = supa.table("events").select("id", count="exact").in_("event_type", bad_list).execute()
        evt_count = r1.count or 0
        for pat in ["fax", "flyer", "thank you", "letter"]:
            r = supa.table("events").select("id", count="exact").ilike("label", f"%{pat}%").execute()
            evt_count += r.count or 0
        r2 = supa.table("contact_log").select("id", count="exact").in_("contact_type", bad_list).execute()
        log_count = r2.count or 0

        supa.table("events").delete().in_("event_type", bad_list).execute()
        for pat in ["fax", "flyer", "thank you", "letter"]:
            try:
                supa.table("events").delete().ilike("label", f"%{pat}%").execute()
            except Exception:
                pass
        supa.table("contact_log").delete().in_("contact_type", bad_list).execute()
        return {"evt_count": evt_count, "log_count": log_count}

    conn = _sqlite()
    placeholders = ",".join("?" * len(bad_list))
    evt_count = conn.execute(
        f"SELECT COUNT(*) FROM events WHERE event_type IN ({placeholders})"
        " OR lower(label) LIKE '%fax%'"
        " OR lower(label) LIKE '%flyer%'"
        " OR lower(label) LIKE '%thank you%'"
        " OR lower(label) LIKE '%letter%'",
        bad_list,
    ).fetchone()[0]
    log_count = conn.execute(
        f"SELECT COUNT(*) FROM contact_log WHERE contact_type IN ({placeholders})",
        bad_list,
    ).fetchone()[0]
    conn.execute(
        f"DELETE FROM events WHERE event_type IN ({placeholders})"
        " OR lower(label) LIKE '%fax%'"
        " OR lower(label) LIKE '%flyer%'"
        " OR lower(label) LIKE '%thank you%'"
        " OR lower(label) LIKE '%letter%'",
        bad_list,
    )
    conn.execute(
        f"DELETE FROM contact_log WHERE contact_type IN ({placeholders})",
        bad_list,
    )
    conn.commit()
    conn.close()
    return {"evt_count": evt_count, "log_count": log_count}


# ── Misc ──────────────────────────────────────────────────────────────────────

def cleanup_providers_date_like(delete=False):
    """Find/delete providers whose name looks like a date string."""
    conn = _sqlite()  # diagnostic/admin — SQLite only
    rows = conn.execute("SELECT id, name FROM providers").fetchall()
    candidates = []
    for r in rows:
        name = r["name"] or ""
        if re.match(r'^\d{4}-\d{2}-\d{2}$', name) or re.match(r'^\d{4}-', name):
            candidates.append({"id": r["id"], "name": name})
    if delete and candidates:
        ids = [c["id"] for c in candidates]
        conn.executemany("DELETE FROM providers WHERE id=?", [(i,) for i in ids])
        conn.commit()
    conn.close()
    return candidates


# ── Users ─────────────────────────────────────────────────────────────────────

def get_user_by_username(username: str):
    """Return active user dict by username, or None."""
    supa = _supa()
    if supa:
        try:
            result = (
                supa.table("users")
                .select("*")
                .eq("username", username)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception:
            pass  # Fall through to SQLite if Supabase query fails
    conn = _sqlite()
    row = conn.execute(
        "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_users():
    """Return all users (all roles, active and inactive)."""
    supa = _supa()
    if supa:
        try:
            result = supa.table("users").select("*").order("username").execute()
            return result.data or []
        except Exception:
            return []
    conn = _sqlite()
    rows = conn.execute("SELECT * FROM users ORDER BY username").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_user(data: dict):
    """Insert a new user row. Returns the new user id."""
    supa = _supa()
    if supa:
        result = supa.table("users").insert(data).execute()
        return result.data[0]["id"] if result.data else None
    conn = _sqlite()
    # Convert Python bools to int for SQLite
    row = {k: (1 if v is True else 0 if v is False else v) for k, v in data.items()}
    cols = ", ".join(row.keys())
    placeholders = ", ".join(["?"] * len(row))
    cur = conn.execute(
        f"INSERT INTO users ({cols}) VALUES ({placeholders})", list(row.values())
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


def update_user(user_id: int, data: dict):
    """Update arbitrary fields on a user row."""
    supa = _supa()
    if supa:
        supa.table("users").update(data).eq("id", user_id).execute()
        return
    conn = _sqlite()
    row = {k: (1 if v is True else 0 if v is False else v) for k, v in data.items()}
    sets = ", ".join(f"{k}=?" for k in row)
    conn.execute(
        f"UPDATE users SET {sets} WHERE id=?", list(row.values()) + [user_id]
    )
    conn.commit()
    conn.close()


def update_last_login(user_id: int):
    """Stamp last_login to now (UTC)."""
    update_user(user_id, {"last_login": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")})


def ensure_default_admin():
    """Create the default admin user if no admin exists (SQLite and Supabase)."""
    import bcrypt
    supa = _supa()
    if supa:
        try:
            result = supa.table("users").select("id").eq("role", "admin").limit(1).execute()
            if not result.data:
                pw_hash = bcrypt.hashpw(b"Admin1234!", bcrypt.gensalt()).decode()
                supa.table("users").upsert({
                    "username": "admin",
                    "password_hash": pw_hash,
                    "full_name": "Administrator",
                    "role": "admin",
                    "is_active": True,
                }, on_conflict="username").execute()
        except Exception:
            pass
        return
    conn = _sqlite()
    existing = conn.execute(
        "SELECT id FROM users WHERE role='admin' LIMIT 1"
    ).fetchone()
    if not existing:
        pw_hash = bcrypt.hashpw(b"Admin1234!", bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT OR IGNORE INTO users "
            "(username, password_hash, full_name, role, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            ("admin", pw_hash, "Administrator", "admin", 1),
        )
        conn.commit()
    conn.close()


# ── Permanent Delete ───────────────────────────────────────────────────────────

def delete_practice_permanently(practice_id: int) -> dict:
    """Permanently delete a practice and all related records (full cascade).

    Returns {'deleted': True, 'error': None} or {'deleted': False, 'error': str}.
    """
    supa = _supa()
    try:
        if supa:
            supa.table("tasks").delete().eq("practice_id", practice_id).execute()
            supa.table("events").delete().eq("practice_id", practice_id).execute()
            supa.table("contact_log").delete().eq("practice_id", practice_id).execute()

            provider_rows = (
                supa.table("providers").select("id")
                .eq("practice_id", practice_id).execute().data or []
            )
            for pr in provider_rows:
                pid = pr["id"]
                try:
                    supa.table("provider_history").delete().eq("provider_id", pid).execute()
                except Exception:
                    pass
                try:
                    supa.table("provider_referrals").delete().eq("provider_id", pid).execute()
                except Exception:
                    pass
            supa.table("providers").delete().eq("practice_id", practice_id).execute()

            lunch_rows = (
                supa.table("lunch_tracking").select("id")
                .eq("practice_id", practice_id).execute().data or []
            )
            for lr in lunch_rows:
                try:
                    supa.table("call_attempts").delete().eq("lunch_id", lr["id"]).execute()
                except Exception:
                    pass
            supa.table("lunch_tracking").delete().eq("practice_id", practice_id).execute()
            try:
                supa.table("call_attempts").delete().eq("practice_id", practice_id).execute()
            except Exception:
                pass

            supa.table("cookie_visits").delete().eq("practice_id", practice_id).execute()
            supa.table("thank_you_letters").delete().eq("practice_id", practice_id).execute()
            supa.table("follow_ups").delete().eq("practice_id", practice_id).execute()
            try:
                supa.table("outreach_records").delete().eq("practice_id", practice_id).execute()
            except Exception:
                pass
            try:
                supa.table("outreach_history").delete().eq("practice_id", practice_id).execute()
            except Exception:
                pass
            try:
                supa.table("flyer_recipients").delete().eq("practice_id", practice_id).execute()
            except Exception:
                pass

            supa.table("practices").delete().eq("id", practice_id).execute()

        else:
            conn = _sqlite()
            try:
                provider_rows = conn.execute(
                    "SELECT id FROM providers WHERE practice_id=?", (practice_id,)
                ).fetchall()
                for pr in provider_rows:
                    conn.execute("DELETE FROM provider_history WHERE provider_id=?", (pr[0],))
                    try:
                        conn.execute("DELETE FROM provider_referrals WHERE provider_id=?", (pr[0],))
                    except Exception:
                        pass
                conn.execute("DELETE FROM providers WHERE practice_id=?", (practice_id,))

                lunch_rows = conn.execute(
                    "SELECT id FROM lunch_tracking WHERE practice_id=?", (practice_id,)
                ).fetchall()
                for lr in lunch_rows:
                    conn.execute("DELETE FROM call_attempts WHERE lunch_id=?", (lr[0],))
                conn.execute("DELETE FROM call_attempts WHERE practice_id=?", (practice_id,))
                conn.execute("DELETE FROM lunch_tracking WHERE practice_id=?", (practice_id,))

                conn.execute("DELETE FROM tasks WHERE practice_id=?", (practice_id,))
                conn.execute("DELETE FROM events WHERE practice_id=?", (practice_id,))
                conn.execute("DELETE FROM contact_log WHERE practice_id=?", (practice_id,))
                conn.execute("DELETE FROM cookie_visits WHERE practice_id=?", (practice_id,))
                conn.execute("DELETE FROM thank_you_letters WHERE practice_id=?", (practice_id,))
                conn.execute("DELETE FROM follow_ups WHERE practice_id=?", (practice_id,))
                try:
                    conn.execute("DELETE FROM outreach_records WHERE practice_id=?", (practice_id,))
                except Exception:
                    pass
                try:
                    conn.execute("DELETE FROM outreach_history WHERE practice_id=?", (practice_id,))
                except Exception:
                    pass
                try:
                    conn.execute("DELETE FROM flyer_recipients WHERE practice_id=?", (practice_id,))
                except Exception:
                    pass

                conn.execute("DELETE FROM practices WHERE id=?", (practice_id,))
                conn.commit()
            finally:
                conn.close()

        return {"deleted": True, "error": None}
    except Exception as exc:
        return {"deleted": False, "error": str(exc)}


def find_empty_practices() -> list:
    """Find practices suitable for bulk cleanup.

    Returns practices where name is blank, a date string (YYYY-MM-DD), or only
    digits — AND has no providers AND no contact_log entries.
    """
    import re
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}')
    number_pattern = re.compile(r'^\d+$')

    supa = _supa()
    if supa:
        try:
            all_practices = (
                supa.table("practices").select("id,name,status").execute().data or []
            )
            has_providers = {
                r["practice_id"] for r in
                (supa.table("providers").select("practice_id").execute().data or [])
                if r.get("practice_id")
            }
            has_contacts = {
                r["practice_id"] for r in
                (supa.table("contact_log").select("practice_id").execute().data or [])
                if r.get("practice_id")
            }
        except Exception:
            return []
    else:
        conn = _sqlite()
        try:
            all_practices = [
                dict(r) for r in
                conn.execute("SELECT id,name,status FROM practices").fetchall()
            ]
            has_providers = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT practice_id FROM providers WHERE practice_id IS NOT NULL"
                ).fetchall()
            }
            has_contacts = {
                r[0] for r in conn.execute(
                    "SELECT DISTINCT practice_id FROM contact_log WHERE practice_id IS NOT NULL"
                ).fetchall()
            }
        except Exception:
            return []
        finally:
            conn.close()

    empty = []
    for p in all_practices:
        name = (p.get("name") or "").strip()
        pid = p["id"]
        if pid in has_providers or pid in has_contacts:
            continue
        if not name or date_pattern.match(name) or number_pattern.match(name):
            empty.append(p)
    return empty


def delete_empty_practices() -> dict:
    """Delete all empty/invalid practices found by find_empty_practices().

    Returns {'deleted_count': int, 'errors': list}.
    """
    empty = find_empty_practices()
    deleted = 0
    errors = []
    for p in empty:
        result = delete_practice_permanently(p["id"])
        if result["deleted"]:
            deleted += 1
        else:
            errors.append(f"{p.get('name') or p['id']}: {result['error']}")
    return {"deleted_count": deleted, "errors": errors}
