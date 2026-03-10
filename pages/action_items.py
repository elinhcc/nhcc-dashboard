"""My Daily Work - personal task list and contact queue."""
import streamlit as st
from datetime import datetime, date, timedelta
from utils import db_exists


def show_action_items():
    st.markdown("## My Daily Work")

    if not db_exists():
        st.warning("No data loaded yet.")
        st.info("Go to **Settings > Data Import** to upload your provider Excel file.")
        return

    from database import (
        get_all_practices, get_contact_log, get_lunches,
        get_call_attempt_count, add_contact_log,
        get_tasks, add_task, update_task,
    )
    from utils import load_config, format_phone_link

    config       = load_config()
    team_members = config.get("team_members", [])

    user_dict = st.session_state.get("user", {})
    username  = user_dict.get("username", "")
    full_name = user_dict.get("full_name", "") or username
    is_admin  = user_dict.get("role") == "admin"

    today     = date.today()
    today_str = today.isoformat()
    in_3_days = (today + timedelta(days=3)).isoformat()

    # Load tasks (admin sees all, staff sees own)
    if is_admin:
        all_tasks = get_tasks()
    else:
        all_tasks = get_tasks(assigned_to=username)

    open_tasks = [t for t in all_tasks if not t.get("is_complete")]
    overdue = sorted(
        [t for t in open_tasks if t.get("due_date") and t["due_date"] < today_str],
        key=lambda x: x.get("due_date", ""),
    )
    due_today = [t for t in open_tasks if t.get("due_date") == today_str]
    upcoming = sorted(
        [t for t in open_tasks if t.get("due_date") and today_str < t["due_date"] <= in_3_days],
        key=lambda x: x.get("due_date", ""),
    )
    no_date = [t for t in open_tasks if not t.get("due_date")]
    completed_today = [
        t for t in all_tasks
        if t.get("is_complete") and (t.get("completed_at") or "")[:10] == today_str
    ]

    # Greeting
    hour     = datetime.now().hour
    greeting = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
    name     = full_name.split()[0] if full_name else ("there" if is_admin else username)
    todo_count = len(overdue) + len(due_today)

    if todo_count == 0:
        st.markdown(f"### {greeting} {name}!")
        st.success(
            "You're all caught up! Check the Contact Queue below "
            "for practices that need outreach."
        )
    else:
        plural = "things" if todo_count != 1 else "thing"
        st.markdown(f"### {greeting} {name}! You have **{todo_count}** {plural} to do today.")

    with st.expander("Add New Task"):
        _show_add_task_form(team_members, username, is_admin)

    st.markdown("---")

    if overdue:
        st.markdown("### Overdue")
        for task in overdue:
            _task_card(task, is_admin, "overdue")

    if due_today:
        st.markdown("### Today")
        for task in due_today:
            _task_card(task, is_admin, "today")

    if upcoming:
        st.markdown("### Upcoming (Next 3 Days)")
        for task in upcoming:
            _task_card(task, is_admin, "upcoming")

    if no_date:
        st.markdown("### No Due Date")
        for task in no_date:
            _task_card(task, is_admin, "no_date")

    if not any([overdue, due_today, upcoming, no_date]):
        st.info("No open tasks. Add one above or check the Contact Queue below.")

    if completed_today:
        with st.expander(f"Completed Today ({len(completed_today)})", expanded=False):
            for task in completed_today:
                _task_card(task, is_admin, "completed")

    st.markdown("---")

    st.markdown("## Practices Waiting for Contact")
    st.caption(
        "Practices where at least one contact attempt has been made "
        "but no lunch is scheduled yet."
    )
    _show_contact_queue()
    _render_contact_log_modal(team_members)


def _task_card(task, is_admin, section):
    from database import update_task

    practice_name = task.get("practice_name") or ""
    task_type     = task.get("task_type", "")
    description   = task.get("description") or ""
    due_str       = (task.get("due_date") or "")[:10]
    notes         = task.get("notes") or ""

    label  = task_type if task_type else description
    detail = description if task_type and description else ""

    extra = ""
    if section == "overdue" and due_str:
        try:
            days_over = (date.today() - date.fromisoformat(due_str)).days
            extra = f" -- **{days_over} day{'s' if days_over != 1 else ''} overdue**"
        except Exception:
            pass
    elif section == "upcoming" and due_str:
        try:
            days_until = (date.fromisoformat(due_str) - date.today()).days
            extra = f" -- in {days_until} day{'s' if days_until != 1 else ''}"
        except Exception:
            pass

    col1, col2, col3 = st.columns([4, 2, 1])

    with col1:
        header = f"**{practice_name}**" if practice_name else "**General Task**"
        if is_admin and task.get("assigned_to"):
            header += f"  *({task['assigned_to']})*"
        st.markdown(header)
        st.markdown(f"{label}{extra}")
        if detail:
            st.caption(detail)
        if notes:
            with st.expander("View Notes", expanded=False):
                st.caption(notes)

    with col2:
        if due_str:
            st.caption(f"Due: {due_str}")

    with col3:
        if section != "completed":
            if st.button(
                "Mark Done",
                key=f"done_{task['id']}_{section}",
                type="primary",
                use_container_width=True,
            ):
                update_task(task["id"], {
                    "is_complete":  1,
                    "completed_at": datetime.now().isoformat(),
                })
                st.rerun()
        else:
            st.caption("Done")

    st.divider()


