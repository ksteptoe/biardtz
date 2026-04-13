#!/usr/bin/env bash
# Install biardtz as a systemd service.
# Run as: sudo bash systemd/install.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/biardtz.service"

if [[ ! -f "$SERVICE_FILE" ]]; then
    echo "Error: $SERVICE_FILE not found" >&2
    exit 1
fi

echo "Installing biardtz.service..."
cp "$SERVICE_FILE" /etc/systemd/system/biardtz.service
systemctl daemon-reload
systemctl enable biardtz.service
echo "Service installed and enabled."

echo ""
echo "Commands:"
echo "  sudo systemctl start biardtz     # start now"
echo "  sudo systemctl stop biardtz      # stop"
echo "  sudo systemctl restart biardtz   # restart"
echo "  sudo systemctl status biardtz    # check status"
echo "  journalctl -u biardtz -f         # follow logs"
echo "  biardtz status                   # pipeline health"
