"""
app_updater.py

Two independent checks, same split Ascended STT uses:

- Content (style.qss, the two logo/icon files) is thin here -- almost
  everything else in Guardian is Python code baked straight into the
  exe by PyInstaller, not loose data files the way STT's ui/ and
  assets/ are, so there's much less to hot-swap. Still handled the
  same way: compare content_version.txt against GitHub, and download
  and overwrite CONTENT_PATHS if there's a newer one. Safe even while
  running. Also used to self-heal if these ever go missing -- they're
  already graceful-degrade files (main.py only applies them if
  .exists() is True, so a missing style.qss just means an unstyled
  window, not a crash) but there's no reason to leave it that way if a
  quick fetch can fix it before the window even opens.

- The app itself (every .py module, all baked into the exe) can't be
  self-updated the same way -- Windows won't let a running process
  overwrite its own exe, and almost all of Guardian's real behavior
  lives in that exe, not in swappable data. So this just checks
  GitHub's latest release tag against APP_VERSION and hands back
  whether something newer exists; main.py decides how to show that.
"""

import os
import sys
import zipfile
import tempfile
import shutil

import requests

# Bump this by hand alongside every GitHub Release tag (vX.Y.Z) -- the
# only thing the app-update check compares against.
APP_VERSION = "0.2.0"

CONTENT_REPO = "hex-vr/guardian"
CONTENT_BRANCH = "main"
CONTENT_PATHS = ["style.qss", "ascended_logo.png", "ascended_logo.ico"]
CONTENT_VERSION_URL = (
    f"https://raw.githubusercontent.com/{CONTENT_REPO}/{CONTENT_BRANCH}/content_version.txt"
)
CONTENT_ZIP_URL = f"https://codeload.github.com/{CONTENT_REPO}/zip/refs/heads/{CONTENT_BRANCH}"
RELEASES_API_URL = f"https://api.github.com/repos/{CONTENT_REPO}/releases/latest"


def get_app_dir():
    """Folder the script/exe actually lives in. The rest of this
    codebase leans on Path(__file__).parent, which isn't reliable
    inside a frozen PyInstaller build -- this new code gets the
    correct version rather than trusting that older pattern, same fix
    Ascended STT already made for the same reason."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def read_local_content_version(app_dir):
    """0 if content_version.txt is missing entirely -- same as a fresh
    checkout that's never been stamped. This file is itself one of the
    things a content update overwrites, so local and remote naturally
    converge after applying one."""
    path = os.path.join(app_dir, "content_version.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def fetch_remote_content_version():
    try:
        resp = requests.get(CONTENT_VERSION_URL, timeout=10)
        resp.raise_for_status()
        return int(resp.text.strip())
    except Exception:
        return None


def download_and_apply_content_update(app_dir, log=print):
    """Pulls the whole repo as a zip -- simplest way to get a
    consistent snapshot in one request rather than walking GitHub's
    Contents API file by file -- and copies just CONTENT_PATHS out of
    it into app_dir. Returns (ok, new_version, error); never raises,
    since this runs both before the QApplication exists and from a
    QTimer tick once the app is up."""
    try:
        log("Downloading latest app content from GitHub...")
        resp = requests.get(CONTENT_ZIP_URL, timeout=60)
        resp.raise_for_status()
        zip_bytes = resp.content
    except Exception as e:
        return False, None, f"Couldn't download content update: {e}"

    tmp_dir = tempfile.mkdtemp(prefix="guardian_content_")
    try:
        zip_path = os.path.join(tmp_dir, "content.zip")
        with open(zip_path, "wb") as f:
            f.write(zip_bytes)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)

        # GitHub's codeload zips wrap everything in one top-level
        # "<repo>-<branch>/" folder -- whatever that folder's actually
        # named, it's the only directory sitting directly in tmp_dir.
        extracted_root = next(
            os.path.join(tmp_dir, name) for name in os.listdir(tmp_dir)
            if os.path.isdir(os.path.join(tmp_dir, name))
        )

        for rel_path in CONTENT_PATHS + ["content_version.txt"]:
            src = os.path.join(extracted_root, rel_path)
            dst = os.path.join(app_dir, rel_path)
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(src, dst)

        new_version = read_local_content_version(app_dir)
        log(f"Content updated to v{new_version}.")
        return True, new_version, None
    except Exception as e:
        return False, None, f"Couldn't apply content update: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def self_heal_content(app_dir, log=print):
    """Called once at startup, before the QApplication/stylesheet are
    even built -- if style.qss or the logo files are missing, fetch
    them fresh so THIS launch gets to use them, not just the next
    one."""
    required = [os.path.join(app_dir, p) for p in CONTENT_PATHS]
    if all(os.path.exists(p) for p in required):
        return
    log("Some app content files are missing -- fetching them from GitHub...")
    download_and_apply_content_update(app_dir, log=log)


def fetch_latest_release():
    """(tag, html_url) for the newest GitHub Release, or (None, None)
    on any failure -- a network hiccup here should never be louder
    than a quiet skip, Guardian already runs fine offline."""
    try:
        resp = requests.get(RELEASES_API_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data.get("tag_name"), data.get("html_url")
    except Exception:
        return None, None


def _version_tuple(v):
    v = (v or "").lstrip("vV")
    parts = []
    for piece in v.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer_version(remote, local):
    return _version_tuple(remote) > _version_tuple(local)
