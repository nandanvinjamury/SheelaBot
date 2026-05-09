# Warden

The codebase that runs Sheela — a personal Discord-based AI assistant. The bot lives on a private Discord server, talks to Gemini (with Anthropic and local Ollama as future fallbacks), and reads/writes a private Obsidian vault.

This repo (`SheelaBot`) is the bot software. The vault repo (`Sheela`) is the data. Separate lifecycles, separate audiences.

## Status: Step 1 — hello world

The bot connects to Discord and replies `pong` to `ping`. The LLM provider abstraction (`sheela/llm/`) is in place but every implementation is a stub that raises `NotImplementedError`. Gemini lands in Step 2.

## Local development

Requires Python 3.12+. Recommended: [uv](https://github.com/astral-sh/uv) (`pipx install uv` or `pip install uv`).

```bash
# Set up a venv and install with dev deps
uv venv
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env: fill in DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, GEMINI_API_KEY at minimum.

# Run the bot
uv run python -m sheela

# Run tests
uv run pytest
```

Plain pip works too if you'd rather: `python -m venv .venv && .venv/Scripts/activate && pip install -e ".[dev]"`.

## Environment variables

See [.env.example](.env.example) for the full list. Key ones:

| Var | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | yes | Free tier; the primary backend in Step 2+. |
| `DISCORD_BOT_TOKEN` | yes | From the Discord Developer Portal. |
| `DISCORD_GUILD_ID` | yes | The bot ignores messages from any other guild and all DMs. |
| `LLM_PROVIDER` | no | `gemini` (default), `anthropic`, `ollama_local`. |
| `ANTHROPIC_API_KEY` | no | Only needed if `LLM_PROVIDER=anthropic`. |
| `SHEELA_LOG_MODE` | no | `console` (local, pretty colors) or `file` (VM, JSON). |
| `SHEELA_LOG_LEVEL` | no | `DEBUG`, `INFO`, `WARNING`, `ERROR`. Default `INFO`. |

## Logging

Routed through `structlog`. discord.py's stdlib log records flow through the same pipeline.

- **Local (`SHEELA_LOG_MODE=console`):** colored key/value output to stderr.
- **VM (`SHEELA_LOG_MODE=file`):** JSON to `/home/sheela/logs/sheela.log` (rotated, 10 MB × 5) AND JSON to stderr (captured by journald).

```bash
# Tail VM logs
ssh -i ~/.ssh/sheela_vm_key ubuntu@$VM_IP 'sudo journalctl -u sheela.service -f'
# or read the file directly
ssh -i ~/.ssh/sheela_vm_key ubuntu@$VM_IP 'sudo -u sheela tail -f /home/sheela/logs/sheela.log'
```

## Deploying to the VM

The bot runs as a systemd service on an Oracle Cloud Always Free ARM VM (Ubuntu 24.04, Chicago region — provisioned in Phase 1).

Before the first deploy, set `VM_IP` (the script defaults `BOT_REPO_URL` to this repo's GitHub SSH URL):

```bash
VM_IP=1.2.3.4 ./deploy/deploy.sh
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
│   ├── llm/                 # provider abstraction
│   │   ├── base.py          # LLMProvider Protocol + dataclasses
│   │   ├── gemini.py        # primary (stub in Step 1)
│   │   ├── anthropic.py     # fallback (stub)
│   │   └── ollama_local.py  # future (stub)
│   ├── discord_bot/
│   │   └── bot.py           # discord.py client + ping handler
│   └── utils/
│       └── logging.py       # structlog config (console / file modes)
├── tests/                   # pytest
├── deploy/
│   ├── sheela.service       # systemd unit
│   └── deploy.sh            # SSH deploy
└── pyproject.toml
```

Files like `persona.py`, `memory/`, `rag/`, `tools/`, and routing/streaming logic are added in later steps — see [PHASE_2_ARCHITECTURE.md](../PHASE_2_ARCHITECTURE.md) (in the parent repo) for the full plan.
