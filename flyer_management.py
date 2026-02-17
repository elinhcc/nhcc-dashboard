"""Cloud-compatible flyer management: upload, list, delete via GitHub storage."""
import base64
import os
import requests
import streamlit as st

FLYERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploaded_flyers")
GITHUB_FLYERS_PATH = "data/flyers"


def ensure_flyers_dir():
    """Create the local uploaded_flyers directory if needed."""
    os.makedirs(FLYERS_DIR, exist_ok=True)


def get_uploaded_flyers() -> list:
    """Return list of locally available flyer files."""
    ensure_flyers_dir()
    flyers = []
    for f in os.listdir(FLYERS_DIR):
        ext = os.path.splitext(f)[1].lower()
        if ext in (".pdf", ".png", ".jpg", ".jpeg", ".docx"):
            full_path = os.path.join(FLYERS_DIR, f)
            size = os.path.getsize(full_path)
            flyers.append({
                "name": f,
                "path": full_path,
                "size_kb": round(size / 1024, 1),
                "modified": os.path.getmtime(full_path),
            })
    flyers.sort(key=lambda x: x["modified"], reverse=True)
    return flyers


def _get_github_config() -> dict:
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


def save_flyer_to_github(filename: str, file_bytes: bytes) -> dict:
    """Upload a flyer file to GitHub at data/flyers/<filename>.

    Returns {"success": True/False, "message": "..."}.
    """
    gh = _get_github_config()
    if not gh:
        return {"success": False, "message": "GitHub not configured"}

    token, repo = gh["token"], gh["repo"]
    path = f"{GITHUB_FLYERS_PATH}/{filename}"
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    content_b64 = base64.b64encode(file_bytes).decode("utf-8")

    # Check if file exists (need SHA for update)
    sha = None
    try:
        resp = requests.get(api_url, headers=_github_headers(token), timeout=30)
        if resp.status_code == 200:
            sha = resp.json().get("sha")
    except Exception:
        pass

    payload = {
        "message": f"Upload flyer: {filename}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(api_url, json=payload, headers=_github_headers(token), timeout=60)
        if resp.status_code in (200, 201):
            return {"success": True, "message": f"Flyer '{filename}' saved to GitHub"}
        else:
            return {"success": False, "message": f"GitHub API error {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def delete_flyer_from_github(filename: str) -> dict:
    """Delete a flyer from GitHub."""
    gh = _get_github_config()
    if not gh:
        return {"success": False, "message": "GitHub not configured"}

    token, repo = gh["token"], gh["repo"]
    path = f"{GITHUB_FLYERS_PATH}/{filename}"
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"

    try:
        resp = requests.get(api_url, headers=_github_headers(token), timeout=30)
        if resp.status_code != 200:
            return {"success": False, "message": "File not found in GitHub"}
        sha = resp.json()["sha"]

        resp = requests.delete(
            api_url,
            json={"message": f"Delete flyer: {filename}", "sha": sha},
            headers=_github_headers(token),
            timeout=30,
        )
        if resp.status_code == 200:
            return {"success": True, "message": f"Deleted '{filename}' from GitHub"}
        else:
            return {"success": False, "message": f"GitHub API error {resp.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)}


def load_flyers_from_github():
    """Download all flyers from GitHub to the local uploaded_flyers directory.

    Call this once at app startup so flyers are available for campaigns.
    Safe to call when GitHub is not configured.
    """
    gh = _get_github_config()
    if not gh:
        return

    ensure_flyers_dir()
    token, repo = gh["token"], gh["repo"]
    api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_FLYERS_PATH}"

    try:
        resp = requests.get(api_url, headers=_github_headers(token), timeout=30)
        if resp.status_code != 200:
            return  # No flyers folder or error

        files = resp.json()
        if not isinstance(files, list):
            return

        for item in files:
            if item.get("type") != "file":
                continue
            name = item["name"]
            local_path = os.path.join(FLYERS_DIR, name)

            # Skip if we already have this file locally
            if os.path.exists(local_path):
                continue

            # Download the file content
            file_resp = requests.get(
                item["url"], headers=_github_headers(token), timeout=30
            )
            if file_resp.status_code != 200:
                continue
            content_b64 = file_resp.json().get("content", "").replace("\n", "")
            file_bytes = base64.b64decode(content_b64)

            with open(local_path, "wb") as f:
                f.write(file_bytes)
            print(f"[flyers] Restored: {name} ({len(file_bytes):,} bytes)")
    except Exception as e:
        print(f"[flyers] Error loading from GitHub: {e}")
