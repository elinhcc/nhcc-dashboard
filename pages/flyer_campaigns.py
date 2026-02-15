"""Flyer campaign page: select recipients, send via Graph API, campaign history."""
import streamlit as st
import pandas as pd
from datetime import datetime
from database import (
    get_all_practices, add_flyer_campaign, add_flyer_recipient,
    get_flyer_campaigns, get_flyer_recipients, add_contact_log,
    validate_vonage_email,
)
from utils import load_config, save_config

# HTML email template used for flyer sends
FLYER_EMAIL_BODY = """\
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
    <p>Dear Office Manager,</p>

    <p>Please find attached information about our comprehensive cancer care
    services at <strong>North Houston Cancer Clinics</strong>.</p>

    <p>We appreciate your continued referrals and partnership in providing
    excellent patient care to our community.</p>

    <p>If you have any questions about our services or would like to schedule
    a lunch presentation for your staff, please don't hesitate to contact us
    at <a href="mailto:office@nhcancerclinics.com">office@nhcancerclinics.com</a>.</p>

    <p>Best regards,<br>
    <strong>NHCC Team</strong><br>
    North Houston Cancer Clinics</p>
</body>
</html>
"""


def _get_available_flyers():
    """List flyer files from the configured folder (no COM dependency)."""
    import os
    config = load_config()
    folder = config.get("flyer_folder", "")
    if not folder or not os.path.exists(folder):
        return []
    flyers = []
    for f in os.listdir(folder):
        ext = os.path.splitext(f)[1].lower()
        if ext in (".pdf", ".png", ".jpg", ".jpeg", ".docx"):
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


