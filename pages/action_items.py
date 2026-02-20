"""Action items page: overdue items, contact queue, thank you checklist, upcoming tasks."""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils import db_exists


def show_action_items():
    st.markdown("## Action Items & Follow-ups")

    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        # Show empty tab structure
        tab_overdue, tab_lunches, tab_thankyou, tab_cookies, tab_contacts = st.tabs([
            "Overdue / Upcoming", "Lunch Tracking", "Thank You Letters",
            "Cookie Visits", "Contact Queue",
        ])
        for tab in [tab_overdue, tab_lunches, tab_thankyou, tab_cookies, tab_contacts]:
            with tab:
                st.info("Import data to see action items.")
        return

    # Lazy imports — only when database exists (avoids crash when DB missing)
    from database import (
        get_all_practices, get_lunches, update_lunch, add_lunch,
        get_thank_yous, update_thank_you, add_thank_you,
        get_providers_for_practice, add_contact_log,
        add_call_attempt, get_call_attempts, add_cookie_visit,
        get_contact_log, create_event, get_call_attempt_count,
        add_follow_up,
    )
    from utils import get_overdue_items, days_since, format_phone_link, format_email_link

    tab_overdue, tab_lunches, tab_thankyou, tab_cookies, tab_contacts = st.tabs([
        "Overdue / Upcoming",
        "Lunch Tracking",
        "Thank You Letters",
        "Cookie Visits",
        "Contact Queue",
    ])

    # ── Overdue / Upcoming ─────────────────────────────────────────────
    with tab_overdue:
        items = get_overdue_items()
        if not items:
            st.success("No overdue items! Everything is on track.")
        else:
            high = [i for i in items if i["priority"] == "high"]
            med = [i for i in items if i["priority"] == "medium"]

            if high:
                st.markdown("### High Priority")
                for item in high:
                    col1, col2, col3 = st.columns([3, 2, 1])
                    col1.markdown(f"**{item['practice']}**")
                    col2.markdown(f"{item['type']}: {item['detail']}")
                    with col3:
                        if st.button("Log Contact", key=f"ov_contact_{item['practice_id']}_{item['type']}"):
                            st.session_state.active_contact_form = item['practice_id']
                            st.rerun()

            if med:
                st.markdown("### Medium Priority")
                for item in med:
                    col1, col2 = st.columns([3, 3])
                    col1.markdown(f"**{item['practice']}**")
                    col2.markdown(f"{item['type']}: {item['detail']}")

    # ── Lunch Tracking ─────────────────────────────────────────────────
    with tab_lunches:
        st.markdown("### Active Lunch Workflows")

        status_tabs = st.tabs(["Not Contacted", "Attempting", "Scheduled", "Completed"])
        status_order = ["Not Contacted", "Attempting", "Scheduled", "Completed"]

        for stab, status in zip(status_tabs, status_order):
            with stab:
                lunches = get_lunches(status_filter=status)
                if not lunches:
                    st.info(f"No lunches with status '{status}'")
                    continue

                for lunch in lunches:
                    date_display = lunch.get('scheduled_date', 'TBD')
                    if date_display and date_display != 'TBD':
                        date_display = str(date_display)[:10]
                    with st.expander(f"{lunch['practice_name']} — {status} | {date_display}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Date:** {lunch.get('scheduled_date', 'TBD')}")
                            st.markdown(f"**Time:** {lunch.get('scheduled_time', 'TBD')}")
                            st.markdown(f"**Staff Count:** {lunch.get('staff_count', 'TBD')}")
                            st.markdown(f"**Restaurant:** {lunch.get('restaurant', 'TBD')}")
                        with col2:
                            st.markdown(f"**Dietary Notes:** {lunch.get('dietary_notes', 'None')}")
                            st.markdown(f"**Confirmed With:** {lunch.get('confirmed_with', 'TBD')}")

                        # Call attempts for this lunch
                        attempts = get_call_attempts(lunch_id=lunch["id"])
                        if attempts:
                            st.markdown("**Call Attempts:**")
                            for att in attempts:
                                att_date = att.get('call_date', '')[:10] if att.get('call_date') else 'N/A'
                                st.caption(f"Call {att_date} {att.get('call_time', '')} — {att.get('outcome', '')} — {att.get('notes', '')}")

                        # Smart suggestion for practices with many failed calls
                        if status in ("Not Contacted", "Attempting"):
                            call_count = len(attempts)
                            if call_count >= 3:
                                st.warning(f"**{call_count} call attempts** with no lunch scheduled. Consider trying email or in-person visit instead.")

                        # ── Status-specific buttons ────────────────────
                        if status == "Not Contacted":
                            btn_c1, btn_c2, btn_c3 = st.columns(3)
                            with btn_c1:
                                if st.button("Log Call Attempt", key=f"call_lunch_{lunch['id']}"):
                                    st.session_state[f"call_attempt_{lunch['id']}"] = True
                            with btn_c2:
                                if st.button("Schedule Lunch", key=f"sched_direct_{lunch['id']}"):
                                    st.session_state[f"schedule_from_workflow_{lunch['id']}"] = True
                            with btn_c3:
                                if st.button("Mark Complete", key=f"comp_nc_{lunch['id']}"):
                                    update_lunch(lunch["id"], {
                                        "status": "Completed",
                                        "completed_date": datetime.now().isoformat(),
                                    })
                                    st.rerun()

                        elif status == "Attempting":
                            btn_c1, btn_c2, btn_c3 = st.columns(3)
                            with btn_c1:
                                if st.button("Log Call Attempt", key=f"call_lunch_{lunch['id']}"):
                                    st.session_state[f"call_attempt_{lunch['id']}"] = True
                            with btn_c2:
                                if st.button("Schedule Lunch", key=f"sched_att_{lunch['id']}"):
                                    st.session_state[f"schedule_from_workflow_{lunch['id']}"] = True
                            with btn_c3:
                                if st.button("Give Up", key=f"giveup_{lunch['id']}"):
                                    update_lunch(lunch["id"], {"status": "Not Contacted"})
                                    st.rerun()

                        elif status == "Scheduled":
                            btn_c1, btn_c2, btn_c3 = st.columns(3)
                            with btn_c1:
                                if st.button("Mark Completed", key=f"comp_{lunch['id']}"):
                                    st.session_state[f"complete_prompt_{lunch['id']}"] = True
                            with btn_c2:
                                if st.button("Edit Details", key=f"edit_lunch_{lunch['id']}"):
                                    st.session_state[f"edit_lunch_{lunch['id']}"] = True
                            with btn_c3:
                                if st.button("Cancel Lunch", key=f"cancel_{lunch['id']}"):
                                    update_lunch(lunch["id"], {"status": "Not Contacted"})
                                    st.rerun()

                        # ── Schedule Lunch form (from Not Contacted / Attempting) ──
                        if st.session_state.get(f"schedule_from_workflow_{lunch['id']}", False):
                            _show_schedule_lunch_form(lunch)

                        # ── Edit Scheduled Lunch ──
                        if st.session_state.get(f"edit_lunch_{lunch['id']}", False):
                            _show_edit_lunch_form(lunch)

                        # ── Completion dialog ──
                        if st.session_state.get(f"complete_prompt_{lunch['id']}", False):
                            _show_complete_lunch_dialog(lunch)

                        # ── Call attempt form ──
                        if st.session_state.get(f"call_attempt_{lunch['id']}", False):
                            _show_call_attempt_form(lunch)

        # Start new lunch workflow
        st.markdown("---")
        st.markdown("### Start New Lunch Workflow")
        practices = get_all_practices(status_filter="Active")
        practice_names = {p["name"]: p["id"] for p in practices}
        selected = st.selectbox("Select Practice", [""] + list(practice_names.keys()), key="new_lunch_practice")
        if selected and st.button("Start Lunch Workflow"):
            add_lunch({
                "practice_id": practice_names[selected],
                "status": "Not Contacted",
            })
            st.success(f"Lunch workflow started for {selected}")
            st.rerun()

    # ── Thank You Letters ──────────────────────────────────────────────
    with tab_thankyou:
        st.markdown("### Thank You Letter Tracking")

        ty_tab_pending, ty_tab_mailed = st.tabs(["Pending", "Mailed"])

        with ty_tab_pending:
            pending = get_thank_yous(status_filter="Pending")
            if not pending:
                st.success("No pending thank you letters!")
            else:
                st.caption(f"{len(pending)} pending thank you letters")
                for ty in pending:
                    col1, col2, col3 = st.columns([3, 2, 1])
                    col1.markdown(f"**{ty.get('provider_name', 'N/A')}** at {ty['practice_name']}")
                    col2.markdown(f"Reason: {ty['reason']} | Created: {ty.get('created_at', '')[:10]}")
                    with col3:
                        if st.button("Mailed", key=f"mail_ty_{ty['id']}"):
                            update_thank_you(ty["id"], {
                                "status": "Mailed",
                                "date_mailed": datetime.now().isoformat(),
                            })
                            st.rerun()

                if st.button("Mark All as Mailed"):
                    for ty in pending:
                        update_thank_you(ty["id"], {
                            "status": "Mailed",
                            "date_mailed": datetime.now().isoformat(),
                        })
                    st.success(f"Marked {len(pending)} letters as mailed!")
                    st.rerun()

        with ty_tab_mailed:
            mailed = get_thank_yous(status_filter="Mailed")
            if mailed:
                df = pd.DataFrame(mailed)
                display_cols = ["provider_name", "practice_name", "reason", "date_mailed"]
                available = [c for c in display_cols if c in df.columns]
                st.dataframe(df[available], use_container_width=True, hide_index=True)
            else:
                st.info("No mailed letters yet.")

        # Add manual thank you
        st.markdown("---")
        st.markdown("### Add Thank You Letter")
        practices = get_all_practices(status_filter="Active")
        practice_map = {p["name"]: p["id"] for p in practices}
        ty_practice = st.selectbox("Practice", [""] + list(practice_map.keys()), key="ty_practice")
        if ty_practice:
            providers = get_providers_for_practice(practice_map[ty_practice])
            prov_map = {p["name"]: p["id"] for p in providers}
            ty_provider = st.selectbox("Provider (optional)", ["All providers"] + list(prov_map.keys()), key="ty_provider")
            ty_reason = st.selectbox("Reason", ["New Referral", "Post-Lunch", "Other"], key="ty_reason")
            if st.button("Add Thank You"):
                if ty_provider == "All providers":
                    for prov in providers:
                        add_thank_you({
                            "provider_id": prov["id"],
                            "practice_id": practice_map[ty_practice],
                            "reason": ty_reason,
                            "status": "Pending",
                        })
                else:
                    add_thank_you({
                        "provider_id": prov_map[ty_provider],
                        "practice_id": practice_map[ty_practice],
                        "reason": ty_reason,
                        "status": "Pending",
                    })
                st.success("Thank you letter(s) added!")
                st.rerun()

    # ── Cookie Visits ──────────────────────────────────────────────────
    with tab_cookies:
        st.markdown("### Cookie Visit Check-in")

        with st.form("cookie_visit_form"):
            practices = get_all_practices(status_filter="Active")
            practice_map = {p["name"]: p["id"] for p in practices}
            cookie_practice = st.selectbox("Practice", list(practice_map.keys()))
            visit_date = st.date_input("Visit Date", value=datetime.now())
            items = st.text_input("Items Delivered", placeholder="e.g., Cookies, brownies, treats")
            delivered_by = st.selectbox("Delivered By", ["Robbie", "Darvin", "Other"])
            cookie_notes = st.text_area("Notes")
            st.markdown("---")
            st.markdown("**Schedule next follow-up**")
            schedule_next = st.checkbox("Schedule next cookie visit follow-up")
            followup_type = None
            followup_interval = None
            custom_followup_date = None
            if schedule_next:
                followup_type = st.selectbox("Follow-up Type", [
                    "Cookie Visit (3 months)",
                    "Next Lunch (6 months)",
                    "Follow-up Call",
                    "Custom Activity",
                ])
                followup_interval = st.radio("Follow-up Interval", [
                    "3 months from today",
                    "6 months from today",
                    "Custom date",
                ], horizontal=True)
                if followup_interval == "Custom date":
                    custom_followup_date = st.date_input("Select follow-up date")

            if st.form_submit_button("Log Cookie Visit", type="primary"):
                data = {
                    "practice_id": practice_map[cookie_practice],
                    "visit_date": visit_date.isoformat(),
                    "items_delivered": items,
                    "delivered_by": delivered_by,
                    "notes": cookie_notes,
                    "status": "Completed",
                }
                if schedule_next and followup_interval == "Custom date" and custom_followup_date:
                    data["next_visit_date"] = custom_followup_date.isoformat()
                vid = add_cookie_visit(data)
                # Add to events table so visit shows on calendar with a clickable ID
                try:
                    create_event({
                        "practice_id": practice_map[cookie_practice],
                        "event_type": "Cookie Visit",
                        "label": f"Cookies - {cookie_practice}",
                        "scheduled_date": visit_date.isoformat(),
                        "status": "Completed",
                        "created_by": "ui",
                    })
                except Exception:
                    pass
                add_contact_log({
                    "practice_id": practice_map[cookie_practice],
                    "contact_type": "Cookie Visit",
                    "contact_date": visit_date.isoformat(),
                    "team_member": delivered_by,
                    "outcome": "Delivered",
                    "notes": f"Items: {items}",
                })
                if schedule_next:
                    try:
                        if followup_interval == "Custom date" and custom_followup_date:
                            next_date = custom_followup_date.isoformat()
                        elif followup_interval == "6 months from today":
                            next_date = (datetime.now() + timedelta(weeks=26)).date().isoformat()
                        else:
                            next_date = (datetime.now() + timedelta(weeks=13)).date().isoformat()

                        fu_map = {
                            "Cookie Visit (3 months)": "Cookie Visit",
                            "Next Lunch (6 months)": "Lunch",
                            "Follow-up Call": "Call",
                            "Custom Activity": "Other",
                        }
                        evt_type = fu_map.get(followup_type, "Cookie Visit") if followup_type else "Cookie Visit"

                        add_follow_up({
                            "practice_id": practice_map[cookie_practice],
                            "follow_up_type": evt_type,
                            "follow_up_date": next_date,
                            "interval": followup_interval,
                            "status": "Scheduled",
                            "notes": f"Follow-up after cookie visit on {visit_date}",
                        })
                        create_event({
                            "practice_id": practice_map[cookie_practice],
                            "event_type": evt_type,
                            "label": f"{evt_type} - {cookie_practice}",
                            "scheduled_date": next_date,
                            "status": "Scheduled",
                            "created_by": "ui",
                        })
                    except Exception:
                        pass

                st.success("Cookie visit logged!")
                st.rerun()

        # Recent cookie visits
        from database import get_cookie_visits
        recent = get_cookie_visits()
        if recent:
            st.markdown("### Recent Cookie Visits")
            df = pd.DataFrame(recent[:20])
            display_cols = ["practice_name", "visit_date", "items_delivered", "delivered_by"]
            available = [c for c in display_cols if c in df.columns]
            st.dataframe(df[available], use_container_width=True, hide_index=True)

    # ── Contact Queue ──────────────────────────────────────────────────
    with tab_contacts:
        st.markdown("### Contact Queue")
        st.markdown("Practices that need follow-up (phone, email, or fax):")

        practices = get_all_practices(status_filter="Active")
        contact_queue = []
        for p in practices:
            contacts = get_contact_log(practice_id=p["id"], limit=1)
            last_days = None
            if contacts:
                last_days = days_since(contacts[0].get("contact_date"))
            call_count = get_call_attempt_count(p["id"])

            entry = {
                "practice": p["name"],
                "practice_id": p["id"],
                "last_contact_days": last_days if last_days else 999,
                "phone": p.get("phone", ""),
                "email": p.get("email", ""),
                "fax_vonage_email": p.get("fax_vonage_email", ""),
                "contact_person": p.get("contact_person", ""),
                "call_attempts": call_count,
            }
            contact_queue.append(entry)

        contact_queue.sort(key=lambda x: x["last_contact_days"], reverse=True)

        for item in contact_queue[:30]:
            days_text = f"{item['last_contact_days']} days ago" if item["last_contact_days"] < 999 else "Never contacted"

            # Smart suggestion
            suggestion = ""
            if item["call_attempts"] >= 3:
                suggestion = " — Try email or fax instead"

            col1, col2, col3 = st.columns([3, 3, 2])
            with col1:
                st.markdown(f"**{item['practice']}**")
                st.caption(f"Last: {days_text}{suggestion}")
            with col2:
                phone_html = format_phone_link(item["phone"]) if item["phone"] else "No phone"
                email_html = format_email_link(item["email"]) if item["email"] else "No email"
                st.markdown(f"{phone_html} &nbsp; {email_html}", unsafe_allow_html=True)
            with col3:
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("Log Contact", key=f"cq_{item['practice_id']}"):
                        st.session_state.active_contact_form = item['practice_id']
                        st.rerun()
                with bc2:
                    if st.button("Schedule", key=f"cq_sched_{item['practice_id']}"):
                        st.session_state.active_lunch_form = item['practice_id']
                        st.rerun()


