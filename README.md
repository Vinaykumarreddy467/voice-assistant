# voice-assistant

Offline, real-time dictation for the Linux desktop. Speak, and your words are
typed into whatever window has focus — editor, browser, terminal, chat — using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally on
the CPU. Nothing leaves your machine.

- **Sentence-by-sentence**: the Silero VAD detects pauses, so each sentence is
  transcribed whole (no words cut at chunk boundaries, no audio dropped).
- **Works on Wayland and X11**: text is typed through a virtual keyboard
  (`/dev/uinput`), or — with no special permissions and on any keyboard
  layout — through the desktop's RemoteDesktop portal.
- **Instant hotkey**: a background service keeps Whisper loaded; press
  <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> to start, again to stop. The
  session is saved to `~/Transcripts`. A top-bar icon shows when it's listening.
- **Push-to-talk**: optionally hold a key (e.g. Right Ctrl) to dictate.
- **Voice commands**: "new line", "new paragraph", "scratch that", "stop dictation".
- **Optional AI cleanup** with a local [Ollama](https://ollama.com) model:
  punctuation, casing and filler words fixed, still fully offline.
- **Personal vocabulary** so names and jargon are spelled right.
- **Noise-robust**: hum/DC filtering, mic warm-up skip and Whisper
  hallucination filtering ("Thank you.", looping output, …).

## Requirements

- Linux with ALSA/PipeWire, Python ≥ 3.11
- `sudo apt install alsa-utils ffmpeg libnotify-bin`
- Optional: your user in the `input` group (`sudo usermod -aG input $USER`,
  then log out and in) for the fastest typing backend and push-to-talk.
  Without it, typing goes through the RemoteDesktop portal (GNOME asks once).

## Install

With [pipx](https://pipx.pypa.io) (once published on PyPI):

```bash
pipx install --system-site-packages whisper-dictate
voice setup          # hotkey + background service for GNOME or KDE
```

`--system-site-packages` lets it use your distro's PyGObject for the top-bar
icon, clipboard and portal typing.

From source:

```bash
git clone https://github.com/Vinaykumarreddy467/voice-assistant.git ~/.voice-assistant
cd ~/.voice-assistant
scripts/install.sh
```

This creates `.venv/`, installs the package in editable mode, puts `voice` and
`voice-toggle` in `~/.local/bin` and registers the GNOME hotkey
(`--no-shortcut` to skip). The first run downloads the Whisper model
(~150 MB for `base`) to `~/.cache/whisper-models`.

## Usage

| Command | What it does |
|---|---|
| `voice` | Live dictation printed in the terminal |
| `voice type` | Live dictation typed into the focused window |
| `voice once` | Record one sentence, transcribe, copy to clipboard |
| `voice file talk.mp3` | Transcribe an audio/video file |
| `voice test-mic` | Check background noise, speech level and clipping |
| `voice devices` | List microphones |
| `voice toggle` | Start/stop dictation via the daemon (what the hotkey runs) |
| `voice daemon` | Background service (installed as `voice-assistant.service`) |
| `voice start` / `stop` / `status` / `quit` | Control the running daemon |
| `voice setup [--remove]` | Install (or remove) the hotkey and background service |

Common options: `--model {tiny,base,small,medium,large-v3}`, `--device hw:0,0`,
`--language en|hi|te|ta|…|auto`, `--config PATH`, `-v`.

### Languages

Whisper understands ~100 languages. Set `language` to a code (`hi`, `te`,
`ta`, `kn`, `bn`, `es`, …) or `"auto"`. Non-English accuracy improves a lot
with `--model small` or larger. Typing non-ASCII text needs the portal
backend (`[output] keyboard = "portal"`) and a keyboard layout that contains
those characters.

### Typing backends

| `[output] keyboard` | How | Needs |
|---|---|---|
| `auto` (default) | uinput if allowed, else portal | — |
| `uinput` | Virtual keyboard device; US layout | `input` group |
| `portal` | RemoteDesktop portal keysyms; any layout | GNOME/KDE on Wayland, one-time permission |

On an 8-thread laptop CPU, `base` transcribes a 5-second sentence in about a
second; `small` is more accurate but ~3× slower.

## Configuration

Copy [`config.example.toml`](config.example.toml) to
`~/.config/voice-assistant/config.toml`. Every key is optional; unknown keys
are rejected so typos don't go unnoticed.

### Voice commands

| Say | Effect |
|---|---|
| "new line" / "new paragraph" | Inserts a line break / blank line (note: Enter sends messages in chat apps) |
| "scratch that" / "delete that" | Removes the previous sentence |
| "stop dictation" | Ends the session |

### AI cleanup (optional)

```toml
[cleanup]
enabled = true
model = "llama3.2:3b"     # any Ollama model
```

Requires a running Ollama. On an older laptop CPU a 3B model adds several
seconds per sentence, so it's off by default; it's fast on a GPU.

## Architecture

```
src/voice_assistant/
├── cli.py          argument parsing, command dispatch, signal handling
├── config.py       typed defaults (dataclasses) + TOML overrides
├── session.py      pipeline: mic → segmenter → transcriber → sink
├── audio.py        arecord capture thread, high-pass filter, ffmpeg decoding
├── vad.py          Silero-VAD utterance segmenter (streaming, chunk-size independent)
├── transcriber.py  faster-whisper wrapper + hallucination filtering
├── sinks.py        output targets: terminal, virtual keyboard, clipboard fallback
├── keyboard.py     uinput virtual keyboard (US layout)
├── portal.py       RemoteDesktop-portal keyboard (any layout, no permissions)
├── setup.py        `voice setup`: hotkey (GNOME/KDE) + systemd user service
├── desktop.py      notifications and clipboard
├── transcripts.py  saving sessions to ~/Transcripts
├── commands.py     spoken commands ("new line", "scratch that", …)
├── cleanup.py      optional Ollama post-processing
├── daemon.py       background service + Unix-socket control protocol
├── indicator.py    top-bar icon (AppIndicator)
├── hotkey.py       push-to-talk via evdev
└── toggle.py       hotkey fallback when the daemon isn't running
```

Each stage depends only on the one before it through plain NumPy arrays or
strings, so the segmenter, transcriber filter and keyboard mapping are unit
tested without a microphone or model.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

```bash
.venv/bin/ruff check . && .venv/bin/python -m pytest
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Random words appear while silent | Input gain too high — run `voice test-mic`; lower the volume in Settings → Sound if it reports clipping |
| Text goes to the clipboard instead of being typed | Not in the `input` group (see Requirements) |
| Hotkey does nothing | `voice status`; logs: `journalctl --user -u voice-assistant -n 50` |
| No top-bar icon | Enable the "AppIndicator and KStatusNotifierItem Support" GNOME extension |
| Characters wrong | uinput assumes a US layout — set `[output] keyboard = "portal"` |
| GNOME shows a "remote control" icon | Expected with the portal backend while the daemon runs |

## License

[MIT](LICENSE)
