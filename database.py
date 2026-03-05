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
    """)
    _migrate_column(c, "contact_log", "purpose", "TEXT")
    _migrate_column(c, "contact_log", "call_attempt_number", "INTEGER")
    _migrate_column(c, "contact_log", "contact_method", "TEXT")
    _migrate_column(c, "contact_log", "email_subject", "TEXT")
    _migrate_column(c, "contact_log", "fax_document", "TEXT")
    _migrate_column(c, "cookie_visits", "status", "TEXT DEFAULT 'Logged'")
    _migrate_column(c, "cookie_visits", "next_visit_date", "DATETIME")
    _migrate_column(c, "practices", "specialty", "TEXT")
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
        q = supa.table("events").select("*, practices(name)").order("scheduled_date", desc=True)
        if practice_id:
            q = q.eq("practice_id", practice_id)
        if event_type:
            q = q.eq("event_type", event_type)
        if year and month:
            start, end = _ym_to_range(f"{year}-{int(month):02d}")
            q = q.gte("scheduled_date", start).lt("scheduled_date", end)
        rows = q.execute().data or []
        for row in rows:
            _pop_embed(row, "practices", "practice_name")
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
