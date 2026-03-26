"""Flyer campaign page: select recipients, send via Graph API, campaign history."""
import streamlit as st
import pandas as pd
from datetime import datetime
from utils import load_config, save_config, db_exists

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
    """List flyer files from uploaded_flyers directory (cloud-compatible).

    Falls back to the legacy local flyer_folder if no uploaded flyers exist.
    """
    import os

    # Primary: uploaded flyers (cloud-compatible)
    try:
        from flyer_management import get_uploaded_flyers
        flyers = get_uploaded_flyers()
        if flyers:
            return flyers
    except Exception:
        pass

    # Fallback: legacy local folder from config
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

    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        tab_send, tab_history = st.tabs(["Send Flyers", "Campaign History"])
        with tab_send:
            st.info("Import provider data to send flyers.")
        with tab_history:
            st.info("No campaigns sent yet.")
        return

    # Lazy imports
    from database import (
        get_all_practices, add_flyer_campaign, add_flyer_recipient,
        get_flyer_campaigns, get_flyer_recipients, add_contact_log,
        validate_vonage_email,
    )

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
            st.error("No flyers found. Go to **Settings > Manage Flyers** to upload PDF/PNG/DOCX files.")
            return

        flyer_options = {f["name"]: f["path"] for f in flyers}
        selected_flyer = st.selectbox("Choose a flyer to send", list(flyer_options.keys()))

        if selected_flyer:
            flyer_info = next(f for f in flyers if f["name"] == selected_flyer)
            st.caption(f"Size: {flyer_info['size_kb']} KB")

        # ── 2. Select Recipients ────────────────────────────────────
        st.markdown("### 2. Select Recipients")
        practices_raw = get_all_practices(status_filter="Active")

        # Deduplicate by practice ID (source data can contain duplicates)
        _seen_ids: set = set()
        practices: list = []
        for _p in practices_raw:
            _pid = _p.get("id")
            if _pid and _pid not in _seen_ids:
                _seen_ids.add(_pid)
                practices.append(_p)

        # On-the-fly fix: convert fax numbers to Vonage emails if missing
        try:
            from data_import import convert_fax_to_vonage_email
            from database import update_practice
            _fixed_any = False
            for p in practices:
                fax = p.get("fax", "")
                vonage = p.get("fax_vonage_email", "")
                if fax and not vonage:
                    new_vonage = convert_fax_to_vonage_email(fax)
                    if new_vonage:
                        update_practice(p["id"], {"fax_vonage_email": new_vonage})
                        p["fax_vonage_email"] = new_vonage
                        _fixed_any = True
            if _fixed_any:
                try:
                    from database_persistence import save_database_to_github
                    save_database_to_github()
                except Exception:
                    pass
        except Exception:
            pass

        fax_practices = [
            p for p in practices
            if p.get("fax_vonage_email") and validate_vonage_email(p.get("fax_vonage_email", ""))
        ]

        # ── Filters ──────────────────────────────────────────────────
        col1, col2 = st.columns(2)
        with col1:
            location_filter = st.multiselect(
                "Filter by Location",
                ["Huntsville", "Woodlands", "Other"],
                default=["Huntsville", "Woodlands", "Other"],
            )

        filtered = [p for p in fax_practices if p.get("location_category") in location_filter]

        # ── Pagination state ──────────────────────────────────────────
        PAGE_SIZE = 25

        # Initialize page only on first load
        if "flyer_page" not in st.session_state:
            st.session_state["flyer_page"] = 0

        # Reset page when filter changes (signature covers location)
        _filter_sig = str(sorted(location_filter))
        if st.session_state.get("_flyer_last_filter") != _filter_sig:
            st.session_state["_flyer_last_filter"] = _filter_sig
            st.session_state["flyer_page"] = 0

        total_pages = max(1, (len(filtered) + PAGE_SIZE - 1) // PAGE_SIZE)

        # Clamp page to valid range
        if st.session_state["flyer_page"] >= total_pages:
            st.session_state["flyer_page"] = total_pages - 1

        _cur_page   = st.session_state["flyer_page"]
        _page_start = _cur_page * PAGE_SIZE
        _page_end   = min(_page_start + PAGE_SIZE, len(filtered))
        _page_practices = filtered[_page_start:_page_end]

        # ── Store keys in session_state BEFORE callbacks are defined ─
        # This prevents stale-closure bugs where the callback would act
        # on the key list from a previous render rather than the current one.
        st.session_state["_flyer_page_keys"] = [f"flyer_sel_{p['id']}" for p in _page_practices]
        st.session_state["_flyer_all_keys"]  = [f"flyer_sel_{p['id']}" for p in filtered]

        # ── Debug / transparency summary ──────────────────────────────
        _selected_count = sum(
            1 for p in filtered if st.session_state.get(f"flyer_sel_{p['id']}", False)
        )
        with st.expander("📊 Recipient Summary", expanded=True):
            _dc1, _dc2, _dc3, _dc4, _dc5 = st.columns(5)
            _dc1.metric("Total Practices", len(practices))
            _dc2.metric("Valid Fax", len(fax_practices))
            _dc3.metric("After Filter", len(filtered))
            _dc4.metric("This Page", len(_page_practices))
            _dc5.metric("Selected", _selected_count)

        # ── Select All controls ───────────────────────────────────────
        # Callback reads keys from session_state (always current, never stale)
        def _on_select_page():
            val = st.session_state.get("flyer_sel_page", False)
            for k in st.session_state.get("_flyer_page_keys", []):
                st.session_state[k] = val

        def _on_select_all_filtered():
            val = st.session_state.get("flyer_sel_all", False)
            for k in st.session_state.get("_flyer_all_keys", []):
                st.session_state[k] = val

        _page_keys = st.session_state["_flyer_page_keys"]
        _all_keys  = st.session_state["_flyer_all_keys"]

        _page_all_checked = bool(_page_keys) and all(
            st.session_state.get(k, False) for k in _page_keys
        )
        _all_filtered_checked = bool(_all_keys) and all(
            st.session_state.get(k, False) for k in _all_keys
        )

        # Sync checkbox widgets to computed state (no callback triggered)
        st.session_state["flyer_sel_page"] = _page_all_checked
        st.session_state["flyer_sel_all"]  = _all_filtered_checked

        _sa_col1, _sa_col2 = st.columns(2)
        with _sa_col1:
            st.checkbox(
                f"Select this page ({len(_page_practices)} visible)",
                key="flyer_sel_page",
                on_change=_on_select_page,
            )
        with _sa_col2:
            st.checkbox(
                f"Select ALL {len(filtered)} filtered practices (all pages)",
                key="flyer_sel_all",
                on_change=_on_select_all_filtered,
            )

        # ── Individual checkboxes for current page only ───────────────
        for p in _page_practices:
            pid    = p["id"]
            cb_key = f"flyer_sel_{pid}"
            vonage = p.get("fax_vonage_email", "")
            valid_marker = "" if validate_vonage_email(vonage) else " [INVALID]"
            st.checkbox(
                f"{p['name']}  —  {p.get('fax', '')}  →  {vonage}{valid_marker}",
                key=cb_key,
            )

        # Count selections across ALL filtered practices
        # (each checkbox lives in session_state keyed by practice ID,
        #  so selections survive page navigation)
        selected_practices = [
            p for p in filtered
            if st.session_state.get(f"flyer_sel_{p['id']}", False)
        ]

        # ── Pagination controls ───────────────────────────────────────
        st.markdown("---")
        if total_pages > 1:
            _pcol1, _pcol2, _pcol3 = st.columns([1, 2, 1])

            def _go_prev():
                st.session_state["flyer_page"] = max(0, st.session_state["flyer_page"] - 1)

            def _go_next():
                # Read total_pages from a stable calculation via session_state
                _tp = st.session_state.get("_flyer_total_pages", 1)
                st.session_state["flyer_page"] = min(_tp - 1, st.session_state["flyer_page"] + 1)

            # Store total_pages so _go_next callback is never stale
            st.session_state["_flyer_total_pages"] = total_pages

            with _pcol1:
                st.button(
                    "← Prev",
                    on_click=_go_prev,
                    disabled=_cur_page == 0,
                    use_container_width=True,
                )
            with _pcol2:
                st.markdown(
                    f"<div style='text-align:center;padding-top:6px'>"
                    f"Page <b>{_cur_page + 1}</b> of {total_pages}"
                    f" &nbsp;|&nbsp; showing {_page_start + 1}–{_page_end}"
                    f" of {len(filtered)} filtered"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with _pcol3:
                st.button(
                    "Next →",
                    on_click=_go_next,
                    disabled=_cur_page >= total_pages - 1,
                    use_container_width=True,
                )

        # ── Selection summary ─────────────────────────────────────────
        _sel = len(selected_practices)
        _tot = len(filtered)
        if _sel == 0:
            st.caption("No practices selected. Use the checkboxes above to select recipients.")
        elif _sel == _tot:
            st.markdown(f"**✅ All {_sel} filtered practices selected (across all {total_pages} page{'s' if total_pages > 1 else ''})**")
        elif _sel == len(_page_practices):
            st.markdown(
                f"**{_sel} practices selected** *(this page only — "
                f"check 'Select ALL {_tot} filtered' to include all pages)*"
            )
        else:
            st.markdown(f"**{_sel} of {_tot} filtered practices selected** (across all pages)")

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

        # ── Test Mode ──────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### Diagnostic / Test Mode")
        test_mode = st.checkbox(
            "Enable TEST MODE (send to a regular email instead of fax)",
            help="Use this to verify Graph API works before sending to Vonage fax addresses.",
        )
        test_email_addr = ""
        if test_mode:
            test_email_addr = st.text_input(
                "Test recipient email (regular email, not fax)",
                value=graph_config.get("sender_email", ""),
                help="Sends to this address instead of fax numbers. Use your own email to verify delivery.",
            )
            st.warning(
                "TEST MODE: Emails will be sent to the test address above, "
                "NOT to any fax numbers. No campaign records will be created."
            )

            if st.button("Send Single Test Email", type="secondary"):
                with st.spinner(f"Sending test to {test_email_addr}..."):
                    flyer_path = flyer_options[selected_flyer] if selected_flyer else None
                    result = outlook_api.send_test_email(
                        sender=send_from,
                        test_recipient=test_email_addr,
                        subject=email_subject,
                        attachment_path=flyer_path,
                    )
                if result["success"]:
                    st.success(f"Test email sent to {test_email_addr}! Check your inbox.")
                    st.info("This confirms Graph API is working. If fax sends fail, the issue is with the Vonage email address or domain.")
                else:
                    st.error(f"Test email FAILED: {result.get('error', 'Unknown')}")
                    if result.get("error_code"):
                        st.error(f"Error code: {result['error_code']}")
                    if result.get("error_details"):
                        with st.expander("Error details"):
                            st.code(result["error_details"])
                    if result.get("error_raw"):
                        with st.expander("Full API response"):
                            st.code(result["error_raw"])
                    st.warning("Graph API itself is failing. Fix the API configuration before trying fax sends.")

                with st.expander("Diagnostic info"):
                    st.json(result.get("diagnostic", {}))

        st.markdown("---")

        # Only allow sending valid recipients
        valid_selected = [
            p for p in selected_practices
            if validate_vonage_email(p.get("fax_vonage_email", ""))
        ]

        if st.button(
            f"Send Flyers ({len(valid_selected)} valid recipients)",
            type="primary",
            disabled=not valid_selected or test_mode,
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
                else:
                    failed_count += 1
                    fail_details.append({
                        "practice": recip["practice_name"],
                        "vonage_email": recip["vonage_email"],
                        "error": error_msg,
                        "error_code": result.get("error_code", ""),
                        "error_details": result.get("error_details", ""),
                        "error_raw": result.get("error_raw", ""),
                    })

                import time
                if i < len(recipients_info) - 1:
                    time.sleep(1)

            progress.progress(1.0, text="Complete!")
            st.success(f"Campaign complete! {sent_count} sent, {failed_count} failed.")

            if fail_details:
                st.markdown("**Failed sends:**")
                for detail in fail_details:
                    st.error(f"{detail['practice']}: {detail['error']}")
                    if detail.get("error_code") or detail.get("error_details"):
                        with st.expander(f"Diagnostic: {detail['practice']} ({detail['vonage_email']})"):
                            st.markdown(f"**Recipient:** `{detail['vonage_email']}`")
                            if detail["error_code"]:
                                st.markdown(f"**Error code:** `{detail['error_code']}`")
                            if detail["error_details"]:
                                st.markdown("**Error details:**")
                                st.code(detail["error_details"])
                            if detail["error_raw"]:
                                st.markdown("**Full API response:**")
                                st.code(detail["error_raw"])

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