# ── Helper forms ──────────────────────────────────────────────────────

def _show_schedule_lunch_form(lunch):
    """Show inline lunch scheduling form within the workflow."""
    from database import update_lunch, get_call_attempts, create_event
    with st.form(f"sched_form_{lunch['id']}"):
        st.markdown(f"#### Schedule Lunch — {lunch.get('practice_name')}")
        col_d, col_t = st.columns(2)
        with col_d:
            sched_date = st.date_input("Date *", value=datetime.now() + timedelta(days=7), key=f"sd_{lunch['id']}")
        with col_t:
            sched_time = st.text_input("Time *", placeholder="11:30 AM", key=f"st_{lunch['id']}")
        staff_count = st.number_input("Attendees", min_value=1, value=5, key=f"sc_{lunch['id']}")
        restaurant = st.text_input("Restaurant / Vendor", key=f"rest_{lunch['id']}")
        dietary_notes = st.text_input("Dietary Restrictions", key=f"diet_{lunch['id']}")
        confirmed_with = st.text_input("Confirmed With", key=f"conf_{lunch['id']}")
        notes = st.text_area("Notes", height=60, key=f"notes_{lunch['id']}")

        col_s, col_c = st.columns(2)
        with col_s:
            submitted = st.form_submit_button("Schedule Lunch", type="primary", use_container_width=True)
        with col_c:
            cancelled = st.form_submit_button("Cancel", use_container_width=True)

        if submitted:
            if not (sched_time or "").strip():
                st.error("Time is required")
            else:
                attempts = get_call_attempts(lunch_id=lunch["id"])
                update_lunch(lunch["id"], {
                    "status": "Scheduled",
                    "scheduled_date": sched_date.isoformat(),
                    "scheduled_time": sched_time,
                    "staff_count": staff_count,
                    "restaurant": restaurant,
                    "dietary_notes": dietary_notes,
                    "confirmed_with": confirmed_with,
                    "visit_notes": notes,
                })
                # Create calendar event
                try:
                    create_event({
                        "practice_id": lunch["practice_id"],
                        "event_type": "Lunch",
                        "label": f"Lunch - {lunch.get('practice_name', '')}",
                        "scheduled_date": sched_date.isoformat(),
                        "scheduled_time": sched_time,
                        "status": "Scheduled",
                        "notes": notes,
                        "created_by": "ui",
                    })
                except Exception:
                    pass
                attempt_msg = f" after {len(attempts)} call attempt(s)" if attempts else ""
                st.success(f"Lunch scheduled for {lunch.get('practice_name')}{attempt_msg}!")
                st.session_state[f"schedule_from_workflow_{lunch['id']}"] = False
                st.rerun()

        if cancelled:
            st.session_state[f"schedule_from_workflow_{lunch['id']}"] = False
            st.rerun()


