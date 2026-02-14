"""Provider list view: search, filter, add, edit, move, archive providers."""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from database import (
    get_all_practices, get_practice, add_practice, update_practice,
    search_practices, get_providers_for_practice, add_provider,
    update_provider, move_provider, get_all_providers, get_provider,
    delete_provider,
    get_contact_log, add_contact_log, get_lunches, add_lunch, update_lunch,
    add_call_attempt, get_call_attempts, get_cookie_visits, add_cookie_visit,
    get_thank_yous, add_thank_you, update_thank_you,
    get_call_attempt_count, get_last_contact,
)
from database import create_event, update_event
from utils import relationship_score, score_color, score_label, categorize_location, days_since
from data_import import fax_to_vonage_email


# ── Callback helpers (execute BEFORE page re-renders) ─────────────────

def _cb_open_contact(practice_id):
    st.session_state.active_contact_form = practice_id
    st.session_state.active_lunch_form = None

def _cb_open_lunch(practice_id):
    st.session_state.active_lunch_form = practice_id
    st.session_state.active_contact_form = None


# ── ICS generation ────────────────────────────────────────────────────

def _generate_ics(practice_name, scheduled_date, scheduled_time, restaurant,
                  staff_count, dietary_notes, confirmed_with):
    """Generate an .ics calendar file string."""
    # Parse time
    hour, minute = 12, 0
    if scheduled_time:
        import re
        m = re.match(r'(\d{1,2}):?(\d{2})?\s*(AM|PM|am|pm)?', scheduled_time.strip())
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            ampm = (m.group(3) or "").upper()
            if ampm == "PM" and hour < 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0

    dt_start = datetime.combine(scheduled_date, datetime.min.time().replace(hour=hour, minute=minute))
    dt_end = dt_start + timedelta(hours=1)
    uid = f"nhcc-lunch-{scheduled_date.isoformat()}-{practice_name.replace(' ', '')}@nhcc"

    def fmt(dt):
        return dt.strftime("%Y%m%dT%H%M%S")

    desc_parts = []
    if restaurant:
        desc_parts.append(f"Restaurant: {restaurant}")
    if staff_count:
        desc_parts.append(f"Expected attendees: {staff_count}")
    if dietary_notes:
        desc_parts.append(f"Dietary notes: {dietary_notes}")
    if confirmed_with:
        desc_parts.append(f"Confirmed with: {confirmed_with}")
    description = "\\n".join(desc_parts)

    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//NHCC//Outreach Dashboard//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{fmt(dt_start)}\r\n"
        f"DTEND:{fmt(dt_end)}\r\n"
        f"SUMMARY:Lunch - {practice_name}\r\n"
        f"DESCRIPTION:{description}\r\n"
        f"LOCATION:{restaurant or 'TBD'}\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


# ── Sidebar forms (rendered from app.py) ──────────────────────────────

