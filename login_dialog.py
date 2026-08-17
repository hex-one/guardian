"""
login_dialog.py

The login screen. The threshold you cross before anything else happens.
Handles the two-step VRChat login (password, then possibly a 2FA code)
using vrchat_api.py, and hands back an authenticated VRChatClient when
successful.

--------------------------------------------------------------------------
BEGINNER NOTES:

- This is a QDialog (a popup window), not the main app window. main.py
  shows this FIRST, and only opens the main QuickMOD window once this
  dialog reports a successful login.

- QStackedWidget is a container that holds multiple "pages" of widgets but
  only shows ONE at a time. We use it to swap between the "enter your
  password" page and the "enter your 2FA code" page, without needing two
  separate windows.

- STYLING HOOK: every widget here has `.setObjectName(...)` called on it.
  That doesn't change how it behaves -- it just gives it a name that a Qt
  Style Sheet (QSS -- Qt's CSS-like styling language) can target later,
  e.g.:

      #loginButton {
          background: #1a1a2e;
          border: 1px solid #00e5ff;
      }
      #loginButton:hover {
          border: 1px solid #ff2fd0;
          /* glow effects usually come from a QGraphicsDropShadowEffect
             applied in code rather than pure QSS, since QSS has no direct
             box-shadow -- happy to wire that up when you're ready */
      }

  This file is intentionally left plain/undecorated so your custom QSS can
  be dropped into style.qss (see main.py) without touching any logic here.

- Network calls (login/2FA) happen directly on the GUI thread here, which
  means the window will briefly "freeze" (not respond to clicks) while
  waiting for VRChat's servers to respond -- usually well under a second.
  If that ever feels laggy, the fix is running the network call on a
  QThread instead; we can add that later without changing how this dialog
  is used from the outside.
--------------------------------------------------------------------------
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QStackedWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QApplication,
)

import vrchat_api
from vrchat_api import VRChatClient, LoginResult
from glow import apply_glow, PRIMARY


class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setObjectName("LoginDialog")
        self.setWindowTitle("Guardian — Login")
        self.resize(340, 220)

        self.client = VRChatClient()
        self.authenticated = False  # main.py checks this after showing the dialog
        self._pending_2fa_method = None

        self._build_ui()

        # If we've got a valid saved session from last time, we can skip
        # the login form entirely.
        if self.client.try_load_session():
            self.authenticated = True

    # -- UI ----------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)

        self.title_label = QLabel("Guardian")
        self.title_label.setObjectName("loginTitle")
        self.title_label.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.title_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("loginStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        self.stack = QStackedWidget()
        self.stack.setObjectName("loginStack")
        outer.addWidget(self.stack)

        self.stack.addWidget(self._build_credentials_page())  # index 0
        self.stack.addWidget(self._build_2fa_page())           # index 1

    def _build_credentials_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("credentialsPage")
        layout = QVBoxLayout(page)

        self.username_input = QLineEdit()
        self.username_input.setObjectName("usernameInput")
        self.username_input.setPlaceholderText("VRChat username")
        self.username_input.setToolTip("Your VRChat account username")
        remembered = vrchat_api.get_remembered_username()
        if remembered:
            self.username_input.setText(remembered)
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setObjectName("passwordInput")
        self.password_input.setPlaceholderText("Password")
        self.password_input.setToolTip("Your VRChat account password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self._attempt_login)
        layout.addWidget(self.password_input)

        self.remember_checkbox = QCheckBox("Remember me on this PC")
        self.remember_checkbox.setObjectName("rememberCheckbox")
        self.remember_checkbox.setToolTip("Save your username/session locally so you don't have to log in every time")
        self.remember_checkbox.setChecked(True)  # default on -- most mods will want this
        layout.addWidget(self.remember_checkbox)

        self.login_button = QPushButton("Log In")
        self.login_button.setObjectName("loginButton")
        self.login_button.setToolTip("Submit and log in")
        apply_glow(self.login_button, PRIMARY)
        self.login_button.clicked.connect(self._attempt_login)
        layout.addWidget(self.login_button)

        return page

    def _build_2fa_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("twoFactorPage")
        layout = QVBoxLayout(page)

        self.twofactor_hint_label = QLabel("")
        self.twofactor_hint_label.setObjectName("twoFactorHint")
        self.twofactor_hint_label.setWordWrap(True)
        layout.addWidget(self.twofactor_hint_label)

        self.twofactor_input = QLineEdit()
        self.twofactor_input.setObjectName("twoFactorInput")
        self.twofactor_input.setPlaceholderText("6-digit code")
        self.twofactor_input.setToolTip("The 6-digit two-factor code from your authenticator or email")
        self.twofactor_input.returnPressed.connect(self._attempt_2fa)
        layout.addWidget(self.twofactor_input)

        self.twofactor_button = QPushButton("Verify")
        self.twofactor_button.setObjectName("twoFactorButton")
        self.twofactor_button.setToolTip("Submit the two-factor code")
        apply_glow(self.twofactor_button, PRIMARY)
        self.twofactor_button.clicked.connect(self._attempt_2fa)
        layout.addWidget(self.twofactor_button)

        return page

    # -- Actions -------------------------------------------------------------

    def _attempt_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text()

        if not username or not password:
            self.status_label.setText("Enter both a username and password.")
            return

        self._attempted_username = username  # used by _handle_result on success

        self.status_label.setText("Logging in...")
        self.login_button.setEnabled(False)
        QApplication.processEvents()  # let the "Logging in..." text actually draw before we block

        result = self.client.login(username, password)
        self.login_button.setEnabled(True)
        self._handle_result(result)

    def _attempt_2fa(self):
        code = self.twofactor_input.text().strip()
        if not code:
            self.status_label.setText("Enter your 2FA code.")
            return

        self.status_label.setText("Verifying...")
        self.twofactor_button.setEnabled(False)
        QApplication.processEvents()

        result = self.client.verify_2fa(code, self._pending_2fa_method)
        self.twofactor_button.setEnabled(True)
        self._handle_result(result)

    def _handle_result(self, result: LoginResult):
        if result.status == "success":
            self.status_label.setText(f"Logged in as {result.display_name}.")

            if self.remember_checkbox.isChecked():
                self.client.save_session()
                username = getattr(self, "_attempted_username", None)
                if username:
                    vrchat_api.remember_username(username)
            else:
                # Explicit opt-out -- don't leave a stale session or
                # username behind from a previous "remember me" choice.
                self.client.clear_saved_session()
                vrchat_api.forget_username()

            self.authenticated = True
            self.accept()  # closes the dialog with an "accepted" result

        elif result.status == "needs_2fa":
            self._pending_2fa_method = result.two_factor_method
            method_label = "authenticator app" if result.two_factor_method == "totp" else "email"
            self.twofactor_hint_label.setText(f"Enter the code from your {method_label}.")
            self.status_label.setText("")
            self.stack.setCurrentIndex(1)
            self.twofactor_input.setFocus()

        else:  # "error"
            self.status_label.setText(result.error_message or "Login failed.")
