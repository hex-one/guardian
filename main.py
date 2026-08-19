"""
main.py

This is the app you actually run. It:
  1. Finds and watches your VRChat log file (using log_watcher.py)
  2. Keeps a live list of who's in your current instance
  3. Shows that list in a window
  4. Lets you right-click a player to pick an action (Note/Kick/Ban/Mute)

--------------------------------------------------------------------------
BEGINNER NOTES (PySide6 edition):

- PySide6 is the official Python bindings for Qt, a serious/professional GUI
  toolkit (lots of real desktop apps are built with Qt). It's a bigger
  library than Tkinter, but much more capable and better-looking, which is
  why we switched.

- Everything you see on screen is a "widget" (QListWidget, QLabel, etc).
  You build widgets, arrange them with "layouts" (QVBoxLayout here just
  means "stack things vertically"), and put the whole arrangement inside a
  QMainWindow.

- Qt apps are event-driven: instead of us writing a loop that checks "did
  anything happen yet?", we connect signals (like "the timer went off" or
  "the user right-clicked") to functions (called "slots" in Qt terms, but
  they're just regular Python functions/methods). Qt calls those functions
  for us when the event happens. Presence, not polling -- you respond to
  what actually occurs instead of constantly asking "are we there yet."

- QTimer is Qt's version of "call this function every N milliseconds."
  We use it to re-check the log file once a second, same idea as before,
  just Qt's way of doing it instead of Tkinter's `root.after`.

- This file still has ZERO VRChat-login/API code in it. Note/Kick/Ban/Mute
  are stubs for now -- they just print to the console and show a small
  popup, exactly like the Tkinter version did. Building this in layers on
  purpose, same as you don't skip to the final boss.
--------------------------------------------------------------------------
"""

import sys
import base64
import threading
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Checked FIRST, before any third-party imports below -- if PySide6 or
# requests aren't installed yet, this tells the user exactly what to run
# and exits cleanly, instead of the import lines below crashing with a
# raw ImportError traceback. Light the candle before you trust the fire.
# See dependency_check.py for how/why.
from dependency_check import ensure_dependencies
ensure_dependencies()

from PySide6.QtCore import QTimer, Qt, QUrl, QEvent, Signal, QPoint
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QPixmap, QFont, QIcon, QPainter, QPen, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QMenu,
    QMessageBox,
    QDialog,
    QToolButton,
    QInputDialog,
    QToolTip,
)

from log_watcher import LogWatcher, find_latest_log_file, compute_initial_state
from login_dialog import LoginDialog
from note_dialog import NoteDialog
from kick_dialog import KickDialog
from ban_dialog import BanDialog
from profile_dialog import ProfileDialog
from invite_dialog import InviteDialog
from invites_dialog import InvitesDialog
from aar_dialog import AARReportDialog
from config_dialog import ConfigDialog
from unban_dialog import UnbansDialog
from watchlist_dialog import WatchlistDialog
from about_dialog import AboutDialog
from group_picker_dialog import GroupPickerDialog
from startup_overlay import StartupOverlay
import app_updater
import group_mod_cache
import instance_info
import trust_rank
import player_profile
from player_entry import PlayerEntry
import temp_bans
import aar
import permission_check
import image_utils
import appearance_settings
import wallpaper_utils
import watchlist
import watchlist_categories
import watchlist_submit
import watchlist_sync_settings
import sheets_watchlist
import vote_kicks
import vote_kick_submit
from votes_dialog import VotesDialog
import crasher_activity
from crasher_activity_dialog import CrasherActivityDialog
import process_check
from glow import DANGER, WARNING
from icon_row_delegate import IconRowDelegate, GROUP_ICON_ROLE, GROUP_ICON_LABELS_ROLE

POLL_INTERVAL_MS = 1000               # how often we check the log file for new lines -- keep the pulse steady
TEMP_BAN_CHECK_INTERVAL_MS = 300_000   # 5 minutes -- safety-net poll; see _reschedule_next_temp_ban_check for the precise one
TEMP_BAN_CHECK_BUFFER_SECONDS = 120    # how long AFTER an expiry the precise check actually fires -- cushion against clock/scheduling slop landing a hair early and finding "not due yet"
DEPARTED_RETENTION_HOURS = 6          # how long a departed player stays in the list before being pruned
DEPARTED_PRUNE_INTERVAL_MS = 300_000  # 5 minutes -- doesn't need to be exact to the second
PENDING_REQUESTS_REFRESH_INTERVAL_MS = 120_000  # 2 minutes -- cheap enough (a handful of list-requests calls, no full permission re-scan) to check this often

# How close an avatar-change has to be, timing-wise, to a Udon exception
# to count as a plausible cause -- a heuristic, not a proven threshold.
# Wider catches more real hits but also more innocent bystanders who
# happened to switch avatars around the same time; this leans toward
# "narrow enough to mean something" over "catch everything."
CRASHER_CORRELATION_WINDOW = timedelta(seconds=30)

# How long the log has to sit motionless before _check_for_silent_crash
# bothers asking the OS whether VRChat.exe is even still running. Only
# gates HOW OFTEN that process check happens -- the check itself (plus
# requiring a validation warning with no graceful quit after it) is
# what actually prevents a normal quiet moment from reading as a crash.
SILENT_CRASH_SILENCE_THRESHOLD = timedelta(seconds=30)
SILENT_CRASH_CHECK_INTERVAL_MS = 20_000

# How long after a model-validation warning a 0MB avatar download still
# counts as "the same load" rather than an unrelated later one. The one
# example seen had them landing within the same second or two; this is
# generous on top of that, not a measured threshold.
ZERO_MB_PAIRING_WINDOW = timedelta(seconds=10)
ZERO_MB_PAIRING_WINDOW_MS = int(ZERO_MB_PAIRING_WINDOW.total_seconds() * 1000)

CRASHER_SIGNAL_LABELS = {
    "udon_exception": "a Udon exception",
    "model_validation_warning": "a model-validation warning",
    "validation_warning_with_zero_mb": "a model-validation warning paired with a 0MB avatar download",
}

COPYRIGHT_TEXT = "Copyright Ascended VRC Group 2026"
FOOTER_ICON_DEFAULT_COLOR = "#ece7fb"  # style.qss's default text color -- used when no custom font color is set


_BREAKABLE_CHARS = ":~(),"


def _wrappable(text: str) -> str:
    """Inserts a zero-width space after punctuation Qt's word-wrap can
    treat as a line-break opportunity. QLabel's setWordWrap(True) only
    breaks at actual whitespace -- a raw world/instance ID string (e.g.
    wrld_xxx:80170~group(grp_xxx)~groupAccessType(public)~region(eu))
    has none at all, so without this it can't wrap anywhere and just
    renders as one long unbroken line. That single label's minimum
    width then becomes the WHOLE WINDOW's minimum width (Qt's layout
    system sizes a window to fit every child's minimum size hint) --
    confirmed directly: ~1010px without this, ~410px with it, for the
    same real instance ID string. Not cosmetic -- this is why the
    window couldn't be resized narrower than that."""
    zero_width_space = chr(0x200B)
    for ch in _BREAKABLE_CHARS:
        text = text.replace(ch, ch + zero_width_space)
    return text