def render_sidebar_contact_form():
    """Render the contact logging form in the sidebar when active."""
    practice_id = st.session_state.get("active_contact_form")
    if not practice_id:
        return

    practice = get_practice(practice_id)
    if not practice:
        st.session_state.active_contact_form = None
        return

    # Render as a modal dialog so it overlays the app
    with st.modal("Log Contact"):
        st.markdown(f"### 📞 Log Contact — {practice['name']}")

        # Call history for this practice
        call_count = get_call_attempt_count(practice_id)
        contacts = get_contact_log(practice_id=practice_id, limit=20)
        phone_contacts = [c for c in contacts if c.get("contact_type") == "Phone Call"]

        if phone_contacts:
            st.markdown("**Recent Call History:**")
            for c in phone_contacts[:5]:
                date_str = (c.get("contact_date") or "")[:10] if c.get("contact_date") else "?"
                attempt_num = c.get("call_attempt_number", "")
                attempt_label = f"Call #{attempt_num}" if attempt_num else "Call"
                outcome = c.get("outcome", "")
                st.caption(f"📞 {attempt_label} - {date_str} - {outcome}")

            if call_count >= 3 and not any(c.get("outcome") == "Scheduled lunch" for c in phone_contacts):
                st.warning(f"**{call_count} calls** with no lunch scheduled. Consider trying email or in-person visit.")

        with st.form("modal_contact_form", clear_on_submit=True):
            contact_type = st.radio(
                "Contact Type",
                ["Phone Call", "Email Sent", "In-Person Visit", "Voicemail Left", "No Answer"],
                horizontal=True,
            )

            col_d, col_t = st.columns(2)
            with col_d:
                contact_date = st.date_input("Date", value=datetime.now())
            with col_t:
                contact_time = st.time_input("Time", value=datetime.now())

            is_phone = contact_type == "Phone Call"

            if is_phone:
                st.caption(f"This will be **Call Attempt #{call_count + 1}**")

            person_contacted = st.text_input("Person Contacted")

            if is_phone:
                outcome = st.selectbox("Call Outcome", [
                    "Scheduled lunch", "Left voicemail", "No answer",
                    "Busy", "Will call back", "Not interested", "Other",
                ])
                purpose = st.selectbox("Purpose of Call", [
                    "Schedule lunch", "Confirm lunch", "Follow-up",
                    "Thank you call", "Introduction", "Other",
                ])
            else:
                outcome = st.selectbox("Outcome", [
                    "Successful", "No Answer", "Left Message",
                    "Follow-up Needed", "Other",
                ])
                purpose = st.selectbox("Purpose", [
                    "Schedule lunch", "Confirm lunch", "Follow-up",
                    "Thank you", "Introduction", "Other",
                ])

            team_member = st.selectbox("Team Member", ["Robbie", "Kianah", "Darvin", "Other"])
            notes = st.text_area("Notes", height=80)

            col_save, col_cancel = st.columns(2)
            with col_save:
                submitted = st.form_submit_button("Save Contact", type="primary", use_container_width=True)
            with col_cancel:
                cancelled = st.form_submit_button("Cancel", use_container_width=True)

            if submitted:
                contact_datetime = datetime.combine(contact_date, contact_time).isoformat()
                log_data = {
                    "practice_id": practice_id,
                    "contact_type": contact_type,
                    "contact_date": contact_datetime,
                    "team_member": team_member,
                    "person_contacted": person_contacted,
                    "outcome": outcome,
                    "purpose": purpose,
                    "notes": notes,
                }
                if is_phone:
                    log_data["call_attempt_number"] = call_count + 1
                add_contact_log(log_data)
                attempt_label = f" (Attempt #{call_count + 1})" if is_phone else ""
                st.session_state.active_contact_form = None
                st.session_state.show_contact_success = f"{contact_type} logged for {practice['name']}{attempt_label}"
                st.experimental_rerun()

            if cancelled:
                st.session_state.active_contact_form = None
                st.experimental_rerun()