def _show_edit_lunch_form(lunch):
    """Show inline edit form for a scheduled lunch."""
    from database import update_lunch
    with st.form(f"edit_lunch_form_{lunch['id']}"):
        st.markdown(f"#### Edit Lunch — {lunch.get('practice_name')}")
        sd = lunch.get('scheduled_date', '')
        try:
            dval = datetime.strptime(str(sd)[:10], "%Y-%m-%d") if sd else datetime.now()
        except Exception:
            dval = datetime.now()
        sched_date = st.date_input("Date", value=dval, key=f"esd_{lunch['id']}")
        sched_time = st.text_input("Time", value=lunch.get('scheduled_time', ''), key=f"est_{lunch['id']}")
        staff_count = st.number_input("Attendees", min_value=1, value=lunch.get('staff_count', 5) or 5, key=f"esc_{lunch['id']}")
        restaurant = st.text_input("Restaurant", value=lunch.get('restaurant', '') or '', key=f"erest_{lunch['id']}")
        dietary_notes = st.text_input("Dietary Restrictions", value=lunch.get('dietary_notes', '') or '', key=f"ediet_{lunch['id']}")
        confirmed_with = st.text_input("Confirmed With", value=lunch.get('confirmed_with', '') or '', key=f"econf_{lunch['id']}")

        col_s, col_c = st.columns(2)
        with col_s:
            if st.form_submit_button("Save Changes", type="primary", use_container_width=True):
                update_lunch(lunch["id"], {
                    "scheduled_date": sched_date.isoformat(),
                    "scheduled_time": sched_time,
                    "staff_count": staff_count,
                    "restaurant": restaurant,
                    "dietary_notes": dietary_notes,
                    "confirmed_with": confirmed_with,
                })
                st.session_state[f"edit_lunch_{lunch['id']}"] = False
                st.success("Lunch updated!")
                st.rerun()
        with col_c:
            if st.form_submit_button("Cancel", use_container_width=True):
                st.session_state[f"edit_lunch_{lunch['id']}"] = False
                st.rerun()


