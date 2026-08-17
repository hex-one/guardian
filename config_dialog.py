"""
config_dialog.py

The app's settings window -- opened from the account menu (username ->
Config...). The control room. Has two sections: Appearance
(wallpaper/font/font color for the player list) and Discord Integration
(webhook targets the AAR report can be sent to).

--------------------------------------------------------------------------
BEGINNER NOTES:

- Appearance changes are applied live: this dialog just saves settings and
  emits `appearance_applied`, which main.py listens for and re-applies
  immediately -- no restart needed to see a change.

- Player trust-rank colors are DELIBERATELY untouched by the font color
  setting here -- those come from item.setForeground() on each row, which
  Qt's default painting honors over a general stylesheet color, so the
  two don't conflict. See main.py's _apply_appearance().

- Each Discord entry is (name, webhook_url) -- see discord_targets.py for
  why a webhook URL is what represents "a server + channel" here, rather
  than a browsable dropdown of Discord servers/channels (that would need
  a full bot with OAuth, which is a much bigger thing to set up and
  maintain).

- The "Test" button lets you confirm a webhook URL actually works BEFORE
  saving it -- sends a real, harmless test message to that channel via
  discord_api.send_report(), same function the real report-sending uses.
--------------------------------------------------------------------------
"""

from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QListWidget,
    QMessageBox,
    QApplication,
    QFrame,
    QFontComboBox,
    QColorDialog,
    QFileDialog,
    QSpinBox,
    QCheckBox,
    QComboBox,
)

import discord_targets
import discord_api
import appearance_settings
import watchlist_sync_settings
import sheets_watchlist
import app_updater
import wallpaper_utils
from glow import apply_glow, PRIMARY, INFO, DANGER


