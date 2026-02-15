"""Microsoft Graph API client for sending emails via Outlook 365."""
import os
import base64
import time
from typing import List, Dict, Optional


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
        """
        import requests

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
            response = requests.post(endpoint, headers=headers, json=message)

            if response.status_code == 202:
                return {
                    "success": True,
                    "message": f"Email sent successfully to {', '.join(recipients)}",
                }
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text}",
            }

        except Exception as e:
            return {"success": False, "error": f"Error sending email: {e}"}

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
                }
            )
            if i < len(recipients) - 1:
                time.sleep(delay_seconds)
        return results
