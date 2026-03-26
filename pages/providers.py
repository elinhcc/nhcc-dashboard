"""Provider list view: search, filter, add, edit, move, archive providers."""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils import db_exists

_SPECIALTIES = [
    "", "Cardiology", "Dermatology", "Endocrinology", "Gastroenterology",
    "Hematology/Oncology", "Infectious Disease", "Internal Medicine",
    "Nephrology", "Neurology", "Obstetrics & Gynecology", "Oncology",
    "Ophthalmology", "Orthopedics", "Otolaryngology (ENT)", "Palliative Care",
    "Primary Care", "Psychiatry", "Pulmonology", "Radiation Oncology",
    "Radiology", "Rheumatology", "Surgery", "Urology", "Other",
]


# ── Callback helpers (execute BEFORE page re-renders) ─────────────────

def _cb_open_contact(practice_id):
    st.session_state.active_contact_form = practice_id
    st.session_state.active_lunch_form = None
    st.session_state.active_fax_form = None

def _cb_open_contact_email(practice_id):
    st.session_state.active_contact_form = practice_id
    st.session_state.contact_type_default = "Email Sent"
    st.session_state.active_lunch_form = None
    st.session_state.active_fax_form = None

def _cb_open_fax(practice_id):
    st.session_state.active_fax_form = practice_id
    st.session_state.active_contact_form = None
    st.session_state.active_lunch_form = None

def _cb_open_lunch(practice_id):
    st.session_state.active_lunch_form = practice_id
    st.session_state.active_contact_form = None
    st.session_state.active_fax_form = None

def _cb_open_delete(practice_id):
    st.session_state.active_delete_form = practice_id


