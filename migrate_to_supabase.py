"""Migrate data from local providers.db (SQLite) to Supabase.

Usage (run from the project directory with the venv active):
    python migrate_to_supabase.py

Requires .streamlit/secrets.toml with SUPABASE_URL and SUPABASE_KEY,
OR environment variables SUPABASE_URL and SUPABASE_KEY.

Skips fax/flyer/thank-you-letter calendar events per the decision to
remove those from the calendar.
"""
import os
import sys
import sqlite3

# ── Load Supabase credentials ────────────────────────────────────────────────

def _get_creds():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if url and key:
        return url, key
    # Try .streamlit/secrets.toml
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        try:
            import re
            text = open(secrets_path).read()
            url_m = re.search(r'SUPABASE_URL\s*=\s*["\']([^"\']+)["\']', text)
            key_m = re.search(r'SUPABASE_KEY\s*=\s*["\']([^"\']+)["\']', text)
            if url_m and key_m:
                return url_m.group(1), key_m.group(1)
        except Exception as e:
            print(f"  Warning: could not parse secrets.toml: {e}")
    return None, None


def main():
    DB_PATH = os.path.join(os.path.dirname(__file__), "providers.db")

    if not os.path.exists(DB_PATH):
        print(f"ERROR: providers.db not found at {DB_PATH}")
        sys.exit(1)

    url, key = _get_creds()
    if not url or not key:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY not found.")
        print("  Set them in .streamlit/secrets.toml or as environment variables.")
        sys.exit(1)

    print(f"Connecting to Supabase: {url[:40]}...")
    from supabase import create_client
    supa = create_client(url, key)

    print(f"Connecting to SQLite: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Bad event types to skip (these are removed from the calendar)
    BAD_EVENT_TYPES = {
        "Flyer", "Fax Sent", "Fax", "fax", "fax sent",
        "Thank You Letter", "Thank You", "thank_you", "flyer",
    }

    def _rows(table):
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]

    def _migrate_table(table, rows, skip_fn=None):
        if not rows:
            print(f"  {table}: 0 rows — skipping")
            return 0
        to_insert = [r for r in rows if not (skip_fn and skip_fn(r))]
        skipped = len(rows) - len(to_insert)
        if not to_insert:
            print(f"  {table}: all {len(rows)} rows skipped")
            return 0
        # Insert in batches of 500 to avoid request-size limits
        batch_size = 500
        inserted = 0
        for i in range(0, len(to_insert), batch_size):
            batch = to_insert[i:i + batch_size]
            # Strip None values that may conflict with NOT NULL defaults
            clean_batch = [{k: v for k, v in r.items() if v is not None} for r in batch]
            try:
                supa.table(table).insert(clean_batch).execute()
                inserted += len(batch)
            except Exception as e:
                print(f"    Batch {i//batch_size + 1} error: {e}")
                # Try row-by-row fallback
                for row in clean_batch:
                    try:
                        supa.table(table).insert(row).execute()
                        inserted += 1
                    except Exception as row_err:
                        print(f"    Row id={row.get('id')} skipped: {row_err}")
        msg = f"  {table}: {inserted} inserted"
        if skipped:
            msg += f", {skipped} skipped"
        print(msg)
        return inserted

    print("\n=== Migrating tables in dependency order ===\n")

    # Order matters — respect foreign key dependencies
    practices = _rows("practices")
    _migrate_table("practices", practices)

    providers = _rows("providers")
    _migrate_table("providers", providers)

    provider_history = _rows("provider_history")
    _migrate_table("provider_history", provider_history)

    contact_log = _rows("contact_log")
    def _skip_contact(r):
        return r.get("contact_type") in BAD_EVENT_TYPES
    _migrate_table("contact_log", contact_log, skip_fn=_skip_contact)

    lunch_tracking = _rows("lunch_tracking")
    _migrate_table("lunch_tracking", lunch_tracking)

    call_attempts = _rows("call_attempts")
    _migrate_table("call_attempts", call_attempts)

    thank_you_letters = _rows("thank_you_letters")
    _migrate_table("thank_you_letters", thank_you_letters)

    cookie_visits = _rows("cookie_visits")
    _migrate_table("cookie_visits", cookie_visits)

    flyer_campaigns = _rows("flyer_campaigns")
    _migrate_table("flyer_campaigns", flyer_campaigns)

    flyer_recipients = _rows("flyer_recipients")
    _migrate_table("flyer_recipients", flyer_recipients)

    follow_ups = _rows("follow_ups")
    _migrate_table("follow_ups", follow_ups)

    recurring_reminders = _rows("recurring_reminders")
    _migrate_table("recurring_reminders", recurring_reminders)

    events = _rows("events")
    def _skip_event(r):
        if r.get("event_type") in BAD_EVENT_TYPES:
            return True
        label = (r.get("label") or "").lower()
        return any(p in label for p in ["fax", "flyer", "thank you", "letter"])
    _migrate_table("events", events, skip_fn=_skip_event)

    conn.close()

    print("\n=== Resetting Supabase sequences ===")
    _reset_sequences(supa, conn)

    print("\n✓ Migration complete!")
    print("\nNext steps:")
    print("  1. Open your app on Streamlit Cloud")
    print("  2. Go to Settings > Data Import — confirm the practice/provider counts")
    print("  3. Check Calendar and Providers pages")


def _reset_sequences(supa, conn):
    """Reset PostgreSQL SERIAL sequences so new inserts don't collide with migrated IDs."""
    tables = [
        "practices", "providers", "provider_history", "contact_log",
        "lunch_tracking", "call_attempts", "thank_you_letters", "cookie_visits",
        "flyer_campaigns", "flyer_recipients", "follow_ups", "recurring_reminders", "events",
    ]
    for table in tables:
        try:
            result = supa.table(table).select("id").order("id", desc=True).limit(1).execute()
            max_id = result.data[0]["id"] if result.data else 0
            if max_id > 0:
                # Use rpc to reset sequence
                supa.rpc("setval", {"seq": f"{table}_id_seq", "val": max_id}).execute()
                print(f"  {table}: sequence reset to {max_id}")
        except Exception as e:
            print(f"  {table}: could not reset sequence (may need manual SQL): {e}")


if __name__ == "__main__":
    main()
