# Contributing

Thanks for helping! Bug reports, ideas and pull requests are all welcome.

## Setup

```bash
git clone https://github.com/Vinaykumarreddy467/voice-assistant.git
cd voice-assistant
scripts/install.sh --no-shortcut     # creates .venv with dev tools
```

## Before opening a pull request

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/python -m pytest
```

- Keep pull requests focused on one change and add a test for it. The
  pipeline stages (`vad`, `transcriber.clean_segments`, `commands`,
  `keyboard.key_for`, …) are pure functions or take injected fakes, so tests
  never need a microphone or a model.
- Add a line under *Unreleased* in `CHANGELOG.md` for user-visible changes.
- When reporting a bug, include `voice --version`, your distro/desktop
  (GNOME/KDE, Wayland/X11) and the output of `voice test-mic`.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `src/voice_assistant/__init__.py`,
   move *Unreleased* notes in `CHANGELOG.md` under the new version.
2. `git tag vX.Y.Z && git push --tags` — the release workflow builds the wheel
   and sdist and attaches them to a GitHub release.
