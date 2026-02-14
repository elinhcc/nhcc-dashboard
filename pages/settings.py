"""Settings page: app configuration, paths, team members, password management."""
import streamlit as st
import os
from utils import load_config, save_config


def show_settings():
    st.markdown("## ⚙️ Settings")

    config = load_config()

    tab_general, tab_paths, tab_team, tab_password, tab_data = st.tabs([
        "General", "File Paths", "Team Members", "Password", "Data Management",
    ])

    # ── General ────────────────────────────────────────────────────────
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
            save_config(config)
            st.success("Settings saved!")

    # ── File Paths ─────────────────────────────────────────────────────
    with tab_paths:
        st.markdown("### File Paths")
        excel_path = st.text_input("Excel File Path", value=config.get("excel_path", ""))
        flyer_folder = st.text_input("Flyer Folder Path", value=config.get("flyer_folder", ""))

        col1, col2 = st.columns(2)
        with col1:
            if os.path.exists(excel_path):
                st.success("✅ Excel file found")
            else:
                st.error("❌ Excel file not found")
        with col2:
            if os.path.exists(flyer_folder):
                st.success("✅ Flyer folder found")
            else:
                st.error("❌ Flyer folder not found")

        if st.button("Save Path Settings", type="primary"):
            config["excel_path"] = excel_path
            config["flyer_folder"] = flyer_folder
            save_config(config)
            st.success("Paths saved!")

    # ── Team Members ───────────────────────────────────────────────────
    with tab_team:
        st.markdown("### Team Members")
        members = config.get("team_members", [])

        for i, member in enumerate(members):
            col1, col2 = st.columns([4, 1])
            col1.text(member)
            with col2:
                if st.button("❌", key=f"rm_member_{i}"):
                    members.pop(i)
                    config["team_members"] = members
                    save_config(config)
                    st.rerun()

        new_member = st.text_input("Add team member")
        if st.button("Add Member") and new_member:
            members.append(new_member)
            config["team_members"] = members
            save_config(config)
            st.success(f"Added {new_member}")
            st.rerun()

    # ── Password ───────────────────────────────────────────────────────
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
                save_config(config)
                st.success("Password set! You'll need it next time you log in.")

        if config.get("app_password_hash"):
            st.info("A password is currently set.")
            if st.button("Remove Password"):
                config["app_password_hash"] = ""
                save_config(config)
                st.success("Password removed. Anyone can access the app.")
                st.rerun()
        else:
            st.warning("No password is set. Anyone can access the app.")

    # ── Data Management ────────────────────────────────────────────────
    with tab_data:
        st.markdown("### Data Management")

        st.markdown("#### Re-import Excel Data")
        st.warning("This will clear all existing data and re-import from the Excel file.")
        if st.button("🔄 Re-import from Excel"):
            st.session_state["confirm_reimport"] = True

        if st.session_state.get("confirm_reimport", False):
            st.error("Are you sure? This will delete all existing data!")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Yes, Re-import", type="primary"):
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
                if st.button("Cancel"):
                    st.session_state["confirm_reimport"] = False
                    st.rerun()

        st.markdown("#### Backup Database")
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "providers.db")
        if os.path.exists(db_path):
            with open(db_path, "rb") as f:
                st.download_button(
                    "📥 Download Database Backup",
                    data=f,
                    file_name=f"providers_backup_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.db",
                    mime="application/octet-stream",
                )

        st.markdown("#### Location Zip Codes")
        st.markdown("**Huntsville Zips:**")
        st.text(", ".join(config.get("huntsville_zips", [])))
        st.markdown("**Woodlands Zips:**")
        st.text(", ".join(config.get("woodlands_zips", [])))
