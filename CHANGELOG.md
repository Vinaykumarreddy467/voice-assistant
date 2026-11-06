# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-11-06

### Added
- NVIDIA Parakeet TDT 0.6B v2 engine (`[asr] engine = "parakeet"` or
  `--engine parakeet`): English-only, far more accurate than Whisper base at
  similar speed, with built-in punctuation and capitalisation.
- `voice bench DIR`: word error rate, speed and peak memory on your own
  reference recordings.
- Strict config validation: wrong types and out-of-range values are rejected
  with a message naming the setting.

### Fixed
- The end of the last sentence could be lost when stopping (the mic reader
  quit before draining the pipe).
- Stopping from the hotkey could time out and crash while the last sentence
  was still being transcribed; stop now returns immediately and the daemon
  reports a `stopping` state.
- Push-to-talk on a modifier key (e.g. Right Ctrl) could turn dictated text
  into keyboard shortcuts; output now waits until the key is released.
- `voice setup --remove` could delete, and `voice setup` overwrite, unrelated
  GNOME shortcuts whose command contained "voice".
- Paths with spaces, quotes or `%` broke the hotkey and systemd unit.
- "new line" in the middle of a sentence ("a new line of products") was
  treated as a command.
- AI cleanup could insert line breaks, which act as Enter in a terminal.
- Transcripts were world-readable and could overwrite each other when two
  sessions ended in the same second; they are now 0600 and never clobbered.
- `pre_roll_secs = 0` made the VAD buffer grow without bound.
- Utterances longer than `max_utterance_secs` were cut mid-word; they are now
  split at the quietest point of the last 1.5 s.
- A config `vocabulary = "word"` (string instead of list) became single
  letters; a missing `--config` file was silently ignored.
- Clipboard copies via `wl-copy` hung for 2 s and then failed.
- The `/tmp` fallback for the runtime directory could be pre-created by
  another user; it is now required to be private and owned by you.
- Microphone failures now report arecord's error message.
- The portal keyboard reconnects if the session is ended from the shell.
- A failing control command now replies with an error instead of nothing.

### Changed
- **Parakeet is now the default engine.** On LibriSpeech (73 clips, 1,150
  words) on an i5-8365U laptop: Parakeet 2.87% WER at 0.36× real time;
  Whisper base 10.26% at 0.43×; Whisper small.en 5.83% at 1.23×. Set
  `[asr] engine = "whisper"` for languages other than English.
- The Silero VAD keeps its recurrent state between chunks: identical
  results, ~4.5× less CPU while listening.

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