def _format_elapsed(delta: timedelta) -> str:
    total_minutes = max(int(delta.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class GuardianWindow(QMainWindow):
    # Qt signals are the supported way to hand data from a background
    # thread back to the GUI thread -- emitting from another thread
    # auto-queues the connected slot to run on this object's own
    # thread, rather than touching Qt widgets from the wrong thread.
    # See _start_group_mod_cache_refresh. Second argument is the pending-
    # join-request count computed in the same background pass -- see
    # _update_menu_bar_counts.
    group_mod_cache_updated = Signal(list, int)

    # Carries just the refreshed count from _refresh_pending_requests_
    # count's background thread back to the GUI thread -- the lighter,
    # more frequent sibling of group_mod_cache_updated above (see that
    # method for why this doesn't just reuse the full-scan signal).
    pending_requests_updated = Signal(int)

    def __init__(self, vrchat_client):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("Guardian")
        self.resize(420, 480)

        logo_path = Path(__file__).parent / "ascended_logo.png"
        if logo_path.exists():
            self.setWindowIcon(QIcon(str(logo_path)))

        # Kept for later features (notes/kick/ban/mute) -- this is the
        # already-authenticated session those will make API calls through.
        self.vrchat_client = vrchat_client

        # Every player seen this session, present OR departed -- a
        # departed player isn't removed immediately, just marked, so a mod
        # can still see/act on who was just here. Nobody who mattered
        # gets erased the instant they leave the room. Pruned automatically
        # after DEPARTED_RETENTION_HOURS (see _prune_departed_players).
        self.players: dict[str, PlayerEntry] = {}
        self._sort_mode = "Name"  # "Name", "Connection Time", "Rank", or "Status"
        self._sort_ascending = True  # flips if the same category is picked twice in a row
        self._watchlist_blink_state = False

        # Short rolling window of "who just switched avatars" -- (display_
        # name, avatar_name, when) tuples, pruned to CRASHER_CORRELATION_
        # WINDOW * 2 so it never grows unbounded. This is the ONLY thing
        # a udon-exception/validation-warning signal ever gets
        # correlated against; see _handle_crasher_signal_event. Purely
        # in-memory -- there's nothing worth persisting about an avatar
        # switch on its own, only what gets DERIVED from it.
        self._recent_avatar_changes: list = []

        # State for _check_for_silent_crash -- see that method for what
        # each one gates. None until we've actually seen the relevant
        # line at least once this session.
        self._last_validation_warning_at = None
        self._last_validation_warning_paired = False
        self._last_graceful_quit_at = None
        self._silent_crash_already_flagged = False

        # Trust rank/age-verified/VRC+ status barely ever change mid-session,
        # so we look them up once per player (when they first appear) and
        # cache them here, rather than re-fetching on every poll tick. All
        # three come from the same lookup, so one cache covers all of them.
        self._player_profile_cache: dict[str, player_profile.PlayerProfile] = {}

        # Set whenever we're in a GROUP instance (None for public/friends/
        # invite instances, since there's no group to ban someone FROM).
        self.current_group_id: str | None = None
        self.current_group_name: str | None = None
        # None = no group instance (n/a), True/False = whether the logged-in
        # user has instance-moderation permission in the current group.
        self.current_has_moderation_permission: bool | None = None
        # Same idea, for the Invite action.
        self.current_has_invite_permission: bool | None = None
        # The current world's recommended/max instance size -- applies
        # to any instance (group or not, capacity is a WORLD property),
        # unlike everything else above which is group-specific. None if
        # it couldn't be resolved; the player-count label just omits the
        # "/ capacity" part in that case rather than showing a guess.
        self.current_world_capacity: int | None = None

        # The current group's icon, as a QPixmap ready to hand to the list
        # delegate -- None when there's no group or the icon failed to load.
        # Cached per group_id (icon art is static, safe to reuse across
        # multiple visits to the same group's instances this session).
        self._group_icon_pixmap_cache: dict[str, QPixmap | None] = {}
        self._group_icon_data_uri_cache: dict[str, str | None] = {}
        self.current_group_icon_pixmap: QPixmap | None = None
        self._current_group_icon_data_uri: str | None = None
        self._status_base_label: str = ""

        # Whether group_mod_cache.py's background scan is currently
        # running -- while it is, the permission dot blinks yellow
        # instead of showing its normal red/green, via _perm_blink_
        # timer. Initialized here (before _build_ui/_start_log_watcher
        # can possibly call _render_status_line) so that call never
        # finds these missing, whichever of this init's later steps
        # happens to touch the status line first.
        self._group_mod_cache_scanning = False
        self._blink_state = False

        # Each player's own full public group list, fetched once (see
        # _ensure_trust_rank_cached) and reused by _player_moderated_
        # group_ids to figure out which of THOSE groups you also
        # moderate -- not tied to the current instance's group at all.
        self._player_group_ids_cache: dict[str, list[str]] = {}

        # Whichever groups the logged-in user can moderate, per the last
        # scan -- what "Grp Kick From"/"Grp Ban From" pick from. Loaded
        # from disk immediately (instant, no network) so the picker
        # isn't empty on the very first frame; _start_group_mod_cache_
        # refresh below then kicks off a fresh background scan to
        # replace it. See group_mod_cache.py for the full reasoning.
        # Raw world/instance IDs behind whatever's currently shown on
        # status_label -- kept for _copy_instance_web_link, since a
        # click can happen at any point, including before the first
        # instance has ever resolved.
        self.current_world_id = None
        self.current_instance_id = None

        self._group_mod_cache: list = group_mod_cache.load_cached()
        self.group_mod_cache_updated.connect(self._on_group_mod_cache_updated)
        self.pending_requests_updated.connect(self._on_pending_requests_refreshed)

        # Total pending join requests across every group can_review_join_
        # requests covers, for the "Requests (##)" menu label -- None
        # until the first scan actually completes (see _update_menu_bar_
        # counts), rather than guessing 0 or trusting a stale disk cache,
        # since pending requests are too volatile to treat a leftover
        # number as still true.
        self._pending_requests_count = None

        self._build_ui()

        # Each step marked active -> (done|error) around the real call
        # doing that work, with processEvents() forced in between so the
        # overlay actually repaints mid-sequence instead of the whole
        # checklist jumping to "done" at once when this synchronous run
        # finally finishes. Only the genuinely slow/networked startup
        # work gets a row -- _start_departed_pruner/_start_watchlist_
        # blinker are just timer setup (instant), and _start_update_
        # checker/_start_group_mod_cache_refresh are deliberately
        # background work that was never meant to hold up the window in
        # the first place, so they run after "Ready" rather than before.
        overlay = self.startup_overlay

        overlay.mark_step("settings_loaded", "active")
        self._apply_appearance()
        overlay.mark_step("settings_loaded", "done")
        QApplication.processEvents()

        overlay.mark_step("log_finding", "active")
        self._start_log_watcher()
        if self.watcher:
            overlay.mark_step("log_finding", "done")
        else:
            overlay.mark_step("log_finding", "error", "No VRChat log file found")
        QApplication.processEvents()

        overlay.mark_step("temp_bans_checked", "active")
        self._start_temp_ban_checker()
        overlay.mark_step("temp_bans_checked", "done")
        QApplication.processEvents()

        self._start_departed_pruner()
        self._start_watchlist_blinker()

        overlay.mark_step("watchlist_synced", "active")
        self._start_watchlist_sync()
        overlay.mark_step("watchlist_synced", "done")
        QApplication.processEvents()

        overlay.mark_step("ready", "done")
        overlay.reveal_and_hide()

        self._start_update_checker()
        self._start_group_mod_cache_refresh()
        self._start_pending_requests_refresh_timer()

    # -- UI setup ----------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        menu_bar = self.menuBar()

        # Left-to-right order: Requests, Bans, Watchlist, Reports -- read
        # it like a room, most urgent stuff nearest the door. Whatever's
        # actually waiting on YOU goes first, the AAR dropdown (looking
        # back, not acting now) sits last. The account menu off in the
        # far corner is its own separate creature entirely (setCornerWidget
        # below), untouched by any of this ordering.
        #
        # These three are plain top-level actions, not dropdown menus --
        # click one, land straight on the list, no submenu standing in
        # the way for just one thing. Bans/Requests wear a live "(##)"
        # count on their label -- see _update_menu_bar_counts -- so
        # they're kept as attributes instead of passing locals, to reach
        # back in and retarget that text later.
        self.requests_action = menu_bar.addAction("Requests", self._show_invites)
        self.bans_action = menu_bar.addAction("Bans", self._show_unbans)
        menu_bar.addAction("Watchlist", self._show_watchlist)
        self._update_menu_bar_counts()

        self.reports_menu = menu_bar.addMenu("Reports")
        self.reports_menu.setToolTipsVisible(True)

        view_aar_action = self.reports_menu.addAction("View AAR", self._show_aar_report)
        view_aar_action.setToolTip("After Action Review")

        show_bans_action = self.reports_menu.addAction(
            "Show Bans", lambda: self._show_aar_category("bans", "Bans Report")
        )
        show_bans_action.setToolTip("Show Bans from the AAR")

        show_kicks_action = self.reports_menu.addAction(
            "Show Kicks", lambda: self._show_aar_category("kicks", "Kicks Report")
        )
        show_kicks_action.setToolTip("Show Kicks from the AAR")

        show_notes_action = self.reports_menu.addAction(
            "Show Notes", lambda: self._show_aar_category("notes", "Notes Report")
        )
        show_notes_action.setToolTip("Show Notes from the AAR")

        show_wl_action = self.reports_menu.addAction(
            "Show WL", lambda: self._show_aar_category("watchlist", "Watchlist Report")
        )
        show_wl_action.setToolTip("Show Watchlist actions from the AAR")

        show_vk_action = self.reports_menu.addAction(
            "Show Vote Kicks", lambda: self._show_aar_category("vote_kicks", "Vote Kicks Report")
        )
        show_vk_action.setToolTip("Show observed vote-kick events from the AAR")

        show_crasher_action = self.reports_menu.addAction(
            "Show Crasher Activity", lambda: self._show_aar_category("crasher_activity", "Crasher Activity Report")
        )
        show_crasher_action.setToolTip(
            "Show possible crasher activity flags from the AAR -- circumstantial, not confirmed"
        )

        # setCornerWidget is Qt's actual supported mechanism for placing a
        # widget in the corner of a menu bar -- more reliable across
        # platforms than trying to fake right-alignment with an expanding
        # spacer action (which didn't render right under Windows' native
        # menu bar style). Using a dropdown (username -> Sign Out) rather
        # than a single one-click button is deliberate: it sits right next
        # to the window's close button, and a plain click there was too
        # easy to hit by accident. Some doors deserve two knocks.
        self.account_button = QToolButton()
        self.account_button.setObjectName("accountButton")
        self.account_button.setText(self.vrchat_client.display_name or "Account")
        self.account_button.setToolTip("Account menu")
        self.account_button.setAutoRaise(True)  # flat, blends into the menu bar
        self.account_button.setPopupMode(QToolButton.InstantPopup)
        self.account_menu = QMenu(self.account_button)
        self.account_menu.setToolTipsVisible(True)
        config_action = self.account_menu.addAction("Config...", self._show_config)
        config_action.setToolTip("Open settings")
        self.update_perms_action = self.account_menu.addAction("Update Perms", self._update_group_mod_cache)
        self.update_perms_action.setToolTip(
            "Rescans every group you're in for moderation permission -- what "
            "\"Grp Kick From\"/\"Grp Ban From\" pick from. Runs automatically "
            "at startup; use this to refresh it without relaunching."
        )
        sign_out_action = self.account_menu.addAction("Sign Out", self._sign_out)
        sign_out_action.setToolTip("Sign out of the current VRChat session")
        self.account_button.setMenu(self.account_menu)

        # The moderation-permission LED (see _render_status_line) used to
        # live tucked inside status_label's own rich text. Moved up here
        # instead, right beside the account button, so it catches your
        # eye without needing to go hunting through the status line for
        # it -- QMenuBar only ever gives you ONE corner widget per corner
        # though, so a small wrapper holds both under one roof.
        self.perm_led_label = QLabel("●")
        self.perm_led_label.setObjectName("permLedLabel")
        self.perm_led_label.setStyleSheet("font-size: 18px;")  # 50% bigger than the 12px base widget font
        self.perm_led_label.setVisible(False)  # nothing to show until an instance resolves a group
        # Held onto as attributes, not passing locals -- PySide will
        # otherwise garbage-collect the Python wrapper (and take the
        # underlying C++ object down with it, right out from under
        # setCornerWidget) the moment _build_ui returns. Same lesson the
        # delegate references elsewhere in this codebase already paid
        # for (see group_picker_dialog.py).
        self._corner_widget = QWidget()
        # A plain QWidget with no rule of its own quietly inherits the
        # global QWidget{background-color:#14121f} from style.qss -- one
        # shade darker than QMenuBar's own #1c1832, which shows up as a
        # mismatched block sitting on top of the menu bar like a patch
        # that doesn't match the cloth. Transparent lets the menu bar's
        # real color show through the way it should.
        self._corner_widget.setStyleSheet("background: transparent;")
        self._corner_layout = QHBoxLayout(self._corner_widget)
        self._corner_layout.setContentsMargins(0, 0, 0, 0)
        self._corner_layout.setSpacing(4)
        self._corner_layout.addWidget(self.perm_led_label)
        self._corner_layout.addWidget(self.account_button)
        menu_bar.setCornerWidget(self._corner_widget, Qt.TopRightCorner)

        layout = QVBoxLayout(central)

        self.status_label = QLabel("Looking for VRChat log file...")
        self.status_label.setObjectName("mainStatusLabel")
        self.status_label.setCursor(Qt.PointingHandCursor)
        self.status_label.setToolTip("Copy web link for this instance")
        self.status_label.installEventFilter(self)
        layout.addWidget(self.status_label)

        # Raw instance ID -- not human-friendly (a world GUID plus a
        # ~key(value) tag string), and clicking the status line above now
        # copies a proper web link to the same instance, so keeping this
        # around just for logs/support isn't worth the clutter anymore.
        # Left in place (not deleted) in case that changes again.
        self.instance_id_label = QLabel("")
        self.instance_id_label.setObjectName("instanceIdLabel")
        self.instance_id_label.setStyleSheet("color: gray; font-size: 10px;")
        self.instance_id_label.setWordWrap(True)
        self.instance_id_label.setVisible(False)
        layout.addWidget(self.instance_id_label)

        self.player_list_label = QLabel("Players in current instance:")
        self.player_list_label.setObjectName("playerListLabel")
        layout.addWidget(self.player_list_label)

        sort_row = QHBoxLayout()
        sort_row.addWidget(QLabel("Sort by:"))
        self.sort_combo = QComboBox()
        self.sort_combo.setObjectName("playerSortCombo")
        self.sort_combo.setToolTip("Sort the player list -- pick the same option again to reverse order")
        self.sort_combo.addItems(["Name", "Connection Time", "Rank", "Status"])
        # Connected AFTER addItems so populating the combo doesn't itself
        # trigger a refresh before the rest of the window exists.
        # textActivated (not currentTextChanged) fires every time the user
        # picks an item from the dropdown -- INCLUDING re-picking the one
        # already selected, which is exactly what's needed to detect
        # "selected the same category again" for the ascending/descending
        # flip below. currentTextChanged only fires when the value
        # actually changes, so it can't see a same-item reselection.
        self.sort_combo.textActivated.connect(self._on_sort_changed)
        sort_row.addWidget(self.sort_combo)
        sort_row.addStretch()
        layout.addLayout(sort_row)

        self.player_list = QListWidget()
        self.player_list.setObjectName("playerList")
        # Custom delegate draws the group-membership icon at the end of a
        # row -- QListWidgetItem's own .setIcon() only supports the LEFT
        # edge, so a plain QListWidget can't do this by itself. Kept as an
        # attribute (not a local variable) so PySide doesn't garbage-collect
        # the Python wrapper out from under the C++ side. Some things need
        # a real anchor to keep existing.
        self._player_list_delegate = IconRowDelegate(self.player_list)
        self.player_list.setItemDelegate(self._player_list_delegate)
        # This makes right-clicking trigger our own custom menu instead of
        # nothing happening (Qt's default is no context menu at all).
        self.player_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.player_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.player_list)

        self.update_banner = QLabel("")
        self.update_banner.setObjectName("updateBanner")
        self.update_banner.setTextFormat(Qt.RichText)
        self.update_banner.linkActivated.connect(self._handle_update_banner_link)
        self.update_banner.hide()
        layout.addWidget(self.update_banner)

        layout.addLayout(self._build_footer())

        # Parented to `central`, not the window itself -- covers the
        # whole content area (status line, instance list, footer) while
        # leaving the menu bar/account dropdown up top usable. Tried
        # sizing this to player_list's own geometry instead (narrower,
        # would have left the status line/footer visible too) but that
        # pushed the window wider -- reverted; central.rect() is the
        # version that actually behaves. resizeEvent below keeps it
        # matched to central's size as the window resizes. __init__
        # instruments the startup sequence right after this with
        # mark_step() calls; see startup_overlay.py.
        self.startup_overlay = StartupOverlay(central)
        self.startup_overlay.setGeometry(central.rect())
        self.startup_overlay.show()
        self.startup_overlay.raise_()
        self.startup_overlay.start_reveal_animation()

        # The wallpaper is a pre-baked PNG sized to whatever the player
        # list happened to be when it was last processed -- growing the
        # window past that size left gaps, since a QSS background-image
        # has no equivalent of CSS's background-size: cover to rescale
        # itself. This re-triggers _apply_appearance() (which re-reads
        # the viewport's CURRENT size and rebuilds the wallpaper to
        # match) after resizing actually stops, not on every frame of a
        # drag -- reprocessing involves a real blur pass, not something
        # to redo continuously while the mouse is still moving. See
        # resizeEvent below for what restarts this timer.
        self._wallpaper_resize_timer = QTimer(self)
        self._wallpaper_resize_timer.setSingleShot(True)
        self._wallpaper_resize_timer.timeout.connect(self._apply_appearance)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "startup_overlay"):
            self.startup_overlay.setGeometry(self.centralWidget().rect())
        if hasattr(self, "_wallpaper_resize_timer"):
            # Restarting on every event (not starting once) is what makes
            # this a debounce -- a resize drag fires this constantly, and
            # each call pushes the actual reprocessing further out until
            # the drag actually stops for 200ms straight.
            self._wallpaper_resize_timer.start(200)

    def _build_footer(self) -> QHBoxLayout:
        """
        Power (shut down, with confirmation) and gear (Config) on the
        left, copyright centered, heart (About/Support) on the far right
        -- same layout as Ascended STT's footer, same family of apps,
        same fingerprint. The three icon buttons' colors are set
        directly in _apply_appearance() (not here, and not via
        style.qss) so they track the user's custom font color the same
        way the heart does in STT, rather than getting stuck on
        style.qss's QToolButton base color.
        """
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(6, 4, 6, 2)
        # Zeroed out overall -- power/gear sit close together via the
        # small addSpacing() below, and the copyright label's stretch
        # factor is what actually keeps gear/heart from crowding it, not
        # this layout-wide spacing.
        footer_row.setSpacing(0)

        self.power_button = QToolButton()
        self.power_button.setObjectName("footerPowerButton")
        self.power_button.setText("⏻")
        self.power_button.setToolTip("Shut down Guardian")
        self.power_button.setCursor(Qt.PointingHandCursor)
        self.power_button.clicked.connect(self._confirm_shutdown)
        footer_row.addWidget(self.power_button)

        self.footer_gear_button = QToolButton()
        self.footer_gear_button.setObjectName("footerGearButton")
        self.footer_gear_button.setText("⚙")
        # U+2699 GEAR renders through Windows' color emoji font by
        # default -- a fixed silver/grey glyph baked into the font itself
        # that ignores the QSS `color:` set below entirely (confirmed:
        # the U+FE0E text-presentation selector alone didn't fix it, this
        # font swap does). Segoe UI Symbol is the older monochrome Windows
        # symbol font -- no color glyph table, so it actually respects
        # the color we set. Power/heart don't need this; only gear
        # defaults to emoji presentation on Windows. Even a small icon
        # deserves to wear the right color.
        self.footer_gear_button.setFont(QFont("Segoe UI Symbol"))
        self.footer_gear_button.setToolTip("Config")
        self.footer_gear_button.setCursor(Qt.PointingHandCursor)
        self.footer_gear_button.clicked.connect(self._show_config)
        footer_row.addWidget(self.footer_gear_button)

        self.copyright_label = QLabel(COPYRIGHT_TEXT)
        self.copyright_label.setObjectName("footerCopyrightLabel")
        self.copyright_label.setAlignment(Qt.AlignCenter)
        footer_row.addWidget(self.copyright_label, 1)

        self.heart_button = QToolButton()
        self.heart_button.setObjectName("footerHeartButton")
        self.heart_button.setText("♥")
        self.heart_button.setToolTip("About / Support")
        self.heart_button.setCursor(Qt.PointingHandCursor)
        self.heart_button.clicked.connect(self._show_about)
        footer_row.addWidget(self.heart_button)

        return footer_row

    def _confirm_shutdown(self):
        confirm = QMessageBox.question(
            self, "Shut Down Guardian", "Shut down Guardian?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm == QMessageBox.Yes:
            self.close()

    def _show_about(self):
        dialog = AboutDialog()
        dialog.exec()

    def _on_sort_changed(self, text: str):
        if text == self._sort_mode:
            # Same category picked again -- flip direction instead of
            # re-sorting the same way. Ask the same question twice, get a
            # different answer.
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_mode = text
            self._sort_ascending = True  # fresh category starts ascending
        # Guard against firing before player_list exists yet (addItems()
        # during _build_ui() can trigger this before the rest of the
        # window is constructed).
        if hasattr(self, "player_list"):
            self._refresh_list()

    def _show_context_menu(self, position):
        item = self.player_list.itemAt(position)
        if item is None:
            return  # right-clicked on empty space, nothing to do

        player_user_id = item.data(Qt.UserRole)  # set in _refresh_list
        # Look up the clean display name rather than the widget's text --
        # the widget text now has badges/departed info appended for
        # display, which we don't want leaking into note text, AAR
        # entries, or dialog titles. The decoration stays decoration.
        entry = self.players.get(player_user_id)
        player_name = entry.display_name if entry else item.text()

        menu = self._build_player_menu(player_user_id, player_name)

        # .exec() shows the menu at the given screen position and blocks
        # until the user picks something (or clicks away to dismiss it).
        menu.exec(self.player_list.viewport().mapToGlobal(position))

    def _build_player_menu(self, player_user_id: str, player_name: str) -> QMenu:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        profile_action = menu.addAction("View Profile", lambda: self._on_action("Profile", player_user_id, player_name))
        profile_action.setToolTip("Show this player's rank, badges, and notes")
        web_profile_action = menu.addAction("Open Web Profile ↗", lambda: self._on_action("WebProfile", player_user_id, player_name))
        web_profile_action.setToolTip("Open this player's profile on the VRChat website")
        menu.addSeparator()
        note_action = menu.addAction("Note", lambda: self._on_action("Note", player_user_id, player_name))
        note_action.setToolTip("Add or edit a note about this player")

        invite_action = menu.addAction("Invite", lambda: self._on_action("Invite", player_user_id, player_name))
        invite_action.setToolTip("Invite this player to join the current instance's group")
        kick_action = menu.addAction("Grp Kick", lambda: self._on_action("Kick", player_user_id, player_name))
        kick_action.setToolTip("Kick this player from the current instance's group")
        ban_action = menu.addAction("Grp Ban", lambda: self._on_action("Ban", player_user_id, player_name))
        ban_action.setToolTip("Ban this player from the current instance's group")

        # Greyed out (not hidden) when we know for certain the logged-in
        # user lacks moderation permission in this group -- same red-light
        # condition as the traffic-light dot next to the group name. Left
        # enabled for public/non-group instances (current_has_moderation_
        # permission is None there) since clicking still gives a clear
        # explanation rather than a silently-disabled option. Say why, not
        # just no.
        if self.current_has_moderation_permission is False:
            no_permission_tip = "You don't have permission to moderate this group's instances."
            kick_action.setEnabled(False)
            ban_action.setEnabled(False)
            kick_action.setToolTip(no_permission_tip)
            ban_action.setToolTip(no_permission_tip)

        if self.current_has_invite_permission is False:
            invite_action.setEnabled(False)
            invite_action.setToolTip("You don't have permission to invite people to this group.")

        # The "...From"/"...To" versions don't care where you're
        # standing at all -- they reach into every group the cached scan
        # found you welcome in (see group_mod_cache.py), so you can act
        # on a group that has nothing to do with the instance you're
        # actually in right now. Greyed out and quiet until that scan
        # has actually turned up something worth offering.
        invite_to_action = menu.addAction(
            "Invite To...", lambda: self._on_action("InviteTo", player_user_id, player_name)
        )
        invite_to_action.setToolTip("Invite this player to a group you choose from a picker")
        kick_from_action = menu.addAction(
            "Grp Kick From...", lambda: self._on_action("KickFrom", player_user_id, player_name)
        )
        kick_from_action.setToolTip("Kick this player from a group you choose from a picker")
        ban_from_action = menu.addAction(
            "Grp Ban From...", lambda: self._on_action("BanFrom", player_user_id, player_name)
        )
        ban_from_action.setToolTip("Ban this player from a group you choose from a picker")
        if not any(e.can_invite for e in self._group_mod_cache):
            no_invite_cache_tip = (
                "Still building the list of groups you can invite to -- try Account "
                "→ Update Perms, or wait for the background scan to finish."
            )
            invite_to_action.setEnabled(False)
            invite_to_action.setToolTip(no_invite_cache_tip)
        if not any(e.can_moderate for e in self._group_mod_cache):
            no_cache_tip = (
                "Still building the list of groups you can moderate -- try Account "
                "→ Update Perms, or wait for the background scan to finish."
            )
            kick_from_action.setEnabled(False)
            ban_from_action.setEnabled(False)
            kick_from_action.setToolTip(no_cache_tip)
            ban_from_action.setToolTip(no_cache_tip)

        watchlist_label = "Remove from WatchList" if player_user_id in watchlist.get_watched_ids() else "Add to WatchList"
        menu.addSeparator()
        watchlist_action = menu.addAction(watchlist_label, lambda: self._on_action("WatchList", player_user_id, player_name))
        watchlist_action.setToolTip("Toggle this player's watchlist membership")

        votes_action = menu.addAction("Votes", lambda: self._on_action("Votes", player_user_id, player_name))
        if vote_kicks.get_events_for_target(player_user_id, player_name):
            votes_action.setToolTip("View known vote-kick events for this player")
        else:
            votes_action.setEnabled(False)
            votes_action.setToolTip("No known vote-kick events for this player.")

        crasher_action = menu.addAction(
            "Crasher Activity", lambda: self._on_action("CrasherActivity", player_user_id, player_name)
        )
        if crasher_activity.get_flags_for_target(player_user_id, player_name):
            crasher_action.setToolTip("View possible crasher activity flags for this player (circumstantial)")
        else:
            crasher_action.setEnabled(False)
            crasher_action.setToolTip("No possible crasher activity observed for this player.")

        return menu

    def _on_action(self, action_name: str, player_user_id: str, player_name: str):
        if action_name == "Profile":
            dialog = ProfileDialog(self.vrchat_client, player_user_id, player_name,
                                    self.current_group_id, self.current_group_name,
                                    self.current_has_moderation_permission)
            dialog.exec()

        elif action_name == "WebProfile":
            QDesktopServices.openUrl(QUrl(f"https://vrchat.com/home/user/{player_user_id}"))

        elif action_name == "Note":
            dialog = NoteDialog(self.vrchat_client, player_user_id, player_name)
            dialog.exec()

        elif action_name == "Invite":
            if not self.current_group_id:
                QMessageBox.information(
                    self, "Not a group instance",
                    "Invite only works in group instances (there has to be a group "
                    "to invite someone TO). This instance doesn't have one.",
                )
                return
            dialog = InviteDialog(self.vrchat_client, player_user_id, player_name,
                                   self.current_group_id, self.current_group_name or "this group")
            dialog.exec()

        elif action_name == "WatchList":
            if player_user_id in watchlist.get_watched_ids():
                watchlist.remove_entries([player_user_id])
                aar.save_entry(aar.AAREntry(
                    timestamp=aar.now_iso(),
                    moderator=self.vrchat_client.display_name or "unknown",
                    action="watchlist_remove",
                    target_display_name=player_name,
                    target_user_id=player_user_id,
                    details="Removed from watchlist",
                    success=True,
                ))
                self._refresh_list()
            else:
                category_labels = [watchlist_categories.CATEGORIES[k].label for k in watchlist_categories.CATEGORY_ORDER]
                chosen_label, ok = QInputDialog.getItem(
                    self, "Add to Watchlist", f"Category for {player_name}:", category_labels, 0, False
                )
                if not ok:
                    return
                category_key = next(k for k in watchlist_categories.CATEGORY_ORDER
                                     if watchlist_categories.CATEGORIES[k].label == chosen_label)

                reason, ok = QInputDialog.getText(
                    self, "Add to Watchlist", f"Reason for watching {player_name} (optional):"
                )
                if not ok:
                    return

                # Routes through the shared submission logic -- if Sheets
                # sync is configured, this actually submits to the shared
                # list (with the fresh duplicate/cleared check), not just a
                # local-only add.
                status = watchlist_submit.submit_watchlist_entry(
                    self, self.vrchat_client, player_user_id, player_name, reason.strip(), category_key
                )
                QMessageBox.information(self, "Watchlist", status)
                self._refresh_list()

        elif action_name == "Votes":
            dialog = VotesDialog(player_user_id, player_name)
            dialog.exec()

        elif action_name == "CrasherActivity":
            dialog = CrasherActivityDialog(self.vrchat_client, player_user_id, player_name)
            dialog.exec()
            self._refresh_list()  # in case clearing their last flag should drop the amber triangle

        elif action_name == "Kick":
            if not self.current_group_id:
                QMessageBox.information(
                    self, "Not a group instance",
                    "Grp Kick (group membership kick) only works in group instances. "
                    "This instance doesn't have an owning group.",
                )
                return
            dialog = KickDialog(self.vrchat_client, player_user_id, player_name,
                                 self.current_group_id, self.current_group_name or "this group")
            dialog.exec()

        elif action_name == "Ban":
            if not self.current_group_id:
                QMessageBox.information(
                    self, "Not a group instance",
                    "Grp Ban only works in group instances (there has to be a group "
                    "to ban someone FROM). This instance doesn't have one.",
                )
                return
            dialog = BanDialog(self.vrchat_client, player_user_id, player_name,
                                self.current_group_id, self.current_group_name or "this group")
            dialog.exec()
            self._refresh_list()  # in case the banned player should visually update
            self._reschedule_next_temp_ban_check()  # in case a new temp ban expires sooner than whatever was scheduled

        elif action_name in ("KickFrom", "BanFrom"):
            self._open_group_action_picker(action_name, player_user_id, player_name)
            self._refresh_list()
            self._reschedule_next_temp_ban_check()

        elif action_name == "InviteTo":
            self._open_group_action_picker(action_name, player_user_id, player_name)

    def _open_group_action_picker(self, action_name: str, player_user_id: str, player_name: str):
        """The "...From"/"...To" flow: pick a group off the cached
        shortlist, then check that permission is STILL real, honestly
        real, before opening the same Kick/Ban/Invite dialog the
        current-instance versions already use. The cache is a shortlist
        for a picker, not scripture -- a permission taken back since the
        last scan needs to actually stop this cold, not just sit there
        as an outdated line nobody double-checked."""
        is_invite = action_name == "InviteTo"
        relevant_entries = [e for e in self._group_mod_cache if (e.can_invite if is_invite else e.can_moderate)]

        if not relevant_entries:
            noun = "invite people to" if is_invite else "moderate"
            QMessageBox.information(
                self, "No groups cached yet",
                f"Still building the list of groups you can {noun}. Try Account "
                "→ Update Perms in a moment, or wait for the background scan to finish.",
            )
            return

        # Draws each entry's icon through the SAME well _get_group_icon
        # already keeps filled for the player list and the status line --
        # a group already seen there costs nothing extra to show again
        # here, and a face fetched here for the first time gets carried
        # everywhere else in turn. Faces remembered, never fetched twice.
        icon_pixmaps = {}
        for entry in relevant_entries:
            pixmap, _data_uri = self._get_group_icon(entry.group_id, entry.icon_url)
            if pixmap:
                icon_pixmaps[entry.group_id] = pixmap

        if is_invite:
            title = "Invite To — Choose a Group"
        else:
            verb = "Kick" if action_name == "KickFrom" else "Ban"
            title = f"Grp {verb} From — Choose a Group"
        picker = GroupPickerDialog(relevant_entries, icon_pixmaps, title=title)
        if picker.exec() != QDialog.Accepted or not picker.selected_entry:
            return
        entry = picker.selected_entry

        details = self.vrchat_client.get_group_details(entry.group_id)
        if details.status != "success":
            QMessageBox.warning(
                self, "Couldn't verify permission",
                f"Couldn't confirm your permission in {entry.group_name} right now: {details.error_message}",
            )
            return

        catalog = self.vrchat_client.get_group_permission_catalog(entry.group_id)
        if is_invite:
            still_has_permission = permission_check.has_group_invite_permission(details.my_permissions, catalog)
            permission_noun = "invite permission in"
        else:
            still_has_permission = permission_check.has_instance_moderation_permission(details.my_permissions, catalog)
            permission_noun = "moderation permission in"
        if not still_has_permission:
            QMessageBox.warning(
                self, "Permission no longer valid",
                f"You no longer have {permission_noun} {entry.group_name}. "
                "Account → Update Perms will refresh the shortlist.",
            )
            return

        if action_name == "KickFrom":
            dialog = KickDialog(self.vrchat_client, player_user_id, player_name, entry.group_id, entry.group_name)
        elif action_name == "BanFrom":
            dialog = BanDialog(self.vrchat_client, player_user_id, player_name, entry.group_id, entry.group_name)
        else:
            dialog = InviteDialog(self.vrchat_client, player_user_id, player_name, entry.group_id, entry.group_name)
        dialog.exec()

    # -- Group moderation-permission cache ---------------------------------

    def _start_group_mod_cache_refresh(self):
        self._set_update_perms_busy(True)
        self._group_mod_cache_scanning = True
        self._start_perm_blink()

        def worker():
            entries = group_mod_cache.refresh(self.vrchat_client)

            # This same scan already told us which groups open their door
            # to join-request review -- one more call per THOSE groups
            # (not every group in reach) is all it takes to turn that
            # into the "Requests (##)" count up top. A group that stumbles
            # on this check just doesn't add to the total, same forgiving
            # rule as the permission check itself: one bad door doesn't
            # close the whole hallway.
            pending_requests_count = 0
            for entry in entries:
                if not entry.can_review_join_requests:
                    continue
                result = self.vrchat_client.get_group_join_requests(entry.group_id)
                if result.status == "success":
                    pending_requests_count += len(result.requests)

            try:
                self.group_mod_cache_updated.emit(entries, pending_requests_count)
            except RuntimeError:
                # The underlying C++ window is already gone (signed out
                # or closed while this was still running) -- nothing
                # left to update, and nothing to do about it either.
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _update_group_mod_cache(self):
        """Manual "Update Perms" trigger -- same scan _start_group_mod_
        cache_refresh runs automatically at startup, just callable on
        demand without relaunching. Also the manual refresh point for
        the Requests (##) count, since it comes from this same scan."""
        self._start_group_mod_cache_refresh()

    def _on_group_mod_cache_updated(self, entries, pending_requests_count):
        self._group_mod_cache = entries
        self._pending_requests_count = pending_requests_count
        self._set_update_perms_busy(False)
        self._group_mod_cache_scanning = False
        self._stop_perm_blink()
        self._update_menu_bar_counts()

    def _start_pending_requests_refresh_timer(self):
        """
        The Requests (##) count used to only ever change at startup or
        on a manual Update Perms click -- a new join request showing up
        mid-session just sat invisible until one of those happened. This
        is the fix: a periodic, MUCH cheaper re-poll than the full
        group_mod_cache scan (see _refresh_pending_requests_count below
        for why it can afford to run every couple minutes instead).
        """
        self.pending_requests_timer = QTimer(self)
        self.pending_requests_timer.timeout.connect(self._refresh_pending_requests_count)
        self.pending_requests_timer.start(PENDING_REQUESTS_REFRESH_INTERVAL_MS)

    def _refresh_pending_requests_count(self):
        """
        Lighter periodic sibling of _start_group_mod_cache_refresh --
        re-polls join requests for whichever groups the last FULL scan
        already found reviewable, without re-running that scan's much
        larger per-group permission check just to keep this one number
        honest. Skips a tick entirely if a full scan is already in
        flight (Update Perms, or the startup scan still finishing) so
        the two never race to write the same count.
        """
        if self._group_mod_cache_scanning:
            return
        entries = self._group_mod_cache

        def worker():
            pending_requests_count = 0
            for entry in entries:
                if not entry.can_review_join_requests:
                    continue
                result = self.vrchat_client.get_group_join_requests(entry.group_id)
                if result.status == "success":
                    pending_requests_count += len(result.requests)

            try:
                self.pending_requests_updated.emit(pending_requests_count)
            except RuntimeError:
                pass  # window's already gone -- nothing left to update

        threading.Thread(target=worker, daemon=True).start()

    def _on_pending_requests_refreshed(self, pending_requests_count):
        self._pending_requests_count = pending_requests_count
        self._update_menu_bar_counts()

    def _update_menu_bar_counts(self):
        """Bans reads straight from the local temp-ban tracker
        (temp_bans.py) -- no network call, no waiting, true the instant
        you look at it. Requests carries the last group_mod_cache scan's
        count forward (see _start_group_mod_cache_refresh) -- that scan
        is the only thing that actually knows this number; asking again
        on its own clock would just spend API calls on a menu badge, so
        it moves at the same startup/"Update Perms" pace as the
        permission shortlist it rides in on. Guarded with hasattr, same
        caution as _set_update_perms_busy above -- nothing calls this
        before _build_ui raises the menu bar into being today, but no
        reason to leave that a landmine if the order ever shifts."""
        if hasattr(self, "bans_action"):
            self.bans_action.setText(f"Bans ({len(temp_bans.load_temp_bans())})")
        if hasattr(self, "requests_action"):
            count_text = str(self._pending_requests_count) if self._pending_requests_count is not None else "…"
            self.requests_action.setText(f"Requests ({count_text})")

    def _set_update_perms_busy(self, busy: bool):
        if not hasattr(self, "update_perms_action"):
            return  # menu not built yet -- the very first startup call is fine to skip
        self.update_perms_action.setEnabled(not busy)
        self.update_perms_action.setText("Update Perms (scanning...)" if busy else "Update Perms")

    def _start_perm_blink(self):
        if not hasattr(self, "_perm_blink_timer"):
            self._perm_blink_timer = QTimer(self)
            self._perm_blink_timer.timeout.connect(self._on_perm_blink_tick)
        self._blink_state = True
        self._render_status_line()
        self._perm_blink_timer.start(400)  # a quick flash, not a slow pulse -- meant to catch the eye

    def _stop_perm_blink(self):
        if hasattr(self, "_perm_blink_timer"):
            self._perm_blink_timer.stop()
        self._render_status_line()  # back to the real red/green, not left mid-blink

    def _on_perm_blink_tick(self):
        self._blink_state = not self._blink_state
        self._render_status_line()

    def _show_aar_report(self):
        dialog = AARReportDialog()
        dialog.exec()

    def _show_aar_category(self, category: str, title: str):
        dialog = AARReportDialog(action_filter=aar.ACTION_CATEGORIES[category], title=title)
        dialog.exec()

    def _show_unbans(self):
        dialog = UnbansDialog(self.vrchat_client)
        dialog.exec()
        self._reschedule_next_temp_ban_check()  # in case an early unban changed who's soonest

    def _show_watchlist(self):
        dialog = WatchlistDialog(self.vrchat_client)
        dialog.exec()
        self._refresh_list()  # in case additions/removals affect who's highlighted right now

    def _show_invites(self):
        if not any(e.can_review_join_requests for e in self._group_mod_cache):
            QMessageBox.information(
                self, "No groups cached yet",
                "Still building the list of groups you can review join requests for. "
                "Try Account → Update Perms in a moment, or wait for the background scan to finish.",
            )
            return

        eligible = [e for e in self._group_mod_cache if e.can_review_join_requests]

        # Same icon-cache reuse _open_group_action_picker already leans
        # on -- a group's face, once fetched for the player list or
        # another picker, costs nothing to borrow again here.
        icon_pixmaps = {}
        for entry in eligible:
            pixmap, _data_uri = self._get_group_icon(entry.group_id, entry.icon_url)
            if pixmap:
                icon_pixmaps[entry.group_id] = pixmap

        dialog = InvitesDialog(self.vrchat_client, eligible, icon_pixmaps)
        dialog.exec()

    def _show_config(self):
        dialog = ConfigDialog()
        # Live-apply appearance changes while the dialog is still open,
        # rather than waiting for it to close. Change should feel
        # immediate, not delayed.
        dialog.appearance_applied.connect(self._apply_appearance)
        dialog.exec()
        # Sync settings (URLs) aren't live-applied the same way -- just
        # restart the sync with whatever's saved now that the dialog's
        # closed, in case they were added/changed.
        self._start_watchlist_sync()

    def _apply_appearance(self):
        """
        Reads appearance_settings and applies font/color app-wide, plus a
        blurred/darkened wallpaper on just the player list -- or, if
        Overlay Mode is on, no wallpaper at all and font-colored borders
        instead, built for pinning Guardian in VR via XSOverlay/OVR
        Toolkit. Called once at startup and again any time Config's
        "Apply Appearance" is used. Deliberately never touches player_list
        item colors set via setForeground() (trust rank) -- those are a
        moderation signal, not decoration, and Qt's item-level foreground
        role takes priority over a general stylesheet color anyway. Some
        colors carry meaning and don't get to be repainted on a whim.
        """
        settings = appearance_settings.load_settings()

        window_style_parts = []
        if settings.font_family or settings.font_color:
            font = QFont(settings.font_family) if settings.font_family else self.font()
            self.setFont(font)
            if settings.font_color:
                window_style_parts.append(f"QWidget {{ color: {settings.font_color}; }}")

        # Overlay Mode: for pinning Guardian in VR via XSOverlay/OVR
        # Toolkit's window capture -- same reasoning as Ascended STT's
        # version of this. Structural container borders (list/table/
        # tree, text inputs, combo boxes) switch from the theme's fixed
        # purple to the font color, so the panel reads as one consistent
        # color in a headset. Left alone on purpose: the action-colored
        # buttons (danger/success/etc.) and every trust-rank/watchlist
        # color -- those carry real meaning, not just decoration, and
        # overlay mode isn't the excuse to flatten that.
        if settings.overlay_mode:
            outline_color = settings.font_color or FOOTER_ICON_DEFAULT_COLOR
            window_style_parts.append(
                f"QListWidget, QTableWidget, QTreeWidget, QLineEdit, QTextEdit, "
                f"QPlainTextEdit, QSpinBox, QComboBox {{ border: 1px solid {outline_color}; }}"
            )

        if window_style_parts:
            self.setStyleSheet("\n".join(window_style_parts))

        # The footer icons sit inside that same QWidget-wide stylesheet
        # scope, but style.qss's QToolButton base rule (a more specific
        # type selector) would otherwise always win over it and pin them
        # to the theme's default color -- setting each icon's own
        # stylesheet directly sidesteps that, so they track the custom
        # font color the same way the heart icon does in Ascended STT.
        footer_icon_color = settings.font_color or FOOTER_ICON_DEFAULT_COLOR
        footer_icon_style = (
            f"QToolButton {{ background: transparent; border: none; "
            f"font-size: 16px; padding: 1px 2px; color: {footer_icon_color}; }}"
            f"QToolButton:hover {{ background-color: #2a2452; border-radius: 4px; }}"
        )
        for footer_button in (self.power_button, self.footer_gear_button, self.heart_button):
            footer_button.setStyleSheet(footer_icon_style)

        # Falls back to the Ascended logo as a default wallpaper when the
        # user hasn't chosen one of their own in Config -- gives the list
        # a branded look out of the box rather than a blank background.
        # A room should never feel empty by default.
        default_logo_path = Path(__file__).parent / "ascended_logo.png"
        wallpaper_source = settings.wallpaper_path or (
            str(default_logo_path) if default_logo_path.exists() else None
        )

        # The wallpaper has to be applied to the list's VIEWPORT, not the
        # QListWidget itself. QListWidget doesn't paint its own background --
        # its internal (anonymous) viewport child does, and style.qss's
        # blanket `QWidget { background-color: ... }` rule matches that
        # viewport directly. A style sheet set on the outer QListWidget only
        # reaches the viewport through a propagation fallback Qt uses when
        # the viewport has no rule of its own -- since the app-wide sheet
        # already gives the viewport one, that fallback never kicks in, and
        # the wallpaper silently loses. Targeting the viewport's own
        # setStyleSheet() sidesteps that entirely.
        viewport = self.player_list.viewport()
        if wallpaper_source and not settings.overlay_mode:
            size = viewport.size()
            if size.width() > 0 and size.height() > 0:
                wallpaper = wallpaper_utils.build_wallpaper(wallpaper_source, size, mode=settings.wallpaper_mode)
                cache_path = wallpaper_utils.save_wallpaper_cache(wallpaper) if wallpaper else None
                if cache_path:
                    viewport.setStyleSheet(
                        f'background-image: url("{cache_path}"); '
                        f'background-position: center; '
                        f'background-repeat: no-repeat;'
                    )
        else:
            # No wallpaper configured and no default logo found -- make
            # sure any previously-applied one doesn't linger from an
            # earlier session/Apply click. Reverts to style.qss's plain
            # themed list background, not a blank/white one. Let go
            # cleanly, don't leave a ghost of the last thing behind.
            viewport.setStyleSheet("")

        if hasattr(self, "poll_timer") and settings.poll_interval_ms:
            self.poll_timer.setInterval(settings.poll_interval_ms)

    def _sign_out(self):
        self.sign_out_requested = True
        if hasattr(self, "poll_timer"):
            self.poll_timer.stop()
        if hasattr(self, "silent_crash_timer"):
            self.silent_crash_timer.stop()
        if hasattr(self, "temp_ban_timer"):
            self.temp_ban_timer.stop()
        if hasattr(self, "temp_ban_precise_timer"):
            self.temp_ban_precise_timer.stop()
        if hasattr(self, "departed_prune_timer"):
            self.departed_prune_timer.stop()
        if hasattr(self, "watchlist_blink_timer"):
            self.watchlist_blink_timer.stop()
        if hasattr(self, "watchlist_sync_timer"):
            self.watchlist_sync_timer.stop()
        if hasattr(self, "pending_requests_timer"):
            self.pending_requests_timer.stop()
        if hasattr(self, "_perm_blink_timer"):
            self._perm_blink_timer.stop()
        if hasattr(self, "_wallpaper_resize_timer"):
            self._wallpaper_resize_timer.stop()
        # Clears the session cookie so the login screen actually prompts
        # again -- deliberately leaves the remembered USERNAME in place
        # (that's a convenience, not a login credential) so signing back
        # in only takes a password, not re-typing everything.
        self.vrchat_client.clear_saved_session()
        self.close()

    # -- Temp ban expiry ------------------------------------------------

    def _start_temp_ban_checker(self):
        # Two timers working together, not one:
        #
        # - temp_ban_timer is a plain 5-minute safety net, always
        #   running regardless of anything else below. If the precise
        #   timer ever gets out of sync (a bug, a system sleep/wake
        #   that loses a QTimer, whatever), this still catches an
        #   overdue unban within 5 minutes.
        #
        # - temp_ban_precise_timer is a single-shot retargeted every
        #   time the list changes (a ban added, one removed early, one
        #   auto-expired) to fire shortly after whichever ban is due
        #   soonest -- see _reschedule_next_temp_ban_check. This is
        #   what actually makes a short (minutes-long) temp ban feel
        #   responsive instead of waiting for the next 5-minute tick.
        self.temp_ban_timer = QTimer(self)
        self.temp_ban_timer.timeout.connect(self._check_temp_ban_expirations)
        self.temp_ban_timer.start(TEMP_BAN_CHECK_INTERVAL_MS)

        self.temp_ban_precise_timer = QTimer(self)
        self.temp_ban_precise_timer.setSingleShot(True)
        self.temp_ban_precise_timer.timeout.connect(self._check_temp_ban_expirations)

        # Check once immediately on startup, in case something expired
        # while Guardian wasn't running -- this also fires the first
        # precise reschedule for whatever's left.
        self._check_temp_ban_expirations()

    def _check_temp_ban_expirations(self):
        for ban in temp_bans.due_for_unban():
            result = self.vrchat_client.unban_from_group(ban.group_id, ban.user_id)

            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(),
                moderator=self.vrchat_client.display_name or "unknown",
                action="unban",
                target_display_name=ban.display_name,
                target_user_id=ban.user_id,
                details=f"Automatic unban -- temp ban from {ban.banned_at} expired",
                success=(result.status == "success"),
                error_message=result.error_message,
            ))

            # Remove from the local tracker either way -- if the unban call
            # itself failed, retrying it forever on a stale entry isn't
            # useful; the failure is already logged to the AAR for a mod
            # to notice and handle manually if needed.
            temp_bans.remove_temp_ban(ban.user_id, ban.group_id)

        self._reschedule_next_temp_ban_check()

    def _reschedule_next_temp_ban_check(self):
        """Points the precise one-shot timer at whichever remaining temp
        ban expires soonest, plus a small buffer -- called after every
        check, and after every place the list can change (a ban added,
        one unbanned early). The 5-minute safety-net timer keeps
        running the whole time regardless, so this never being called
        somewhere it should have been just means "wait up to 5 minutes
        longer," not "never."""
        if not hasattr(self, "temp_ban_precise_timer"):
            return  # not started yet -- _start_temp_ban_checker will call this itself once it is
        self.temp_ban_precise_timer.stop()

        bans = temp_bans.load_temp_bans()
        self._update_menu_bar_counts()  # every place that can change the list routes through here
        if not bans:
            return  # nothing waiting -- next add_temp_ban's caller reschedules

        now = datetime.now(timezone.utc)
        soonest = min(datetime.fromisoformat(b.expires_at) for b in bans)
        delay_seconds = (soonest - now).total_seconds() + TEMP_BAN_CHECK_BUFFER_SECONDS
        self.temp_ban_precise_timer.start(max(int(delay_seconds * 1000), 1000))

    # -- Departed player pruning ------------------------------------------

    def _start_departed_pruner(self):
        self.departed_prune_timer = QTimer(self)
        self.departed_prune_timer.timeout.connect(self._prune_departed_players)
        self.departed_prune_timer.start(DEPARTED_PRUNE_INTERVAL_MS)

    def _prune_departed_players(self):
        cutoff = datetime.now() - timedelta(hours=DEPARTED_RETENTION_HOURS)
        any_departed = False
        to_remove = []

        for user_id, entry in self.players.items():
            if entry.status != "departed":
                continue
            any_departed = True
            if entry.departed_at and entry.departed_at <= cutoff:
                to_remove.append(user_id)

        for user_id in to_remove:
            del self.players[user_id]

        # Refresh whenever there's ANY departed player on screen, not just
        # when one got pruned -- otherwise their "left Xh Ym ago" text sits
        # frozen at whatever it said the moment they left, since nothing
        # else re-triggers a repaint of that label on its own. This runs
        # every DEPARTED_PRUNE_INTERVAL_MS regardless, which is exactly the
        # "update every few minutes, doesn't need to be real-time" cadence
        # that's fine here. Time keeps moving, the display should too.
        if any_departed or to_remove:
            self._refresh_list()

    # -- Watchlist blinking ------------------------------------------------

    WATCHLIST_BLINK_INTERVAL_MS = 600

    def _start_watchlist_blinker(self):
        self.watchlist_blink_timer = QTimer(self)
        self.watchlist_blink_timer.timeout.connect(self._tick_watchlist_blink)
        self.watchlist_blink_timer.start(self.WATCHLIST_BLINK_INTERVAL_MS)

    def _tick_watchlist_blink(self):
        self._watchlist_blink_state = not self._watchlist_blink_state
        # Only bother refreshing the whole list if someone with a
        # BLINKING-category watchlist entry is currently present -- VIP/
        # Creator/PoI entries never blink, so their presence alone
        # shouldn't trigger a refresh here; keeps this cheap the vast
        # majority of the time. No alarm rings in an empty room.
        watched_entries = watchlist.get_watched_entries()
        has_blinking_present = any(
            uid in watched_entries and watchlist_categories.get_category(watched_entries[uid].category).blinking
            for uid in self.players
        )
        if has_blinking_present:
            self._refresh_list()

    # -- Watchlist cloud sync (Google Sheets) -------------------------------

    def _start_update_checker(self):
        # A single deferred one-shot, not a repeating timer -- both
        # checks are cheap, quiet, and only meaningful once per
        # session; there's no reason to keep asking GitHub the same
        # question every few minutes while Guardian's just sitting
        # open. singleShot(0, ...) instead of calling this directly
        # from __init__ so it runs after the window's first paint,
        # same reasoning _sync_watchlist_from_sheet already applies
        # via "once immediately on startup."
        QTimer.singleShot(0, self._check_for_updates)

    def _check_for_updates(self):
        app_dir = app_updater.get_app_dir()
        local_version = app_updater.read_local_content_version(app_dir)
        remote_version = app_updater.fetch_remote_content_version()
        if remote_version is not None and remote_version > local_version:
            ok, new_version, _error = app_updater.download_and_apply_content_update(app_dir, log=print)
            if ok:
                print(f"Content updated to v{new_version}. Some changes need a restart to show up.")

        tag, url = app_updater.fetch_latest_release()
        if tag and url and app_updater.is_newer_version(tag, app_updater.APP_VERSION):
            self.update_banner.setText(
                f"Update available: {tag} (you're on v{app_updater.APP_VERSION}) - "
                f'<a href="{url}">Get it</a> &nbsp; <a href="#dismiss">&#10005;</a>'
            )
            self.update_banner.show()

    def _handle_update_banner_link(self, link):
        if link == "#dismiss":
            self.update_banner.hide()
        else:
            QDesktopServices.openUrl(QUrl(link))

    def _start_watchlist_sync(self):
        if hasattr(self, "watchlist_sync_timer"):
            self.watchlist_sync_timer.stop()

        settings = watchlist_sync_settings.load_settings()
        if not watchlist_sync_settings.is_configured():
            return  # nothing to do until Config has both URLs set

        self._sync_watchlist_from_sheet()  # once immediately on startup...
        self.watchlist_sync_timer = QTimer(self)
        self.watchlist_sync_timer.timeout.connect(self._sync_watchlist_from_sheet)
        self.watchlist_sync_timer.start(max(settings.sync_interval_minutes, 1) * 60_000)  # ...then repeating

    def _sync_watchlist_from_sheet(self):
        settings = watchlist_sync_settings.load_settings()
        if not watchlist_sync_settings.is_configured():
            return

        result = sheets_watchlist.fetch_all(settings.csv_url)
        if result.status != "success":
            return  # a failed background sync is silent -- Watchlist window's Sync Now surfaces errors explicitly

        active_statuses = ("approved", "pending_removal")
        inactive_statuses = ("cleared", "rejected", "removed")

        for sheet_entry in result.entries:
            if sheet_entry.status not in active_statuses:
                continue
            watchlist.upsert_entry(watchlist.WatchlistEntry(
                user_id=sheet_entry.user_id,
                display_name=sheet_entry.display_name,
                reason=sheet_entry.reason,
                added_at=sheet_entry.submitted_at or aar.now_iso(),
                category=sheet_entry.category,
            ))

        # Same prune step as the Watchlist window's Sync Now -- without
        # this, a confirmed removal (or any other status change away from
        # "active") would never actually take effect locally; the stale
        # entry would just sit there forever since upserting only ever
        # adds/updates, never removes.
        inactive_ids = {e.user_id for e in result.entries if e.status in inactive_statuses}
        to_prune = [uid for uid in watchlist.get_watched_ids() if uid in inactive_ids]
        if to_prune:
            watchlist.remove_entries(to_prune)

        self._refresh_list()

    # Traffic-light colors for the moderation-permission dot. SCANNING
    # isn't a steady state like the other two -- it's blinked on/off
    # by _perm_blink_timer while group_mod_cache.py's background scan
    # is running, so it reads as "something's happening right now"
    # rather than a fourth color to memorize alongside red/green.
    PERMISSION_GREEN = "#2ECC71"
    PERMISSION_RED = "#E74C3C"
    PERMISSION_SCANNING = "#F1C40F"

    def _update_instance_display(self, world_id: str, instance_id: str):
        self.current_world_id = world_id
        self.current_instance_id = instance_id
        self.instance_id_label.setText(_wrappable(f"{world_id}:{instance_id}"))
        self.status_label.setText("Resolving instance name...")
        QApplication.processEvents()

        # Pure text parsing (no network call) -- pulls out the group ID (if
        # any) so Ban/Kick know what group to act against.
        parsed = instance_info.parse_instance_id(instance_id)
        self.current_group_id = parsed.group_id

        # World name resolution -- cached after the first time, so this is
        # only slow the first time you see a given world.
        base_label = instance_info.describe_instance_base(self.vrchat_client, world_id, parsed)
        self._status_base_label = base_label

        # Capacity is a WORLD property, not a group one -- resolved here
        # regardless of instance type, unlike the group-permission stuff
        # below which only applies when there's actually a group.
        self.current_world_capacity = self.vrchat_client.get_world_capacity(world_id)

        if not parsed.group_id:
            # Public/friends/invite instance -- no group, so no permission
            # dot or group icon to show (there's nothing to be permitted to
            # moderate, and nothing to fetch an icon for).
            self.current_group_name = None
            self.current_has_moderation_permission = None
            self.current_has_invite_permission = None
            self.current_group_icon_pixmap = None
            self._current_group_icon_data_uri = None
            self.status_label.setTextFormat(Qt.PlainText)
            self.status_label.setText(base_label)
            return

        # Group instance -- fetch the group's name, icon URL, AND the
        # logged-in user's own resolved permissions in one call (myMember),
        # plus the group's permission catalog (cached) to figure out which
        # permission name actually means "can moderate instances" for THIS
        # group.
        details = self.vrchat_client.get_group_details(parsed.group_id)

        if details.status != "success":
            self.current_group_name = None
            self.current_has_moderation_permission = None
            self.current_has_invite_permission = None
            self.current_group_icon_pixmap = None
            self._current_group_icon_data_uri = None
            self.status_label.setTextFormat(Qt.PlainText)
            self.status_label.setText(f"{base_label} · {parsed.group_id} (couldn't check permissions)")
            # Still copyable even when the permission check itself failed
            # -- the instance identity resolved fine, only the group
            # details call didn't. Combined with the error so neither
            # piece of info gets lost.
            error_suffix = f"\n\n{details.error_message}" if details.error_message else ""
            self.status_label.setToolTip(f"Copy web link for this instance{error_suffix}")
            return

        self.current_group_name = details.name or parsed.group_id
        catalog = self.vrchat_client.get_group_permission_catalog(parsed.group_id)
        has_permission = permission_check.has_instance_moderation_permission(details.my_permissions, catalog)
        self.current_has_moderation_permission = has_permission
        # Reuses the same myMember.permissions + catalog already fetched
        # above -- no extra API call needed for this second check.
        self.current_has_invite_permission = permission_check.has_group_invite_permission(
            details.my_permissions, catalog
        )

        pixmap, icon_data_uri = self._get_group_icon(parsed.group_id, details.icon_url)
        self.current_group_icon_pixmap = pixmap
        self._current_group_icon_data_uri = icon_data_uri

        # No status_label.setToolTip() here on purpose -- that tooltip now
        # permanently says "Copy web link for this instance" (set once in
        # _build_ui). The permission explanation moved to perm_led_label's
        # tooltip instead, set by _render_status_line below.
        self._render_status_line()

    def _render_status_line(self):
        """(Re)builds the group-instance status line's rich text AND the
        permission LED up by the account button -- called once whenever
        _update_instance_display settles on a new instance, and again on
        every blink tick while group_mod_cache's background scan is out
        wandering, to swap just the LED's color without stirring up or
        re-fetching anything else. A no-op outside a group instance --
        current_group_name is None there, nothing to have permission
        over either way, so the LED just stays dark and out of sight."""
        if not self.current_group_name:
            self.perm_led_label.setVisible(False)
            return

        if self._group_mod_cache_scanning:
            dot_color = self.PERMISSION_SCANNING if self._blink_state else "transparent"
            led_tooltip = "Checking your permission in this group..."
        elif self.current_has_moderation_permission:
            dot_color = self.PERMISSION_GREEN
            led_tooltip = f"You can moderate {self.current_group_name}'s instances."
        else:
            dot_color = self.PERMISSION_RED
            led_tooltip = f"You don't have permission to moderate {self.current_group_name}'s instances."

        self.perm_led_label.setStyleSheet(f"font-size: 18px; color: {dot_color};")
        self.perm_led_label.setToolTip(led_tooltip)
        self.perm_led_label.setVisible(True)

        icon_html = (
            f'<img src="{self._current_group_icon_data_uri}" width="16" height="16">'
            if self._current_group_icon_data_uri else ""
        )
        # Group name, then the group icon, in that order -- the
        # permission dot used to stand between the two of them here, but
        # it's moved on up by the account button now instead (see
        # _build_ui).
        self.status_label.setTextFormat(Qt.RichText)
        self.status_label.setText(
            f'{self._status_base_label} · {self.current_group_name}'
            f'&nbsp;&nbsp;{icon_html}'
        )

    def eventFilter(self, obj, event):
        """Only keeping an eye on status_label right now, watching for
        clicks -- see _build_ui's installEventFilter call and
        _copy_instance_web_link below. A QLabel has no click signal of
        its own to howl with, and this is the well-worn Qt way to teach
        one a click without going to the trouble of subclassing just
        for that one trick."""
        if obj is self.status_label and event.type() == QEvent.MouseButtonPress:
            self._copy_instance_web_link()
            return True
        return super().eventFilter(obj, event)

    def _copy_instance_web_link(self):
        """Copies a vrchat.com/home/launch link for wherever you're
        standing RIGHT NOW to the clipboard -- confirmed against a real,
        live vrchat.com URL of this exact shape (worldId + instanceId
        riding along as query params), not just guessed at, same care
        this app already gives every other VRChat-API-facing corner of
        itself. A quiet no-op if no instance has settled in yet
        (current_world_id/current_instance_id still None) -- can't hand
        someone a door to nowhere."""
        if not self.current_world_id or not self.current_instance_id:
            return

        query = urllib.parse.urlencode({
            "worldId": self.current_world_id,
            "instanceId": self.current_instance_id,
        })
        url = f"https://vrchat.com/home/launch?{query}"
        QApplication.clipboard().setText(url)
        QToolTip.showText(QCursor.pos(), "Copied web link!", self.status_label)

    def _vote_kick_checkmark_pixmap(self) -> QPixmap:
        """A small red checkmark, drawn once and cached -- no image asset
        needed for something this simple. Reuses the same right-edge
        icon-row mechanism the group badges already use (see
        icon_row_delegate.py), just with a plain hand-drawn glyph
        instead of a fetched group icon."""
        if not hasattr(self, "_vote_kick_checkmark_cache"):
            size = IconRowDelegate.ICON_SIZE
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor(DANGER))  # same red the rest of the UI already speaks (glow.py)
            pen.setWidth(2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            # A simple check mark path, scaled to the icon box.
            painter.drawLine(int(size * 0.18), int(size * 0.55), int(size * 0.42), int(size * 0.78))
            painter.drawLine(int(size * 0.42), int(size * 0.78), int(size * 0.85), int(size * 0.22))
            painter.end()
            self._vote_kick_checkmark_cache = pixmap
        return self._vote_kick_checkmark_cache

    def _crasher_warning_pixmap(self) -> QPixmap:
        """
        An amber caution triangle, deliberately NOT the vote-kick
        checkmark's flat red -- that one marks something VRChat itself
        confirmed happened; this one marks a timing correlation a
        human still needs to judge. Different certainty, different
        color, same right-edge icon-row mechanism.
        """
        if not hasattr(self, "_crasher_warning_cache"):
            size = IconRowDelegate.ICON_SIZE
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)

            triangle = QPolygon([
                QPoint(int(size * 0.5), int(size * 0.06)),
                QPoint(int(size * 0.05), int(size * 0.92)),
                QPoint(int(size * 0.95), int(size * 0.92)),
            ])
            painter.setPen(QPen(QColor(WARNING), 1))
            painter.setBrush(QColor(WARNING))
            painter.drawPolygon(triangle)

            # Exclamation mark, dark-on-amber for contrast -- same
            # "caution" language a real warning sign uses.
            mark_pen = QPen(QColor("#1a1a1a"))
            mark_pen.setWidth(2)
            mark_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(mark_pen)
            painter.drawLine(int(size * 0.5), int(size * 0.38), int(size * 0.5), int(size * 0.66))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#1a1a1a"))
            dot_r = max(1, size // 12)
            painter.drawEllipse(QPoint(int(size * 0.5), int(size * 0.80)), dot_r, dot_r)

            painter.end()
            self._crasher_warning_cache = pixmap
        return self._crasher_warning_cache

    def _get_group_icon(self, group_id: str, icon_url: str) -> tuple:
        """
        Returns (QPixmap or None, data-uri string or None) for a group's
        icon -- the pixmap is for the player-list delegate, the data URI is
        for embedding directly in the status_label's rich text. Cached per
        group_id since icon art is static content, unlike the permission
        check above it (which is deliberately re-fetched every time). Some
        things need to stay fresh; a logo isn't one of them.

        A cached SUCCESS is trusted unconditionally. A cached FAILURE is
        only trusted if we still don't have an icon_url to try either --
        group_mod_cache.py's entries can genuinely have icon_url=None
        for a group its background scan hasn't reached yet (or hadn't,
        the very first time this was called for it), and that shouldn't
        be a permanent "no icon" verdict for the rest of the session
        once a real URL actually shows up.
        """
        if group_id in self._group_icon_pixmap_cache:
            cached_pixmap = self._group_icon_pixmap_cache[group_id]
            if cached_pixmap is not None or not icon_url:
                return cached_pixmap, self._group_icon_data_uri_cache.get(group_id)

        fetched = image_utils.fetch_image_bytes(self.vrchat_client, icon_url)
        if not fetched:
            self._group_icon_pixmap_cache[group_id] = None
            self._group_icon_data_uri_cache[group_id] = None
            return None, None

        content, content_type = fetched
        pixmap = QPixmap()
        pixmap.loadFromData(content)
        if pixmap.isNull():
            self._group_icon_pixmap_cache[group_id] = None
            self._group_icon_data_uri_cache[group_id] = None
            return None, None

        data_uri = f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}"
        self._group_icon_pixmap_cache[group_id] = pixmap
        self._group_icon_data_uri_cache[group_id] = data_uri
        return pixmap, data_uri

    def _ensure_trust_rank_cached(self, user_id: str):
        """
        Looks up a player's trust rank/age-verified/VRC+ status AND their
        full public group list the FIRST time we see them, and caches
        both -- these essentially never change mid-session, so there's
        no reason to re-fetch on every poll tick. Silently does nothing
        on failure (offline, rate limit, etc) -- a player just shows
        with no badges/icons instead of crashing anything. Grace under
        a bad connection, same as anywhere else.
        """
        if not user_id.startswith("usr_"):
            return

        if user_id not in self._player_profile_cache:
            result = self.vrchat_client.get_user(user_id)
            if result.status == "success":
                self._player_profile_cache[user_id] = player_profile.build_profile(result)
                if result.display_name:
                    self._revalidate_watchlist_name(user_id, result.display_name)

        # Fetched ONCE per player and cached as their full raw group
        # list, not re-fetched per group -- VRChat already hands back
        # everything in one call, so checking it against however many
        # groups are in _group_mod_cache costs nothing extra locally.
        # (Used to be keyed by (user_id, group_id) and only ever
        # checked against the single current-instance group; see
        # _player_moderated_group_ids for what actually reads this now.)
        if user_id not in self._player_group_ids_cache:
            result = self.vrchat_client.get_user_group_ids(user_id)
            if result.status == "success":
                self._player_group_ids_cache[user_id] = result.group_ids or []

    def _player_moderated_group_ids(self, user_id: str) -> list[str]:
        """Every group in _group_mod_cache this player is ALSO a member
        of, in the cache's own (alphabetical) order. Pure local set
        work -- no network call here, _ensure_trust_rank_cached above
        is what actually fetched the player's group list. Recomputed
        fresh each call (cheap) rather than cached itself, so a
        mid-session "Update Perms" that changes which groups you
        moderate shows up on the next refresh without needing to
        re-fetch anyone's membership."""
        player_group_ids = self._player_group_ids_cache.get(user_id)
        if not player_group_ids:
            return []
        player_group_ids = set(player_group_ids)
        return [entry.group_id for entry in self._group_mod_cache if entry.group_id in player_group_ids]

    def _revalidate_watchlist_name(self, user_id: str, current_display_name: str):
        """
        Opportunistic revalidation: if this player happens to be on the
        watchlist AND their name has drifted from what we have on file,
        update the local copy and (if the shared Sheet is configured)
        push the correction up too -- keeps names accurate over time
        without anyone having to manually re-type them, using whatever
        sightings naturally happen during normal moderation. People
        change; the record should keep up without being asked twice.
        """
        local_entries = {e.user_id: e for e in watchlist.load_entries()}
        entry = local_entries.get(user_id)
        if not entry or entry.display_name == current_display_name:
            return

        watchlist.remove_entries([user_id])
        watchlist.add_entry(watchlist.WatchlistEntry(
            user_id=user_id, display_name=current_display_name,
            reason=entry.reason, added_at=entry.added_at,
        ))

        sync_settings = watchlist_sync_settings.load_settings()
        if watchlist_sync_settings.is_configured():
            # Best-effort -- a failed name-sync is never worth interrupting
            # anything else over, so failures are silently ignored here.
            try:
                sheets_watchlist.update_display_name(sync_settings.script_url, user_id, current_display_name)
            except Exception:
                pass

    # -- Log watching --------------------------------------------------------

    def _start_log_watcher(self):
        log_path = find_latest_log_file()

        if log_path is None:
            self.status_label.setText("No VRChat log file found. Is VRChat installed/has it been run?")
            self.watcher = None
            return

        self.status_label.setText(f"Watching: {log_path}")

        # Catch up on who's already here, instead of starting empty and
        # waiting for the next join/leave. Arrive present, not late.
        initial_state = compute_initial_state(log_path)
        now = datetime.now()
        self.players = {
            user_id: PlayerEntry(
                user_id=user_id,
                display_name=active.display_name,
                joined_at=active.joined_at or now,
                status="present",
            )
            for user_id, active in initial_state.active_players.items()
        }
        if initial_state.world_id:
            self._update_instance_display(initial_state.world_id, initial_state.instance_id)
        for user_id in self.players:
            self._ensure_trust_rank_cached(user_id)
        self._refresh_list()

        self.watcher = LogWatcher(log_path)

        # Set up the repeating timer that keeps the list live. Interval is
        # user-adjustable via Config -- read fresh here so a change made
        # before this point (there isn't one on first launch) is respected;
        # _apply_appearance() updates it live afterward if changed later.
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_log)
        self.poll_timer.start(appearance_settings.load_settings().poll_interval_ms or POLL_INTERVAL_MS)

        # Separate, much slower timer -- only ever does real work (a
        # process check) once the log's already gone quiet past
        # SILENT_CRASH_SILENCE_THRESHOLD, so running it independently of
        # the fast poll_timer above costs nothing on the common path.
        self.silent_crash_timer = QTimer(self)
        self.silent_crash_timer.timeout.connect(self._check_for_silent_crash)
        self.silent_crash_timer.start(SILENT_CRASH_CHECK_INTERVAL_MS)

    def _poll_log(self):
        if not self.watcher:
            return
        for event in self.watcher.poll():
            self._handle_event(event)

    def _handle_event(self, event):
        if event.kind == "instance_change":
            # New instance -- whoever was tracked (present OR departed)
            # belonged to the old one and no longer applies. New room,
            # clean slate.
            self.players.clear()
            self._update_instance_display(event.world_id, event.instance_id)

        elif event.kind == "player_join":
            key = event.user_id or event.display_name
            joined_at = event.timestamp or datetime.now()
            existing = self.players.get(key)
            if existing:
                # Re-joining after having left earlier this instance --
                # treat it as a fresh connection (updates their "connection
                # time" to now, clears the departed marker). A return is
                # still a return, not a continuation of the old timer.
                existing.display_name = event.display_name
                existing.status = "present"
                existing.departed_at = None
                existing.joined_at = joined_at
            else:
                self.players[key] = PlayerEntry(
                    user_id=key, display_name=event.display_name, joined_at=joined_at, status="present",
                )
            self._ensure_trust_rank_cached(key)

        elif event.kind == "player_left":
            key = event.user_id or event.display_name
            entry = self.players.get(key)
            if entry:
                # Marked, not removed -- they stay visible (greyed out)
                # until _prune_departed_players clears them out after
                # DEPARTED_RETENTION_HOURS.
                entry.status = "departed"
                entry.departed_at = event.timestamp or datetime.now()

        elif event.kind in ("vote_kick_initiated", "vote_kick_succeeded"):
            self._handle_vote_kick_event(event)

        elif event.kind == "avatar_change":
            timestamp = event.timestamp or datetime.now()
            self._recent_avatar_changes.append((event.display_name, event.avatar_name, timestamp))
            cutoff = datetime.now() - CRASHER_CORRELATION_WINDOW * 2
            self._recent_avatar_changes = [c for c in self._recent_avatar_changes if c[2] >= cutoff]

        elif event.kind == "udon_exception":
            self._handle_crasher_signal_event(event.timestamp or datetime.now(), signal="udon_exception")

        elif event.kind == "model_validation_warning":
            warning_time = event.timestamp or datetime.now()
            self._last_validation_warning_at = warning_time
            self._last_validation_warning_paired = False
            # Don't flag yet -- wait to see whether a zero-MB avatar
            # download follows within the pairing window (see
            # _handle_zero_mb_pairing). If nothing pairs with it in
            # time, _resolve_validation_warning falls back to the
            # plain, weaker standalone flag.
            QTimer.singleShot(
                ZERO_MB_PAIRING_WINDOW_MS,
                lambda ts=warning_time: self._resolve_validation_warning(ts),
            )

        elif event.kind == "avatar_zero_mb_download":
            self._handle_zero_mb_pairing(event.timestamp or datetime.now())

        elif event.kind == "application_quit":
            self._last_graceful_quit_at = event.timestamp or datetime.now()

        self._refresh_list()

    def _correlate_avatar_changes(self, anchor: datetime) -> list:
        """Every avatar-change within CRASHER_CORRELATION_WINDOW of
        `anchor`, turned into CrasherCandidates. Shared by every signal
        type that needs "who switched avatars right before this" --
        the udon-exception path, the validation-warning path, and the
        silent-crash path all lean on the exact same window and the
        exact same never-guess-one-of-several rule."""
        window_start = anchor - CRASHER_CORRELATION_WINDOW
        recent = [c for c in self._recent_avatar_changes if window_start <= c[2] <= anchor]
        return [
            crasher_activity.CrasherCandidate(
                display_name=display_name,
                user_id=self._resolve_player_id_by_name(display_name),
                avatar_name=avatar_name,
                seconds_before_exception=(anchor - changed_at).total_seconds(),
            )
            for display_name, avatar_name, changed_at in recent
        ]

    def _record_crasher_flag(self, candidates: list, anchor: datetime, signal: str, confidence: str,
                              single_detail: str, ambiguous_detail: str):
        """Shared tail end of every crasher-signal path: save the flag,
        write the AAR entry. `single_detail`/`ambiguous_detail` are
        format strings the caller's already filled in -- kept here only
        so the save-and-log plumbing isn't duplicated three times."""
        observed_by = self.vrchat_client.display_name if self.vrchat_client else "unknown"
        crasher_activity.record_flag(
            candidates, self.current_world_id, self.current_instance_id, observed_by, anchor.isoformat(),
            signal=signal, confidence=confidence,
        )

        if len(candidates) == 1:
            target_name, target_id, detail = candidates[0].display_name, candidates[0].user_id, single_detail
        else:
            target_name, target_id, detail = "multiple possible", "", ambiguous_detail

        aar.save_entry(aar.AAREntry(
            timestamp=aar.now_iso(), moderator=observed_by, action="crasher_activity_flag",
            target_display_name=target_name, target_user_id=target_id, details=detail, success=True,
        ))

    def _handle_crasher_signal_event(self, timestamp: datetime, signal: str):
        """
        Correlates a bare "something happened" signal against whoever
        switched avatars in the last CRASHER_CORRELATION_WINDOW seconds.
        Zero candidates means nothing recent to blame it on -- most of
        these signals are ordinary noise unrelated to any player's
        avatar, so silently skipping those keeps this from drowning in
        false alarms. More than one candidate means genuine ambiguity,
        and every candidate gets flagged rather than arbitrarily picking
        one -- guessing which of several people did it would turn a
        timing correlation into something that looks like an accusation.
        """
        candidates = self._correlate_avatar_changes(timestamp)
        if not candidates:
            return

        signal_label = CRASHER_SIGNAL_LABELS.get(signal, signal)

        if len(candidates) == 1:
            single_detail = (
                f"Possible crasher activity: {signal_label} fired {candidates[0].seconds_before_exception:.0f}s "
                f"after {candidates[0].display_name} switched to avatar \"{candidates[0].avatar_name}\". "
                "Circumstantial, not confirmed -- an ordinary broken avatar looks identical in the log."
            )
            ambiguous_detail = ""  # unused in the single-candidate branch
        else:
            names = ", ".join(c.display_name for c in candidates)
            single_detail = ""  # unused in the ambiguous branch
            ambiguous_detail = (
                f"Possible crasher activity: {signal_label} fired with {len(candidates)} players having "
                f"just switched avatars ({names}) -- ambiguous, can't attribute to one of them."
            )

        self._record_crasher_flag(candidates, timestamp, signal, "circumstantial", single_detail, ambiguous_detail)

    def _handle_zero_mb_pairing(self, timestamp: datetime):
        """
        A tip passed along secondhand, checked rather than trusted
        whole: a lone 0MB avatar download is common and mostly
        meaningless (an already-cached avatar reports that legitimately,
        nothing left to fetch). What was actually claimed is the PAIR --
        a validation warning immediately followed by a 0MB report for
        that same load. Only that combination gets treated as its own,
        more specific signal; an unpaired 0MB download does nothing here
        at all.
        """
        if self._last_validation_warning_at is None or self._last_validation_warning_paired:
            return
        if timestamp - self._last_validation_warning_at > ZERO_MB_PAIRING_WINDOW:
            return
        self._last_validation_warning_paired = True
        self._handle_crasher_signal_event(self._last_validation_warning_at, signal="validation_warning_with_zero_mb")

    def _resolve_validation_warning(self, warning_time: datetime):
        """
        Fires ZERO_MB_PAIRING_WINDOW_MS after a validation warning, and
        only actually does anything if NOTHING paired with it in that
        window -- falls back to flagging it as the plain, weaker
        standalone signal. The `warning_time` equality check guards
        against a NEWER validation warning having since overwritten
        _last_validation_warning_at (a rare case -- two warnings inside
        one pairing window -- where the older one is simply dropped
        rather than double-tracked; not worth the extra state for how
        seldom that actually happens)."""
        if self._last_validation_warning_at != warning_time or self._last_validation_warning_paired:
            return
        self._handle_crasher_signal_event(warning_time, signal="model_validation_warning")

    def _check_for_silent_crash(self):
        """
        Guardian's strongest crasher signal, and the only one that
        actually correlates with a real crash outcome rather than just
        an exception the game shrugged off and kept running past. Fires
        at most once per gap: the log stops growing, VRChat.exe is
        confirmed gone (not just quiet), and the last suspicious thing
        logged was a model-validation warning with no graceful
        OnApplicationQuit/HandleApplicationQuit in between. Still not
        "confirmed" -- a client can die for plenty of reasons that have
        nothing to do with any particular avatar -- just meaningfully
        stronger than a correlation the game recovered from.
        """
        if not self.watcher or not self.watcher.last_line_read_at:
            return

        silence = datetime.now() - self.watcher.last_line_read_at
        if silence < SILENT_CRASH_SILENCE_THRESHOLD:
            self._silent_crash_already_flagged = False  # the log's moving again -- clear the guard
            return

        if self._silent_crash_already_flagged:
            return
        if self._last_validation_warning_at is None:
            return
        if self._last_graceful_quit_at and self._last_graceful_quit_at >= self._last_validation_warning_at:
            return
        if process_check.is_vrchat_running():
            return

        candidates = self._correlate_avatar_changes(self._last_validation_warning_at)
        self._silent_crash_already_flagged = True  # don't re-check/re-flag every tick while VRChat stays closed
        if not candidates:
            return  # VRChat's gone and the timing is suspicious, but nobody to actually name

        # Extra corroborating detail, not a confidence bump -- the flag
        # is already "strong" on the silence alone; this just gives a
        # mod reading it one more data point to weigh for themselves.
        pairing_note = (
            " That avatar's asset bundle also reported as 0.0 MB, matching the paired pattern this tool "
            "watches for separately." if self._last_validation_warning_paired else ""
        )

        if len(candidates) == 1:
            single_detail = (
                f"VRChat's log went silent (process no longer running) shortly after a model-validation warning "
                f"that followed {candidates[0].display_name} switching to avatar \"{candidates[0].avatar_name}\". "
                "No graceful shutdown was logged in between -- consistent with an actual crash, though a client "
                f"can also die for unrelated reasons.{pairing_note}"
            )
            ambiguous_detail = ""
        else:
            names = ", ".join(c.display_name for c in candidates)
            single_detail = ""
            ambiguous_detail = (
                f"VRChat's log went silent shortly after a model-validation warning, with {len(candidates)} "
                f"players having just switched avatars ({names}) -- ambiguous, can't attribute to one of "
                f"them.{pairing_note}"
            )

        self._record_crasher_flag(
            candidates, self._last_validation_warning_at, "crash_after_validation_warning", "strong",
            single_detail, ambiguous_detail,
        )

    def _resolve_player_id_by_name(self, display_name: str) -> str:
        """VRChat's vote-kick log lines only ever give a display name,
        never a user ID -- this cross-references whoever's currently (or
        was recently) tracked in this instance to attach a real user_id
        where possible. Returns "" if nobody matches (they may have
        already left before we got here, or the name just doesn't line
        up with anyone we've seen)."""
        for entry in self.players.values():
            if entry.display_name == display_name:
                return entry.user_id if entry.user_id.startswith("usr_") else ""
        return ""

    def _handle_vote_kick_event(self, event):
        observed_by = self.vrchat_client.display_name if self.vrchat_client else "unknown"
        target_user_id = self._resolve_player_id_by_name(event.display_name)
        timestamp = event.timestamp or datetime.now()

        if event.kind == "vote_kick_initiated":
            vk_event = vote_kicks.record_initiated(
                event.display_name, target_user_id, self.current_world_id, self.current_instance_id,
                timestamp, observed_by,
            )
        else:
            vk_event = vote_kicks.record_succeeded(
                event.display_name, target_user_id, self.current_world_id, self.current_instance_id,
                timestamp, observed_by,
            )

        # Submission (and the AAR log either way) can hit the network --
        # doesn't need to block the log-poll loop, so it runs in the
        # background same as the group-mod cache scan does elsewhere.
        threading.Thread(
            target=vote_kick_submit.submit_vote_kick_event, args=(self.vrchat_client, vk_event), daemon=True,
        ).start()

    def _refresh_list(self):
        self.player_list.clear()

        active_count = sum(1 for e in self.players.values() if e.status == "present")
        if self.current_world_capacity:
            self.player_list_label.setText(
                f"Players in current instance: {active_count} / {self.current_world_capacity}"
            )
        else:
            self.player_list_label.setText(f"Players in current instance: {active_count}")

        entries = list(self.players.values())
        watched_entries = watchlist.get_watched_entries()
        vote_kick_ids, vote_kick_names = vote_kicks.get_targets_with_events()
        crasher_ids, crasher_names = crasher_activity.get_targets_with_flags()

        # Each mode's "natural" (ascending=True) direction -- toggled to
        # the opposite when the same category was just re-picked.
        # Connection Time's natural direction is newest-first (reverse=
        # True) since that's the more useful default for keeping an eye
        # on new arrivals; picking it again flips to oldest-first.
        NATURAL_REVERSE = {"Name": False, "Connection Time": True, "Rank": False, "Status": False}
        reverse = NATURAL_REVERSE[self._sort_mode] if self._sort_ascending else not NATURAL_REVERSE[self._sort_mode]

        if self._sort_mode == "Name":
            entries.sort(key=lambda e: e.display_name.lower(), reverse=reverse)
        elif self._sort_mode == "Connection Time":
            entries.sort(key=lambda e: e.joined_at, reverse=reverse)
        elif self._sort_mode == "Rank":
            def rank_sort_key(e):
                profile = self._player_profile_cache.get(e.user_id)
                rank_order = trust_rank.RANK_SORT_ORDER.get(profile.rank.key, 99) if profile else 99
                return (rank_order, e.display_name.lower())
            entries.sort(key=rank_sort_key, reverse=reverse)
        elif self._sort_mode == "Status":
            # Present first, departed last; alphabetical within each group.
            entries.sort(key=lambda e: (0 if e.status == "present" else 1, e.display_name.lower()), reverse=reverse)

        for entry in entries:
            profile = self._player_profile_cache.get(entry.user_id)
            watch_entry = watched_entries.get(entry.user_id)
            category = watchlist_categories.get_category(watch_entry.category) if watch_entry else None

            label = entry.display_name
            if profile and profile.badge_text:
                label = f"{label}  {profile.badge_text}"
            if category:
                label = f"{category.icon} {label}"  # category-specific icon, not a generic caution sign
            if entry.status == "departed" and entry.departed_at:
                label = f"{label}  — left {_format_elapsed(datetime.now() - entry.departed_at)} ago"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry.user_id)

            if category:
                # Watchlist category color takes priority over both rank
                # color and the departed-grey. Only genuinely threatening
                # categories (predator/stalker/troll) blink -- VIP/Creator/
                # PoI are informational tags, not alarms, so they just show
                # their color steadily. Not every glow means danger.
                if category.blinking:
                    color_hex = category.color if self._watchlist_blink_state else watchlist_categories.dim(category.color)
                else:
                    color_hex = category.color
                item.setForeground(QColor(color_hex))
            elif entry.status == "departed":
                # Muted grey regardless of trust rank -- the color's job
                # here is "not currently in the instance", which matters
                # more at a glance than their rank does once they've left.
                item.setForeground(QColor("#888888"))
            elif profile:
                item.setForeground(QColor(profile.rank.color))

            tooltip_parts = []
            if category and watch_entry:
                tooltip_parts.append(category.label + (f": {watch_entry.reason}" if watch_entry.reason else ""))
            if profile:
                tooltip_parts.append(profile.tooltip)
            if tooltip_parts:
                item.setToolTip("\n".join(tooltip_parts))

            # Group icons at the end of the row (painted by
            # IconRowDelegate). Two sources, kept deliberately separate:
            #
            # 1. The group hosting THIS instance, unconditionally, for
            #    any member -- same as this always worked before "Grp
            #    Kick/Ban From" existed, and NOT gated on whether you
            #    happen to moderate it. Uses the pixmap already fetched
            #    live for the status line, not group_mod_cache -- that
            #    cache is scanned in the background and can legitimately
            #    lag behind or miss a group it hasn't gotten to yet,
            #    which shouldn't cost this its own always-worked icon.
            #
            # 2. Any OTHER group this player is in that you also
            #    moderate, per group_mod_cache.py -- could be zero, one,
            #    or several, deduplicated against #1 so a group that's
            #    both "hosting this instance" and "one you moderate"
            #    doesn't draw its icon twice.
            #
            # Shown for departed players too, since group membership
            # doesn't depend on still being here. Belonging doesn't
            # expire the moment you step out.
            pixmaps = []
            labels = []  # index-aligned with pixmaps -- each icon's hover tooltip
            seen_group_ids = set()
            player_group_ids = self._player_group_ids_cache.get(entry.user_id) or []

            # Small red checkmark -- flags a player with known vote-kick
            # event(s) attached to them (see vote_kicks.py). Drawn first
            # so it sits leftmost among the trailing icons, ahead of
            # group badges. Right-click → Votes shows the actual history.
            has_vote_kick_history = (
                (entry.user_id.startswith("usr_") and entry.user_id in vote_kick_ids)
                or entry.display_name in vote_kick_names
            )
            if has_vote_kick_history:
                pixmaps.append(self._vote_kick_checkmark_pixmap())
                labels.append("Has known vote-kick event(s) — right-click → Votes")

            # Amber caution triangle -- a timing correlation Guardian
            # noticed, not a confirmed finding. Drawn right after the
            # checkmark so the two never get visually confused for one
            # another at a glance.
            has_crasher_flag = (
                (entry.user_id.startswith("usr_") and entry.user_id in crasher_ids)
                or entry.display_name in crasher_names
            )
            if has_crasher_flag:
                pixmaps.append(self._crasher_warning_pixmap())
                labels.append("Possible crasher activity observed — right-click → Crasher Activity")

            if self.current_group_id and self.current_group_icon_pixmap and self.current_group_id in player_group_ids:
                pixmaps.append(self.current_group_icon_pixmap)
                labels.append(self.current_group_name)
                seen_group_ids.add(self.current_group_id)

            entries_by_id = {e.group_id: e for e in self._group_mod_cache}
            for group_id in self._player_moderated_group_ids(entry.user_id):
                if group_id in seen_group_ids:
                    continue
                matched_entry = entries_by_id.get(group_id)
                if not matched_entry:
                    continue
                pixmap, _data_uri = self._get_group_icon(group_id, matched_entry.icon_url)
                if pixmap:
                    pixmaps.append(pixmap)
                    labels.append(matched_entry.group_name)
                    seen_group_ids.add(group_id)

            if pixmaps:
                item.setData(GROUP_ICON_ROLE, pixmaps)
                item.setData(GROUP_ICON_LABELS_ROLE, labels)

            self.player_list.addItem(item)


