"""Helper utilities: date calculations, relationship scoring, backups, location categorization."""
import os
import json
import shutil
from datetime import datetime, timedelta

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


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

    score = 0

    # Recent contact bonus (within 30 days = +20, 60 = +10, 90 = +5)
    if contacts:
        most_recent = contacts[0].get("contact_date")
        days = days_since(most_recent)
        if days is not None:
            if days <= 30:
                score += 20
            elif days <= 60:
                score += 10
            elif days <= 90:
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


def get_overdue_items():
    """Get all overdue action items across all practices."""
    from database import get_all_practices, get_contact_log, get_lunches, get_thank_yous
    config = load_config()
    items = []
    practices = get_all_practices(status_filter="Active")

    for practice in practices:
        pid = practice["id"]

        # Check last contact date
        contacts = get_contact_log(practice_id=pid, limit=1)
        if contacts:
            last_date = contacts[0].get("contact_date")
            days = days_since(last_date)
            if days and days > config["reminder_days"]["lunch_followup"]:
                items.append({
                    "type": "Follow-up Overdue",
                    "practice": practice["name"],
                    "practice_id": pid,
                    "detail": f"Last contact was {days} days ago",
                    "days_overdue": days - config["reminder_days"]["lunch_followup"],
                    "priority": "high" if days > 120 else "medium",
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

        # Pending thank you letters
        pending_ty = get_thank_yous(practice_id=pid, status_filter="Pending")
        for ty in pending_ty:
            days = days_since(ty.get("created_at"))
            if days and days > 7:
                items.append({
                    "type": "Thank You Letter",
                    "practice": practice["name"],
                    "practice_id": pid,
                    "detail": f"Pending for {days} days ({ty.get('reason', '')})",
                    "days_overdue": days - 7,
                    "priority": "medium",
                })

        # Scheduled lunches approaching
        lunches = get_lunches(practice_id=pid, status_filter="Scheduled")
        for lunch in lunches:
            if lunch.get("scheduled_date"):
                days = days_since(lunch["scheduled_date"])
                if days is not None and days < 0:
                    items.append({
                        "type": "Upcoming Lunch",
                        "practice": practice["name"],
                        "practice_id": pid,
                        "detail": f"Lunch in {abs(days)} days - {lunch.get('scheduled_time', '')}",
                        "days_overdue": days,
                        "priority": "medium",
                    })

    items.sort(key=lambda x: x.get("days_overdue", 0), reverse=True)
    return items
