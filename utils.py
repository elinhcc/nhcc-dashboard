"""Helper utilities: date calculations, relationship scoring, backups, location categorization."""
import os
import json
import shutil
from datetime import datetime, timedelta

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Default config used when config.json is missing (e.g. Streamlit Cloud)
_DEFAULT_CONFIG = {
    "excel_path": "",
    "flyer_folder": "",
    "send_from_email": "office@nhcancerclinics.com",
    "backup_folder": "backups",
    "team_members": ["Robbie", "Kianah"],
    "vonage_domain": "fax.vonagebusiness.com",
    "app_password_hash": "",
    "reminder_days": {"lunch_followup": 90, "cookie_visit": 60, "flyer_send": 30},
    "huntsville_zips": [],
    "woodlands_zips": [],
    "microsoft_graph": {
        "client_id": "", "client_secret": "", "tenant_id": "",
        "sender_email": "office@nhcancerclinics.com",
    },
}


def is_cloud():
    """Return True when running on Streamlit Cloud (no local files expected)."""
    return os.environ.get("STREAMLIT_SHARING_MODE") is not None or os.environ.get("STREAMLIT_SERVER_HEADLESS") == "true"


def db_exists():
    """Return True if the database has at least one practice (Supabase or SQLite)."""
    try:
        from database import db_exists as _db_exists
        return _db_exists()
    except Exception:
        return False


def load_config():
    # Start with defaults
    config = dict(_DEFAULT_CONFIG)
    # Try loading config.json
    try:
        with open(CONFIG_PATH, "r") as f:
            file_config = json.load(f)
        config.update(file_config)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    # Overlay Streamlit Cloud secrets onto config
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            if "microsoft_graph" in st.secrets:
                graph = dict(st.secrets["microsoft_graph"])
                config.setdefault("microsoft_graph", {}).update(
                    {k: v for k, v in graph.items() if v}
                )
            if "app" in st.secrets:
                app_sec = dict(st.secrets["app"])
                if app_sec.get("password_hash"):
                    config["app_password_hash"] = app_sec["password_hash"]
    except Exception:
        pass
    return config


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


def backup_excel():
    """Backup the Excel file before import."""
    config = load_config()
    excel_path = config["excel_path"]
    if not os.path.exists(excel_path):
        return None
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), config["backup_folder"])
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    basename = os.path.basename(excel_path)
    name, ext = os.path.splitext(basename)
    backup_name = f"{name}_backup_{timestamp}{ext}"
    backup_path = os.path.join(backup_dir, backup_name)
    shutil.copy2(excel_path, backup_path)
    return backup_path


def categorize_location(address: str) -> str:
    """Categorize a practice location based on address/zip code."""
    if not address:
        return "Other"
    config = load_config()
    address_upper = address.upper()

    # Check for city names first
    if "HUNTSVILLE" in address_upper:
        return "Huntsville"
    if "WOODLANDS" in address_upper or "THE WOODLANDS" in address_upper:
        return "Woodlands"
    if "CONROE" in address_upper or "WILLIS" in address_upper or "MAGNOLIA" in address_upper:
        return "Woodlands"
    if "SPRING" in address_upper or "TOMBALL" in address_upper:
        return "Woodlands"
    if "MADISONVILLE" in address_upper or "ANDERSON" in address_upper or "CROCKETT" in address_upper:
        return "Huntsville"
    if "TRINITY" in address_upper or "CENTERVILLE" in address_upper or "LIVINGSTON" in address_upper:
        return "Huntsville"

    # Check zip codes
    import re
    zips = re.findall(r'\b(\d{5})\b', address)
    for z in zips:
        if z in config.get("huntsville_zips", []):
            return "Huntsville"
        if z in config.get("woodlands_zips", []):
            return "Woodlands"

    return "Other"


