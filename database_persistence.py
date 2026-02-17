"""GitHub-backed persistence for the SQLite database.

On Streamlit Cloud the filesystem is ephemeral — providers.db is lost on every
restart.  This module stores a base64-encoded copy of the database as a file
in the GitHub repo (data/providers_backup.b64) and restores it automatically
when the app boots and no local database exists.
"""
import base64
import os
import requests
import streamlit as st

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "providers.db")
GITHUB_BACKUP_PATH = "data/providers_backup.b64"


def get_github_config() -> dict:
    """Return GitHub token and repo from Streamlit secrets, or empty dict."""
    try:
        return {
            "token": st.secrets["github"]["token"],
            "repo": st.secrets["github"]["repo"],
        }
    except Exception:
        return {}


def _github_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }


def save_database_to_github() -> dict:
    """Upload the current providers.db to GitHub as a base64 file.

    Returns {"success": True/False, "message": "..."}.
    """
    gh = get_github_config()
    if not gh:
        return {"success": False, "message": "GitHub not configured in secrets"}

    if not os.path.exists(DB_PATH):
        return {"success": False, "message": "No database file to save"}

    token, repo = gh["token"], gh["repo"]
    api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"

    # Read and encode the database
    with open(DB_PATH, "rb") as f:
        db_bytes = f.read()
    content_b64 = base64.b64encode(db_bytes).decode("utf-8")

    # Check if file already exists (need SHA for update)
    sha = None
    try:
        resp = requests.get(api_url, headers=_github_headers(token), timeout=30)
        if resp.status_code == 200:
            sha = resp.json().get("sha")
    except Exception:
        pass

    # Build payload
    payload = {
        "message": "Auto-save database backup",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(api_url, json=payload, headers=_github_headers(token), timeout=60)
        if resp.status_code in (200, 201):
            return {"success": True, "message": "Database saved to GitHub"}
        else:
            return {"success": False, "message": f"GitHub API error {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def load_database_from_github() -> dict:
    """Download the database backup from GitHub and write it to DB_PATH.

    Returns {"success": True/False, "message": "..."}.
    """
    gh = get_github_config()
    if not gh:
        return {"success": False, "message": "GitHub not configured in secrets"}

    token, repo = gh["token"], gh["repo"]
    api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_BACKUP_PATH}"

    try:
        resp = requests.get(api_url, headers=_github_headers(token), timeout=30)
        if resp.status_code == 404:
            return {"success": False, "message": "No backup found in GitHub"}
        if resp.status_code != 200:
            return {"success": False, "message": f"GitHub API error {resp.status_code}"}

        data = resp.json()
        content_b64 = data.get("content", "")
        # GitHub returns base64 with newlines — strip them
        content_b64 = content_b64.replace("\n", "")
        db_bytes = base64.b64decode(content_b64)

        with open(DB_PATH, "wb") as f:
            f.write(db_bytes)

        return {"success": True, "message": f"Database restored ({len(db_bytes):,} bytes)"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def auto_restore_database():
    """If no local database exists, try to restore from GitHub.

    Call this once at app startup (before init_db).
    Safe to call when GitHub is not configured — just does nothing.
    """
    if os.path.exists(DB_PATH):
        return  # Already have a local DB, nothing to do

    gh = get_github_config()
    if not gh:
        return  # No GitHub config, nothing we can do

    result = load_database_from_github()
    if result["success"]:
        print(f"[persistence] {result['message']}")
    else:
        print(f"[persistence] Could not restore: {result['message']}")
