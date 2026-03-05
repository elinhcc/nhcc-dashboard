"""Admin-only: manage app users (create, deactivate, reset password)."""
import streamlit as st
import bcrypt
from database import get_all_users, create_user, update_user


def show_user_management():
    current_user = st.session_state.get("user", {})
    if current_user.get("role") != "admin":
        st.error("Access denied — Admins only.")
        return

    st.markdown("## User Management")

    tab_list, tab_add = st.tabs(["All Users", "Add New User"])

    # ── All Users ─────────────────────────────────────────────────────
    with tab_list:
        users = get_all_users()
        if not users:
            st.info("No users found. Add one in the 'Add New User' tab.")
        else:
            for u in users:
                uid       = u["id"]
                uname     = u.get("username", "")
                fname     = u.get("full_name") or uname
                role      = u.get("role", "staff")
                active    = bool(u.get("is_active", True))
                last_in   = (u.get("last_login") or "Never")[:16]
                is_self   = (uid == current_user.get("id"))

                with st.expander(
                    f"{'🟢' if active else '🔴'}  {fname}  (@{uname})  —  {role.capitalize()}",
                    expanded=False,
                ):
                    info_col, action_col = st.columns([2, 1])

                    with info_col:
                        st.markdown(f"**Username:** {uname}")
                        st.markdown(f"**Full Name:** {fname}")
                        st.markdown(f"**Role:** {role.capitalize()}")
                        st.markdown(f"**Status:** {'Active' if active else 'Inactive'}")
                        st.markdown(f"**Last Login:** {last_in}")

                    with action_col:
                        # ── Reset password ────────────────────────────
                        with st.form(f"reset_pw_{uid}"):
                            st.markdown("**Reset Password**")
                            new_pw = st.text_input(
                                "New password", type="password",
                                key=f"npw_{uid}",
                            )
                            if st.form_submit_button("Reset", use_container_width=True):
                                if len(new_pw) < 8:
                                    st.error("Min 8 characters")
                                else:
                                    hashed = bcrypt.hashpw(
                                        new_pw.encode(), bcrypt.gensalt()
                                    ).decode()
                                    update_user(uid, {"password_hash": hashed})
                                    st.success("Password updated")

                        st.markdown("")

                        # ── Activate / Deactivate ─────────────────────
                        if is_self:
                            st.caption("Cannot deactivate yourself")
                        else:
                            if active:
                                if st.button(
                                    "Deactivate", key=f"deact_{uid}",
                                    use_container_width=True,
                                ):
                                    update_user(uid, {"is_active": False})
                                    st.rerun()
                            else:
                                if st.button(
                                    "Activate", key=f"act_{uid}",
                                    use_container_width=True, type="primary",
                                ):
                                    update_user(uid, {"is_active": True})
                                    st.rerun()

    # ── Add New User ──────────────────────────────────────────────────
    with tab_add:
        st.markdown("### Add New User")
        with st.form("add_user_form"):
            new_username  = st.text_input("Username *", placeholder="e.g. jsmith")
            new_full_name = st.text_input("Full Name *", placeholder="e.g. Jane Smith")
            new_password  = st.text_input("Password *", type="password",
                                          help="Minimum 8 characters")
            new_role      = st.selectbox("Role", ["staff", "admin"],
                                         format_func=lambda r: r.capitalize())

            submitted = st.form_submit_button("Create User", type="primary",
                                              use_container_width=True)
            if submitted:
                uname_clean = new_username.strip().lower()
                if not uname_clean:
                    st.error("Username is required")
                elif not new_full_name.strip():
                    st.error("Full name is required")
                elif len(new_password) < 8:
                    st.error("Password must be at least 8 characters")
                else:
                    # Check for duplicate username
                    existing = [u for u in get_all_users()
                                if u.get("username") == uname_clean]
                    if existing:
                        st.error(f"Username '{uname_clean}' already exists")
                    else:
                        pw_hash = bcrypt.hashpw(
                            new_password.encode(), bcrypt.gensalt()
                        ).decode()
                        create_user({
                            "username":      uname_clean,
                            "password_hash": pw_hash,
                            "full_name":     new_full_name.strip(),
                            "role":          new_role,
                            "is_active":     True,
                        })
                        st.success(
                            f"User '{uname_clean}' created as {new_role.capitalize()}."
                        )
                        st.rerun()
