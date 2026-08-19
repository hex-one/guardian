"""
about_dialog.py

The footer's heart icon (main.py) opens this -- a small, quiet room off
to the side of the main app. Credits, links to the Ascended VRChat
Group/Discord, and a donation link. Pure static content, no VRChat API
calls involved -- nothing to fetch, nothing to wait on, just the truth
about who built this and why. Same links/donation blurb as the other
Ascended apps, since it's the same community, the same funding, the
same reason any of it exists.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from glow import apply_glow, PRIMARY, INFO, DISCORD

APP_CREDITS_TEXT = (
    "Hey. I'm Jasper Hex -- made this, alongside Ryy, for the Ascended "
    "VRChat community.\n\n"
    "In Ascended, a mod is called a Guardian -- that's where the name "
    "comes from. Built free, for our own mod team, so their day-to-day "
    "got a little easier instead of a little harder. It's branded ours, "
    "but any VRChat group is welcome to run this for their own "
    "community too.\n\n"
    "Part purple wolf who meditates by the lake at 3am, part gamer who "
    "cut his teeth before dial-up was a sure thing -- both halves show "
    "up in how this was built: patient where it needs to be, fast "
    "where it counts, never shipped half-finished.\n\n"
    "Guardian exists so your mods can stay present with your community "
    "instead of buried in browser tabs. That's the whole point."
)
DONATE_BLURB = (
    "Running the Group and building tools like this one has been "
    "fully out-of-pocket the whole way -- VRC+ drops, extra services "
    "for the community, all of it, on me. I want to keep it that "
    "way: everything free, forever, and always getting a little "
    "better. Anything you toss in goes straight back into that, "
    "nothing else. Thank you for being here."
)
DONATION_URL = "https://ko-fi.com/jasperhex_vr"
GROUP_URL = "https://vrchat.com/home/group/grp_3de3f36a-8ac6-4fa3-8a39-b366e85ac1c7"
DISCORD_URL = "https://discord.gg/AUNyc6kjcd"


class AboutDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setObjectName("AboutDialog")
        self.setWindowTitle("About / Support")
        self.resize(360, 600)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Guardian")
        title.setObjectName("aboutTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        credits = QLabel(APP_CREDITS_TEXT)
        credits.setObjectName("aboutCredits")
        credits.setWordWrap(True)
        layout.addWidget(credits)

        link_row = QHBoxLayout()
        group_button = QPushButton("Ascended VRChat Group")
        group_button.setObjectName("aboutGroupButton")
        group_button.setToolTip("Open the Ascended VRChat Group page")
        apply_glow(group_button, INFO)
        group_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(GROUP_URL)))
        link_row.addWidget(group_button)

        discord_button = QPushButton("Ascended Discord")
        discord_button.setObjectName("aboutDiscordButton")
        discord_button.setToolTip("Open the Ascended Discord server")
        apply_glow(discord_button, DISCORD)
        discord_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DISCORD_URL)))
        link_row.addWidget(discord_button)
        layout.addLayout(link_row)

        layout.addSpacing(6)

        donate_blurb = QLabel(DONATE_BLURB)
        donate_blurb.setObjectName("aboutDonateBlurb")
        donate_blurb.setWordWrap(True)
        layout.addWidget(donate_blurb)

        donate_button = QPushButton("☕ Buy us a coffee")
        donate_button.setObjectName("aboutDonateButton")
        donate_button.setToolTip("Open the donation page")
        apply_glow(donate_button, PRIMARY)
        donate_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DONATION_URL)))
        layout.addWidget(donate_button)

        layout.addStretch()

        close_button = QPushButton("Close")
        close_button.setObjectName("aboutCloseButton")
        close_button.setToolTip("Close this window")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)