def render_sidebar_lunch_form():
    """Render the lunch scheduling form in the sidebar when active."""
    practice_id = st.session_state.get("active_lunch_form")
    if not practice_id:
        return

    practice = get_practice(practice_id)
    if not practice:
        st.session_state.active_lunch_form = None
        return

    providers = get_providers_for_practice(practice_id)

    # Render as a modal dialog for scheduling lunch
    with st.modal("Schedule Lunch"):
        st.markdown(f"### 🍽️ Schedule Lunch — {practice['name']}")

        # Show existing scheduled lunches
        existing = get_lunches(practice_id=practice_id, status_filter="Scheduled")
        if existing:
            st.info(f"This practice already has {len(existing)} scheduled lunch(es).")

        with st.form("modal_lunch_form", clear_on_submit=True):
            prov_options = ["All Providers / General"] + [p["name"] for p in providers]
            selected_provider = st.selectbox("Provider *", prov_options)

            col_d, col_t = st.columns(2)
            with col_d:
                scheduled_date = st.date_input("Date *", value=datetime.now() + timedelta(days=7))
            with col_t:
                scheduled_time = st.text_input("Time *", placeholder="11:30 AM")

            staff_count = st.number_input("Expected Attendees", min_value=1, value=5)
            restaurant = st.text_input("Restaurant / Vendor")
            dietary_notes = st.text_input("Dietary Restrictions")
            confirmed_with = st.text_input("Confirmed With")
            lunch_notes = st.text_area("Notes", height=60)

            st.markdown("---")
            st.markdown("**Schedule next follow-up**")
            schedule_next = st.checkbox("Schedule next follow-up after completing this lunch")
            followup_interval = None
            custom_followup_date = None
            if schedule_next:
                followup_interval = st.selectbox("Follow-up interval", ["12 weeks", "3 months", "6 months", "Custom"], index=0)
                if followup_interval == "Custom":
                    custom_followup_date = st.date_input("Custom next follow-up date")

            col_save, col_cancel = st.columns(2)
            with col_save:
                submitted = st.form_submit_button("Schedule Lunch", type="primary", use_container_width=True)
            with col_cancel:
                cancelled = st.form_submit_button("Cancel", use_container_width=True)

            if submitted:
                if not (scheduled_time or "").strip():
                    st.error("Time is required")
                else:
                    lunch_id = add_lunch({
                        "practice_id": practice_id,
                        "status": "Scheduled",
                        "scheduled_date": scheduled_date.isoformat(),
                        "scheduled_time": scheduled_time,
                        "staff_count": staff_count,
                        "dietary_notes": dietary_notes,
                        "restaurant": restaurant,
                        "confirmed_with": confirmed_with,
                        "visit_notes": lunch_notes,
                    })
                    # Also log as contact
                    add_contact_log({
                        "practice_id": practice_id,
                        "contact_type": "Phone Call",
                        "contact_date": datetime.now().isoformat(),
                        "team_member": "Robbie",
                        "outcome": "Scheduled lunch",
                        "purpose": "Schedule lunch",
                        "call_attempt_number": get_call_attempt_count(practice_id) + 1,
                        "notes": f"Lunch scheduled at {restaurant} for {staff_count} people on {scheduled_date}",
                    })

                    # Create an event record for the calendar
                    try:
                        evt_label = f"Lunch - {practice['name']}"
                        evt_data = {
                            "practice_id": practice_id,
                            "event_type": "Lunch",
                            "label": evt_label,
                            "scheduled_date": scheduled_date.isoformat(),
                            "scheduled_time": scheduled_time,
                            "status": "Scheduled",
                            "notes": lunch_notes,
                            "created_by": "ui",
                        }
                        eid = create_event(evt_data)
                    except Exception:
                        eid = None

                    # If schedule_next selected and custom date provided, create a linked event
                    if schedule_next and custom_followup_date:
                        try:
                            next_evt = create_event({
                                "practice_id": practice_id,
                                "event_type": "Lunch",
                                "label": f"Follow-up Lunch - {practice['name']}",
                                "scheduled_date": custom_followup_date.isoformat(),
                                "status": "Scheduled",
                                "created_by": "ui",
                                "followup_interval": followup_interval,
                            })
                            if eid and next_evt:
                                update_event(next_evt, {"next_event_id": None})
                        except Exception:
                            pass

                    # Generate ICS for download
                    ics_content = _generate_ics(
                        practice['name'], scheduled_date, scheduled_time,
                        restaurant, staff_count, dietary_notes, confirmed_with,
                    )
                    st.session_state.last_ics = ics_content
                    st.session_state.last_ics_name = f"lunch_{practice['name'].replace(' ', '_')}_{scheduled_date}.ics"
                    st.session_state.active_lunch_form = None
                    st.session_state.show_lunch_success = f"Lunch scheduled at {practice['name']} on {scheduled_date} at {scheduled_time}"
                    st.experimental_rerun()

            if cancelled:
                st.session_state.active_lunch_form = None
                st.experimental_rerun()


