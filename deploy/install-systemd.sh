#!/usr/bin/env bash
#
# Supervise the ingestion stack with systemd user units.
#
# Why this exists: a Temporal schedule can only fire while the Temporal server
# AND the worker are both running. There are two - `icc-daily-sync` at 06:00
# and `news-sync` every three hours - and the news one makes this sharper, not
# softer: eight windows a day means eight silent misses a day, and a news feed
# that is a day stale is visibly wrong in a way a ranking snapshot is not. Started by hand in a terminal they die
# with the session, and the schedule then skips silently -- it fired on 13 and 14
# August 2026 and missed the 15th and 16th for exactly that reason. A missed run
# leaves no error anywhere; the data just quietly stops being daily.
#
# Units are generated here rather than committed as files so the paths match
# wherever the repo actually lives.
#
#   ./deploy/install-systemd.sh            # install, enable and start
#   ./deploy/install-systemd.sh --uninstall
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
VENV_PY="$PROJECT_ROOT/venv/bin/python"
TEMPORAL_BIN="$(command -v temporal || echo "$HOME/.temporalio/bin/temporal")"
UNITS=(cricket-temporal.service cricket-worker.service)

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now "${UNITS[@]}" 2>/dev/null || true
  rm -f "${UNITS[@]/#/$UNIT_DIR/}"
  systemctl --user daemon-reload
  echo "Removed: ${UNITS[*]}"
  exit 0
fi

for required in "$VENV_PY" "$TEMPORAL_BIN"; do
  [[ -x "$required" ]] || { echo "Not executable: $required" >&2; exit 1; }
done

mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/cricket-temporal.service" <<UNIT
[Unit]
Description=Temporal dev server for The Cricket Index
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$PROJECT_ROOT
ExecStart=$TEMPORAL_BIN server start-dev --db-filename $PROJECT_ROOT/temporal.db
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT

# Requires= rather than only After=: a worker with no server to poll is not
# degraded, it is useless, and it should stop and restart with the server.
cat > "$UNIT_DIR/cricket-worker.service" <<UNIT
[Unit]
Description=Ingestion worker for The Cricket Index
After=cricket-temporal.service
Requires=cricket-temporal.service

[Service]
Type=simple
WorkingDirectory=$PROJECT_ROOT/ingestion
ExecStart=$VENV_PY -u worker.py
# systemd user units do NOT inherit the shell environment, so anything the
# worker reads from os.environ has to be named here or it silently takes its
# default. GUARDIAN_API_KEY falling back to their open `test` key is the one
# that bites: it works, so nothing fails, it just runs the Guardian leg on a
# shared key. Set these in ~/.config/cricket-index.env; the file is optional.
EnvironmentFile=-%h/.config/cricket-index.env
Restart=always
RestartSec=5
# The server needs a moment to accept connections after a cold start; without
# this the worker crash-loops on the first boot and systemd rate-limits it.
ExecStartPre=/bin/sleep 5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now "${UNITS[@]}"

echo "Installed and started: ${UNITS[*]}"
echo
echo "  status:  systemctl --user status cricket-worker"
echo "  logs:    journalctl --user -u cricket-worker -f"
echo
echo "  Optional worker environment (create if you need it):"
echo "    ~/.config/cricket-index.env"
echo "      GUARDIAN_API_KEY=your-key      # defaults to their open 'test' key"
echo "      NEWS_IMAGE_PROBE=1             # measure image dimensions no source declares"
echo "      NEWS_USER_AGENT=...            # identify this crawler to publishers"
echo
echo "  Register both schedules once the worker is up:"
echo "    cd $PROJECT_ROOT/ingestion && $VENV_PY schedule.py"
echo
if [[ "$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null)" != "yes" ]]; then
  cat <<'NOTE'
NOTE: linger is off, so these stop when you log out and both schedules will
still miss windows on a machine you do not stay logged into. Enable it with:

    sudo loginctl enable-linger $USER

That is a persistent change to your login session, so it is left for you to run.
NOTE
fi
