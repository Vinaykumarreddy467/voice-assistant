"""Desktop integration installer: ``voice setup`` / ``voice setup --remove``.

Registers the global hotkey (GNOME via dconf, KDE Plasma via kglobalaccel)
and the systemd user service that keeps the model loaded. Works the same
whether the package came from pipx, pip or a git checkout.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_NAME = "voice-assistant.service"
DESKTOP_ID = "io.github.vinaykumarreddy467.VoiceToggle.desktop"
GNOME_BASE = "/org/gnome/settings-daemon/plugins/media-keys"

SERVICE_TEMPLATE = """\
[Unit]
Description=Voice dictation daemon (speech model kept loaded for instant hotkey)
Documentation=https://github.com/Vinaykumarreddy467/voice-assistant
PartOf=graphical-session.target
After=graphical-session.target pipewire.service

[Service]
ExecStart={exec_voice} daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
"""


SHORTCUT_NAME = "Voice Dictation"


def voice_executable() -> str:
    """Absolute path of the `voice` command that is running this setup.

    Prefers the invoked script over ``which voice``, which could find a
    different install (or an unrelated program) earlier on $PATH.
    """
    argv0 = Path(sys.argv[0])
    if argv0.name == "voice" and argv0.exists():
        return str(argv0.absolute())
    beside = Path(sys.executable).with_name("voice")
    if beside.exists():
        return str(beside)
    found = shutil.which("voice")
    return str(Path(found).absolute()) if found else str(beside)


def gvariant_str(value: str) -> str:
    """Quote a string as a GVariant text literal for `dconf write`."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def desktop_exec(voice: str) -> str:
    """Exec= line for a .desktop file (freedesktop quoting rules)."""
    escaped = "".join("\\" + c if c in '"`$\\' else c for c in voice).replace("%", "%%")
    return f'"{escaped}" toggle'


def systemd_quote(value: str) -> str:
    """Quote one ExecStart argument (spaces, quotes, and % specifiers)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    return f'"{escaped}"'


def _run(*cmd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def desktop_environment() -> str:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in desktop or "unity" in desktop:
        return "gnome"
    if "kde" in desktop:
        return "kde"
    return desktop or "unknown"


# ── GNOME ──


def _dconf_list(raw: str) -> list[str]:
    return re.findall(r"'([^']*)'", raw)


def _dconf_format(paths: list[str]) -> str:
    return "[" + ", ".join(f"'{p}'" for p in paths) + "]" if paths else "@as []"


_OUR_COMMAND = re.compile(r"(^|/)(voice toggle|voice-toggle)$")


def _is_ours(path: str) -> bool:
    """Only shortcuts this tool created — never another app's 'voice' shortcut."""
    name = _run("dconf", "read", f"{path}name").stdout.strip()
    command = _run("dconf", "read", f"{path}command").stdout.strip().strip("'\"")
    command = command.replace("'", "").replace('"', "")
    return name == gvariant_str(SHORTCUT_NAME) and bool(_OUR_COMMAND.search(command))


def gnome_shortcut(command: str, binding: str, remove: bool = False) -> str:
    paths = _dconf_list(_run("dconf", "read", f"{GNOME_BASE}/custom-keybindings").stdout)
    ours = [p for p in paths if _is_ours(p)]
    if remove:
        for p in ours:
            _run("dconf", "reset", "-f", p)
        _run(
            "dconf",
            "write",
            f"{GNOME_BASE}/custom-keybindings",
            _dconf_format([p for p in paths if p not in ours]),
        )
        return "GNOME hotkey removed"
    if ours:
        path = ours[0]
    else:
        i = 0
        while any(p.endswith(f"/custom{i}/") for p in paths):
            i += 1
        path = f"{GNOME_BASE}/custom-keybindings/custom{i}/"
        _run("dconf", "write", f"{GNOME_BASE}/custom-keybindings", _dconf_format(paths + [path]))
    _run("dconf", "write", f"{path}name", gvariant_str(SHORTCUT_NAME))
    _run("dconf", "write", f"{path}command", gvariant_str(command))
    _run("dconf", "write", f"{path}binding", gvariant_str(binding))
    return f"GNOME hotkey {binding} → {command}"