# ── Main page ─────────────────────────────────────────────────────────

def show_providers():
    st.markdown("## 🏢 Provider & Practice Management")

    # Show success messages from sidebar form submissions
    if st.session_state.get("show_contact_success"):
        st.success(st.session_state.show_contact_success)
        st.session_state.show_contact_success = None

    if st.session_state.get("show_lunch_success"):
        st.success(st.session_state.show_lunch_success)
        # Offer ICS download
        if st.session_state.get("last_ics"):
            st.download_button(
                "📅 Download Calendar Event (.ics)",
                data=st.session_state.last_ics,
                file_name=st.session_state.get("last_ics_name", "lunch.ics"),
                mime="text/calendar",
            )
            st.session_state.last_ics = None
            st.session_state.last_ics_name = None
        st.session_state.show_lunch_success = None

    tab_practices, tab_providers, tab_add = st.tabs(["Practices", "Individual Providers", "Add New"])

    # ── Practices Tab ──────────────────────────────────────────────────
    with tab_practices:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            search_query = st.text_input("🔍 Search practices", placeholder="Name, address, phone...")
        with col2:
            status_filter = st.selectbox("Status", ["Active", "Inactive", "All"])
        with col3:
            location_filter = st.selectbox("Location", ["All", "Huntsville", "Woodlands", "Other"])

        if search_query:
            practices = search_practices(search_query)
        elif status_filter == "All":
            practices = get_all_practices()
        else:
            practices = get_all_practices(status_filter=status_filter)

        if location_filter != "All":
            practices = [p for p in practices if p.get("location_category") == location_filter]

        st.caption(f"Showing {len(practices)} practices")

        for practice in practices:
            score = relationship_score(practice["id"])
            color = score_color(score)
            providers = get_providers_for_practice(practice["id"])

            with st.expander(f"{'🟢' if score >= 70 else '🟡' if score >= 40 else '🔴'} {practice['name']} — {practice.get('location_category', 'Other')} | {len(providers)} providers"):
                # Practice detail view
                detail_col1, detail_col2 = st.columns(2)

                with detail_col1:
                    st.markdown(f"**Address:** {practice.get('address', 'N/A')}")
                    st.markdown(f"**Phone:** {practice.get('phone', 'N/A')}")
                    st.markdown(f"**Fax:** {practice.get('fax', 'N/A')}")
                    if practice.get("fax_vonage_email"):
                        st.markdown(f"**Vonage Email:** {practice['fax_vonage_email']}")
                    st.markdown(f"**Relationship Score:** :{color[1:]}: {score}/100 ({score_label(score)})")

                with detail_col2:
                    st.markdown(f"**Status:** {practice.get('status', 'Active')}")
                    st.markdown(f"**Contact Person:** {practice.get('contact_person', 'N/A')}")
                    st.markdown(f"**Notes:** {practice.get('notes', '')[:200]}")

                # Last contact summary
                last = get_last_contact(practice["id"])
                if last:
                    lc_date = last.get("contact_date", "")[:10] if last.get("contact_date") else "?"
                    lc_days = days_since(last.get("contact_date"))
                    lc_days_str = f"{lc_days} days ago" if lc_days is not None else ""
                    lc_type = last.get("contact_type", "")
                    lc_attempt = last.get("call_attempt_number")
                    attempt_str = f" (Attempt #{lc_attempt})" if lc_attempt else ""
                    lc_outcome = last.get("outcome", "")
                    st.caption(f"**Last Contact:** {lc_type}{attempt_str} {lc_days_str} — {lc_outcome}")
                    # Show pending lunch scheduling attempts
                    call_count = get_call_attempt_count(practice["id"])
                    if call_count > 0:
                        scheduled = any(c.get("outcome") == "Scheduled lunch" for c in get_contact_log(practice_id=practice["id"], limit=50))
                        if not scheduled:
                            st.caption(f"**Pending:** Schedule lunch ({call_count} call{'s' if call_count != 1 else ''} made)")
                else:
                    st.caption("**Last Contact:** None — no contact logged yet")

                # Providers list with management controls
                st.markdown("**Providers:**")
                if providers:
                    for prov in providers:
                        prov_col1, prov_col2, prov_col3, prov_col4 = st.columns([3, 1, 1, 1])
                        with prov_col1:
                            status_icon = "🟢" if prov["status"] == "Active" else "⚪"
                            st.markdown(f"{status_icon} {prov['name']} ({prov['status']})")
                        with prov_col2:
                            if st.button("✏️", key=f"edit_prov_{prov['id']}", help="Edit provider"):
                                st.session_state[f"editing_prov_{prov['id']}"] = True
                        with prov_col3:
                            toggle_label = "⚪ Deactivate" if prov["status"] == "Active" else "🟢 Activate"
                            if st.button(toggle_label, key=f"toggle_prov_{prov['id']}"):
                                new_status = "Inactive" if prov["status"] == "Active" else "Active"
                                update_provider(prov["id"], {"status": new_status})
                                st.success(f"{prov['name']} set to {new_status}")
                                st.rerun()
                        with prov_col4:
                            if st.button("🗑️", key=f"del_prov_{prov['id']}", help="Remove provider"):
                                st.session_state[f"confirm_del_prov_{prov['id']}"] = True

                        # Confirm delete dialog
                        if st.session_state.get(f"confirm_del_prov_{prov['id']}", False):
                            st.warning(f"Are you sure you want to remove **{prov['name']}** from this practice?")
                            confirm_col1, confirm_col2 = st.columns(2)
                            with confirm_col1:
                                if st.button("Yes, Remove", key=f"confirm_yes_{prov['id']}", type="primary"):
                                    delete_provider(prov["id"])
                                    st.session_state[f"confirm_del_prov_{prov['id']}"] = False
                                    st.success(f"{prov['name']} removed from practice")
                                    st.rerun()
                            with confirm_col2:
                                if st.button("Cancel", key=f"confirm_no_{prov['id']}"):
                                    st.session_state[f"confirm_del_prov_{prov['id']}"] = False
                                    st.rerun()

                        # Edit provider inline form
                        if st.session_state.get(f"editing_prov_{prov['id']}", False):
                            with st.form(f"edit_prov_form_{prov['id']}"):
                                st.markdown(f"#### Edit Provider: {prov['name']}")
                                new_name = st.text_input("Provider Name", value=prov["name"])
                                new_prov_status = st.selectbox("Status", ["Active", "Inactive"],
                                    index=0 if prov["status"] == "Active" else 1)
                                inactive_reason = st.text_input("Inactive Reason",
                                    value=prov.get("inactive_reason", "") or "")
                                ep_col1, ep_col2 = st.columns(2)
                                with ep_col1:
                                    if st.form_submit_button("Save", type="primary"):
                                        update_data = {"name": new_name, "status": new_prov_status}
                                        if new_prov_status == "Inactive" and inactive_reason:
                                            update_data["inactive_reason"] = inactive_reason
                                        elif new_prov_status == "Active":
                                            update_data["inactive_reason"] = ""
                                        update_provider(prov["id"], update_data)
                                        st.session_state[f"editing_prov_{prov['id']}"] = False
                                        st.success(f"Provider '{new_name}' updated!")
                                        st.rerun()
                                with ep_col2:
                                    if st.form_submit_button("Cancel"):
                                        st.session_state[f"editing_prov_{prov['id']}"] = False
                                        st.rerun()
                else:
                    st.caption("No providers listed for this practice.")

                # Add provider button
                if st.button("➕ Add Provider", key=f"add_prov_{practice['id']}"):
                    st.session_state[f"adding_prov_{practice['id']}"] = True

                if st.session_state.get(f"adding_prov_{practice['id']}", False):
                    with st.form(f"add_prov_form_{practice['id']}"):
                        st.markdown("#### Add Provider to Practice")
                        new_prov_name = st.text_input("Provider Name *")
                        new_prov_status = st.selectbox("Status", ["Active", "Inactive"])
                        ap_col1, ap_col2 = st.columns(2)
                        with ap_col1:
                            if st.form_submit_button("Add Provider", type="primary"):
                                if not new_prov_name.strip():
                                    st.error("Provider name is required")
                                else:
                                    add_provider({
                                        "name": new_prov_name.strip(),
                                        "practice_id": practice["id"],
                                        "status": new_prov_status,
                                    })
                                    st.session_state[f"adding_prov_{practice['id']}"] = False
                                    st.success(f"Provider '{new_prov_name.strip()}' added!")
                                    st.rerun()
                        with ap_col2:
                            if st.form_submit_button("Cancel"):
                                st.session_state[f"adding_prov_{practice['id']}"] = False
                                st.rerun()

                st.divider()

                # Action buttons — use on_click callbacks to avoid session state errors
                btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)

                with btn_col1:
                    if st.button("✏️ Edit", key=f"edit_{practice['id']}"):
                        st.session_state[f"editing_{practice['id']}"] = True

                with btn_col2:
                    st.button(
                        "📞 Log Contact",
                        key=f"contact_{practice['id']}",
                        on_click=_cb_open_contact,
                        args=(practice["id"],),
                    )

                with btn_col3:
                    st.button(
                        "🍽️ Schedule Lunch",
                        key=f"lunch_{practice['id']}",
                        on_click=_cb_open_lunch,
                        args=(practice["id"],),
                    )

                with btn_col4:
                    new_status = "Inactive" if practice["status"] == "Active" else "Active"
                    if st.button(f"{'🔴 Archive' if practice['status'] == 'Active' else '🟢 Reactivate'}", key=f"archive_{practice['id']}"):
                        update_practice(practice["id"], {"status": new_status})
                        st.success(f"Practice set to {new_status}")
                        st.rerun()

                # Edit form
                if st.session_state.get(f"editing_{practice['id']}", False):
                    _show_edit_form(practice)

                # Contact history timeline
                contacts = get_contact_log(practice_id=practice["id"], limit=10)
                if contacts:
                    st.markdown("**Recent Contact History:**")
                    for c in contacts[:5]:
                        date_str = c.get("contact_date", "")[:16] if c.get("contact_date") else "N/A"
                        ctype = c.get("contact_type", "")
                        attempt = c.get("call_attempt_number")
                        attempt_str = f" #{attempt}" if attempt else ""
                        outcome = c.get("outcome", "")
                        purpose = c.get("purpose", "")
                        purpose_str = f" ({purpose})" if purpose else ""
                        st.caption(f"📅 {date_str} | {ctype}{attempt_str} | {outcome}{purpose_str} | {c.get('notes', '')[:60]}")

    # ── Individual Providers Tab ───────────────────────────────────────
    with tab_providers:
        all_providers = get_all_providers()
        prov_search = st.text_input("🔍 Search providers by name", key="prov_search")
        if prov_search:
            all_providers = [p for p in all_providers if prov_search.lower() in p["name"].lower()]

        if all_providers:
            df = pd.DataFrame(all_providers)[["name", "practice_name", "status"]]
            df.columns = ["Provider Name", "Practice", "Status"]
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Move provider
            st.markdown("### Move Provider to New Practice")
            prov_options = {f"{p['name']} ({p.get('practice_name', 'N/A')})": p["id"] for p in all_providers}
            selected_prov = st.selectbox("Select Provider", options=list(prov_options.keys()))
            all_practices = get_all_practices()
            practice_options = {p["name"]: p["id"] for p in all_practices}
            new_practice = st.selectbox("Move to Practice", options=list(practice_options.keys()))
            move_notes = st.text_input("Move notes")
            if st.button("Move Provider"):
                if selected_prov and new_practice:
                    move_provider(prov_options[selected_prov], practice_options[new_practice], move_notes)
                    st.success(f"Provider moved to {new_practice}")
                    st.rerun()
        else:
            st.info("No providers found.")

    # ── Add New Tab ────────────────────────────────────────────────────
    with tab_add:
        st.markdown("### Add New Practice")
        with st.form("add_practice_form"):
            name = st.text_input("Practice Name *")
            address = st.text_input("Address")
            phone = st.text_input("Phone")
            fax = st.text_input("Fax Number")
            contact_person = st.text_input("Contact Person")
            email = st.text_input("Email")
            website = st.text_input("Website")
            notes = st.text_area("Notes")
            new_providers = st.text_area("Providers (one per line)")

            if st.form_submit_button("Add Practice", type="primary"):
                if not name:
                    st.error("Practice name is required")
                else:
                    config_data = __import__("utils").load_config()
                    vonage_email = fax_to_vonage_email(fax, config_data.get("vonage_domain", "fax.vonagebusiness.com")) if fax else ""
                    zip_code = ""
                    import re
                    zip_match = re.search(r'\b(\d{5})\b', address)
                    if zip_match:
                        zip_code = zip_match.group(1)

                    practice_id = add_practice({
                        "name": name,
                        "address": address,
                        "zip_code": zip_code,
                        "location_category": categorize_location(address),
                        "phone": phone,
                        "fax": fax,
                        "fax_vonage_email": vonage_email,
                        "contact_person": contact_person,
                        "email": email,
                        "website": website,
                        "notes": notes,
                    })

                    if new_providers:
                        for prov_name in new_providers.strip().split("\n"):
                            prov_name = prov_name.strip()
                            if prov_name:
                                add_provider({"name": prov_name, "practice_id": practice_id, "status": "Active"})

                    st.success(f"Practice '{name}' added successfully!")
                    st.rerun()