def _migrate_data_dir():
    """
    One-time move from ~/.ascended_quickmod (Guardian's original folder
    name, back when the app was still called QuickMOD) to ~/.ascended_
    guardian -- so finishing the rename to the app's real name doesn't
    quietly orphan anyone's saved session, AAR log, watchlist, or any of
    the rest. Safe to call every launch: a no-op the moment the new
    folder exists, and if both somehow already exist, the old one is
    just left alone rather than guessed about.
    """
    old_dir = Path.home() / ".ascended_quickmod"
    new_dir = Path.home() / ".ascended_guardian"
    if old_dir.exists() and not new_dir.exists():
        try:
            old_dir.rename(new_dir)
        except OSError:
            pass  # cross-device or a locked file -- worst case, a fresh start, nothing corrupts either way


def main():
    # Before anything else, including the QApplication -- carry forward
    # anyone's existing local data from the app's old folder name.
    _migrate_data_dir()

    # If style.qss or the logo files are missing, fetch them now so
    # THIS launch gets to use them, not just the next one.
    app_updater.self_heal_content(app_updater.get_app_dir(), log=print)

    app = QApplication(sys.argv)

    # App-wide icon -- covers the taskbar and any window that doesn't set
    # its own icon explicitly. Also set explicitly on GuardianWindow below
    # for the title bar, since not all platforms/themes reliably fall back
    # to the QApplication-level icon for that.
    logo_path = Path(__file__).parent / "ascended_logo.png"
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    # STYLING HOOK: if a style.qss file exists next to this script, it gets
    # applied to the whole app. This is where the visual identity goes
    # once it's ready -- nothing else needs to change.
    #
    # %%ASSETS%% lets style.qss reference image files (like the combo box
    # arrow) by an absolute path without hardcoding one -- Qt QSS resolves
    # relative url()s against the process's current working directory, not
    # this script's folder, so a plain relative path would break if Guardian
    # is ever launched from somewhere else.
    style_path = Path(__file__).parent / "style.qss"
    if style_path.exists():
        qss_text = style_path.read_text().replace("%%ASSETS%%", Path(__file__).parent.as_posix())
        app.setStyleSheet(qss_text)

    while True:
        login = LoginDialog()

        # login.authenticated may already be True here if a saved session
        # from last time was valid -- skip showing the form in that case.
        # No need to ask twice for trust already given.
        if not login.authenticated:
            if login.exec() != QDialog.Accepted:
                return  # user closed the login window without logging in

        window = GuardianWindow(vrchat_client=login.client)
        window.show()
        app.exec()  # blocks until the window closes (Sign Out or the X button)

        if not getattr(window, "sign_out_requested", False):
            break  # closed normally -- exit the app

        # Sign Out was chosen -- loop back around to a fresh login screen.

    sys.exit(0)


if __name__ == "__main__":
    main()
