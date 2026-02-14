"""Outlook COM automation for sending flyers via Vonage fax email."""
import os
import time
from utils import load_config


def check_outlook_running():
    """Check if Outlook is running."""
    try:
        import win32com.client
        outlook = win32com.client.Dispatch("Outlook.Application")
        _ = outlook.GetNamespace("MAPI")
        return True, "Outlook is running"
    except Exception as e:
        return False, f"Outlook is not available: {e}"


def get_available_flyers():
    """List available flyer files from the flyer folder."""
    config = load_config()
    folder = config["flyer_folder"]
    if not os.path.exists(folder):
        return []
    flyers = []
    for f in os.listdir(folder):
        ext = os.path.splitext(f)[1].lower()
        if ext in ('.pdf', '.png', '.jpg', '.jpeg', '.docx'):
            full_path = os.path.join(folder, f)
            size = os.path.getsize(full_path)
            flyers.append({
                "name": f,
                "path": full_path,
                "size_kb": round(size / 1024, 1),
                "modified": os.path.getmtime(full_path),
            })
    flyers.sort(key=lambda x: x["modified"], reverse=True)
    return flyers


def send_flyer_via_outlook(vonage_email: str, flyer_path: str, send_from: str = None):
    """Send a flyer as email attachment to a Vonage fax email address.

    Returns (success: bool, message: str)
    """
    try:
        import win32com.client
        config = load_config()

        if not os.path.exists(flyer_path):
            return False, f"Flyer file not found: {flyer_path}"

        outlook = win32com.client.Dispatch("Outlook.Application")
        mail = outlook.CreateItem(0)  # 0 = olMailItem

        # Set send-from account if specified
        from_email = send_from or config.get("send_from_email", "")
        if from_email:
            accounts = outlook.Session.Accounts
            for i in range(accounts.Count):
                acct = accounts.Item(i + 1)
                if acct.SmtpAddress.lower() == from_email.lower():
                    mail._oleobj_.Invoke(*(64209, 0, 8, 0, acct))  # Set SendUsingAccount
                    break

        mail.To = vonage_email
        mail.Subject = "Fax"
        mail.Body = ""
        mail.Attachments.Add(flyer_path)
        mail.Send()

        return True, "Sent successfully"

    except Exception as e:
        return False, str(e)


def send_flyer_batch(recipients: list, flyer_path: str, send_from: str = None, delay_seconds: float = 2.0):
    """Send a flyer to multiple recipients. Yields progress updates.

    recipients: list of dicts with 'practice_id', 'vonage_email', 'practice_name'
    """
    results = []
    for i, recipient in enumerate(recipients):
        vonage_email = recipient.get("vonage_email", "")
        if not vonage_email:
            results.append({
                "practice_id": recipient["practice_id"],
                "practice_name": recipient.get("practice_name", ""),
                "vonage_email": "",
                "status": "Failed",
                "error_message": "No Vonage email configured",
            })
            continue

        success, message = send_flyer_via_outlook(vonage_email, flyer_path, send_from)
        results.append({
            "practice_id": recipient["practice_id"],
            "practice_name": recipient.get("practice_name", ""),
            "vonage_email": vonage_email,
            "status": "Sent" if success else "Failed",
            "error_message": "" if success else message,
        })

        # Delay between sends to avoid overwhelming Outlook
        if i < len(recipients) - 1:
            time.sleep(delay_seconds)

    return results
