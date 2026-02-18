"""Microsoft Graph API client for sending emails via Outlook 365."""
import os
import json
import base64
import time
import logging
from typing import List, Dict, Optional

log = logging.getLogger(__name__)


def _parse_graph_error(response) -> Dict:
    """Extract detailed error info from a Microsoft Graph API response.

    Returns dict with keys: code, message, details, status_code, raw.
    """
    info: Dict = {
        "status_code": response.status_code,
        "code": "",
        "message": "",
        "details": "",
        "raw": "",
    }
    try:
        body = response.json()
        err = body.get("error", {})
        info["code"] = err.get("code", "")
        info["message"] = err.get("message", "")
        # Some Graph errors include innerError or details array
        inner = err.get("innerError", {})
        if inner:
            info["details"] = json.dumps(inner, indent=2)
        detail_list = err.get("details", [])
        if detail_list:
            info["details"] += "\n" + json.dumps(detail_list, indent=2)
        info["raw"] = json.dumps(body, indent=2)
    except Exception:
        info["raw"] = response.text
    return info


class OutlookGraphAPI:
    """Send emails through Microsoft Graph API using app-only (client credentials) auth."""

    def __init__(self, client_id: str, client_secret: str, tenant_id: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.authority = f"https://login.microsoftonline.com/{tenant_id}"
        self.scope = ["https://graph.microsoft.com/.default"]
        self.graph_endpoint = "https://graph.microsoft.com/v1.0"
        self._token = None

    def get_access_token(self) -> str:
        """Acquire access token from Azure AD using client credentials."""
        import msal

        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=self.authority,
            client_credential=self.client_secret,
        )
        result = app.acquire_token_for_client(scopes=self.scope)

        if "access_token" in result:
            self._token = result["access_token"]
            return self._token

        error_desc = result.get("error_description", "Unknown error")
        raise Exception(f"Could not acquire token: {error_desc}")

    def test_connection(self) -> Dict:
        """Test whether the Graph API credentials work."""
        try:
            self.get_access_token()
            return {"success": True, "message": "Successfully connected to Microsoft Graph API"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_email(
        self,
        sender: str,
        recipients: List[str],
        subject: str,
        body: str,
        attachment_path: Optional[str] = None,
        body_type: str = "HTML",
    ) -> Dict:
        """Send an email via Microsoft Graph API.

        Args:
            sender: Sender email (e.g. office@nhcancerclinics.com).
            recipients: List of recipient email addresses.
            subject: Email subject line.
            body: Email body (HTML or plain text).
            attachment_path: Optional file to attach.
            body_type: "HTML" or "Text".

        Returns:
            Dict with ``success`` bool and ``message`` or ``error``.
            On failure also includes ``error_code``, ``error_details``,
            ``error_raw``, and ``diagnostic`` for debugging.
        """
        import requests

        # -- Diagnostic logging --
        diag = {
            "sender": sender,
            "recipients": recipients,
            "recipient_count": len(recipients),
            "subject": subject,
            "has_attachment": bool(attachment_path and os.path.exists(attachment_path)),
        }
        log.info("Graph API send_email diagnostic: %s", json.dumps(diag))

        try:
            token = self.get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            message = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": body_type, "content": body},
                    "toRecipients": [
                        {"emailAddress": {"address": addr}} for addr in recipients
                    ],
                },
                "saveToSentItems": "true",
            }

            # Attach file if provided
            if attachment_path and os.path.exists(attachment_path):
                with open(attachment_path, "rb") as f:
                    file_content = base64.b64encode(f.read()).decode("utf-8")
                filename = os.path.basename(attachment_path)
                message["message"]["attachments"] = [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": filename,
                        "contentBytes": file_content,
                    }
                ]

            endpoint = f"{self.graph_endpoint}/users/{sender}/sendMail"
            log.info("POST %s  recipients=%s", endpoint, recipients)
            response = requests.post(endpoint, headers=headers, json=message)

            if response.status_code == 202:
                log.info("Email sent OK to %s", recipients)
                return {
                    "success": True,
                    "message": f"Email sent successfully to {', '.join(recipients)}",
                    "diagnostic": diag,
                }

            # -- Parse detailed error from Graph API --
            err_info = _parse_graph_error(response)
            error_summary = (
                f"HTTP {err_info['status_code']} | "
                f"{err_info['code']}: {err_info['message']}"
            )
            log.error("Graph API error: %s", error_summary)
            log.error("Full response: %s", err_info["raw"])

            return {
                "success": False,
                "error": error_summary,
                "error_code": err_info["code"],
                "error_details": err_info["details"],
                "error_raw": err_info["raw"],
                "diagnostic": diag,
            }

        except Exception as e:
            log.exception("Exception in send_email")
            return {
                "success": False,
                "error": f"Error sending email: {e}",
                "diagnostic": diag,
            }

    def send_test_email(
        self,
        sender: str,
        test_recipient: str,
        subject: str = "NHCC Graph API Test",
        body: str = "<html><body><p>This is a test email from NHCC Dashboard to verify Microsoft Graph API is working.</p></body></html>",
        attachment_path: Optional[str] = None,
    ) -> Dict:
        """Send a test email to a regular email address (not fax) to verify Graph API works.

        Use this to isolate whether a send failure is caused by the Graph API
        configuration or by the Vonage fax email address / domain.
        """
        log.info("TEST MODE: sending to %s (instead of fax)", test_recipient)
        result = self.send_email(
            sender=sender,
            recipients=[test_recipient],
            subject=f"[TEST] {subject}",
            body=body,
            attachment_path=attachment_path,
        )
        result["test_mode"] = True
        result["test_recipient"] = test_recipient
        return result

    def send_batch_emails(
        self,
        sender: str,
        recipients: List[str],
        subject: str,
        body: str,
        attachment_path: Optional[str] = None,
        delay_seconds: float = 1.0,
    ) -> List[Dict]:
        """Send one email per recipient with optional delay between sends."""
        results = []
        for i, recipient in enumerate(recipients):
            result = self.send_email(
                sender=sender,
                recipients=[recipient],
                subject=subject,
                body=body,
                attachment_path=attachment_path,
            )
            results.append(
                {
                    "recipient": recipient,
                    "success": result["success"],
                    "message": result.get("message") or result.get("error"),
                    "error_code": result.get("error_code", ""),
                    "error_details": result.get("error_details", ""),
                    "error_raw": result.get("error_raw", ""),
                    "diagnostic": result.get("diagnostic", {}),
                }
            )
            if i < len(recipients) - 1:
                time.sleep(delay_seconds)
        return results
