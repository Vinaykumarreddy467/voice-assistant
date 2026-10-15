# voice-assistant

Offline, real-time dictation for the Linux desktop. Speak, and your words are
typed into whatever window has focus — editor, browser, terminal, chat — using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally on
the CPU. Nothing leaves your machine.

- **Sentence-by-sentence**: the Silero VAD detects pauses, so each sentence is
  transcribed whole (no words cut at chunk boundaries, no audio dropped).
- **Works on Wayland and X11**: text is typed through a virtual keyboard
  (`/dev/uinput`), not the clipboard.
- **Hotkey toggle**: press <kbd>Super</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> to start,
  again to stop; the session is saved to `~/Transcripts`.
- **Noise-robust**: hum/DC filtering, mic warm-up skip and Whisper
  hallucination filtering ("Thank you.", looping output, …).

## Requirements

- Linux with ALSA/PipeWire, Python ≥ 3.11
- `sudo apt install alsa-utils ffmpeg libnotify-bin`
- For typing into apps: your user in the `input` group
  (`sudo usermod -aG input $USER`, then log out and in)

## Install

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
| `voice toggle` | Start/stop background `voice type` (what the hotkey runs) |

Common options: `--model {tiny,base,small,medium,large-v3}`, `--device hw:0,0`,
`--config PATH`, `-v`.

On an 8-thread laptop CPU, `base` transcribes a 5-second sentence in about a
second; `small` is more accurate but ~3× slower.

## Configuration

Copy [`config.example.toml`](config.example.toml) to
`~/.config/voice-assistant/config.toml`. Every key is optional; unknown keys
are rejected so typos don't go unnoticed.

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
├── desktop.py      notifications and clipboard
├── transcripts.py  saving sessions to ~/Transcripts
└── toggle.py       pid-file/flock based start/stop for the hotkey
```

Each stage depends only on the one before it through plain NumPy arrays or
strings, so the segmenter, transcriber filter and keyboard mapping are unit
tested without a microphone or model.

## Development

```bash
.venv/bin/python -m pytest
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| Random words appear while silent | Input gain too high — run `voice test-mic`; lower the volume in Settings → Sound if it reports clipping |
| Text goes to the clipboard instead of being typed | Not in the `input` group (see Requirements) |
| Hotkey does nothing | Check the log: `cat $XDG_RUNTIME_DIR/voice-dictation.log` |
| Characters wrong | The virtual keyboard assumes a US layout |

## License

[MIT](LICENSE)
