# Tekken Tournament Organizer

Custom Tekken tournament organizer and tracker: a Phase 1 bracket + round robin
feeding into the Gauntlet (Big Champ / Little Champ king-of-the-hill), run as a
LAN-session desktop app. Players join from their phones via QR code over a
Windows Mobile Hotspot; a second laptop running the app discovers the session
automatically and joins as a match station.

Download the latest Windows build from
[Releases](https://github.com/jzchan132/tournament_organizer/releases) -- no
install needed. Extract the zip and run `TekkenTournamentOrganizer.exe`.

## Development

Requires Python 3.12+ on Windows.

```powershell
# set up
pip install -r requirements.txt

# run the app headless (server only, no desktop window) on port 5000
python run.py --no-window

# run the full desktop app (pywebview window)
python run.py

# run a second instance for LAN-discovery testing
python run.py --no-window --port 5001

# run the tests
pytest tests/
```

The SQLite database lives in `data/tournament.db` (created on first run);
saves and the rolling autosave live in `data/saves/`. Delete
`data/tournament.db` for a clean slate.

## Building the binaries

```powershell
pip install -r requirements.txt pyinstaller
pyinstaller build.spec --noconfirm
```

The app is written to `dist/TekkenTournamentOrganizer/` -- run
`TekkenTournamentOrganizer.exe` inside it. The build bundles templates,
static assets, the schema, and the pywebview/WebView2 loader DLLs; the
WebView2 runtime itself is a runtime dependency that ships with Windows
10/11 (the app falls back to the default browser if it's missing).

## Tagging and pushing a release

Releases are built and published automatically by GitHub Actions
([.github/workflows/release.yml](.github/workflows/release.yml)) whenever a
`v*` tag is pushed:

```powershell
git tag v2.2.0
git push origin v2.2.0
```

The workflow runs the test suite, builds the exe on a Windows runner, stamps
the tag into the build (shown on the app's landing page), and attaches
`TekkenTournamentOrganizer-<tag>-win64.zip` to a GitHub release with player
setup instructions. Nothing needs to be built locally.