def _show_complete_lunch_dialog(lunch):
    """Show completion dialog with follow-up scheduling."""
    from database import (update_lunch, get_providers_for_practice, add_thank_you,
                          add_contact_log, add_follow_up, create_event)
    st.markdown(f"#### Mark Lunch Completed — {lunch.get('practice_name')}")
    schedule_next = st.checkbox("Schedule next follow-up?", value=False, key=f"sn_{lunch['id']}")
    followup_type = None
    interval = None
    custom_date = None
    if schedule_next:
        followup_type = st.selectbox("Follow-up Type", [
            "Next Lunch (6 months)",
            "Cookie Visit (3 months)",
            "Follow-up Call",
            "Send Flyer",
            "Thank You Letter",
            "Custom Activity",
        ], key=f"ft_{lunch['id']}")
        interval = st.radio("Interval", [
            "3 months from today",
            "6 months from today",
            "Custom date",
        ], horizontal=True, key=f"int_{lunch['id']}")
        if interval == "Custom date":
            custom_date = st.date_input("Select date", key=f"cd_{lunch['id']}")

    if st.button("Confirm Completed", key=f"cc_{lunch['id']}"):
        update_lunch(lunch["id"], {
            "status": "Completed",
            "completed_date": datetime.now().isoformat(),
        })
        # Auto-generate thank you letters
        providers = get_providers_for_practice(lunch["practice_id"])
        for prov in providers:
            add_thank_you({
                "provider_id": prov["id"],
                "practice_id": lunch["practice_id"],
                "lunch_id": lunch["id"],
                "reason": "Post-Lunch",
                "status": "Pending",
            })
        add_contact_log({
            "practice_id": lunch["practice_id"],
            "contact_type": "Lunch",
            "contact_date": datetime.now().isoformat(),
            "team_member": "Robbie",
            "outcome": "Completed",
            "notes": f"Lunch completed at {lunch.get('restaurant', '')}",
        })
        # Schedule follow-up if requested
        if schedule_next:
            try:
                if interval == "Custom date" and custom_date:
                    next_date = custom_date.isoformat()
                elif interval == "6 months from today":
                    next_date = (datetime.now() + timedelta(weeks=26)).date().isoformat()
                else:
                    next_date = (datetime.now() + timedelta(weeks=13)).date().isoformat()

                fu_map = {
                    "Next Lunch (6 months)": "Lunch",
                    "Cookie Visit (3 months)": "Cookie Visit",
                    "Follow-up Call": "Call",
                    "Send Flyer": "Other",
                    "Thank You Letter": "Other",
                    "Custom Activity": "Other",
                }
                evt_type = fu_map.get(followup_type, "Lunch") if followup_type else "Lunch"

                add_follow_up({
                    "practice_id": lunch["practice_id"],
                    "follow_up_type": evt_type,
                    "follow_up_date": next_date,
                    "interval": interval,
                    "status": "Scheduled",
                    "notes": f"Follow-up after completed lunch",
                })
                create_event({
                    "practice_id": lunch["practice_id"],
                    "event_type": evt_type,
                    "label": f"{evt_type} - {lunch.get('practice_name')}",
                    "scheduled_date": next_date,
                    "status": "Scheduled",
                    "created_by": "ui",
                })
            except Exception:
                pass
        st.success(f"Lunch completed! {len(providers)} thank you letters auto-generated.")
        st.session_state[f"complete_prompt_{lunch['id']}"] = False
        st.rerun()


