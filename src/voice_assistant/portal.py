"""Typing through the XDG RemoteDesktop portal (Wayland).

Unlike the uinput keyboard this needs no ``input`` group membership and
sends *keysyms*, so the compositor maps them onto whatever keyboard layout
is active. The first session shows a one-time "Allow remote interaction"
dialog; the restore token it returns is stored so later sessions start
without asking.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.RemoteDesktop"
DEVICE_KEYBOARD = 1
PERSIST_UNTIL_REVOKED = 2

KEYSYM_SPECIAL = {"\n": 0xFF0D, "\t": 0xFF09, "\b": 0xFF08}  # Return, Tab, BackSpace
KEYSYM_BACKSPACE = 0xFF08


class PortalError(RuntimeError):
    pass


def token_path() -> Path:
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return state / "voice-assistant" / "portal-restore-token"


def keysym_for(char: str) -> int | None:
    """X11 keysym for a character (Latin-1 maps 1:1, the rest via 0x01000000 + code)."""
    if char in KEYSYM_SPECIAL:
        return KEYSYM_SPECIAL[char]
    code = ord(char)
    if code < 0x20 or code == 0x7F:
        return None
    if code <= 0xFF:
        return code
    return 0x01000000 + code


class PortalKeyboard:
    def __init__(self, key_delay: float = 0.004, timeout: float = 120.0):
        from gi.repository import Gio, GLib

        self._GLib = GLib
        self._delay = key_delay
        self._timeout = timeout
        self._bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self._sender = self._bus.get_unique_name()[1:].replace(".", "_")
        # Private context so portal replies are processed on this thread,
        # independent of whatever main loop the application runs.
        self._ctx = GLib.MainContext.new()
        self._session = self._open_session()

    # ── portal request/response plumbing ──
    def _call(self, method: str, params: Any, reply_type: str | None = None):
        return self._bus.call_sync(
            BUS_NAME,
            OBJECT_PATH,
            IFACE,
            method,
            params,
            self._GLib.VariantType(reply_type) if reply_type else None,
            0,
            -1,
            None,
        )

    def _request(self, method: str, args: list, options: dict) -> dict:
        """Call a portal method and wait for its Request::Response signal."""
        GLib = self._GLib
        handle = "voice_" + secrets.token_hex(6)
        request_path = f"{OBJECT_PATH}/request/{self._sender}/{handle}"
        result: dict[str, Any] = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            code, results = params.unpack()
            result["code"], result["results"] = code, results

        self._ctx.push_thread_default()
        try:
            sub = self._bus.signal_subscribe(
                BUS_NAME,
                "org.freedesktop.portal.Request",
                "Response",
                request_path,
                None,
                0,
                on_response,
            )
            options = {"handle_token": GLib.Variant("s", handle), **options}
            signature = "(" + "".join(sig for sig, _ in args) + "a{sv})"
            values = tuple(v for _, v in args) + (options,)
            self._call(method, GLib.Variant(signature, values), "(o)")
            deadline = time.monotonic() + self._timeout
            while "code" not in result and time.monotonic() < deadline:
                if not self._ctx.iteration(False):
                    time.sleep(0.02)
            self._bus.signal_unsubscribe(sub)
        finally:
            self._ctx.pop_thread_default()

        if "code" not in result:
            raise PortalError(f"{method}: no answer from the portal")
        if result["code"] != 0:
            raise PortalError(f"{method}: denied or cancelled (code {result['code']})")
        return result["results"]

    def _open_session(self) -> str:
        GLib = self._GLib
        created = self._request(
            "CreateSession",
            [],
            {
                "session_handle_token": GLib.Variant("s", "voice_" + secrets.token_hex(6)),
            },
        )
        session = created["session_handle"]

        select = {
            "types": GLib.Variant("u", DEVICE_KEYBOARD),
            "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED),
        }
        path = token_path()
        if path.is_file():
            select["restore_token"] = GLib.Variant("s", path.read_text().strip())
        self._request("SelectDevices", [("o", session)], select)

        started = self._request("Start", [("o", session), ("s", "")], {})
        if not started.get("devices", 0) & DEVICE_KEYBOARD:
            raise PortalError("keyboard access was not granted")
        if started.get("restore_token"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(started["restore_token"])
            path.chmod(0o600)
        log.info("remote-desktop portal session ready")
        return session

    # ── typing ──
    def _keysym(self, keysym: int) -> None:
        GLib = self._GLib
        for state in (1, 0):
            self._call(
                "NotifyKeyboardKeysym",
                GLib.Variant("(oa{sv}iu)", (self._session, {}, keysym, state)),
            )
            time.sleep(self._delay)

    def type(self, text: str) -> None:
        for char in text:
            keysym = keysym_for(char)
            if keysym is not None:
                self._keysym(keysym)

    def backspace(self, count: int) -> None:
        for _ in range(count):
            self._keysym(KEYSYM_BACKSPACE)

    def close(self) -> None:
        try:
            self._bus.call_sync(
                BUS_NAME,
                self._session,
                "org.freedesktop.portal.Session",
                "Close",
                None,
                None,
                0,
                -1,
                None,
            )
        except Exception as exc:  # session already gone
            log.debug("closing portal session: %s", exc)
