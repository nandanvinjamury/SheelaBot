# Warden

The codebase that runs Sheela — a personal Discord-based AI assistant. The bot lives on a private Discord server, talks to Claude, and reads/writes a private Obsidian vault.

This repo (`SheelaBot`) is the bot software. The vault repo (`Sheela`) is the data. Separate lifecycles, separate audiences.

## Status: Step 1 — hello world

The bot connects to Discord and replies `pong` to `ping`. No Claude integration, no vault tools, no persona loading yet — those land in Steps 2–6.

## Local development

Requires Python 3.12+. Recommended: [uv](https://github.com/astral-sh/uv) (`pipx install uv` or `pip install uv`).

```bash
# Set up a venv and install with dev deps
uv venv
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env: fill in DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, ANTHROPIC_API_KEY at minimum.

# Run the bot
uv run python -m sheela

# Run tests
uv run pytest
```

Plain pip works too if you'd rather: `python -m venv .venv && .venv/Scripts/activate && pip install -e ".[dev]"`.

## Deploying to the VM

The bot runs as a systemd service on an Oracle Cloud Always Free ARM VM (Ubuntu 24.04, Chicago region — provisioned in Phase 1).

Before the first deploy, edit [deploy/deploy.sh](deploy/deploy.sh) and set:
- `VM_IP` — the VM's public IP
- `BOT_REPO_URL` — the SSH URL of the GitHub `SheelaBot` repo

Or pass them as env vars at invocation:

```bash
VM_IP=1.2.3.4 BOT_REPO_URL=git@github.com:youruser/SheelaBot.git ./deploy/deploy.sh
```

Run from Git Bash or WSL on Windows. The script:

1. SSHes to the VM as `ubuntu` (using `~/.ssh/sheela_vm_key`)
2. Pulls the latest code into `/home/sheela/bot/` — initializes the git repo on first deploy, hard-resets to `origin/main` thereafter
3. Installs deps via `pip install -e .` in the venv at `/home/sheela/bot/venv/`
4. Installs/reloads the systemd unit and restarts the service
5. Prints recent journal logs

## Environment file on the VM

Phase 1 created `/home/sheela/.config/sheela.env` (mode 0600). The systemd unit reads it via `EnvironmentFile=`. Keys must match those listed in [.env.example](.env.example). To change config without redeploying code, edit that file and `sudo systemctl restart sheela.service`.

## Layout

```
Warden/
├── sheela/                  # the package — entry: python -m sheela
│   ├── config.py            # pydantic-settings Settings
│   ├── __main__.py          # logging + bot startup
│   └── discord_bot/
│       └── bot.py           # discord.py client + ping handler
├── tests/                   # pytest
├── deploy/
│   ├── sheela.service       # systemd unit
│   └── deploy.sh            # SSH deploy
└── pyproject.toml
```

Files like `persona.py`, `llm.py`, `memory.py`, and `tools/` are added in later steps.

## Logs

- Local: stdout
- VM: stdout (captured by systemd → `journalctl -u sheela.service`) and a rotating file at `/home/sheela/logs/sheela.log`

```bash
# Tail VM logs
ssh -i ~/.ssh/sheela_vm_key ubuntu@$VM_IP 'sudo journalctl -u sheela.service -f'
```