def days_since(date_str):
    """Calculate days since a given date string."""
    if not date_str:
        return None
    try:
        if isinstance(date_str, datetime):
            dt = date_str
        else:
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m-%d-%Y"):
                try:
                    dt = datetime.strptime(str(date_str), fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        return (datetime.now() - dt).days
    except Exception:
        return None


def relationship_score(practice_id):
    """Calculate a relationship strength score (0-100) for a practice."""
    from database import get_contact_log, get_lunches, get_cookie_visits
    contacts = get_contact_log(practice_id=practice_id, limit=100)
    lunches = get_lunches(practice_id=practice_id)
    cookies = get_cookie_visits(practice_id=practice_id)
    return _score_from_data(contacts, lunches, cookies)


def relationship_score_from_bulk(practice_id, contacts_by_pid, lunches_by_pid, cookies_by_pid):
    """Calculate relationship score using pre-fetched bulk data (no extra DB calls)."""
    contacts = contacts_by_pid.get(practice_id, [])
    lunches = lunches_by_pid.get(practice_id, [])
    cookies = cookies_by_pid.get(practice_id, [])
    return _score_from_data(contacts, lunches, cookies)


def _score_from_data(contacts, lunches, cookies):
    """Core scoring logic shared by both relationship_score variants."""
    score = 0

    # Recent contact bonus (within 30 days = +20, 60 = +10, 90 = +5)
    if contacts:
        most_recent = contacts[0].get("contact_date")
        d = days_since(most_recent)
        if d is not None:
            if d <= 30:
                score += 20
            elif d <= 60:
                score += 10
            elif d <= 90:
                score += 5

    # Contact frequency (up to 30 points)
    recent_contacts = [c for c in contacts if days_since(c.get("contact_date", "")) is not None and days_since(c.get("contact_date", "")) <= 180]
    score += min(len(recent_contacts) * 5, 30)

    # Lunch completion (up to 25 points)
    completed_lunches = [l for l in lunches if l.get("status") == "Completed"]
    score += min(len(completed_lunches) * 10, 25)

    # Cookie visits (up to 15 points)
    recent_cookies = [cv for cv in cookies if days_since(cv.get("visit_date", "")) is not None and days_since(cv.get("visit_date", "")) <= 180]
    score += min(len(recent_cookies) * 5, 15)

    # Variety of contact types (up to 10 points)
    contact_types = set(c.get("contact_type") for c in contacts)
    score += min(len(contact_types) * 3, 10)

    return min(score, 100)


def score_color(score):
    """Return a color based on relationship score."""
    if score >= 70:
        return "#28a745"  # green
    elif score >= 40:
        return "#ffc107"  # yellow
    else:
        return "#dc3545"  # red


def score_label(score):
    if score >= 70:
        return "Strong"
    elif score >= 40:
        return "Moderate"
    else:
        return "Needs Attention"


def format_phone_link(phone: str) -> str:
    """Return clickable HTML link for a phone number (no +1 prefix)."""
    import re
    if not phone:
        return "N/A"
    digits = re.sub(r'\D', '', phone)
    # Strip leading 1 if 11 digits
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
        return f'<a class="contact-phone" href="tel:{digits}">📞 {formatted}</a>'
    return f"📞 {phone}"


def format_email_link(email: str) -> str:
    """Return clickable HTML mailto link for an email."""
    if not email:
        return "N/A"
    return f'<a class="contact-email" href="mailto:{email}">✉️ {email}</a>'


def format_fax_link(fax: str, vonage_domain: str = "fax.vonagebusiness.com") -> str:
    """Return clickable HTML mailto link for fax-to-email."""
    import re
    if not fax:
        return "N/A"
    digits = re.sub(r'\D', '', fax)
    if len(digits) == 11 and digits.startswith("1"):
        digits_display = digits[1:]
    elif len(digits) == 10:
        digits_display = digits
    else:
        digits_display = digits
    if len(digits_display) == 10:
        formatted = f"({digits_display[:3]}) {digits_display[3:6]}-{digits_display[6:]}"
    else:
        formatted = fax
    fax_email = f"1{digits_display}@{vonage_domain}" if len(digits_display) == 10 else fax
    return f'<a class="contact-fax" href="mailto:{fax_email}">📠 {formatted}</a>'


def get_overdue_items():
    """Get all overdue action items across all practices using bulk queries."""
    from database import get_contact_queue_data, get_thank_yous, get_lunches
    config = load_config()
    items = []

    # 3 bulk calls instead of 275×3 individual calls
    practices, last_contact_by_pid, _, _ = get_contact_queue_data()

    # Bulk fetch pending thank yous and scheduled lunches
    all_pending_ty = get_thank_yous(status_filter="Pending")
    ty_by_pid = {}
    for ty in all_pending_ty:
        pid = ty.get("practice_id")
        if pid:
            ty_by_pid.setdefault(pid, []).append(ty)

    all_sched_lunches = get_lunches(status_filter="Scheduled")
    sched_lunches_by_pid = {}
    for l in all_sched_lunches:
        pid = l.get("practice_id")
        if pid:
            sched_lunches_by_pid.setdefault(pid, []).append(l)

    for practice in practices:
        pid = practice["id"]

        last_contact = last_contact_by_pid.get(pid)
        if last_contact:
            d = days_since(last_contact.get("contact_date"))
            if d and d > config["reminder_days"]["lunch_followup"]:
                items.append({
                    "type": "Follow-up Overdue",
                    "practice": practice["name"],
                    "practice_id": pid,
                    "detail": f"Last contact was {d} days ago",
                    "days_overdue": d - config["reminder_days"]["lunch_followup"],
                    "priority": "high" if d > 120 else "medium",
                })
        else:
            items.append({
                "type": "No Contact",
                "practice": practice["name"],
                "practice_id": pid,
                "detail": "No contact logged yet",
                "days_overdue": 0,
                "priority": "high",
            })

        for ty in ty_by_pid.get(pid, []):
            d = days_since(ty.get("created_at"))
            if d and d > 7:
                items.append({
                    "type": "Thank You Letter",
                    "practice": practice["name"],
                    "practice_id": pid,
                    "detail": f"Pending for {d} days ({ty.get('reason', '')})",
                    "days_overdue": d - 7,
                    "priority": "medium",
                })

        for lunch in sched_lunches_by_pid.get(pid, []):
            if lunch.get("scheduled_date"):
                d = days_since(lunch["scheduled_date"])
                if d is not None and d < 0:
                    items.append({
                        "type": "Upcoming Lunch",
                        "practice": practice["name"],
                        "practice_id": pid,
                        "detail": f"Lunch in {abs(d)} days - {lunch.get('scheduled_time', '')}",
                        "days_overdue": d,
                        "priority": "medium",
                    })

    items.sort(key=lambda x: x.get("days_overdue", 0), reverse=True)
    return items