def _show_call_attempt_form(lunch):
    """Show call attempt logging form."""
    from database import add_call_attempt, update_lunch
    with st.form(f"call_form_{lunch['id']}"):
        st.markdown("#### Log Call Attempt")
        call_date = st.date_input("Date", value=datetime.now(), key=f"cad_{lunch['id']}")
        call_time = st.text_input("Time", key=f"cat_{lunch['id']}")
        person = st.text_input("Person Contacted", key=f"cap_{lunch['id']}")
        outcome = st.selectbox("Outcome", ["No Answer", "Left Message", "Spoke With", "Scheduled", "Call Back"], key=f"cao_{lunch['id']}")
        notes = st.text_input("Notes", key=f"can_{lunch['id']}")
        if st.form_submit_button("Save Call"):
            add_call_attempt({
                "lunch_id": lunch["id"],
                "practice_id": lunch["practice_id"],
                "call_date": call_date.isoformat(),
                "call_time": call_time,
                "person_contacted": person,
                "outcome": outcome,
                "notes": notes,
            })
            if lunch["status"] == "Not Contacted":
                update_lunch(lunch["id"], {"status": "Attempting"})
            st.session_state[f"call_attempt_{lunch['id']}"] = False
            st.success("Call attempt logged!")
            st.rerun()