class ConfigDialog(QDialog):
    appearance_applied = Signal()  # main.py connects to this to live-refresh the wallpaper/font

    def __init__(self):
        super().__init__()
        self.setObjectName("ConfigDialog")
        self.setWindowTitle("Guardian — Config")
        self.resize(420, 640)

        self._chosen_wallpaper_path = None
        self._chosen_font_color = None

        self._build_ui()
        self._reload_target_list()
        self._load_current_appearance()
        self._load_current_sync_settings()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        title = QLabel("Guardian Settings")
        title.setObjectName("configTitle")
        outer.addWidget(title)

        outer.addWidget(self._hline())

        # -- Appearance ----------------------------------------------------

        appearance_label = QLabel("Appearance")
        appearance_label.setObjectName("appearanceSectionLabel")
        appearance_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(appearance_label)

        appearance_hint = QLabel(
            "Wallpaper applies to the player list only, automatically blurred and "
            "darkened so names/badges/rank colors stay readable on top of it. Rank "
            "colors themselves are never affected by the font color below."
        )
        appearance_hint.setObjectName("appearanceHint")
        appearance_hint.setWordWrap(True)
        outer.addWidget(appearance_hint)

        wallpaper_row = QHBoxLayout()
        self.wallpaper_path_label = QLabel("No wallpaper set")
        self.wallpaper_path_label.setObjectName("wallpaperPathLabel")
        self.wallpaper_path_label.setWordWrap(True)
        wallpaper_row.addWidget(self.wallpaper_path_label, stretch=1)

        wallpaper_choose_button = QPushButton("Choose Image...")
        wallpaper_choose_button.setObjectName("wallpaperChooseButton")
        wallpaper_choose_button.setToolTip("Pick an image to use as the player list's wallpaper")
        wallpaper_choose_button.clicked.connect(self._choose_wallpaper)
        wallpaper_row.addWidget(wallpaper_choose_button)

        wallpaper_clear_button = QPushButton("Clear")
        wallpaper_clear_button.setObjectName("wallpaperClearButton")
        wallpaper_clear_button.setToolTip("Remove the current wallpaper")
        wallpaper_clear_button.clicked.connect(self._clear_wallpaper)
        wallpaper_row.addWidget(wallpaper_clear_button)
        outer.addLayout(wallpaper_row)

        wallpaper_mode_row = QHBoxLayout()
        wallpaper_mode_row.addWidget(QLabel("Wallpaper Mode:"))
        self.wallpaper_mode_combo = QComboBox()
        self.wallpaper_mode_combo.setObjectName("wallpaperModeCombo")
        self.wallpaper_mode_combo.setToolTip("How the wallpaper image is fit/scaled to the list")
        for value, label in wallpaper_utils.WALLPAPER_MODES:
            self.wallpaper_mode_combo.addItem(label, userData=value)
        wallpaper_mode_row.addWidget(self.wallpaper_mode_combo, stretch=1)
        outer.addLayout(wallpaper_mode_row)

        self.overlay_mode_checkbox = QCheckBox("Overlay Mode (for VR window capture)")
        self.overlay_mode_checkbox.setObjectName("overlayModeCheckbox")
        self.overlay_mode_checkbox.setToolTip("Switch to a flat, wallpaper-free style for VR overlay capture")
        outer.addWidget(self.overlay_mode_checkbox)

        overlay_mode_hint = QLabel(
            "For pinning this window in VR via XSOverlay or OVR Toolkit's window "
            "capture. Hides the player-list wallpaper (a plain panel captures more "
            "reliably than a photo) and switches list/input borders over to your "
            "font color above. Your wallpaper isn't cleared -- turn this off to "
            "get it back."
        )
        overlay_mode_hint.setObjectName("appearanceHint")
        overlay_mode_hint.setWordWrap(True)
        outer.addWidget(overlay_mode_hint)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font:"))
        self.font_combo = QFontComboBox()
        self.font_combo.setObjectName("appearanceFontCombo")
        self.font_combo.setToolTip("Font used for the player list")
        font_row.addWidget(self.font_combo, stretch=1)
        outer.addLayout(font_row)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Font Color:"))
        self.font_color_swatch = QPushButton("")
        self.font_color_swatch.setObjectName("appearanceFontColorSwatch")
        self.font_color_swatch.setToolTip("Choose the player list's text color")
        self.font_color_swatch.setFixedWidth(60)
        self.font_color_swatch.clicked.connect(self._choose_font_color)
        color_row.addWidget(self.font_color_swatch)
        color_row.addStretch()
        outer.addLayout(color_row)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Player list update interval:"))
        self.poll_interval_spin = QSpinBox()
        self.poll_interval_spin.setObjectName("pollIntervalSpin")
        self.poll_interval_spin.setToolTip("How often the player list re-reads VRChat's log (1-60 seconds)")
        self.poll_interval_spin.setRange(1, 60)
        self.poll_interval_spin.setSuffix(" second(s)")
        self.poll_interval_spin.setValue(1)
        interval_row.addWidget(self.poll_interval_spin)
        interval_row.addStretch()
        outer.addLayout(interval_row)

        self.appearance_status_label = QLabel("")
        self.appearance_status_label.setObjectName("appearanceStatus")
        self.appearance_status_label.setWordWrap(True)
        outer.addWidget(self.appearance_status_label)

        apply_row = QHBoxLayout()
        apply_row.addStretch()
        apply_appearance_button = QPushButton("Apply Appearance")
        apply_appearance_button.setObjectName("applyAppearanceButton")
        apply_appearance_button.setToolTip("Save and live-apply the appearance settings above")
        apply_glow(apply_appearance_button, PRIMARY)
        apply_appearance_button.clicked.connect(self._apply_appearance)
        apply_row.addWidget(apply_appearance_button)
        outer.addLayout(apply_row)

        outer.addWidget(self._hline())

        # -- Watchlist Sync (Google Sheets) --------------------------------

        sync_label = QLabel("Watchlist Sync (Google Sheets)")
        sync_label.setObjectName("watchlistSyncSectionLabel")
        sync_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(sync_label)

        sync_hint = QLabel(
            "Pulls approved watchlist entries from a shared Google Sheet, and lets "
            "Add-to-Watchlist submit new candidates for review. See watchlist_sync.gs "
            "and SETUP.md for how to set the sheet and script up."
        )
        sync_hint.setObjectName("watchlistSyncHint")
        sync_hint.setWordWrap(True)
        outer.addWidget(sync_hint)

        self.csv_url_input = QLineEdit()
        self.csv_url_input.setObjectName("watchlistCsvUrlInput")
        self.csv_url_input.setPlaceholderText("Sheet CSV URL (read-only pulls)")
        self.csv_url_input.setToolTip("The published Google Sheet CSV URL to pull approved entries from")
        outer.addWidget(self.csv_url_input)

        self.script_url_input = QLineEdit()
        self.script_url_input.setObjectName("watchlistScriptUrlInput")
        self.script_url_input.setPlaceholderText("Apps Script Web App URL (submissions/reviews)")
        self.script_url_input.setToolTip("The Apps Script Web App URL used for watchlist submissions and reviews")
        outer.addWidget(self.script_url_input)

        self.sync_status_label = QLabel("")
        self.sync_status_label.setObjectName("watchlistSyncStatus")
        self.sync_status_label.setWordWrap(True)
        outer.addWidget(self.sync_status_label)

        sync_button_row = QHBoxLayout()

        self.sync_test_button = QPushButton("Test Connection")
        self.sync_test_button.setObjectName("watchlistSyncTestButton")
        self.sync_test_button.setToolTip("Test that the Sheet CSV URL can be fetched")
        apply_glow(self.sync_test_button, INFO)
        self.sync_test_button.clicked.connect(self._test_sync_connection)
        sync_button_row.addWidget(self.sync_test_button)

        self.sync_save_button = QPushButton("Save Sync Settings")
        self.sync_save_button.setObjectName("watchlistSyncSaveButton")
        self.sync_save_button.setToolTip("Save the Sheet CSV and Apps Script URLs")
        apply_glow(self.sync_save_button, PRIMARY)
        self.sync_save_button.clicked.connect(self._save_sync_settings)
        sync_button_row.addWidget(self.sync_save_button)

        outer.addLayout(sync_button_row)

        outer.addWidget(self._hline())

        # -- Discord Integration ---------------------------------------------

        section_label = QLabel("Discord Integration")
        section_label.setObjectName("discordSectionLabel")
        section_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(section_label)

        hint = QLabel(
            "Each entry below sends reports to ONE specific Discord channel via that "
            "channel's own Incoming Webhook (Discord \u2192 Edit Channel \u2192 Integrations "
            "\u2192 Webhooks \u2192 New Webhook \u2192 Copy URL). Add one entry per group's channel."
        )
        hint.setObjectName("discordHint")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        self.target_list = QListWidget()
        self.target_list.setObjectName("discordTargetList")
        self.target_list.setToolTip("Configured Discord webhook targets")
        outer.addWidget(self.target_list)

        remove_row = QHBoxLayout()
        remove_row.addStretch()
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.setObjectName("discordRemoveButton")
        self.remove_button.setToolTip("Remove the selected Discord webhook target")
        apply_glow(self.remove_button, DANGER)
        self.remove_button.clicked.connect(self._remove_selected)
        remove_row.addWidget(self.remove_button)
        outer.addLayout(remove_row)

        divider2 = QFrame()
        divider2.setFrameShape(QFrame.HLine)
        outer.addWidget(divider2)

        add_label = QLabel("Add a target")
        add_label.setObjectName("discordAddLabel")
        outer.addWidget(add_label)

        self.name_input = QLineEdit()
        self.name_input.setObjectName("discordNameInput")
        self.name_input.setPlaceholderText("Name (e.g. \"Ascended - #mod-reports\")")
        self.name_input.setToolTip("A display name for this webhook target, so you can tell targets apart")
        outer.addWidget(self.name_input)

        self.webhook_input = QLineEdit()
        self.webhook_input.setObjectName("discordWebhookInput")
        self.webhook_input.setPlaceholderText("Webhook URL")
        self.webhook_input.setToolTip("The Discord channel's Incoming Webhook URL")
        outer.addWidget(self.webhook_input)

        self.status_label = QLabel("")
        self.status_label.setObjectName("discordConfigStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        button_row = QHBoxLayout()

        self.test_button = QPushButton("Test")
        self.test_button.setObjectName("discordTestButton")
        self.test_button.setToolTip("Send a harmless test message to this webhook URL")
        apply_glow(self.test_button, INFO)
        self.test_button.clicked.connect(self._test_webhook)
        button_row.addWidget(self.test_button)

        self.add_button = QPushButton("Add")
        self.add_button.setObjectName("discordAddButton")
        self.add_button.setToolTip("Save this Discord webhook target")
        apply_glow(self.add_button, PRIMARY)
        self.add_button.clicked.connect(self._add_target)
        button_row.addWidget(self.add_button)

        outer.addLayout(button_row)

        outer.addWidget(self._hline())

        # -- Updates ---------------------------------------------------------

        update_label = QLabel("Updates")
        update_label.setObjectName("updateSectionLabel")
        update_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(update_label)

        update_hint = QLabel(
            "Content (style.qss, the logo/icon art) updates itself automatically "
            "in the background. Use these to check by hand, or to check for a "
            "whole new app version."
        )
        update_hint.setObjectName("updateHint")
        update_hint.setWordWrap(True)
        outer.addWidget(update_hint)

        self.update_status_label = QLabel("")
        self.update_status_label.setObjectName("updateStatus")
        self.update_status_label.setWordWrap(True)
        self.update_status_label.setTextFormat(Qt.RichText)
        self.update_status_label.setOpenExternalLinks(False)
        self.update_status_label.linkActivated.connect(lambda link: QDesktopServices.openUrl(QUrl(link)))
        outer.addWidget(self.update_status_label)

        update_button_row = QHBoxLayout()

        content_update_button = QPushButton("Check for Content Updates")
        content_update_button.setObjectName("checkContentUpdateButton")
        content_update_button.setToolTip("Check for and apply a style/art content update now")
        apply_glow(content_update_button, INFO)
        content_update_button.clicked.connect(self._check_content_update)
        update_button_row.addWidget(content_update_button)

        app_update_button = QPushButton("Check for App Updates")
        app_update_button.setObjectName("checkAppUpdateButton")
        app_update_button.setToolTip("Check for a newer app release")
        apply_glow(app_update_button, INFO)
        app_update_button.clicked.connect(self._check_app_update)
        update_button_row.addWidget(app_update_button)

        outer.addLayout(update_button_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Close")
        close_button.setObjectName("configCloseButton")
        close_button.setToolTip("Close settings")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        outer.addLayout(close_row)

    # -- Updates ------------------------------------------------------------

    def _check_content_update(self):
        self.update_status_label.setText("Checking...")
        QApplication.processEvents()

        app_dir = app_updater.get_app_dir()
        local_version = app_updater.read_local_content_version(app_dir)
        remote_version = app_updater.fetch_remote_content_version()
        if remote_version is None:
            self.update_status_label.setText("Couldn't reach GitHub to check for a content update.")
            return
        if remote_version <= local_version:
            self.update_status_label.setText(f"Already up to date (v{local_version}).")
            return

        ok, new_version, error = app_updater.download_and_apply_content_update(app_dir)
        if ok:
            self.update_status_label.setText(f"Updated to content v{new_version}. Restart to see everything.")
        else:
            self.update_status_label.setText(error)

    def _check_app_update(self):
        self.update_status_label.setText("Checking...")
        QApplication.processEvents()

        tag, url = app_updater.fetch_latest_release()
        if not tag:
            self.update_status_label.setText("Couldn't reach GitHub to check for an app update.")
            return
        if app_updater.is_newer_version(tag, app_updater.APP_VERSION):
            self.update_status_label.setText(
                f'v{tag} is available (you\'re on v{app_updater.APP_VERSION}). <a href="{url}">Get it</a>'
            )
        else:
            self.update_status_label.setText(f"Up to date (v{app_updater.APP_VERSION}).")

    def _hline(self) -> QFrame:
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        return divider

    # -- Watchlist Sync ---------------------------------------------------

    def _load_current_sync_settings(self):
        settings = watchlist_sync_settings.load_settings()
        if settings.csv_url:
            self.csv_url_input.setText(settings.csv_url)
        if settings.script_url:
            self.script_url_input.setText(settings.script_url)

    def _save_sync_settings(self):
        settings = watchlist_sync_settings.WatchlistSyncSettings(
            csv_url=self.csv_url_input.text().strip() or None,
            script_url=self.script_url_input.text().strip() or None,
        )
        watchlist_sync_settings.save_settings(settings)
        self.sync_status_label.setText("Saved.")

    def _test_sync_connection(self):
        csv_url = self.csv_url_input.text().strip()
        if not csv_url:
            self.sync_status_label.setText("Enter a Sheet CSV URL first.")
            return

        self.sync_status_label.setText("Testing...")
        self.sync_test_button.setEnabled(False)
        QApplication.processEvents()

        result = sheets_watchlist.fetch_master(csv_url)
        self.sync_test_button.setEnabled(True)

        if result.status == "success":
            self.sync_status_label.setText(f"Connected \u2014 {len(result.entries)} approved entr"
                                            f"{'y' if len(result.entries) == 1 else 'ies'} found.")
        else:
            self.sync_status_label.setText(f"Failed: {result.error_message}")

    # -- Appearance ----------------------------------------------------

    def _load_current_appearance(self):
        settings = appearance_settings.load_settings()

        if settings.wallpaper_path:
            self._chosen_wallpaper_path = settings.wallpaper_path
            self.wallpaper_path_label.setText(settings.wallpaper_path)

        mode_index = self.wallpaper_mode_combo.findData(settings.wallpaper_mode)
        self.wallpaper_mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 0)

        if settings.font_family:
            self.font_combo.setCurrentFont(self.font_combo.currentFont().__class__(settings.font_family))

        if settings.font_color:
            self._chosen_font_color = settings.font_color
            self.font_color_swatch.setStyleSheet(f"background-color: {settings.font_color};")

        self.poll_interval_spin.setValue(max(round(settings.poll_interval_ms / 1000), 1))
        self.overlay_mode_checkbox.setChecked(settings.overlay_mode)

    def _choose_wallpaper(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose Wallpaper Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if path:
            self._chosen_wallpaper_path = path
            self.wallpaper_path_label.setText(path)

    def _clear_wallpaper(self):
        self._chosen_wallpaper_path = None
        self.wallpaper_path_label.setText("No wallpaper set")

    def _choose_font_color(self):
        initial = QColor(self._chosen_font_color) if self._chosen_font_color else QColor("#EEEEEE")
        color = QColorDialog.getColor(initial, self, "Choose Font Color")
        if color.isValid():
            self._chosen_font_color = color.name()
            self.font_color_swatch.setStyleSheet(f"background-color: {color.name()};")

    def _apply_appearance(self):
        settings = appearance_settings.AppearanceSettings(
            wallpaper_path=self._chosen_wallpaper_path,
            wallpaper_mode=self.wallpaper_mode_combo.currentData() or wallpaper_utils.DEFAULT_WALLPAPER_MODE,
            font_family=self.font_combo.currentFont().family(),
            font_color=self._chosen_font_color,
            poll_interval_ms=self.poll_interval_spin.value() * 1000,
            overlay_mode=self.overlay_mode_checkbox.isChecked(),
        )
        appearance_settings.save_settings(settings)
        self.appearance_status_label.setText("Applied.")
        self.appearance_applied.emit()

    # -- Discord target list -----------------------------------------------

    def _reload_target_list(self):
        self.target_list.clear()
        for target in discord_targets.load_targets():
            self.target_list.addItem(target.name)

    def _remove_selected(self):
        item = self.target_list.currentItem()
        if item is None:
            return

        confirm = QMessageBox.question(
            self, "Remove Discord Target",
            f'Remove "{item.text()}"? You can always re-add it later with its webhook URL.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        discord_targets.remove_target(item.text())
        self._reload_target_list()

    # -- Add / test --------------------------------------------------------

    def _validate_inputs(self) -> tuple:
        name = self.name_input.text().strip()
        url = self.webhook_input.text().strip()

        if not name or not url:
            return None, None, "Both a name and a webhook URL are required."
        if not url.startswith("https://discord.com/api/webhooks/") and \
           not url.startswith("https://discordapp.com/api/webhooks/"):
            return None, None, "That doesn't look like a Discord webhook URL."
        return name, url, None

    def _test_webhook(self):
        name, url, error = self._validate_inputs()
        if error:
            self.status_label.setText(error)
            return

        self.status_label.setText("Sending test message...")
        self.test_button.setEnabled(False)
        QApplication.processEvents()

        result = discord_api.send_report(url, f"\u2705 Guardian is connected to this channel (test from \"{name}\").")
        self.test_button.setEnabled(True)

        if result.status == "success":
            self.status_label.setText("Test message sent \u2014 check the channel.")
        else:
            self.status_label.setText(f"Test failed: {result.error_message}")

    def _add_target(self):
        name, url, error = self._validate_inputs()
        if error:
            self.status_label.setText(error)
            return

        existing_names = {t.name for t in discord_targets.load_targets()}
        if name in existing_names:
            self.status_label.setText(f'A target named "{name}" already exists.')
            return

        discord_targets.add_target(discord_targets.DiscordTarget(name=name, webhook_url=url))
        self._reload_target_list()
        self.name_input.clear()
        self.webhook_input.clear()
        self.status_label.setText(f'Added "{name}".')
