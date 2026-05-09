#!/usr/bin/env bash
# Deploy the Sheela bot to the Oracle Cloud VM.
# Run from your Windows PC via Git Bash or WSL after pushing to the
# SheelaBot GitHub repo.

set -euo pipefail

# ---- Configuration ----------------------------------------------------------
VM_IP="${VM_IP:-REPLACE_WITH_VM_PUBLIC_IP}"
VM_USER="${VM_USER:-ubuntu}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/sheela_vm_key}"
BOT_REPO_URL="${BOT_REPO_URL:-git@github.com:nandanvinjamury/SheelaBot.git}"
BOT_DIR="/home/sheela/bot"
SERVICE_NAME="sheela.service"
# -----------------------------------------------------------------------------

if [[ "$VM_IP" == "REPLACE_WITH_VM_PUBLIC_IP" ]]; then
    echo "ERROR: set VM_IP at the top of deploy.sh (or as env var)." >&2
    exit 1
fi
if [[ ! -f "$SSH_KEY" ]]; then
    echo "ERROR: SSH key not found at $SSH_KEY" >&2
    exit 1
fi

SSH_BASE=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$VM_USER@$VM_IP")
SCP_BASE=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> [1/4] Syncing code on VM ($VM_IP)..."
"${SSH_BASE[@]}" bash <<EOF
set -euo pipefail
sudo -u sheela bash -c '
  set -euo pipefail
  cd "$BOT_DIR"
  if [ ! -d ".git" ]; then
    echo "First deploy: initializing git repo at $BOT_DIR"
    git init -b main
    git remote add origin "$BOT_REPO_URL"
    git fetch origin
    git checkout -B main origin/main
  else
    git fetch origin
    git reset --hard origin/main
  fi
'
EOF

echo "==> [2/4] Installing Python dependencies..."
"${SSH_BASE[@]}" "sudo -u sheela $BOT_DIR/venv/bin/pip install --upgrade pip --quiet && sudo -u sheela $BOT_DIR/venv/bin/pip install -e $BOT_DIR --quiet"

echo "==> [3/4] Installing systemd unit..."
"${SCP_BASE[@]}" "$SCRIPT_DIR/sheela.service" "$VM_USER@$VM_IP:/tmp/sheela.service"
"${SSH_BASE[@]}" "sudo install -m 644 /tmp/sheela.service /etc/systemd/system/$SERVICE_NAME && sudo systemctl daemon-reload && sudo systemctl enable $SERVICE_NAME && sudo systemctl restart $SERVICE_NAME && rm /tmp/sheela.service"

echo "==> [4/4] Recent logs:"
"${SSH_BASE[@]}" "sudo journalctl -u $SERVICE_NAME -n 30 --no-pager" || true

echo
echo "==> Done. Tail logs with:"
echo "    ssh -i $SSH_KEY $VM_USER@$VM_IP 'sudo journalctl -u $SERVICE_NAME -f'"