@st.dialog("Delete Practice", width="small")
def _delete_dialog(practice_id):
    """Confirmation modal for permanently deleting a practice."""
    from database import get_practice, delete_practice_permanently
    practice = get_practice(practice_id)
    if not practice:
        st.error("Practice not found.")
        return

    pname = practice["name"]
    st.error(f"**Permanently delete '{pname}'?**")
    st.warning(
        "This **cannot be undone**. All of the following will also be deleted:\n\n"
        "- All contact log entries\n"
        "- All tasks\n"
        "- All calendar events\n"
        "- All providers belonging to this practice\n"
        "- All lunch & outreach records"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Yes, Delete Permanently", type="primary", use_container_width=True):
            result = delete_practice_permanently(practice_id)
            if result["deleted"]:
                st.session_state.active_delete_form = None
                st.rerun()
            else:
                st.error(f"Delete failed: {result['error']}")
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.active_delete_form = None
            st.rerun()


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


# ── Modal dialog forms (rendered from app.py) ────────────────────────

@st.dialog("Log Contact", width="large")
def _contact_dialog(practice_id):
    """Centered modal popup for logging a contact."""
    from database import (get_practice, get_contact_log, add_contact_log,
                          get_call_attempt_count)
    practice = get_practice(practice_id)
    if not practice:
        st.error("Practice not found.")
        return

    st.markdown(f"### Log Contact - {practice['name']}")

    call_count = get_call_attempt_count(practice_id)
    contacts = get_contact_log(practice_id=practice_id, limit=20)
    phone_contacts = [c for c in contacts if c.get("contact_type") == "Phone Call"]

    if call_count >= 3 and not any(c.get("outcome") == "Scheduled lunch" for c in phone_contacts):
        st.warning(f"**{call_count} calls** with no lunch scheduled. Consider trying email or in-person visit.")

    # Two-column layout: form on left, full history on right
    col_form, col_hist = st.columns([3, 2])

    with col_hist:
        st.markdown("**Recent Contact History**")
        if contacts:
            for c in contacts[:15]:
                dt = c.get("contact_date") or ""
                date_str = dt[:10] if dt else "?"
                time_str = dt[11:16] if len(dt) > 10 else ""
                ctype    = c.get("contact_type") or ""
                outcome  = c.get("outcome") or ""
                person   = c.get("person_contacted") or ""
                member   = c.get("team_member") or ""
                notes    = c.get("notes") or ""

                label_parts = [f"**{date_str}**"]
                if time_str:
                    label_parts.append(time_str)
                label_parts.append(f"— {ctype}")
                st.markdown(" ".join(label_parts))
                detail_parts = []
                if outcome:
                    detail_parts.append(f"Outcome: {outcome}")
                if person:
                    detail_parts.append(f"With: {person}")
                if member:
                    detail_parts.append(f"By: {member}")
                if detail_parts:
                    st.caption(" · ".join(detail_parts))
                if notes:
                    st.caption(f"📝 {notes}")
                st.divider()
        else:
            st.info("No previous contacts for this practice")

    with col_form:
        with st.form("modal_contact_form", clear_on_submit=True):
            _contact_options = ["Phone Call", "Email Sent", "Fax Sent", "In-Person Visit"]
            _default_type = st.session_state.get("contact_type_default")
            _default_idx = _contact_options.index(_default_type) if _default_type in _contact_options else 0
            # Clear the default so it doesn't persist to the next open
            st.session_state.contact_type_default = None

            contact_type = st.radio(
                "Contact Type",
                _contact_options,
                index=_default_idx,
                horizontal=True,
            )

            col_d, col_t = st.columns(2)
            with col_d:
                contact_date = st.date_input("Date", value=datetime.now())
            with col_t:
                contact_time = st.time_input("Time", value=datetime.now())

            is_phone = contact_type == "Phone Call"
            is_email = contact_type == "Email Sent"
            is_fax = contact_type == "Fax Sent"

            phone_sub_type = None
            if is_phone:
                st.caption(f"This will be **Call Attempt #{call_count + 1}**")
                phone_sub_type = st.selectbox(
                    "How did the call go?",
                    ["Spoke with someone", "Left Voicemail", "No Answer"],
                )

            person_contacted = st.text_input("Person Contacted")

            # Type-specific fields
            email_subject = ""
            fax_document = ""
            if is_email:
                email_subject = st.text_input("Email Subject", placeholder="e.g. Lunch scheduling request")
                email_addr = practice.get("email", "")
                if email_addr:
                    st.markdown(f'Open Outlook: <a class="contact-email" href="mailto:{email_addr}">✉️ {email_addr}</a>', unsafe_allow_html=True)

            if is_fax:
                fax_document = st.text_input("Document Sent", placeholder="e.g. Referral form, Flyer")
                fax_email = practice.get("fax_vonage_email", "")
                if fax_email:
                    st.markdown(f'Send via Outlook: <a class="contact-fax" href="mailto:{fax_email}">📠 {fax_email}</a>', unsafe_allow_html=True)

            if is_phone:
                outcome = st.selectbox("Call Outcome (when spoke with someone)", [
                    "Scheduled lunch", "Interested", "Will call back",
                    "Not interested", "Declined", "Other",
                ])
                purpose = st.selectbox("Purpose of Call", [
                    "Schedule lunch", "Confirm lunch", "Follow-up",
                    "Thank you call", "Introduction", "Other",
                ])
            elif is_email:
                outcome = st.selectbox("Outcome", [
                    "Sent", "Replied", "Bounced", "No Response", "Interested", "Other",
                ])
                purpose = st.selectbox("Purpose", [
                    "Schedule lunch", "Confirm lunch", "Follow-up",
                    "Send information", "Introduction", "Other",
                ])
            elif is_fax:
                outcome = st.selectbox("Outcome", [
                    "Sent Successfully", "Failed", "Pending", "Other",
                ])
                purpose = st.selectbox("Purpose", [
                    "Send flyer", "Send referral form", "Send information",
                    "Schedule lunch", "Other",
                ])
            else:
                outcome = st.selectbox("Outcome", [
                    "Successful", "Interested", "Follow-up Needed",
                    "Not interested", "Other",
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
                from database import add_task, _add_business_days
                contact_datetime = datetime.combine(contact_date, contact_time).isoformat()

                # Resolve effective outcome for phone calls
                if is_phone and phone_sub_type in ("Left Voicemail", "No Answer"):
                    effective_outcome = phone_sub_type
                else:
                    effective_outcome = outcome

                log_data = {
                    "practice_id": practice_id,
                    "contact_type": contact_type,
                    "contact_date": contact_datetime,
                    "contact_method": "phone" if is_phone else ("email" if is_email else ("fax" if is_fax else "in-person")),
                    "team_member": team_member,
                    "person_contacted": person_contacted,
                    "outcome": effective_outcome,
                    "purpose": purpose,
                    "notes": notes,
                }
                if is_phone:
                    log_data["call_attempt_number"] = call_count + 1
                if is_email and email_subject:
                    log_data["email_subject"] = email_subject
                if is_fax and fax_document:
                    log_data["fax_document"] = fax_document
                add_contact_log(log_data)

                # Auto-create follow-up tasks based on outcome
                _today = contact_date
                try:
                    _base = {
                        "practice_id": practice_id,
                        "assigned_to": team_member,
                        "is_complete": 0,
                        "created_at":  datetime.now().isoformat(),
                    }
                    if is_phone and phone_sub_type == "Left Voicemail":
                        add_task({**_base,
                            "task_type":   "Follow-up Call",
                            "description": f"Follow-up call to {practice['name']} (attempt #{call_count + 2})",
                            "due_date":    _add_business_days(_today, 2).isoformat(),
                        })
                    elif is_phone and phone_sub_type == "No Answer":
                        add_task({**_base,
                            "task_type":   "Follow-up Call",
                            "description": f"Follow-up call to {practice['name']} — no answer (attempt #{call_count + 2})",
                            "due_date":    _add_business_days(_today, 1).isoformat(),
                        })
                    elif is_phone and phone_sub_type == "Spoke with someone" and outcome == "Scheduled lunch":
                        add_task({**_base,
                            "task_type":   "Catering",
                            "description": f"Order catering for {practice['name']} lunch",
                            "due_date":    _add_business_days(_today, 3).isoformat(),
                        })
                        add_task({**_base,
                            "task_type":   "Confirmation Email",
                            "description": f"Send confirmation email to {practice['name']}",
                            "due_date":    _add_business_days(_today, 1).isoformat(),
                        })
                    elif effective_outcome in ("Interested", "Will call back", "Follow-up Needed"):
                        add_task({**_base,
                            "task_type":   "Follow-up",
                            "description": f"Follow up with {practice['name']} — {effective_outcome}",
                            "due_date":    _add_business_days(_today, 3).isoformat(),
                        })
                except Exception:
                    pass  # Don't block contact log on task creation failure

                attempt_label = f" (Attempt #{call_count + 1}, {phone_sub_type})" if is_phone else ""
                st.session_state.active_contact_form = None
                st.session_state.show_contact_success = f"{contact_type} logged for {practice['name']}{attempt_label}"
                st.rerun()

            if cancelled:
                st.session_state.active_contact_form = None
                st.rerun()


def render_contact_modal():
    """Check if a contact modal should be shown and render it."""
    if not db_exists():
        return
    practice_id = st.session_state.get("active_contact_form")
    if practice_id:
        from database import (get_practice, get_contact_log, add_contact_log,
                              get_call_attempt_count)
        _contact_dialog(practice_id)


@st.dialog("Schedule Lunch", width="large")
def _lunch_dialog(practice_id):
    """Centered modal popup for scheduling a lunch."""
    from database import (get_practice, get_providers_for_practice, get_lunches,
                          add_lunch, add_contact_log, get_call_attempt_count,
                          create_event, add_follow_up)
    practice = get_practice(practice_id)
    if not practice:
        st.error("Practice not found.")
        return

    providers = get_providers_for_practice(practice_id)

    st.markdown(f"### Schedule Lunch - {practice['name']}")

    # Show existing scheduled lunches
    existing = get_lunches(practice_id=practice_id, status_filter="Scheduled")
    if existing:
        st.info(f"This practice already has {len(existing)} scheduled lunch(es).")

    with st.form("modal_lunch_form", clear_on_submit=True):
        prov_options = ["All Providers / General"] + [p["name"] for p in providers]
        selected_provider = st.selectbox("Provider(s) Attending *", prov_options)

        col_d, col_t = st.columns(2)
        with col_d:
            scheduled_date = st.date_input("Date *", value=datetime.now() + timedelta(days=7))
        with col_t:
            scheduled_time = st.text_input("Time *", placeholder="11:30 AM")

        staff_count = st.number_input("Number of Attendees", min_value=1, value=5)
        restaurant = st.text_input("Restaurant / Vendor")
        dietary_notes = st.text_input("Dietary Restrictions")
        confirmed_with = st.text_input("Contact Person Confirmed With")
        lunch_notes = st.text_area("Notes", height=60)

        st.markdown("---")
        st.markdown("**Schedule next follow-up**")
        schedule_next = st.checkbox("Schedule next follow-up after completing this lunch")
        followup_type = None
        followup_interval = None
        custom_followup_date = None
        if schedule_next:
            followup_type = st.selectbox("Follow-up Type", [
                "Next Lunch (6 months)",
                "Cookie Visit (3 months)",
                "Follow-up Call",
                "Send Flyer",
                "Thank You Letter",
                "Custom Activity",
            ])
            followup_interval = st.radio("Follow-up Interval", [
                "3 months from today",
                "6 months from today",
                "Custom date",
            ], horizontal=True)
            if followup_interval == "Custom date":
                custom_followup_date = st.date_input("Select follow-up date")

        col_save, col_cancel = st.columns(2)
        with col_save:
            submitted = st.form_submit_button("Save", type="primary", use_container_width=True)
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

                # If schedule_next, create follow-up event + database record
                if schedule_next:
                    try:
                        pass  # add_follow_up already imported above
                        # Determine date
                        if followup_interval == "Custom date" and custom_followup_date:
                            next_date = custom_followup_date.isoformat()
                        elif followup_interval == "6 months from today":
                            next_date = (datetime.now() + timedelta(weeks=26)).date().isoformat()
                        else:  # 3 months
                            next_date = (datetime.now() + timedelta(weeks=13)).date().isoformat()

                        fu_type_map = {
                            "Next Lunch (6 months)": "Lunch",
                            "Cookie Visit (3 months)": "Cookie Visit",
                            "Follow-up Call": "Call",
                            "Send Flyer": "Other",
                            "Thank You Letter": "Other",
                            "Custom Activity": "Other",
                        }
                        evt_type = fu_type_map.get(followup_type, "Lunch") if followup_type else "Lunch"
                        fu_label = f"{evt_type} - {practice['name']}"

                        add_follow_up({
                            "practice_id": practice_id,
                            "follow_up_type": evt_type,
                            "follow_up_date": next_date,
                            "interval": followup_interval or "6 months from today",
                            "status": "Scheduled",
                            "notes": f"Follow-up after lunch on {scheduled_date}",
                        })
                        create_event({
                            "practice_id": practice_id,
                            "event_type": evt_type,
                            "label": fu_label,
                            "scheduled_date": next_date,
                            "status": "Scheduled",
                            "created_by": "ui",
                            "followup_interval": followup_interval,
                        })
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
                st.rerun()

        if cancelled:
            st.session_state.active_lunch_form = None
            st.rerun()


def render_lunch_modal():
    """Check if a lunch modal should be shown and render it."""
    if not db_exists():
        return
    practice_id = st.session_state.get("active_lunch_form")
    if practice_id:
        _lunch_dialog(practice_id)


@st.dialog("Send Fax", width="large")
def _fax_dialog(practice_id):
    """Modal popup for sending a fax document via Graph API."""
    import os
    from utils import load_config
    from database import validate_vonage_email, get_practice, add_contact_log

    practice = get_practice(practice_id)
    if not practice:
        st.error("Practice not found.")
        return

    config = load_config()
    graph_config = config.get("microsoft_graph", {})
    graph_ok = all([
        graph_config.get("client_id"),
        graph_config.get("client_secret"),
        graph_config.get("tenant_id"),
    ])

    fax_email = practice.get("fax_vonage_email", "")
    st.markdown(f"### Send Fax - {practice['name']}")
    st.markdown(f"**Fax email:** `{fax_email or 'Not configured'}`")

    if not fax_email:
        st.error("This practice has no Vonage fax email configured. Add a fax number first.")
        if st.button("Close"):
            st.session_state.active_fax_form = None
            st.rerun()
        return

    if not validate_vonage_email(fax_email):
        st.warning(
            f"Fax email `{fax_email}` has an invalid format. "
            "Go to **Settings > Data Management > Fix All Vonage Fax Emails** to repair."
        )

    if not graph_ok:
        st.warning("Microsoft Graph API not configured. Go to **Settings > Email (Graph API)** first.")
        if st.button("Close"):
            st.session_state.active_fax_form = None
            st.rerun()
        return

    # List available flyer / document files
    flyer_folder = config.get("flyer_folder", "")
    flyer_files = []
    if flyer_folder and os.path.exists(flyer_folder):
        for f in os.listdir(flyer_folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in (".pdf", ".png", ".jpg", ".jpeg", ".docx"):
                flyer_files.append(f)
        flyer_files.sort()

    with st.form("fax_send_form", clear_on_submit=False):
        if flyer_files:
            selected_doc = st.selectbox("Document to fax", flyer_files)
        else:
            st.error("No documents found in Flyers folder.")
            selected_doc = None

        subject = st.text_input(
            "Subject",
            value="North Houston Cancer Clinics - Referral Information",
        )
        message = st.text_area(
            "Message (optional)",
            value="Please see attached information about our cancer care services.",
            height=80,
        )

        col_send, col_cancel = st.columns(2)
        with col_send:
            submitted = st.form_submit_button(
                "Send Fax", type="primary", use_container_width=True,
                disabled=not selected_doc,
            )
        with col_cancel:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if submitted and selected_doc:
            flyer_path = os.path.join(flyer_folder, selected_doc)
            with st.spinner("Sending fax via Graph API..."):
                try:
                    from outlook_graph import OutlookGraphAPI
                    api = OutlookGraphAPI(
                        graph_config["client_id"],
                        graph_config["client_secret"],
                        graph_config["tenant_id"],
                    )
                    body_html = f"<html><body><p>{message}</p></body></html>"
                    result = api.send_email(
                        sender=graph_config.get("sender_email", config.get("send_from_email", "")),
                        recipients=[fax_email],
                        subject=subject,
                        body=body_html,
                        attachment_path=flyer_path,
                    )
                    if result["success"]:
                        st.session_state.active_fax_form = None
                        st.session_state.show_contact_success = f"Fax sent to {practice['name']} ({selected_doc})"
                        st.rerun()
                    else:
                        st.error(f"Failed to send: {result.get('error', 'Unknown error')}")
                        if result.get("error_code"):
                            st.error(f"Error code: {result['error_code']}")
                        with st.expander("Diagnostic details"):
                            st.markdown(f"**Recipient:** `{fax_email}`")
                            st.markdown(f"**Sender:** `{graph_config.get('sender_email', '')}`")
                            if result.get("error_details"):
                                st.markdown("**Error details:**")
                                st.code(result["error_details"])
                            if result.get("error_raw"):
                                st.markdown("**Full API response:**")
                                st.code(result["error_raw"])
                            if result.get("diagnostic"):
                                st.markdown("**Request diagnostic:**")
                                st.json(result["diagnostic"])
                except Exception as e:
                    st.error(f"Error: {e}")

        if cancelled:
            st.session_state.active_fax_form = None
            st.rerun()


def render_fax_modal():
    """Check if a fax modal should be shown and render it."""
    if not db_exists():
        return
    practice_id = st.session_state.get("active_fax_form")
    if practice_id:
        _fax_dialog(practice_id)


def render_delete_modal():
    """Check if a delete confirmation modal should be shown and render it."""
    if not db_exists():
        return
    practice_id = st.session_state.get("active_delete_form")
    if practice_id:
        _delete_dialog(practice_id)


# ── Referral Intelligence Helpers ─────────────────────────────────────

_STAGE_COLORS = {
    "New Referrer":    "#16a34a",
    "Active Referrer": "#0D9488",
    "Cooling Down":    "#d97706",
    "Inactive":        "#ef4444",
    "No Referrals":    "#94a3b8",
}


def _provider_stage(first_date, last_date, total, d30, d90, d180):
    if not total:
        return "No Referrals"
    if not last_date:
        return "No Referrals"
    last_d  = str(last_date)[:10]
    first_d = str(first_date)[:10] if first_date else last_d
    if first_d >= d30 and total <= 3:
        return "New Referrer"
    if last_d >= d90:
        return "Active Referrer"
    if last_d >= d180:
        return "Cooling Down"
    return "Inactive"


def _next_outreach_rec(stage, is_new_referrer, welcome_sent):
    if is_new_referrer and not welcome_sent:
        return "Send Welcome Package"
    if stage == "New Referrer":
        return "Call Office"
    if stage == "Active Referrer":
        return "Send Thank You / Schedule Lunch"
    if stage == "Cooling Down":
        return "Reconnect"
    if stage == "Inactive":
        return "Reconnect"
    return "Monitor"


def _stage_badge(stage):
    color = _STAGE_COLORS.get(stage, "#94a3b8")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:0.78em;font-weight:600;">{stage}</span>'
    )


# ── Log Referral Dialog ───────────────────────────────────────────────

@st.dialog("Log Referral", width="large")
def _log_referral_dialog(provider_id):
    from database import get_provider, get_practice, log_provider_referral, add_task, _add_business_days
    from datetime import date as _date

    prov = get_provider(provider_id)
    if not prov:
        st.error("Provider not found.")
        return

    practice_id   = prov.get("practice_id")
    practice      = get_practice(practice_id) if practice_id else None
    pname         = practice["name"] if practice else "Unknown Practice"
    is_first      = not prov.get("total_referrals") or prov["total_referrals"] == 0

    st.markdown(f"**Provider:** {prov['name']}  \n**Practice:** {pname}")
    if is_first:
        st.success("This appears to be a first referral — welcome package workflow will trigger automatically.")

    today = _date.today()
    referral_date = st.date_input("Referral Date", value=today)
    patient_initials = st.text_input("Patient Initials (optional)", placeholder="e.g. J.D.")
    notes = st.text_input("Notes", placeholder="Optional details")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Referral", type="primary", use_container_width=True):
            user_dict = st.session_state.get("user", {})
            username  = user_dict.get("username", "")

            log_provider_referral({
                "provider_id":       provider_id,
                "practice_id":       practice_id or 0,
                "referral_date":     referral_date.isoformat(),
                "patient_initials":  patient_initials.strip(),
                "notes":             notes.strip(),
                "logged_by":         username,
            })

            # First-referral automation
            if is_first and practice_id:
                try:
                    add_task({
                        "practice_id": practice_id,
                        "task_type":   "Send Welcome Package",
                        "description": f"Send welcome package to {prov['name']} at {pname}",
                        "due_date":    _add_business_days(today, 1).isoformat(),
                        "assigned_to": username,
                        "is_complete": 0,
                        "notes":       "Auto-created: first referral from this provider",
                        "created_at":  datetime.now().isoformat(),
                    })
                    add_task({
                        "practice_id": practice_id,
                        "task_type":   "Call Office Introduction",
                        "description": f"Call office re: new referrer {prov['name']}",
                        "due_date":    _add_business_days(today, 2).isoformat(),
                        "assigned_to": username,
                        "is_complete": 0,
                        "notes":       "Auto-created: first referral from this provider",
                        "created_at":  datetime.now().isoformat(),
                    })
                    add_task({
                        "practice_id": practice_id,
                        "task_type":   "Schedule Lunch",
                        "description": f"Schedule lunch to welcome new referrer {prov['name']} at {pname}",
                        "due_date":    _add_business_days(today, 14).isoformat(),
                        "assigned_to": username,
                        "is_complete": 0,
                        "notes":       "Auto-created: first referral from this provider",
                        "created_at":  datetime.now().isoformat(),
                    })
                except Exception:
                    pass

            st.session_state.prov_log_referral_id = None
            st.success("Referral logged!")
            st.rerun()
    with col2:
        if st.button("Cancel", use_container_width=True):
            st.session_state.prov_log_referral_id = None
            st.rerun()


# ── Provider Detail Dialog ────────────────────────────────────────────

@st.dialog("Provider Detail", width="large")
def _provider_detail_dialog(provider_id):
    from database import (
        get_provider, get_practice, get_provider_referrals,
        get_provider_referral_stats, get_last_contact,
        get_outreach_record, update_provider,
    )
    from datetime import date as _date, timedelta as _td

    prov = get_provider(provider_id)
    if not prov:
        st.error("Provider not found.")
        return

    practice_id   = prov.get("practice_id")
    practice      = get_practice(practice_id) if practice_id else None
    pname         = practice["name"] if practice else "—"
    today         = _date.today()
    d30           = (today - _td(days=30)).isoformat()
    d90           = (today - _td(days=90)).isoformat()
    d180          = (today - _td(days=180)).isoformat()

    stats         = get_provider_referral_stats(provider_id)
    stage         = _provider_stage(
        prov.get("first_referral_date"), prov.get("last_referral_date"),
        stats["total"] or prov.get("total_referrals") or 0, d30, d90, d180,
    )
    is_new        = bool(prov.get("is_new_referrer"))
    welcome_sent  = bool(prov.get("welcome_package_sent"))
    last_contact  = get_last_contact(practice_id) if practice_id else None
    outreach_rec  = get_outreach_record(practice_id) if practice_id else None

    # Header
    st.markdown(
        f"### {prov['name']}\n"
        f"**Practice:** {pname}  |  **Status:** {prov.get('status','Active')}"
    )
    if prov.get("specialty"):
        st.caption(f"Specialty: {prov['specialty']}")
    st.markdown(
        _stage_badge(stage) +
        (" &nbsp;" + '<span style="background:#dc2626;color:#fff;padding:2px 8px;border-radius:4px;font-size:0.78em;font-weight:600;">NEW REFERRER</span>' if is_new else ""),
        unsafe_allow_html=True,
    )
    st.markdown("---")

    # Referral intelligence
    col_ref, col_out = st.columns(2)
    with col_ref:
        st.markdown("**Referral Intelligence**")
        st.caption(f"First Referral: {(prov.get('first_referral_date') or 'None')[:10]}")
        st.caption(f"Last Referral:  {(prov.get('last_referral_date')  or 'None')[:10]}")
        st.caption(f"Total Referrals: {stats['total']}")
        st.caption(f"Last 30 days: {stats['last_30']}  |  Last 90 days: {stats['last_90']}")
        trend_label = ("Up ↑" if stats["last_90"] > stats["prior_90"]
                       else "Down ↓" if stats["last_90"] < stats["prior_90"] else "Stable →")
        st.caption(f"Trend: {trend_label}")

    with col_out:
        st.markdown("**Outreach Connection**")
        lc_date = (last_contact.get("contact_date") or "None")[:10] if last_contact else "None"
        st.caption(f"Last Office Contact: {lc_date}")
        if outreach_rec:
            st.caption(f"Lunch Status: {outreach_rec.get('lunch_status') or 'Not Started'}")
            st.caption(f"Cookie Status: {outreach_rec.get('cookie_status') or 'Not Started'}")
        next_rec = _next_outreach_rec(stage, is_new, welcome_sent)
        st.markdown(f"**Next Recommended:** {next_rec}")

    # Welcome package checklist
    st.markdown("---")
    st.markdown("**Welcome Package Checklist**")
    wc1, wc2 = st.columns(2)
    with wc1:
        new_wp    = st.checkbox("Welcome Package Sent", value=welcome_sent, key=f"wp_{provider_id}")
        new_ty    = st.checkbox("Thank You Letter Sent",value=bool(prov.get("thank_you_sent")), key=f"ty_{provider_id}")
    with wc2:
        new_if    = st.checkbox("Intro Folder Sent",    value=bool(prov.get("intro_folder_sent")), key=f"if_{provider_id}")
        new_bc    = st.checkbox("Business Card Sent",   value=bool(prov.get("business_card_sent")), key=f"bc_{provider_id}")

    wp_date = None
    if new_wp and not welcome_sent:
        wp_date = st.date_input("Welcome Package Date", value=today, key=f"wpd_{provider_id}")

    # Specialist / new referrer flag
    st.markdown("---")
    new_is_new = st.checkbox("Mark as New Referrer (manual override)", value=is_new, key=f"nr_{provider_id}")
    new_specialty = st.text_input("Specialty (provider-level)", value=prov.get("specialty") or "", key=f"spec_{provider_id}")

    sc1, sc2 = st.columns(2)
    with sc1:
        if st.button("Save Changes", type="primary", use_container_width=True, key=f"det_save_{provider_id}"):
            update_data = {
                "welcome_package_sent":  1 if new_wp else 0,
                "thank_you_sent":        1 if new_ty else 0,
                "intro_folder_sent":     1 if new_if else 0,
                "business_card_sent":    1 if new_bc else 0,
                "is_new_referrer":       1 if new_is_new else 0,
                "specialty":             new_specialty.strip(),
            }
            if new_wp and not welcome_sent and wp_date:
                update_data["welcome_package_sent_date"] = wp_date.isoformat()
            update_provider(provider_id, update_data)
            st.session_state.prov_detail_id = None
            st.success("Provider updated!")
            st.rerun()
    with sc2:
        if st.button("Close", use_container_width=True, key=f"det_close_{provider_id}"):
            st.session_state.prov_detail_id = None
            st.rerun()

    # Recent referral history
    refs = get_provider_referrals(provider_id, limit=15)
    if refs:
        st.markdown("---")
        st.markdown("**Recent Referral Activity**")
        for ref in refs:
            ref_date = str(ref.get("referral_date", ""))[:10]
            initials = ref.get("patient_initials") or "—"
            note     = ref.get("notes") or ""
            by       = ref.get("logged_by") or ""
            st.caption(f"📅 {ref_date}  |  Patient: {initials}  |  {note}  |  By: {by}")


# ── Main page ─────────────────────────────────────────────────────────

def show_providers():
    st.markdown("## Provider & Practice Management")

    # Red styling for the 7th-column delete buttons
    st.markdown("""<style>
[data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(7) button {
    background-color: #dc3545 !important;
    border-color: #b02a37 !important;
    color: white !important;
}
[data-testid="stHorizontalBlock"] [data-testid="column"]:nth-child(7) button:hover {
    background-color: #bb2d3b !important;
    border-color: #b02a37 !important;
}
</style>""", unsafe_allow_html=True)

    st.session_state.setdefault("active_delete_form", None)

    if not db_exists():
        st.text_input("Search practices", placeholder="Name, address, phone...", disabled=True)
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        return

    # Lazy imports — only when database exists
    from database import (
        get_all_practices, get_practice, add_practice, update_practice,
        search_practices, get_providers_for_practice, add_provider,
        update_provider, move_provider, get_all_providers, get_provider,
        delete_provider,
        get_contact_log, add_contact_log, get_lunches, add_lunch, update_lunch,
        add_call_attempt, get_call_attempts, get_cookie_visits, add_cookie_visit,
        get_thank_yous, add_thank_you, update_thank_you,
        get_call_attempt_count, get_last_contact, get_tasks,
    )
    from database import create_event, update_event
    from utils import (
        relationship_score, score_color, score_label, categorize_location,
        days_since, format_phone_link, format_email_link, format_fax_link,
    )
    from data_import import fax_to_vonage_email

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

    tab_practices, tab_providers, tab_add = st.tabs(["Practices", "Referral Intelligence", "Add New"])

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

        _STAGE_EMOJI = {
            "New Lead": "🔵", "Referring": "🟢", "Routine Referring": "⭐",
            "Inactive": "🔴", "Dropped": "⚫",
        }

        for practice in practices:
            score = relationship_score(practice["id"])
            color = score_color(score)
            providers = get_providers_for_practice(practice["id"])
            p_stage = practice.get("pipeline_stage") or "New Lead"
            s_emoji = _STAGE_EMOJI.get(p_stage, "🔵")
            total_refs = practice.get("total_referrals") or 0
            ref_str = f" | {total_refs} refs" if total_refs else ""

            with st.expander(
                f"{'🟢' if score >= 70 else '🟡' if score >= 40 else '🔴'} {practice['name']} — "
                f"{practice.get('location_category', 'Other')} | {len(providers)} providers | "
                f"{s_emoji} {p_stage}{ref_str}"
            ):
                # Practice detail view
                detail_col1, detail_col2 = st.columns(2)

                with detail_col1:
                    st.markdown(f"**Address:** {practice.get('address', 'N/A')}")
                    phone_html = format_phone_link(practice.get('phone', ''))
                    st.markdown(f"**Phone:** {phone_html}", unsafe_allow_html=True)
                    fax_html = format_fax_link(practice.get('fax', ''))
                    st.markdown(f"**Fax:** {fax_html}", unsafe_allow_html=True)
                    if practice.get("email"):
                        email_html = format_email_link(practice['email'])
                        st.markdown(f"**Email:** {email_html}", unsafe_allow_html=True)
                    if practice.get("fax_vonage_email"):
                        vonage_html = format_email_link(practice['fax_vonage_email'])
                        st.markdown(f"**Vonage Fax:** {vonage_html}", unsafe_allow_html=True)
                    st.markdown(f"**Relationship Score:** :{color[1:]}: {score}/100 ({score_label(score)})")

                with detail_col2:
                    st.markdown(f"**Status:** {practice.get('status', 'Active')}")
                    st.markdown(f"**Contact Person:** {practice.get('contact_person', 'N/A')}")
                    if practice.get("specialty"):
                        st.markdown(f"**Specialty:** {practice['specialty']}")
                    if practice.get("website"):
                        website_url = practice["website"]
                        if not website_url.startswith(("http://", "https://")):
                            website_url = "https://" + website_url
                        st.markdown(f'**Website:** <a class="contact-website" href="{website_url}" target="_blank">{practice["website"]}</a>', unsafe_allow_html=True)
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
                            if call_count >= 3:
                                st.warning(f"**Needs Attention:** {call_count} calls with no lunch scheduled")
                            else:
                                st.caption(f"**Pending:** Schedule lunch ({call_count} call{'s' if call_count != 1 else ''} made)")
                else:
                    st.caption("**Last Contact:** None — no contact logged yet")

                # Pending tasks
                pending_tasks = get_tasks(practice_id=practice["id"], is_complete=False)
                if pending_tasks:
                    today_iso = datetime.now().date().isoformat()
                    task_lines = []
                    for t in pending_tasks[:4]:
                        due = (t.get("due_date") or "")[:10]
                        overdue = due and due < today_iso
                        prefix = "🔴 " if overdue else ""
                        task_lines.append(f"{prefix}{t.get('task_type', '')}: due {due or 'TBD'}")
                    st.caption(f"**Open Tasks ({len(pending_tasks)}):** " + " | ".join(task_lines))

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
                btn_col1, btn_col2, btn_col3, btn_col4, btn_col5, btn_col6, btn_col7, btn_col8 = st.columns(8)

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
                    # Email button — always enabled, opens Log Contact with Email pre-selected
                    st.button(
                        "✉️ Email",
                        key=f"email_{practice['id']}",
                        on_click=_cb_open_contact_email,
                        args=(practice["id"],),
                    )

                with btn_col4:
                    # Fax button — always enabled, opens fax-send dialog via Graph API
                    st.button(
                        "📠 Fax",
                        key=f"fax_{practice['id']}",
                        on_click=_cb_open_fax,
                        args=(practice["id"],),
                    )

                with btn_col5:
                    st.button(
                        "🍽️ Schedule Lunch",
                        key=f"lunch_{practice['id']}",
                        on_click=_cb_open_lunch,
                        args=(practice["id"],),
                    )

                with btn_col6:
                    new_status = "Inactive" if practice["status"] == "Active" else "Active"
                    if st.button(f"{'🔴 Archive' if practice['status'] == 'Active' else '🟢 Reactivate'}", key=f"archive_{practice['id']}"):
                        update_practice(practice["id"], {"status": new_status})
                        st.success(f"Practice set to {new_status}")
                        st.rerun()

                with btn_col7:
                    st.button(
                        "🗑️ Delete",
                        key=f"delete_{practice['id']}",
                        on_click=_cb_open_delete,
                        args=(practice["id"],),
                        help="Permanently delete this practice and all its records",
                    )

                with btn_col8:
                    if st.button("🔗 Log Ref", key=f"log_ref_{practice['id']}", help="Log weekly referral count"):
                        st.session_state["ref_log_practice_id"]   = practice["id"]
                        st.session_state["ref_log_practice_name"] = practice["name"]
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

    # Log Referral dialog — triggered from any practice card button
    if st.session_state.get("ref_log_practice_id"):
        try:
            from pages.referrals import _log_referral_dialog
            _log_referral_dialog(
                st.session_state["ref_log_practice_id"],
                st.session_state.get("ref_log_practice_name", ""),
            )
        except Exception:
            pass

    # ── Referral Intelligence Tab ─────────────────────────────────────
    with tab_providers:
        from database import (
            get_provider_referral_stats, get_provider_referrals,
            get_all_outreach_records,
        )

        st.session_state.setdefault("prov_log_referral_id", None)
        st.session_state.setdefault("prov_detail_id",       None)

        all_providers = get_all_providers()
        outreach_map  = get_all_outreach_records()

        today    = datetime.now().date()
        d30_str  = (today - timedelta(days=30)).isoformat()
        d90_str  = (today - timedelta(days=90)).isoformat()
        d180_str = (today - timedelta(days=180)).isoformat()

        # Quick filter bar
        quick_filter = st.radio(
            "Quick View",
            ["All Providers", "New Referrers", "Active Referrers",
             "Cooling Down", "Inactive", "Needs Attention"],
            horizontal=True,
            key="prov_quick_filter",
            label_visibility="collapsed",
        )

        # Detailed filters
        with st.expander("Filters", expanded=False):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                filter_name     = st.text_input("Provider Name",  key="pf_name").strip().lower()
                filter_practice = st.text_input("Practice",       key="pf_practice").strip().lower()
            with fc2:
                filter_specialty = st.text_input("Specialty",     key="pf_specialty").strip().lower()
                filter_status    = st.selectbox("Status", ["All", "Active", "Inactive"], key="pf_status")
            with fc3:
                filter_new_only  = st.checkbox("New Referrers Only", key="pf_new")
                filter_trend     = st.selectbox("Trend", ["Any", "Up", "Stable", "Down"], key="pf_trend")
                filter_attention = st.checkbox("Needs Attention Only", key="pf_attention")

        # Build enriched rows
        enriched = []
        for prov in all_providers:
            pid    = prov["id"]
            stats  = get_provider_referral_stats(pid)
            total  = stats["total"] or prov.get("total_referrals") or 0
            last_30  = stats["last_30"]
            last_90  = stats["last_90"]
            prior_90 = stats["prior_90"]

            first_date = prov.get("first_referral_date") or ""
            last_date  = prov.get("last_referral_date")  or ""

            stage         = _provider_stage(first_date, last_date, total, d30_str, d90_str, d180_str)
            is_new_ref    = bool(prov.get("is_new_referrer"))
            welcome_sent  = bool(prov.get("welcome_package_sent"))
            needs_attn    = (last_90 < prior_90 and total > 0) or stage in ("Cooling Down", "Inactive")
            outreach_rec  = _next_outreach_rec(stage, is_new_ref, welcome_sent)
            practice_rec  = outreach_map.get(prov.get("practice_id"), {})

            if last_90 > prior_90:
                trend, trend_icon = "Up", "↑"
            elif last_90 < prior_90:
                trend, trend_icon = "Down", "↓"
            else:
                trend, trend_icon = "Stable", "→"

            last_contact    = get_last_contact(prov.get("practice_id"))
            last_contact_dt = (last_contact.get("contact_date") or "")[:10] if last_contact else ""

            enriched.append({
                "prov": prov, "total": total,
                "last_30": last_30, "last_90": last_90, "prior_90": prior_90,
                "first_date": first_date, "last_date": last_date,
                "stage": stage, "trend": trend, "trend_icon": trend_icon,
                "is_new_ref": is_new_ref, "needs_attn": needs_attn,
                "last_contact_dt": last_contact_dt,
                "outreach_rec": outreach_rec, "practice_rec": practice_rec,
            })

        # Filter
        _qf_stage_map = {
            "New Referrers":    "New Referrer",
            "Active Referrers": "Active Referrer",
            "Cooling Down":     "Cooling Down",
            "Inactive":         "Inactive",
        }
        filtered = []
        for r in enriched:
            prov = r["prov"]
            if quick_filter in _qf_stage_map and r["stage"] != _qf_stage_map[quick_filter]:
                continue
            if quick_filter == "Needs Attention" and not r["needs_attn"]:
                continue
            if filter_name     and filter_name     not in prov["name"].lower():
                continue
            if filter_practice and filter_practice not in (prov.get("practice_name") or "").lower():
                continue
            if filter_specialty and filter_specialty not in (prov.get("specialty") or "").lower():
                continue
            if filter_status != "All" and prov.get("status") != filter_status:
                continue
            if filter_new_only and not r["is_new_ref"]:
                continue
            if filter_trend != "Any" and r["trend"] != filter_trend:
                continue
            if filter_attention and not r["needs_attn"]:
                continue
            filtered.append(r)

        filtered.sort(key=lambda r: (
            not r["is_new_ref"],
            not r["needs_attn"],
            -r["total"],
            r["prov"]["name"],
        ))

        # Summary metrics
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Providers",     len(filtered))
        m2.metric("New Referrers", sum(1 for r in filtered if r["is_new_ref"]))
        m3.metric("Active",        sum(1 for r in filtered if r["stage"] == "Active Referrer"))
        m4.metric("Cooling Down",  sum(1 for r in filtered if r["stage"] == "Cooling Down"))
        m5.metric("Inactive",      sum(1 for r in filtered if r["stage"] == "Inactive"))

        st.markdown("---")

        if not filtered:
            st.info("No providers match the current filters.")
        else:
            for r in filtered:
                prov  = r["prov"]
                pid   = prov["id"]
                stage = r["stage"]
                stage_color = _STAGE_COLORS.get(stage, "#94a3b8")

                alert_prefix = "🔔 " if r["is_new_ref"] else ("⚠️ " if r["needs_attn"] else "")
                trend_display = f"{r['trend_icon']} {r['trend']}"
                header = (
                    f"{alert_prefix}{prov['name']}  —  "
                    f"{prov.get('practice_name', '?')}  |  "
                    f"{stage}  |  "
                    f"Total: {r['total']}  |  "
                    f"30d: {r['last_30']}  |  "
                    f"Trend: {trend_display}"
                )

                with st.expander(header, expanded=r["is_new_ref"]):
                    # Top metrics row
                    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
                    mc1.metric("Total",   r["total"])
                    mc2.metric("30 Days", r["last_30"])
                    mc3.metric("90 Days", r["last_90"])
                    mc4.metric("Trend",   trend_display)
                    mc5.markdown(
                        f'<span style="background:{stage_color};color:#fff;padding:3px 8px;'
                        f'border-radius:4px;font-size:0.8em;font-weight:600;">{stage}</span>',
                        unsafe_allow_html=True,
                    )
                    if r["is_new_ref"]:
                        mc6.markdown(
                            '<span style="background:#dc2626;color:#fff;padding:3px 8px;'
                            'border-radius:4px;font-size:0.8em;font-weight:600;">NEW REFERRER</span>',
                            unsafe_allow_html=True,
                        )
                    elif r["needs_attn"]:
                        mc6.warning("Needs Attention")

                    # Info columns
                    info_l, info_r = st.columns(2)
                    with info_l:
                        spec = prov.get("specialty") or ""
                        st.caption(f"Practice: {prov.get('practice_name', '?')}" + (f"  |  {spec}" if spec else ""))
                        st.caption(f"Status: {prov.get('status', 'Active')}")
                        st.caption(f"First Referral: {(r['first_date'] or 'None')[:10]}")
                        st.caption(f"Last Referral:  {(r['last_date']  or 'None')[:10]}")
                        st.caption(f"Last Contact (Office): {r['last_contact_dt'] or 'None'}")
                    with info_r:
                        st.markdown(f"**Next Recommended:** {r['outreach_rec']}")
                        pr = r["practice_rec"]
                        if pr:
                            st.caption(f"Practice Lunch: {pr.get('lunch_status') or 'Not Started'}")
                            st.caption(f"Practice Cookies: {pr.get('cookie_status') or 'Not Started'}")
                        if prov.get("welcome_package_sent") or r["is_new_ref"]:
                            st.caption(
                                f"{'✅' if prov.get('welcome_package_sent') else '⬜'} Welcome Package  "
                                f"{'✅' if prov.get('thank_you_sent') else '⬜'} Thank You  "
                                f"{'✅' if prov.get('intro_folder_sent') else '⬜'} Intro Folder  "
                                f"{'✅' if prov.get('business_card_sent') else '⬜'} Business Card"
                            )

                    # Action buttons
                    st.markdown("---")
                    a1, a2, a3, a4, a5 = st.columns(5)
                    with a1:
                        if st.button("Log Referral", key=f"lr_{pid}", type="primary", use_container_width=True):
                            st.session_state.prov_log_referral_id = pid
                            st.rerun()
                    with a2:
                        st.button(
                            "Log Contact",
                            key=f"prov_lc_{pid}",
                            use_container_width=True,
                            on_click=_cb_open_contact,
                            args=(prov.get("practice_id"),),
                        )
                    with a3:
                        if st.button("Provider Details", key=f"pd_{pid}", use_container_width=True):
                            st.session_state.prov_detail_id = pid
                            st.rerun()
                    with a4:
                        if st.button("Outreach Page", key=f"op_{pid}", use_container_width=True):
                            st.session_state._nav_override = "🤝 Outreach"
                            st.rerun()
                    with a5:
                        toggle_lbl = "Deactivate" if prov.get("status") == "Active" else "Activate"
                        if st.button(toggle_lbl, key=f"tog_{pid}", use_container_width=True):
                            new_s = "Inactive" if prov.get("status") == "Active" else "Active"
                            update_provider(pid, {"status": new_s})
                            st.rerun()

                    # Recent referral history (collapsed)
                    if r["total"] > 0:
                        with st.expander("Recent Referral Activity", expanded=False):
                            refs = get_provider_referrals(pid, limit=10)
                            for ref in refs:
                                st.caption(
                                    f"📅 {str(ref.get('referral_date',''))[:10]}  |  "
                                    f"Patient: {ref.get('patient_initials') or '—'}  |  "
                                    f"{ref.get('notes') or ''}  |  "
                                    f"By: {ref.get('logged_by') or ''}"
                                )

                    st.divider()

        # Dialogs
        if st.session_state.get("prov_log_referral_id"):
            _log_referral_dialog(st.session_state.prov_log_referral_id)
        if st.session_state.get("prov_detail_id"):
            _provider_detail_dialog(st.session_state.prov_detail_id)

        # Move provider (preserved, collapsed)
        st.markdown("---")
        with st.expander("Move Provider to New Practice", expanded=False):
            prov_options = {
                f"{p['name']} ({p.get('practice_name', 'N/A')})": p["id"]
                for p in all_providers
            }
            selected_prov  = st.selectbox("Select Provider", list(prov_options.keys()), key="mv_prov_sel")
            all_prac_list  = get_all_practices()
            practice_opts  = {p["name"]: p["id"] for p in all_prac_list}
            new_prac_sel   = st.selectbox("Move to Practice", list(practice_opts.keys()), key="mv_prac_sel")
            mv_notes       = st.text_input("Move notes", key="mv_notes")
            if st.button("Move Provider", key="mv_prov_btn"):
                if selected_prov and new_prac_sel:
                    move_provider(prov_options[selected_prov], practice_opts[new_prac_sel], mv_notes)
                    st.success(f"Provider moved to {new_prac_sel}")
                    st.rerun()

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
            specialty_choice = st.selectbox("Specialty", _SPECIALTIES)
            specialty_other = st.text_input("Specify Specialty (if Other)")
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

                    specialty = specialty_other.strip() if specialty_choice == "Other" else specialty_choice
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
                        "specialty": specialty,
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
    from database import update_practice
    from utils import categorize_location
    from data_import import fax_to_vonage_email
    with st.form(f"edit_form_{practice['id']}"):
        st.markdown("#### Edit Practice")
        name = st.text_input("Name", value=practice.get("name", ""))
        address = st.text_input("Address", value=practice.get("address", ""))
        phone = st.text_input("Phone", value=practice.get("phone", ""))
        fax = st.text_input("Fax", value=practice.get("fax", ""))
        contact_person = st.text_input("Contact Person", value=practice.get("contact_person", ""))
        email = st.text_input("Email", value=practice.get("email", ""))
        website = st.text_input("Website", value=practice.get("website", ""))
        current_specialty = practice.get("specialty", "") or ""
        spec_index = _SPECIALTIES.index(current_specialty) if current_specialty in _SPECIALTIES else 0
        specialty_choice = st.selectbox("Specialty", _SPECIALTIES, index=spec_index)
        specialty_other = st.text_input("Specify Specialty (if Other)", value=current_specialty if current_specialty not in _SPECIALTIES else "")
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

                specialty = specialty_other.strip() if specialty_choice == "Other" else specialty_choice
                update_practice(practice["id"], {
                    "name": name, "address": address, "phone": phone, "fax": fax,
                    "fax_vonage_email": vonage_email, "contact_person": contact_person,
                    "email": email, "website": website, "specialty": specialty, "notes": notes,
                    "zip_code": zip_code, "location_category": categorize_location(address),
                })
                st.session_state[f"editing_{practice['id']}"] = False
                st.success("Practice updated!")
                st.rerun()
        with col2:
            if st.form_submit_button("Cancel"):
                st.session_state[f"editing_{practice['id']}"] = False
                st.rerun()