def _show_edit_form(practice):
    """Show inline edit form for a practice."""
    with st.form(f"edit_form_{practice['id']}"):
        st.markdown("#### Edit Practice")
        name = st.text_input("Name", value=practice.get("name", ""))
        address = st.text_input("Address", value=practice.get("address", ""))
        phone = st.text_input("Phone", value=practice.get("phone", ""))
        fax = st.text_input("Fax", value=practice.get("fax", ""))
        contact_person = st.text_input("Contact Person", value=practice.get("contact_person", ""))
        email = st.text_input("Email", value=practice.get("email", ""))
        website = st.text_input("Website", value=practice.get("website", ""))
        notes = st.text_area("Notes", value=practice.get("notes", ""))

        col1, col2 = st.columns(2)
        with col1:
            if st.form_submit_button("Save Changes", type="primary"):
                config_data = __import__("utils").load_config()
                vonage_email = fax_to_vonage_email(fax, config_data.get("vonage_domain", "fax.vonagebusiness.com")) if fax else ""
                import re
                zip_code = ""
                zip_match = re.search(r'\b(\d{5})\b', address)
                if zip_match:
                    zip_code = zip_match.group(1)

                update_practice(practice["id"], {
                    "name": name, "address": address, "phone": phone, "fax": fax,
                    "fax_vonage_email": vonage_email, "contact_person": contact_person,
                    "email": email, "website": website, "notes": notes,
                    "zip_code": zip_code, "location_category": categorize_location(address),
                })
                st.session_state[f"editing_{practice['id']}"] = False
                st.success("Practice updated!")
                st.rerun()
        with col2:
            if st.form_submit_button("Cancel"):
                st.session_state[f"editing_{practice['id']}"] = False
                st.rerun()