def show_flyer_campaigns():
    st.markdown("## Flyer Campaigns")

    tab_send, tab_history = st.tabs(["Send Flyers", "Campaign History"])

    # ── Send Flyers ──────────────────────────────────────────────────
    with tab_send:
        config = load_config()
        graph_config = config.get("microsoft_graph", {})
        graph_configured = all([
            graph_config.get("client_id"),
            graph_config.get("client_secret"),
            graph_config.get("tenant_id"),
        ])

        if not graph_configured:
            st.warning("Microsoft Graph API not configured")
            st.info("Go to **Settings > Email (Graph API)** to enter your Azure credentials (Client ID, Client Secret, Tenant ID).")
            with st.expander("Why do I need this?"):
                st.markdown("""
                To send flyers automatically the dashboard needs permission to
                send emails on your behalf via Microsoft 365.

                1. Go to **Settings** page
                2. Open the **Email (Graph API)** tab
                3. Enter your Azure App Registration credentials
                4. Click **Test Connection**
                5. Come back here to send flyers!
                """)
            st.stop()

        # Try to connect
        from outlook_graph import OutlookGraphAPI
        try:
            outlook_api = OutlookGraphAPI(
                client_id=graph_config["client_id"],
                client_secret=graph_config["client_secret"],
                tenant_id=graph_config["tenant_id"],
            )
            test_result = outlook_api.test_connection()
            if not test_result["success"]:
                st.error(f"Cannot connect to Microsoft Graph: {test_result['error']}")
                st.info("Check your credentials in **Settings > Email (Graph API)**.")
                st.stop()
            else:
                st.success("Connected to Microsoft Graph API - Ready to send flyers!")
        except Exception as e:
            st.error(f"Error initializing Graph API: {e}")
            st.stop()

        # ── 1. Select Flyer ─────────────────────────────────────────
        st.markdown("### 1. Select Flyer")
        flyers = _get_available_flyers()
        if not flyers:
            st.error("No flyers found. Add PDF/PNG/DOCX files to the Flyers folder.")
            return

        flyer_options = {f["name"]: f["path"] for f in flyers}
        selected_flyer = st.selectbox("Choose a flyer to send", list(flyer_options.keys()))

        if selected_flyer:
            flyer_info = next(f for f in flyers if f["name"] == selected_flyer)
            st.caption(f"Size: {flyer_info['size_kb']} KB")

        # ── 2. Select Recipients ────────────────────────────────────
        st.markdown("### 2. Select Recipients")
        practices = get_all_practices(status_filter="Active")
        fax_practices = [p for p in practices if p.get("fax_vonage_email")]

        st.caption(f"{len(fax_practices)} of {len(practices)} practices have fax/Vonage configured")

        col1, col2 = st.columns(2)
        with col1:
            location_filter = st.multiselect(
                "Filter by Location",
                ["Huntsville", "Woodlands", "Other"],
                default=["Huntsville", "Woodlands", "Other"],
            )

        filtered = [p for p in fax_practices if p.get("location_category") in location_filter]

        # --- Select All checkbox (uses on_change callback) ---
        # Build list of individual-checkbox keys for the current visible set
        _visible_keys = [f"flyer_sel_{p['id']}" for p in filtered]

        def _on_select_all_changed():
            """Callback: write Select All state into every individual checkbox key."""
            val = st.session_state.get("flyer_select_all", False)
            for k in _visible_keys:
                st.session_state[k] = val

        # Before rendering Select All, check whether all individuals are
        # already checked (so the Select All checkbox reflects reality).
        all_checked = (
            all(st.session_state.get(k, False) for k in _visible_keys)
            if _visible_keys else False
        )
        # Sync Select All key to match individual state (without triggering callback)
        st.session_state["flyer_select_all"] = all_checked

        st.checkbox(
            "Select All",
            key="flyer_select_all",
            on_change=_on_select_all_changed,
        )

        # Individual checkboxes
        selected_practices = []
        for p in filtered:
            pid = p["id"]
            cb_key = f"flyer_sel_{pid}"
            vonage = p.get("fax_vonage_email", "")
            valid_marker = "" if validate_vonage_email(vonage) else " [INVALID]"

            checked = st.checkbox(
                f"{p['name']}  ---  {p.get('fax', '')}  ->  {vonage}{valid_marker}",
                key=cb_key,
            )
            if checked:
                selected_practices.append(p)

        st.markdown(f"**{len(selected_practices)} recipients selected**")

        # Warn about invalid vonage emails
        invalid_in_selection = [
            p for p in selected_practices
            if not validate_vonage_email(p.get("fax_vonage_email", ""))
        ]
        if invalid_in_selection:
            st.warning(
                f"{len(invalid_in_selection)} selected practice(s) have invalid fax email format. "
                "Go to **Settings > Data Management** and click **Fix All Vonage Fax Emails**."
            )

        # ── 3. Send ─────────────────────────────────────────────────
        st.markdown("### 3. Send")
        sender_email = graph_config.get("sender_email", config.get("send_from_email", ""))
        send_from = st.text_input("Send from email", value=sender_email)
        email_subject = st.text_input("Email subject", value="North Houston Cancer Clinics - Referral Information")

        with st.expander("Preview email body"):
            st.markdown(FLYER_EMAIL_BODY, unsafe_allow_html=True)

        # Only allow sending valid recipients
        valid_selected = [
            p for p in selected_practices
            if validate_vonage_email(p.get("fax_vonage_email", ""))
        ]

        if st.button(
            f"Send Flyers ({len(valid_selected)} valid recipients)",
            type="primary",
            disabled=not valid_selected,
        ):
            flyer_path = flyer_options[selected_flyer]

            campaign_id = add_flyer_campaign({
                "sent_date": datetime.now().isoformat(),
                "flyer_name": selected_flyer,
                "sent_by": "Robbie",
            })

            recipients_info = [
                {
                    "practice_id": p["id"],
                    "practice_name": p["name"],
                    "vonage_email": p["fax_vonage_email"],
                }
                for p in valid_selected
            ]

            progress = st.progress(0, text="Sending flyers...")
            sent_count = 0
            failed_count = 0
            fail_details = []

            for i, recip in enumerate(recipients_info):
                progress.progress(
                    (i + 1) / len(recipients_info),
                    text=f"Sending to {recip['practice_name']}...",
                )

                result = outlook_api.send_email(
                    sender=send_from,
                    recipients=[recip["vonage_email"]],
                    subject=email_subject,
                    body=FLYER_EMAIL_BODY,
                    attachment_path=flyer_path,
                )

                status = "Sent" if result["success"] else "Failed"
                error_msg = "" if result["success"] else result.get("error", "")

                add_flyer_recipient({
                    "campaign_id": campaign_id,
                    "practice_id": recip["practice_id"],
                    "vonage_email": recip["vonage_email"],
                    "status": status,
                    "error_message": error_msg,
                })

                if result["success"]:
                    sent_count += 1
                    add_contact_log({
                        "practice_id": recip["practice_id"],
                        "contact_type": "Fax Sent",
                        "contact_date": datetime.now().isoformat(),
                        "contact_method": "fax",
                        "team_member": "Robbie",
                        "outcome": "Sent Successfully",
                        "fax_document": selected_flyer,
                        "notes": f"Flyer campaign: {selected_flyer}",
                    })
                else:
                    failed_count += 1
                    fail_details.append(f"{recip['practice_name']}: {error_msg}")

                import time
                if i < len(recipients_info) - 1:
                    time.sleep(1)

            progress.progress(1.0, text="Complete!")
            st.success(f"Campaign complete! {sent_count} sent, {failed_count} failed.")

            if fail_details:
                st.markdown("**Failed sends:**")
                for detail in fail_details:
                    st.error(detail)

    # ── Campaign History ─────────────────────────────────────────────
    with tab_history:
        campaigns = get_flyer_campaigns()
        if not campaigns:
            st.info("No campaigns sent yet.")
        else:
            for camp in campaigns:
                with st.expander(
                    f"{camp['flyer_name']} -- {camp.get('sent_date', '')[:10]} | "
                    f"{camp.get('sent_count', 0)} sent, {camp.get('failed_count', 0)} failed"
                ):
                    recipients = get_flyer_recipients(camp["id"])
                    if recipients:
                        df = pd.DataFrame(recipients)
                        display = ["practice_name", "vonage_email", "status", "error_message"]
                        available = [c for c in display if c in df.columns]
                        st.dataframe(df[available], use_container_width=True, hide_index=True)
