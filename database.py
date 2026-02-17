"""SQLite database schema, CRUD operations, and history logging."""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.db")


def db_exists():
    """Return True if the database file exists and has the practices table with data."""
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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS practices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT,
        zip_code TEXT,
        location_category TEXT DEFAULT 'Other',
        website TEXT,
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
    """)

    # follow_ups table for scheduled follow-up activities
    c.execute("""
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
    )
    """)

    # Migrations for existing databases
    _migrate_column(c, "contact_log", "purpose", "TEXT")
    _migrate_column(c, "contact_log", "call_attempt_number", "INTEGER")
    _migrate_column(c, "contact_log", "contact_method", "TEXT")
    _migrate_column(c, "contact_log", "email_subject", "TEXT")
    _migrate_column(c, "contact_log", "fax_document", "TEXT")
    _migrate_column(c, "cookie_visits", "status", "TEXT DEFAULT 'Logged'")
    _migrate_column(c, "cookie_visits", "next_visit_date", "DATETIME")

    conn.commit()
    conn.close()


def _migrate_column(cursor, table, column, col_type):
    """Add a column to a table if it doesn't exist yet."""
    try:
        cursor.execute(f"SELECT {column} FROM {table} LIMIT 1")
    except sqlite3.OperationalError:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass


# ── Practice CRUD ──────────────────────────────────────────────────────

