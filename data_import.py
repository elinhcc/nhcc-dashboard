"""Excel import: read provider spreadsheet, parse fax numbers, convert to Vonage format, populate DB."""
import re
import openpyxl
from datetime import datetime
from database import get_connection, init_db, add_practice, add_provider
from utils import backup_excel, load_config, categorize_location


def parse_fax_number(contact_info: str) -> str:
    """Extract fax number from contact information text."""
    if not contact_info:
        return ""
    # Look for fax patterns
    patterns = [
        r'[Ff][Aa][Xx]\s*(?:[Nn]umber)?\s*:?\s*\(?\s*(\d{3})\s*\)?\s*[-.\s]*(\d{3})\s*[-.\s]*(\d{4})',
        r'[Ff][Aa][Xx]\s*:?\s*(\d{3})\s*[-.\s]*(\d{3})\s*[-.\s]*(\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, contact_info)
        if match:
            groups = match.groups()
            return f"{groups[0]}-{groups[1]}-{groups[2]}"
    return ""


def parse_phone_number(contact_info: str) -> str:
    """Extract phone number from contact information text."""
    if not contact_info:
        return ""
    # Remove fax lines to avoid picking up fax as phone
    lines = contact_info.split("\n")
    non_fax_lines = [l for l in lines if "fax" not in l.lower()]
    text = "\n".join(non_fax_lines) if non_fax_lines else contact_info

    patterns = [
        r'(?:[Pp]hone|[Pp][Hh]|[Tt]el|[Oo]ffice)\s*:?\s*\(?\s*(\d{3})\s*\)?\s*[-.\s]*(\d{3})\s*[-.\s]*(\d{4})',
        r'\((\d{3})\)\s*(\d{3})\s*[-.\s]*(\d{4})',
        r'(\d{3})\s*[-.\s](\d{3})\s*[-.\s](\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            return f"{groups[0]}-{groups[1]}-{groups[2]}"
    return ""


def fax_to_vonage_email(fax_number: str, domain: str = "fax.vonagebusiness.com") -> str:
    """Convert a fax number to Vonage email format: 1XXXXXXXXXX@fax.vonagebusiness.com.

    Uses plain digits only (no parentheses) so the address is valid RFC 5321.
    """
    if not fax_number:
        return ""
    digits = re.sub(r'[^0-9]', '', str(fax_number))
    if not digits:
        return ""
    # Strip leading 1 for 11-digit numbers then re-add for consistency
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    elif len(digits) > 11:
        digits = digits[-10:]
    if len(digits) != 10:
        return ""
    return f"1{digits}@{domain}"


def parse_providers(providers_text: str) -> list:
    """Parse provider names from the Providers column."""
    if not providers_text:
        return []
    providers = []
    lines = providers_text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip category headers like "PA's:", "NPs:", etc.
        if re.match(r'^[A-Z]+[\'\u2019]?s?\s*:?\s*$', line):
            continue
        # Skip numbered prefixes
        line = re.sub(r'^\d+[\.\)]\s*', '', line)
        # Remove leading role prefixes like "N-", "Dr."
        line = re.sub(r'^N-', '', line)
        if line and len(line) > 1:
            providers.append(line.strip())
    return providers


def extract_zip(address: str) -> str:
    """Extract zip code from address."""
    if not address:
        return ""
    match = re.search(r'\b(\d{5})(?:-\d{4})?\b', address)
    return match.group(1) if match else ""


def import_excel(excel_path: str = None) -> dict:
    """Import the Excel file into the database. Returns import stats."""
    config = load_config()
    if not excel_path:
        excel_path = config["excel_path"]

    # Backup first
    backup_path = backup_excel()

    # Initialize database
    init_db()

    wb = openpyxl.load_workbook(excel_path)
    ws = wb["Full List"]
    vonage_domain = config.get("vonage_domain", "fax.vonagebusiness.com")

    stats = {
        "practices_imported": 0,
        "providers_imported": 0,
        "fax_numbers_found": 0,
        "rows_processed": 0,
        "skipped_rows": 0,
        "backup_path": backup_path,
    }

    current_practice_name = None

    for row in range(2, ws.max_row + 1):
        practice_name = ws.cell(row, 2).value
        address = ws.cell(row, 3).value
        contact_info = ws.cell(row, 4).value
        providers_text = ws.cell(row, 5).value
        details = ws.cell(row, 6).value
        next_followup = ws.cell(row, 7).value
        last_contact = ws.cell(row, 9).value

        # Skip completely empty rows
        if not practice_name and not address and not contact_info and not providers_text:
            stats["skipped_rows"] += 1
            continue

        # Handle sub-rows (no practice name = continuation of previous)
        if not practice_name and current_practice_name:
            practice_name = current_practice_name + " (Branch)"
        elif practice_name:
            current_practice_name = practice_name
        else:
            stats["skipped_rows"] += 1
            continue

        stats["rows_processed"] += 1

        # Parse contact info
        contact_str = str(contact_info) if contact_info else ""
        fax = parse_fax_number(contact_str)
        phone = parse_phone_number(contact_str)
        vonage_email = fax_to_vonage_email(fax, vonage_domain) if fax else ""
        zip_code = extract_zip(str(address) if address else "")
        location = categorize_location(str(address) if address else "")

        if fax:
            stats["fax_numbers_found"] += 1

        # Build notes from details and follow-up
        notes_parts = []
        if details:
            notes_parts.append(str(details))
        if next_followup:
            notes_parts.append(f"Next follow-up: {next_followup}")
        notes = "\n".join(notes_parts)

        # Format last contact date
        last_contact_str = None
        if last_contact:
            if isinstance(last_contact, datetime):
                last_contact_str = last_contact.isoformat()
            else:
                last_contact_str = str(last_contact)

        # Add practice
        practice_data = {
            "name": str(practice_name).strip(),
            "address": str(address).strip() if address else "",
            "zip_code": zip_code,
            "location_category": location,
            "phone": phone,
            "fax": fax,
            "fax_vonage_email": vonage_email,
            "contact_person": "",
            "notes": notes,
            "status": "Active",
        }
        practice_id = add_practice(practice_data)
        stats["practices_imported"] += 1

        # If we have a last contact date, add it to contact log
        if last_contact_str:
            from database import add_contact_log
            add_contact_log({
                "practice_id": practice_id,
                "contact_type": "Other",
                "contact_date": last_contact_str,
                "team_member": "Robbie",
                "notes": "Imported from Excel",
            })

        # Parse and add providers
        provider_names = parse_providers(str(providers_text) if providers_text else "")
        for pname in provider_names:
            add_provider({
                "name": pname,
                "practice_id": practice_id,
                "status": "Active",
            })
            stats["providers_imported"] += 1

    wb.close()
    return stats


def get_import_status():
    """Check if data has been imported."""
    import os
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.db")
    if not os.path.exists(db_path):
        return False
    try:
        conn = get_connection()
        count = conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False