def _show_add_task_form(team_members, username, is_admin):
    from database import get_all_practices, add_task

    practices  = get_all_practices(status_filter="Active")
    prac_names = [p["name"] for p in practices]
    prac_map   = {p["name"]: p["id"] for p in practices}

    with st.form("add_task_form", clear_on_submit=True):
        selected_practice = st.selectbox("Practice *", prac_names) if prac_names else None
        task_type = st.selectbox("Task Type *", [
            "Follow-up Call", "Catering Order", "Confirmation Email",
            "Schedule Lunch", "Follow-up Visit", "General",
        ])
        description = st.text_input("Notes / Details", placeholder="Optional extra details")

        col1, col2 = st.columns(2)
        with col1:
            due_date = st.date_input("Due Date", value=date.today())
        with col2:
            staff_opts = team_members or ["Robbie", "Kianah"]
            if is_admin:
                assigned_to = st.selectbox("Assign To", staff_opts)
            else:
                assigned_to = username
                st.text(f"Assigned to: {username}")

        if st.form_submit_button("Add Task", type="primary"):
            if not selected_practice:
                st.error("Please select a practice.")
            else:
                add_task({
                    "practice_id": prac_map[selected_practice],
                    "task_type":   task_type,
                    "description": description.strip(),
                    "due_date":    due_date.isoformat(),
                    "assigned_to": assigned_to,
                    "is_complete": 0,
                    "created_at":  datetime.now().isoformat(),
                })
                st.success("Task added!")
                st.rerun()


def _show_contact_queue():
    from database import get_contact_queue_data
    from utils import format_phone_link

    # 3 bulk calls instead of 275×3 individual calls
    practices, last_contact_by_pid, lunch_active_pids, phone_count_by_pid = get_contact_queue_data()
    queue = []

    for p in practices:
        pid = p["id"]
        last = last_contact_by_pid.get(pid)
        call_count = phone_count_by_pid.get(pid, 0)
        has_lunch = pid in lunch_active_pids

        if last and not has_lunch and call_count > 0:
            queue.append({
                "practice":          p["name"],
                "practice_id":       pid,
                "last_contact_date": (last.get("contact_date") or "")[:10],
                "last_contact_type": last.get("contact_type", ""),
                "attempt_count":     call_count,
                "phone":             p.get("phone", ""),
            })

    queue.sort(key=lambda x: x["last_contact_date"])

    if not queue:
        st.info("No practices waiting for follow-up contact right now.")
        return

    st.caption(f"{len(queue)} practices waiting for follow-up")

    for item in queue[:30]:
        col1, col2, col3 = st.columns([3, 3, 1])
        with col1:
            st.markdown(f"**{item['practice']}**")
            st.caption(
                f"Last: {item['last_contact_date']} ({item['last_contact_type']}) "
                f"* {item['attempt_count']} attempt(s)"
            )
        with col2:
            phone_html = format_phone_link(item["phone"]) if item["phone"] else "No phone on file"
            st.markdown(phone_html, unsafe_allow_html=True)
        with col3:
            if st.button("Log Contact", key=f"cq_{item['practice_id']}"):
                st.session_state.active_contact_form = item["practice_id"]
                st.rerun()
        st.divider()


def _render_contact_log_modal(team_members):
    if not st.session_state.get("active_contact_form"):
        return

    from database import get_all_practices, add_contact_log

    practice_id = st.session_state.active_contact_form
    practices   = get_all_practices()
    practice    = next((p for p in practices if p["id"] == practice_id), None)
    pname       = practice["name"] if practice else "Practice"

    @st.dialog(f"Log Contact - {pname}")
    def _dialog():
        with st.form("log_contact_modal"):
            contact_type = st.selectbox("Contact Type", [
                "Phone Call", "Email", "Fax", "In-Person Visit",
                "Lunch", "Cookie Visit", "Other",
            ])
            contact_date = st.date_input("Date", value=date.today())
            member_opts  = team_members if team_members else ["Robbie", "Kianah"]
            team_member  = st.selectbox("Team Member", member_opts)
            outcome      = st.selectbox("Outcome", [
                "No Answer", "Left Message", "Spoke With",
                "Scheduled", "Call Back", "Completed",
            ])
            notes = st.text_area("Notes", height=80)

            c1, c2 = st.columns(2)
            with c1:
                if st.form_submit_button("Save", type="primary", use_container_width=True):
                    add_contact_log({
                        "practice_id":  practice_id,
                        "contact_type": contact_type,
                        "contact_date": contact_date.isoformat(),
                        "team_member":  team_member,
                        "outcome":      outcome,
                        "notes":        notes,
                    })
                    st.session_state.active_contact_form = None
                    st.success("Contact logged!")
                    st.rerun()
            with c2:
                if st.form_submit_button("Cancel", use_container_width=True):
                    st.session_state.active_contact_form = None
                    st.rerun()

    _dialog()