def get_all_practices(status_filter=None):
    conn = get_connection()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM practices WHERE status=? ORDER BY name", (status_filter,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM practices ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_practice(practice_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM practices WHERE id=?", (practice_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def add_practice(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO practices ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_practice(practice_id: int, data: dict):
    conn = get_connection()
    data["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(
        f"UPDATE practices SET {sets} WHERE id=?",
        list(data.values()) + [practice_id],
    )
    conn.commit()
    conn.close()


def search_practices(query: str):
    conn = get_connection()
    q = f"%{query}%"
    rows = conn.execute(
        "SELECT * FROM practices WHERE name LIKE ? OR address LIKE ? OR phone LIKE ? OR fax LIKE ? ORDER BY name",
        (q, q, q, q),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Provider CRUD ──────────────────────────────────────────────────────

def get_providers_for_practice(practice_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM providers WHERE practice_id=? ORDER BY name", (practice_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_providers():
    conn = get_connection()
    rows = conn.execute(
        "SELECT p.*, pr.name as practice_name FROM providers p "
        "LEFT JOIN practices pr ON p.practice_id=pr.id ORDER BY p.name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_provider(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO providers ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def update_provider(provider_id: int, data: dict):
    conn = get_connection()
    data["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(
        f"UPDATE providers SET {sets} WHERE id=?",
        list(data.values()) + [provider_id],
    )
    conn.commit()
    conn.close()


def get_provider(provider_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM providers WHERE id=?", (provider_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_provider(provider_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM provider_history WHERE provider_id=?", (provider_id,))
    conn.execute("UPDATE thank_you_letters SET provider_id=NULL WHERE provider_id=?", (provider_id,))
    conn.execute("DELETE FROM providers WHERE id=?", (provider_id,))
    conn.commit()
    conn.close()


def move_provider(provider_id: int, new_practice_id: int, notes: str = ""):
    conn = get_connection()
    old = conn.execute(
        "SELECT practice_id FROM providers WHERE id=?", (provider_id,)
    ).fetchone()
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


# ── Contact Log ────────────────────────────────────────────────────────

def add_contact_log(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO contact_log ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def get_contact_log(practice_id=None, limit=50):
    conn = get_connection()
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
    """Get the number of phone call contacts for a practice."""
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE practice_id=? AND contact_type='Phone Call'",
        (practice_id,),
    ).fetchone()[0]
    conn.close()
    return count


def get_last_contact(practice_id: int):
    """Get the most recent contact for a practice."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM contact_log WHERE practice_id=? ORDER BY contact_date DESC LIMIT 1",
        (practice_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── Lunch Tracking ────────────────────────────────────────────────────

def add_lunch(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO lunch_tracking ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def get_lunches(practice_id=None, status_filter=None):
    conn = get_connection()
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
    conn = get_connection()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(
        f"UPDATE lunch_tracking SET {sets} WHERE id=?",
        list(data.values()) + [lunch_id],
    )
    conn.commit()
    conn.close()


# ── Call Attempts ──────────────────────────────────────────────────────

def add_call_attempt(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO call_attempts ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def get_call_attempts(lunch_id=None, practice_id=None):
    conn = get_connection()
    if lunch_id:
        rows = conn.execute(
            "SELECT * FROM call_attempts WHERE lunch_id=? ORDER BY call_date DESC",
            (lunch_id,),
        ).fetchall()
    elif practice_id:
        rows = conn.execute(
            "SELECT * FROM call_attempts WHERE practice_id=? ORDER BY call_date DESC",
            (practice_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM call_attempts ORDER BY call_date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Thank You Letters ─────────────────────────────────────────────────

def add_thank_you(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO thank_you_letters ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


def get_thank_yous(practice_id=None, status_filter=None):
    conn = get_connection()
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
    conn = get_connection()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(
        f"UPDATE thank_you_letters SET {sets} WHERE id=?",
        list(data.values()) + [ty_id],
    )
    conn.commit()
    conn.close()


# ── Cookie Visits ──────────────────────────────────────────────────────

def add_cookie_visit(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO cookie_visits ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    vid = cur.lastrowid
    conn.close()
    return vid


def get_cookie_visits(practice_id=None):
    conn = get_connection()
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


# ── Flyer Campaigns ───────────────────────────────────────────────────

def add_flyer_campaign(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO flyer_campaigns ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    cid = cur.lastrowid
    conn.close()
    return cid


def add_flyer_recipient(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO flyer_recipients ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_flyer_campaigns():
    conn = get_connection()
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
    conn = get_connection()
    rows = conn.execute(
        "SELECT fr.*, pr.name as practice_name FROM flyer_recipients fr "
        "JOIN practices pr ON fr.practice_id=pr.id "
        "WHERE fr.campaign_id=? ORDER BY pr.name",
        (campaign_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Stats ──────────────────────────────────────────────────────────────

# ── Follow-ups ────────────────────────────────────────────────────────

def add_follow_up(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO follow_ups ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def get_follow_ups(practice_id=None, status_filter=None):
    conn = get_connection()
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
    conn = get_connection()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(
        f"UPDATE follow_ups SET {sets} WHERE id=?",
        list(data.values()) + [follow_up_id],
    )
    conn.commit()
    conn.close()


# ── Stats ──────────────────────────────────────────────────────────────

def get_dashboard_stats():
    conn = get_connection()
    stats = {}
    stats["total_practices"] = conn.execute(
        "SELECT COUNT(*) FROM practices WHERE status='Active'"
    ).fetchone()[0]
    stats["total_providers"] = conn.execute(
        "SELECT COUNT(*) FROM providers WHERE status='Active'"
    ).fetchone()[0]
    stats["contacts_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM contact_log WHERE strftime('%Y-%m', contact_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["lunches_scheduled"] = conn.execute(
        "SELECT COUNT(*) FROM lunch_tracking WHERE status='Scheduled'"
    ).fetchone()[0]
    stats["lunches_completed_month"] = conn.execute(
        "SELECT COUNT(*) FROM lunch_tracking WHERE status='Completed' AND strftime('%Y-%m', completed_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["lunches_completed_total"] = conn.execute(
        "SELECT COUNT(*) FROM lunch_tracking WHERE status='Completed'"
    ).fetchone()[0]
    stats["cookie_visits_this_month"] = conn.execute(
        "SELECT COUNT(*) FROM cookie_visits WHERE strftime('%Y-%m', visit_date)=strftime('%Y-%m', 'now')"
    ).fetchone()[0]
    stats["cookie_visits_total"] = conn.execute(
        "SELECT COUNT(*) FROM cookie_visits"
    ).fetchone()[0]
    stats["pending_thank_yous"] = conn.execute(
        "SELECT COUNT(*) FROM thank_you_letters WHERE status='Pending'"
    ).fetchone()[0]
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


def create_event(data: dict) -> int:
    conn = get_connection()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO events ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def get_event(event_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_event(event_id: int, data: dict):
    conn = get_connection()
    sets = ", ".join(f"{k}=?" for k in data)
    conn.execute(
        f"UPDATE events SET {sets} WHERE id=?",
        list(data.values()) + [event_id],
    )
    conn.commit()
    conn.close()


def delete_event(event_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()


def list_events(practice_id=None, event_type=None, month=None, year=None):
    conn = get_connection()
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
        # match YYYY-MM
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


def validate_vonage_email(email: str) -> bool:
    """Return True if email matches Vonage fax format.

    Accepts both formats:
      1(XXX)XXXXXXX@fax.vonagebusiness.com  (parentheses)
      1XXXXXXXXXX@fax.vonagebusiness.com     (plain digits)
    """
    import re
    if not email:
        return False
    return bool(re.match(
        r'^1(?:\(\d{3}\)\d{7}|\d{10})@fax\.vonagebusiness\.com$', email
    ))


def fix_all_vonage_emails() -> dict:
    """Re-derive every practice's fax_vonage_email from its fax column.

    Uses convert_fax_to_vonage_email which produces format:
    1(XXX)XXXXXXX@fax.vonagebusiness.com

    Returns dict with 'fixed' count and list of 'errors'.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, fax, fax_vonage_email FROM practices "
        "WHERE fax IS NOT NULL AND fax != ''"
    ).fetchall()

    from data_import import convert_fax_to_vonage_email

    fixed = 0
    errors = []
    for r in rows:
        pid = r["id"]
        old_email = r["fax_vonage_email"] or ""
        new_email = convert_fax_to_vonage_email(r["fax"])
        if new_email and new_email != old_email:
            conn.execute(
                "UPDATE practices SET fax_vonage_email=? WHERE id=?",
                (new_email, pid),
            )
            fixed += 1
        elif not new_email and old_email:
            conn.execute(
                "UPDATE practices SET fax_vonage_email='' WHERE id=?",
                (pid,),
            )
            errors.append(f"{r['name']}: could not parse fax '{r['fax']}'")
    conn.commit()
    conn.close()
    return {"fixed": fixed, "errors": errors}


def cleanup_providers_date_like(delete=False):
    """Find providers where name looks like YYYY-MM-DD or starts with YYYY- and optionally delete them.
    If delete=False the function returns candidates without removing them."""
    import re
    conn = get_connection()
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
