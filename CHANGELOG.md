# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.4.0] - 2026-10-16

### Added
- Typing through the XDG RemoteDesktop portal: no `input` group needed and
  any keyboard layout works (`[output] keyboard = "auto" | "uinput" | "portal"`).
  The one-time permission is remembered via a restore token.
- `voice setup [--remove]` installs the hotkey (GNOME, and KDE Plasma via
  kglobalaccel) and the systemd user service — works for pipx installs too.
- `--language` option (e.g. `hi`, `te`, `auto`).
- mypy type checking in CI; PyPI trusted-publishing job in the release workflow.

### Changed
- Distribution renamed to `whisper-dictate` on PyPI (`voice-assistant` was
  taken). The `voice` command and import package are unchanged.

## [0.3.0] - 2026-10-15

### Added
- `voice daemon` background service (systemd user unit) that keeps Whisper
  loaded, so the hotkey starts listening instantly; `voice start|stop|status|quit`.
- Top-bar icon showing idle/listening state, with a start/stop menu.
- Push-to-talk: hold a configurable key (`[hotkey] push_to_talk`) to dictate.
- Voice commands: "new line", "new paragraph", "scratch that", "stop dictation".
- Optional local LLM cleanup through Ollama (`[cleanup] enabled = true`).
- Personal vocabulary (`[whisper] vocabulary = [...]`) and `language = "auto"`.
- Release workflow, ruff linting in CI, contributor guide.

### Changed
- "Listening" is signalled only after the microphone warm-up, so the first
  words are no longer discarded.

## [0.2.0] - 2026-10-15

### Changed
- Restructured the single-file script into a tested, installable package with
  Silero-VAD segmentation, a `voice` CLI, TOML config and an install script.
