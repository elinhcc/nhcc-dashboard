"""Action items page: overdue items, call queue, thank you checklist, upcoming tasks."""
import streamlit as st
import pandas as pd
from datetime import datetime
from database import (
    get_all_practices, get_lunches, update_lunch,
    get_thank_yous, update_thank_you, add_thank_you,
    get_providers_for_practice, add_contact_log,
    add_call_attempt, get_call_attempts, add_cookie_visit,
)
from utils import get_overdue_items, days_since


def show_action_items():
    st.markdown("## 📋 Action Items & Follow-ups")

    tab_overdue, tab_lunches, tab_thankyou, tab_cookies, tab_calls = st.tabs([
        "⚠️ Overdue / Upcoming",
        "🍽️ Lunch Tracking",
        "💌 Thank You Letters",
        "🍪 Cookie Visits",
        "📞 Call Queue",
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
                st.markdown("### 🔴 High Priority")
                for item in high:
                    col1, col2, col3 = st.columns([3, 2, 1])
                    col1.markdown(f"**{item['practice']}**")
                    col2.markdown(f"{item['type']}: {item['detail']}")
                    with col3:
                        if st.button("📞 Log Contact", key=f"ov_contact_{item['practice_id']}_{item['type']}"):
                            st.session_state[f"quick_log_{item['practice_id']}"] = True

            if med:
                st.markdown("### 🟡 Medium Priority")
                for item in med:
                    col1, col2 = st.columns([3, 3])
                    col1.markdown(f"**{item['practice']}**")
                    col2.markdown(f"{item['type']}: {item['detail']}")

    # ── Lunch Tracking ─────────────────────────────────────────────────
    with tab_lunches:
        st.markdown("### Active Lunch Workflows")

        status_tabs = st.tabs(["Attempting", "Scheduled", "Completed", "Not Contacted"])

        for stab, status in zip(status_tabs, ["Attempting", "Scheduled", "Completed", "Not Contacted"]):
            with stab:
                lunches = get_lunches(status_filter=status)
                if not lunches:
                    st.info(f"No lunches with status '{status}'")
                    continue

                for lunch in lunches:
                    with st.expander(f"{lunch['practice_name']} — {status} | {lunch.get('scheduled_date', 'TBD')[:10] if lunch.get('scheduled_date') else 'TBD'}"):
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
                                st.caption(f"📞 {att.get('call_date', '')[:10] if att.get('call_date') else 'N/A'} {att.get('call_time', '')} — {att.get('outcome', '')} — {att.get('notes', '')}")

                        # Status progression buttons
                        btn_cols = st.columns(4)
                        if status != "Completed":
                            with btn_cols[0]:
                                if st.button("Log Call Attempt", key=f"call_lunch_{lunch['id']}"):
                                    st.session_state[f"call_attempt_{lunch['id']}"] = True

                        if status == "Attempting":
                            with btn_cols[1]:
                                if st.button("✅ Mark Scheduled", key=f"sched_{lunch['id']}"):
                                    update_lunch(lunch["id"], {"status": "Scheduled"})
                                    st.rerun()

                        if status == "Scheduled":
                            with btn_cols[1]:
                                if st.button("✅ Mark Completed", key=f"comp_{lunch['id']}"):
                                    st.session_state[f"complete_prompt_{lunch['id']}"] = True

                        # Completion modal with schedule-next option
                        if st.session_state.get(f"complete_prompt_{lunch['id']}", False):
                            with st.modal("Complete Lunch"):
                                st.markdown(f"### Mark Lunch Completed — {lunch.get('practice_name')}")
                                schedule_next = st.checkbox("Schedule next follow-up?", value=False)
                                interval = None
                                custom_date = None
                                if schedule_next:
                                    interval = st.selectbox("Interval", ["12 weeks", "3 months", "6 months", "Custom"], index=0)
                                    if interval == "Custom":
                                        custom_date = st.date_input("Next follow-up date")

                                if st.button("Confirm Completed"):
                                    update_lunch(lunch["id"], {
                                        "status": "Completed",
                                        "completed_date": datetime.now().isoformat(),
                                    })
                                    # Auto-generate thank you letters for providers
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
                                    # If schedule next requested, create new event
                                    if schedule_next:
                                        try:
                                            from database import create_event
                                            next_date = None
                                            if custom_date:
                                                next_date = custom_date.isoformat()
                                            else:
                                                # simple heuristics
                                                if interval == "12 weeks":
                                                    next_date = (datetime.now() + timedelta(weeks=12)).date().isoformat()
                                                elif interval == "3 months":
                                                    next_date = (datetime.now() + timedelta(weeks=13)).date().isoformat()
                                                elif interval == "6 months":
                                                    next_date = (datetime.now() + timedelta(weeks=26)).date().isoformat()
                                            if next_date:
                                                create_event({
                                                    "practice_id": lunch["practice_id"],
                                                    "event_type": "Lunch",
                                                    "label": f"Follow-up Lunch - {lunch.get('practice_name')}",
                                                    "scheduled_date": next_date,
                                                    "status": "Scheduled",
                                                    "created_by": "ui",
                                                })
                                        except Exception:
                                            pass
                                    st.success(f"Lunch completed! {len(providers)} thank you letters auto-generated.")
                                    st.session_state[f"complete_prompt_{lunch['id']}"] = False
                                    st.rerun()

                        # Call attempt form
                        if st.session_state.get(f"call_attempt_{lunch['id']}", False):
                            with st.form(f"call_form_{lunch['id']}"):
                                st.markdown("#### Log Call Attempt")
                                call_date = st.date_input("Date", value=datetime.now())
                                call_time = st.text_input("Time")
                                person = st.text_input("Person Contacted")
                                outcome = st.selectbox("Outcome", ["No Answer", "Left Message", "Spoke With", "Scheduled", "Call Back"])
                                notes = st.text_input("Notes")
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

        # Start new lunch workflow
        st.markdown("---")
        st.markdown("### Start New Lunch Workflow")
        practices = get_all_practices(status_filter="Active")
        practice_names = {p["name"]: p["id"] for p in practices}
        selected = st.selectbox("Select Practice", [""] + list(practice_names.keys()), key="new_lunch_practice")
        if selected and st.button("Start Lunch Workflow"):
            from database import add_lunch
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
                        if st.button("✅ Mailed", key=f"mail_ty_{ty['id']}"):
                            update_thank_you(ty["id"], {
                                "status": "Mailed",
                                "date_mailed": datetime.now().isoformat(),
                            })
                            st.rerun()

                # Bulk mark as mailed
                if st.button("✅ Mark All as Mailed"):
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
        st.markdown("### 🍪 Cookie Visit Check-in")

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
            schedule_next = st.checkbox("Schedule next follow-up after this visit")
            followup_interval = None
            custom_followup_date = None
            if schedule_next:
                followup_interval = st.selectbox("Follow-up interval", ["12 weeks", "3 months", "6 months", "Custom"], index=0)
                if followup_interval == "Custom":
                    custom_followup_date = st.date_input("Custom next follow-up date")

            if st.form_submit_button("Log Cookie Visit", type="primary"):
                data = {
                    "practice_id": practice_map[cookie_practice],
                    "visit_date": visit_date.isoformat(),
                    "items_delivered": items,
                    "delivered_by": delivered_by,
                    "notes": cookie_notes,
                    "status": "Completed",
                }
                if schedule_next and custom_followup_date:
                    data["next_visit_date"] = custom_followup_date.isoformat()
                vid = add_cookie_visit(data)
                add_contact_log({
                    "practice_id": practice_map[cookie_practice],
                    "contact_type": "Cookie Visit",
                    "contact_date": visit_date.isoformat(),
                    "team_member": delivered_by,
                    "outcome": "Delivered",
                    "notes": f"Items: {items}",
                })
                # create follow-up event if requested
                if schedule_next:
                    try:
                        from database import create_event
                        next_date = None
                        if custom_followup_date:
                            next_date = custom_followup_date.isoformat()
                        else:
                            if followup_interval == "12 weeks":
                                next_date = (datetime.now() + timedelta(weeks=12)).date().isoformat()
                            elif followup_interval == "3 months":
                                next_date = (datetime.now() + timedelta(weeks=13)).date().isoformat()
                            elif followup_interval == "6 months":
                                next_date = (datetime.now() + timedelta(weeks=26)).date().isoformat()
                        if next_date:
                            create_event({
                                "practice_id": practice_map[cookie_practice],
                                "event_type": "Cookie Visit",
                                "label": f"Cookie Visit - {cookie_practice}",
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

    # ── Call Queue ─────────────────────────────────────────────────────
    with tab_calls:
        st.markdown("### 📞 Call Queue")
        st.markdown("Practices that need follow-up calls:")

        practices = get_all_practices(status_filter="Active")
        call_queue = []
        for p in practices:
            from database import get_contact_log
            contacts = get_contact_log(practice_id=p["id"], limit=1)
            last_days = None
            if contacts:
                last_days = days_since(contacts[0].get("contact_date"))
            call_queue.append({
                "practice": p["name"],
                "practice_id": p["id"],
                "last_contact_days": last_days if last_days else 999,
                "phone": p.get("phone", "N/A"),
                "contact_person": p.get("contact_person", ""),
            })

        call_queue.sort(key=lambda x: x["last_contact_days"], reverse=True)

        for item in call_queue[:20]:
            days_text = f"{item['last_contact_days']} days ago" if item["last_contact_days"] < 999 else "Never contacted"
            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
            col1.markdown(f"**{item['practice']}**")
            col2.markdown(f"📞 {item['phone']}")
            col3.markdown(f"Last: {days_text}")
            with col4:
                if st.button("📞 Call", key=f"cq_{item['practice_id']}"):
                    st.session_state[f"quick_log_{item['practice_id']}"] = True

    # Quick log modal for any practice
    for pid_key in list(st.session_state.keys()):
        if pid_key.startswith("quick_log_") and st.session_state[pid_key]:
            practice_id = int(pid_key.replace("quick_log_", ""))
            practice = get_all_practices()
            practice = next((p for p in practice if p["id"] == practice_id), None)
            if practice:
                with st.form(f"quick_contact_{practice_id}"):
                    st.markdown(f"#### Quick Contact Log — {practice['name']}")
                    ct = st.selectbox("Type", ["Call", "Other"], key=f"qc_type_{practice_id}")
                    outcome = st.selectbox("Outcome", ["Successful", "No Answer", "Left Message", "Follow-up Needed"], key=f"qc_out_{practice_id}")
                    notes = st.text_input("Notes", key=f"qc_notes_{practice_id}")
                    if st.form_submit_button("Save"):
                        add_contact_log({
                            "practice_id": practice_id,
                            "contact_type": ct,
                            "contact_date": datetime.now().isoformat(),
                            "team_member": "Robbie",
                            "outcome": outcome,
                            "notes": notes,
                        })
                        st.session_state[pid_key] = False
                        st.success("Contact logged!")
                        st.rerun()
