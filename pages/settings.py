"""Settings page: data import, app configuration, paths, team members, password, Graph API credentials."""
import streamlit as st
import os
import tempfile
from utils import load_config, save_config, is_cloud, db_exists


def _is_cloud():
    """Detect Streamlit Cloud (secrets present and config.json likely read-only)."""
    try:
        return bool(st.secrets) and os.environ.get("STREAMLIT_SHARING_MODE") or not os.access(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config.json"), os.W_OK
        )
    except Exception:
        return False


def _safe_save(config):
    """Save config, returning True on success. Shows warning on read-only filesystem."""
    try:
        save_config(config)
        return True
    except OSError:
        st.warning("Cannot save settings — config.json is read-only. On Streamlit Cloud, use the Secrets dashboard instead.")
        return False


def show_settings():
    st.markdown("## Settings")

    config = load_config()

    if _is_cloud():
        st.info("Running on Streamlit Cloud — sensitive settings (Graph API credentials, password) are managed via the Secrets dashboard. Config.json changes may not persist.")

    tab_data, tab_general, tab_paths, tab_team, tab_graph, tab_password, tab_mgmt = st.tabs([
        "Data Import", "General", "File Paths", "Team Members",
        "Email (Graph API)", "Password", "Data Management",
    ])

    # ── Data Import (first tab — most important for cloud) ────────────
    with tab_data:
        st.markdown("### Import Provider Data")
        st.markdown("Upload your Excel file to create or update the database.")

        # Database status
        st.markdown("#### Database Status")
        try:
            if db_exists():
                from database import get_connection
                conn = get_connection()
                practice_count = conn.execute("SELECT COUNT(*) FROM practices").fetchone()[0]
                provider_count = conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0]
                conn.close()
                st.success(f"Database loaded: **{practice_count}** practices, **{provider_count}** providers")
            else:
                st.warning("No data loaded yet. Upload an Excel file below to get started.")
        except Exception:
            st.warning("No data loaded yet. Upload an Excel file below to get started.")

        st.markdown("---")

        # File uploader
        uploaded_file = st.file_uploader(
            "Upload Excel file (.xlsx / .xls)",
            type=["xlsx", "xls"],
            key="settings_upload",
        )

        if uploaded_file is not None:
            st.info(f"File ready: **{uploaded_file.name}** ({uploaded_file.size / 1024:.1f} KB)")

            if st.button("Import Data", type="primary", use_container_width=True):
                with st.spinner("Importing data... This may take a moment."):
                    # Save uploaded file to temp location
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name

                    try:
                        from database import init_db
                        init_db()
                        from data_import import import_excel
                        stats = import_excel(tmp_path)
                    finally:
                        os.unlink(tmp_path)

                st.balloons()
                st.success("Import complete!")
                col1, col2, col3 = st.columns(3)
                col1.metric("Practices Imported", stats["practices_imported"])
                col2.metric("Providers Imported", stats["providers_imported"])
                col3.metric("Fax Numbers Found", stats["fax_numbers_found"])

        # Download existing database
        st.markdown("---")
        st.markdown("#### Download Database Backup")
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "providers.db")
        if os.path.exists(db_path):
            with open(db_path, "rb") as f:
                st.download_button(
                    "Download Database Backup",
                    data=f,
                    file_name=f"providers_backup_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.db",
                    mime="application/octet-stream",
                )
        else:
            st.caption("No database file exists yet.")

    # ── General ──────────────────────────────────────────────────────
    with tab_general:
        st.markdown("### Email Configuration")
        send_from = st.text_input("Send-from Email", value=config.get("send_from_email", ""))
        vonage_domain = st.text_input("Vonage Domain", value=config.get("vonage_domain", "fax.vonagebusiness.com"))

        st.markdown("### Reminder Settings (days)")
        lunch_days = st.number_input("Lunch Follow-up Reminder", value=config.get("reminder_days", {}).get("lunch_followup", 90))
        cookie_days = st.number_input("Cookie Visit Reminder", value=config.get("reminder_days", {}).get("cookie_visit", 60))
        flyer_days = st.number_input("Flyer Send Reminder", value=config.get("reminder_days", {}).get("flyer_send", 30))

        if st.button("Save General Settings", type="primary"):
            config["send_from_email"] = send_from
            config["vonage_domain"] = vonage_domain
            config["reminder_days"] = {
                "lunch_followup": int(lunch_days),
                "cookie_visit": int(cookie_days),
                "flyer_send": int(flyer_days),
            }
            if _safe_save(config):
                st.success("Settings saved!")

    # ── File Paths ───────────────────────────────────────────────────
    with tab_paths:
        st.markdown("### File Paths")
        if is_cloud():
            st.info("File paths are not used on Streamlit Cloud. Use the **Data Import** tab to upload files instead.")
        excel_path = st.text_input("Excel File Path", value=config.get("excel_path", ""))
        flyer_folder = st.text_input("Flyer Folder Path", value=config.get("flyer_folder", ""))

        col1, col2 = st.columns(2)
        with col1:
            if excel_path and os.path.exists(excel_path):
                st.success("Excel file found")
            else:
                st.warning("Excel file not found (expected on cloud)")
        with col2:
            if flyer_folder and os.path.exists(flyer_folder):
                st.success("Flyer folder found")
            else:
                st.warning("Flyer folder not found (expected on cloud)")

        if st.button("Save Path Settings", type="primary"):
            config["excel_path"] = excel_path
            config["flyer_folder"] = flyer_folder
            if _safe_save(config):
                st.success("Paths saved!")

    # ── Team Members ─────────────────────────────────────────────────
    with tab_team:
        st.markdown("### Team Members")
        members = config.get("team_members", [])

        for i, member in enumerate(members):
            col1, col2 = st.columns([4, 1])
            col1.text(member)
            with col2:
                if st.button("Remove", key=f"rm_member_{i}"):
                    members.pop(i)
                    config["team_members"] = members
                    if _safe_save(config):
                        st.rerun()

        new_member = st.text_input("Add team member")
        if st.button("Add Member") and new_member:
            members.append(new_member)
            config["team_members"] = members
            if _safe_save(config):
                st.success(f"Added {new_member}")
                st.rerun()

    # ── Email (Graph API) ────────────────────────────────────────────
    with tab_graph:
        st.markdown("### Microsoft Graph API Configuration")
        st.info(
            "Enter your Azure App Registration credentials here. "
            "You need a **Client ID**, **Client Secret**, and **Tenant ID** "
            "from the Azure Portal."
        )

        graph_config = config.get("microsoft_graph", {})

        with st.form("graph_api_config"):
            st.markdown("#### Azure Credentials")

            client_id = st.text_input(
                "Client ID (Application ID)",
                value=graph_config.get("client_id", ""),
                help="Azure Portal > App registrations > NHCC Outreach Dashboard > Overview > Application (client) ID",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            )
            client_secret = st.text_input(
                "Client Secret (Secret Value)",
                value=graph_config.get("client_secret", ""),
                type="password",
                help="Azure Portal > Certificates & secrets > Client secrets > VALUE (not Secret ID!)",
                placeholder="Enter the secret VALUE here",
            )
            tenant_id = st.text_input(
                "Tenant ID (Directory ID)",
                value=graph_config.get("tenant_id", ""),
                help="Azure Portal > App registrations > Overview > Directory (tenant) ID",
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            )
            sender_email = st.text_input(
                "Sender Email Address",
                value=graph_config.get("sender_email", "office@nhcancerclinics.com"),
                help="The email address that will send flyers and other automated emails",
            )

            col_save, col_clear = st.columns(2)
            with col_save:
                submitted = st.form_submit_button("Save Configuration", type="primary")
            with col_clear:
                cleared = st.form_submit_button("Clear All")

            if submitted:
                if not all([client_id.strip(), client_secret.strip(), tenant_id.strip()]):
                    st.error("Please fill in all required fields (Client ID, Secret, Tenant ID)")
                else:
                    config["microsoft_graph"] = {
                        "client_id": client_id.strip(),
                        "client_secret": client_secret.strip(),
                        "tenant_id": tenant_id.strip(),
                        "sender_email": sender_email.strip(),
                    }
                    if _safe_save(config):
                        st.success("Configuration saved! Click **Test Connection** below to verify.")
                        st.rerun()

            if cleared:
                config["microsoft_graph"] = {
                    "client_id": "",
                    "client_secret": "",
                    "tenant_id": "",
                    "sender_email": "office@nhcancerclinics.com",
                }
                if _safe_save(config):
                    st.success("Configuration cleared")
                    st.rerun()

        # Test connection (outside form so it can run independently)
        st.markdown("#### Test Connection")

        if st.button("Test Microsoft Graph Connection", type="primary"):
            graph_config = config.get("microsoft_graph", {})
            if not all([graph_config.get("client_id"), graph_config.get("client_secret"), graph_config.get("tenant_id")]):
                st.error("Please save your credentials first")
            else:
                with st.spinner("Testing connection..."):
                    try:
                        from outlook_graph import OutlookGraphAPI
                        api = OutlookGraphAPI(
                            graph_config["client_id"],
                            graph_config["client_secret"],
                            graph_config["tenant_id"],
                        )
                        result = api.test_connection()
                        if result["success"]:
                            st.success(f"{result['message']}")
                            st.balloons()
                            st.info("You're ready to send flyers! Go to Flyer Campaigns page.")
                        else:
                            st.error(f"Connection failed: {result['error']}")
                            st.warning("Please check your credentials and try again")
                    except ImportError:
                        st.error("Missing dependency: run `pip install msal requests` in the project virtual environment.")
                    except Exception as e:
                        st.error(f"Error testing connection: {e}")

        # Current status
        graph_configured = all([
            graph_config.get("client_id"),
            graph_config.get("client_secret"),
            graph_config.get("tenant_id"),
        ])
        if graph_configured:
            st.success("Microsoft Graph API is configured")
            st.write(f"**Sender Email:** {graph_config.get('sender_email', 'N/A')}")
        else:
            st.warning("Microsoft Graph API not configured yet")

        # Help section
        with st.expander("How to get these credentials from Azure Portal"):
            st.markdown("""
            ### Step-by-Step Guide

            1. **Open Azure Portal** - https://portal.azure.com (sign in with your work account)
            2. **Navigate to App Registration** - Azure Active Directory > App registrations > "NHCC Outreach Dashboard"
            3. **Copy Client ID and Tenant ID** from the **Overview** page
               - Application (client) ID -> paste in "Client ID" above
               - Directory (tenant) ID -> paste in "Tenant ID" above
            4. **Get Client Secret** - Certificates & secrets > Client secrets
               - Copy the **VALUE** column (NOT the Secret ID!)
            5. **Save and Test** - Click Save Configuration, then Test Connection

            ### Required API Permissions (already configured):
            - Microsoft Graph > **Mail.Send** (Application) - Admin consent granted
            - Microsoft Graph > **User.Read** (Delegated) - Admin consent granted
            """)

    # ── Password ─────────────────────────────────────────────────────
    with tab_password:
        st.markdown("### Set App Password")
        new_pw = st.text_input("New Password", type="password", key="new_pw")
        confirm_pw = st.text_input("Confirm Password", type="password", key="confirm_pw")

        if st.button("Set Password", type="primary"):
            if not new_pw:
                st.error("Password cannot be empty")
            elif new_pw != confirm_pw:
                st.error("Passwords do not match")
            else:
                import bcrypt
                hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
                config["app_password_hash"] = hashed
                if _safe_save(config):
                    st.success("Password set! You'll need it next time you log in.")

        if config.get("app_password_hash"):
            st.info("A password is currently set.")
            if st.button("Remove Password"):
                config["app_password_hash"] = ""
                if _safe_save(config):
                    st.success("Password removed. Anyone can access the app.")
                    st.rerun()
        else:
            st.warning("No password is set. Anyone can access the app.")

    # ── Data Management ──────────────────────────────────────────────
    with tab_mgmt:
        st.markdown("### Data Management")

        st.markdown("#### Re-import Excel Data")
        st.warning("This will clear all existing data and re-import from an Excel file.")

        reimport_file = st.file_uploader(
            "Upload Excel file for re-import",
            type=["xlsx", "xls"],
            key="reimport_upload",
        )

        if reimport_file is not None:
            if st.button("Re-import from Uploaded File"):
                st.session_state["confirm_reimport_upload"] = True

            if st.session_state.get("confirm_reimport_upload", False):
                st.error("Are you sure? This will delete all existing data!")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, Re-import", type="primary", key="confirm_reimport_yes"):
                        with st.spinner("Re-importing..."):
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                                tmp.write(reimport_file.getvalue())
                                tmp_path = tmp.name
                            try:
                                from database import get_connection, init_db
                                init_db()
                                conn = get_connection()
                                tables = ["flyer_recipients", "flyer_campaigns", "cookie_visits",
                                          "thank_you_letters", "call_attempts", "lunch_tracking",
                                          "contact_log", "provider_history", "providers", "practices",
                                          "events", "follow_ups"]
                                for t in tables:
                                    try:
                                        conn.execute(f"DELETE FROM {t}")
                                    except Exception:
                                        pass
                                conn.commit()
                                conn.close()

                                from data_import import import_excel
                                stats = import_excel(tmp_path)
                            finally:
                                os.unlink(tmp_path)
                        st.session_state["confirm_reimport_upload"] = False
                        st.success(f"Re-imported: {stats['practices_imported']} practices, {stats['providers_imported']} providers")
                        st.rerun()
                with col2:
                    if st.button("Cancel", key="confirm_reimport_no"):
                        st.session_state["confirm_reimport_upload"] = False
                        st.rerun()

        # Legacy local file re-import (only if local path exists)
        excel_path = config.get("excel_path", "")
        if excel_path and os.path.exists(excel_path):
            st.markdown("---")
            st.markdown("#### Re-import from Local File")
            if st.button("Re-import from Local Excel"):
                st.session_state["confirm_reimport"] = True

            if st.session_state.get("confirm_reimport", False):
                st.error("Are you sure? This will delete all existing data!")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, Re-import", type="primary", key="local_reimport_yes"):
                        from database import get_connection
                        conn = get_connection()
                        tables = ["flyer_recipients", "flyer_campaigns", "cookie_visits",
                                  "thank_you_letters", "call_attempts", "lunch_tracking",
                                  "contact_log", "provider_history", "providers", "practices"]
                        for t in tables:
                            conn.execute(f"DELETE FROM {t}")
                        conn.commit()
                        conn.close()

                        from data_import import import_excel
                        stats = import_excel()
                        st.session_state["confirm_reimport"] = False
                        st.success(f"Re-imported: {stats['practices_imported']} practices, {stats['providers_imported']} providers")
                        st.rerun()
                with col2:
                    if st.button("Cancel", key="local_reimport_no"):
                        st.session_state["confirm_reimport"] = False
                        st.rerun()

        st.markdown("---")
        st.markdown("#### Fix Vonage Fax Emails")
        st.caption(
            "Re-derives every practice's Vonage fax email from its fax number. "
            "Fixes invalid formats (parentheses, double underscores, etc.)."
        )
        if db_exists():
            if st.button("Fix All Vonage Fax Emails", type="primary"):
                with st.spinner("Fixing fax email formats..."):
                    from database import fix_all_vonage_emails
                    result = fix_all_vonage_emails()
                st.success(f"Fixed {result['fixed']} fax email address(es)")
                if result["errors"]:
                    st.warning(f"{len(result['errors'])} could not be parsed:")
                    for err in result["errors"]:
                        st.caption(f"- {err}")
        else:
            st.caption("Import data first to use this feature.")

        st.markdown("#### Location Zip Codes")
        st.markdown("**Huntsville Zips:**")
        st.text(", ".join(config.get("huntsville_zips", [])))
        st.markdown("**Woodlands Zips:**")
        st.text(", ".join(config.get("woodlands_zips", [])))
