"""
profile_dialog.py

Right-click a player -> View Profile. Loads everything VRChat's GET
/users/{id} returns into a read-only view, and puts every moderation
action we have working (Note, Grp Kick, Grp Ban, Mute) as buttons at the
bottom -- so a mod can look someone up and act on them without going back
to the player list. The whole present picture of someone, in one place.

--------------------------------------------------------------------------
BEGINNER NOTES:

- Always fetches fresh when opened (never cached, unlike the player list's
  trust-rank/badge cache) -- a profile view is something you open when you
  specifically want the CURRENT picture of someone, so showing stale data
  here would be actively misleading.

- QScrollArea wraps the info section because profile data can be a lot of
  text (bio especially) -- this keeps the window a reasonable fixed size
  and lets the content scroll instead of the window growing to fit
  whatever the longest bio happens to be.

- The moderation buttons at the bottom just open the SAME dialogs
  (NoteDialog/KickDialog/BanDialog) the player list's right-click menu
  uses -- no new action logic here, just another entry point to it.
--------------------------------------------------------------------------
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QWidget,
    QFrame,
    QApplication,
)

import trust_rank
from note_dialog import NoteDialog
from kick_dialog import KickDialog
from ban_dialog import BanDialog
from glow import apply_glow, DANGER


class _CopyableLabel(QLabel):
    """A QLabel that copies `copy_value` to the clipboard when clicked, with a hand cursor as the hint."""

    def __init__(self, text: str, copy_value: str, status_label: QLabel = None):
        super().__init__(text)
        self._copy_value = copy_value
        self._status_label = status_label
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to copy")

    def mousePressEvent(self, event):
        QApplication.clipboard().setText(self._copy_value)
        if self._status_label is not None:
            self._status_label.setText(f"Copied: {self._copy_value}")
        super().mousePressEvent(event)


class ProfileDialog(QDialog):
    def __init__(self, client, target_user_id: str, target_display_name: str,
                 group_id: str = None, group_name: str = None,
                 has_moderation_permission: bool = None):
        super().__init__()
        self.setObjectName("ProfileDialog")
        self.setWindowTitle(f"Profile — {target_display_name}")
        self.resize(420, 640)

        self.client = client
        self.target_user_id = target_user_id
        self.target_display_name = target_display_name
        # Passed through from the main window so the action buttons below
        # know whether Grp Kick/Ban are even possible right now (same rule
        # as the right-click menu: only in group instances, and greyed out
        # when the logged-in user is known not to have permission there).
        self.group_id = group_id
        self.group_name = group_name
        self.has_moderation_permission = has_moderation_permission

        self._build_ui()
        self._load_profile()

    # -- UI ------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)

        self.status_label = QLabel("Loading profile...")
        self.status_label.setObjectName("profileStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.avatar_label = QLabel()
        self.avatar_label.setObjectName("profileAvatar")
        self.avatar_label.setFixedHeight(128)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.avatar_label)

        # No "open this specific profile in-game" deep link exists the way
        # VRCX's instance-invite launch link does -- confirmed by checking
        # VRChat's docs and VRCX's own source; the only supported vrchat://
        # protocol is for joining worlds/instances, not opening a user's
        # profile. This opens the closest real equivalent: their profile on
        # the VRChat website.
        self.web_profile_button = QPushButton("Open Web Profile ↗")
        self.web_profile_button.setObjectName("profileWebLinkButton")
        self.web_profile_button.setToolTip("Open this player's profile on the VRChat website")
        self.web_profile_button.clicked.connect(self._open_web_profile)
        outer.addWidget(self.web_profile_button)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.info_layout = QVBoxLayout(content)
        self.info_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        outer.addWidget(self._build_action_bar())

    def _build_action_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("profileActionBar")
        layout = QVBoxLayout(bar)

        label = QLabel("Moderation")
        label.setObjectName("profileActionLabel")
        layout.addWidget(label)

        button_row = QHBoxLayout()

        note_btn = QPushButton("Note")
        note_btn.setObjectName("profileNoteButton")
        note_btn.setToolTip("Add or edit a note about this player")
        note_btn.clicked.connect(self._open_note)
        button_row.addWidget(note_btn)

        kick_btn = QPushButton("Grp Kick")
        kick_btn.setObjectName("profileKickButton")
        apply_glow(kick_btn, DANGER)
        kick_btn.setEnabled(bool(self.group_id) and self.has_moderation_permission is not False)
        if self.has_moderation_permission is False:
            kick_btn.setToolTip("You don't have permission to moderate this group's instances.")
        else:
            kick_btn.setToolTip("Kick this player from the group's membership")
        kick_btn.clicked.connect(self._open_kick)
        button_row.addWidget(kick_btn)

        ban_btn = QPushButton("Grp Ban")
        ban_btn.setObjectName("profileBanButton")
        apply_glow(ban_btn, DANGER)
        ban_btn.setEnabled(bool(self.group_id) and self.has_moderation_permission is not False)
        if self.has_moderation_permission is False:
            ban_btn.setToolTip("You don't have permission to moderate this group's instances.")
        else:
            ban_btn.setToolTip("Ban this player from the group")
        ban_btn.clicked.connect(self._open_ban)
        button_row.addWidget(ban_btn)

        layout.addLayout(button_row)

        if not self.group_id:
            hint = QLabel("Grp Kick/Grp Ban need a group instance -- disabled here.")
            hint.setObjectName("profileActionHint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        elif self.has_moderation_permission is False:
            hint = QLabel("You don't have moderation permission in this group -- Grp Kick/Grp Ban disabled.")
            hint.setObjectName("profileActionHint")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        return bar

    # -- Loading the profile ---------------------------------------------

    def _load_profile(self):
        result = self.client.get_user(self.target_user_id)

        if result.status != "success":
            self.status_label.setText(f"Couldn't load profile: {result.error_message}")
            return

        self.status_label.setText("")
        # iconUrl is VRChat's own pre-resolved effective picture (icon
        # override -> avatar thumbnail -> default, already combined
        # server-side) -- this is what VRCX and the VRChat website actually
        # display, so it's tried first. currentAvatarThumbnailImageUrl and
        # userIcon are often blank even when the account clearly has a
        # profile picture (confirmed against a real account) -- they're
        # kept only as a last-resort fallback if iconUrl is ever missing.
        avatar_url = (
            result.icon_url
            or result.profile_pic_override
            or result.avatar_thumbnail_url
            or result.user_icon_url
        )
        self._load_avatar_image(avatar_url)

        rank = trust_rank.determine_trust_rank(result.tags or [])
        rank_label = QLabel(rank.label)
        rank_label.setStyleSheet(f"color: {rank.color}; font-weight: bold; font-size: 14px;")
        self.info_layout.addWidget(rank_label)

        badges = []
        if result.age_verified:
            badges.append("🪪 Age Verified (18+)")
        if "system_supporter" in (result.tags or []):
            badges.append("💎 VRC+ Subscriber")
        if result.is_friend:
            badges.append("Friend")
        if badges:
            self._add_row("", "  •  ".join(badges))

        self._add_row("Display Name", self.target_display_name, copy_value=self.target_display_name)
        self._add_row("User ID", self.target_user_id, copy_value=self.target_user_id)
        if result.pronouns:
            self._add_row("Pronouns", result.pronouns)
        if result.status_text:
            status_line = result.status_text
            if result.status_description:
                status_line += f" — {result.status_description}"
            self._add_row("Status", status_line)
        if result.bio:
            self._add_row("Bio", result.bio)
        if result.date_joined:
            self._add_row("Joined VRChat", result.date_joined)
        if result.last_login:
            self._add_row("Last Login", result.last_login)
        if result.last_platform:
            self._add_row("Last Platform", result.last_platform)
        self._add_row("Current Note", result.note or "(none on file)")

    def _load_avatar_image(self, url: str):
        if not url:
            return
        try:
            response = self.client.session.get(url, timeout=5)
            if response.status_code != 200:
                return
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            if not pixmap.isNull():
                self.avatar_label.setPixmap(
                    pixmap.scaledToHeight(128, Qt.SmoothTransformation)
                )
        except Exception:
            pass  # a missing/broken thumbnail is cosmetic, never worth failing the dialog over

    def _add_row(self, field: str, value: str, copy_value: str = None):
        """
        copy_value, when given, makes the row clickable -- clicking copies
        that exact text to the clipboard (used for Display Name and User
        ID, where a mod's next step is often pasting the value somewhere
        else, like a ban appeal thread or a note).
        """
        row = _CopyableLabel(f"<b>{field}:</b> {value}" if field else value, copy_value, self.status_label) \
            if copy_value else QLabel(f"<b>{field}:</b> {value}" if field else value)
        row.setObjectName("profileInfoRow")
        row.setWordWrap(True)
        row.setTextFormat(Qt.RichText)
        self.info_layout.addWidget(row)

    # -- Moderation button handlers ---------------------------------------

    def _open_web_profile(self):
        QDesktopServices.openUrl(QUrl(f"https://vrchat.com/home/user/{self.target_user_id}"))

    def _open_note(self):
        NoteDialog(self.client, self.target_user_id, self.target_display_name).exec()

    def _open_kick(self):
        KickDialog(self.client, self.target_user_id, self.target_display_name,
                   self.group_id, self.group_name or "this group").exec()

    def _open_ban(self):
        BanDialog(self.client, self.target_user_id, self.target_display_name,
                  self.group_id, self.group_name or "this group").exec()