# ── KDE Plasma ──


def _gnome_to_kde(binding: str) -> str:
    """'<Shift><Super>v' → 'Meta+Shift+V'."""
    mods = re.findall(r"<(\w+)>", binding)
    key = re.sub(r"<\w+>", "", binding).upper()
    names = {"Super": "Meta", "Shift": "Shift", "Control": "Ctrl", "Primary": "Ctrl", "Alt": "Alt"}
    order = ["Meta", "Ctrl", "Alt", "Shift"]
    kde = sorted({names.get(m, m) for m in mods}, key=lambda m: order.index(m) if m in order else 9)
    return "+".join([*kde, key])


def kde_shortcut(command: str, binding: str, remove: bool = False) -> str:
    apps = Path.home() / ".local/share/applications"
    desktop_file = apps / DESKTOP_ID
    writer = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if remove:
        desktop_file.unlink(missing_ok=True)
        if writer:
            _run(
                writer,
                "--file",
                "kglobalshortcutsrc",
                "--group",
                "services",
                "--group",
                DESKTOP_ID,
                "--key",
                "_launch",
                "--delete",
            )
        return "KDE hotkey removed"
    apps.mkdir(parents=True, exist_ok=True)
    desktop_file.write_text(
        "[Desktop Entry]\nType=Application\nName=Voice Dictation Toggle\n"
        f"Exec={command}\nIcon=audio-input-microphone\nNoDisplay=true\n"
    )
    if not writer:
        return f"KDE: kwriteconfig not found; bind '{command}' in System Settings → Shortcuts"
    kde_key = _gnome_to_kde(binding)
    _run(
        writer,
        "--file",
        "kglobalshortcutsrc",
        "--group",
        "services",
        "--group",
        DESKTOP_ID,
        "--key",
        "_launch",
        kde_key,
    )
    _run(
        "dbus-send",
        "--session",
        "--type=method_call",
        "--dest=org.kde.kglobalaccel",
        "/kglobalaccel",
        "org.kde.KGlobalAccel.reloadConfig",
    )
    return f"KDE hotkey {kde_key} → {command} (log out and in if it doesn't fire)"


# ── systemd ──


def systemd_service(voice: str, remove: bool = False) -> str:
    if _run("systemctl", "--user", "show-environment").returncode != 0:
        return "systemd user session not available; run 'voice daemon' from your autostart"
    unit = Path.home() / ".config/systemd/user" / SERVICE_NAME
    if remove:
        _run("systemctl", "--user", "disable", "--now", SERVICE_NAME)
        unit.unlink(missing_ok=True)
        _run("systemctl", "--user", "daemon-reload")
        return "background service removed"
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(SERVICE_TEMPLATE.format(exec_voice=systemd_quote(voice)))
    _run("systemctl", "--user", "daemon-reload")
    _run("systemctl", "--user", "enable", SERVICE_NAME)
    result = _run("systemctl", "--user", "restart", SERVICE_NAME)
    if result.returncode != 0:
        return f"background service installed but failed to start: {result.stderr.strip()}"
    return "background service enabled (voice-assistant.service)"


def run(binding: str = "<Shift><Super>v", hotkey: bool = True, remove: bool = False) -> list[str]:
    voice = voice_executable()
    command = f"{shlex.quote(voice)} toggle"  # GNOME/KDE split commands shell-style
    report = [systemd_service(voice, remove)]
    if hotkey:
        de = desktop_environment()
        if de == "gnome" and shutil.which("dconf"):
            report.append(gnome_shortcut(command, binding, remove))
        elif de == "kde":
            report.append(kde_shortcut(desktop_exec(voice), binding, remove))
        elif not remove:
            report.append(f"unsupported desktop '{de}': bind a key to run '{command}'")
    return report
