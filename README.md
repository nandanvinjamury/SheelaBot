# Warden

The codebase that runs **Sheela** — a personal Discord-based AI assistant. The bot lives on a private Discord server, talks to Gemini, and reads and writes a private Obsidian vault (a second repo).

This repo (`SheelaBot`) is the bot software. The vault repo (`Sheela`) is the data. Separate lifecycles, separate audiences.

## Status: Phase 2 complete (v0.1.0)

A stable, observable, conversational Sheela. What works today:

- Discord client connecting to one configured guild; ignores DMs.
- Gemini 2.5 Flash for conversation, Flash-Lite for summaries, Pro reserved for high-context fallback.
- Streaming responses (in-place message edits with a cursor visual).
- Per-channel context loaded from `routing.yaml` — descriptions, tone hints, preloaded vault files.
- Persona/rules/personal-config assembled into the system prompt; cached and reloaded on mtime change.
- LLM-callable tools: `vault_read`, `vault_list`, `vault_search` (hybrid vector + keyword RAG), `vault_write`, `vault_cancel_draft`, `vault_list_drafts`.
- Lazy git pull on first vault read in any 60-second window.
- Vault writes go through a 30-second draft-then-commit batcher; safety gates (allowlist / confirm-list / deny-list) enforce RULES.md; one git commit + push per batch, with `pull --rebase` retry on conflict.
- Sliding-window memory per channel: last 10 exchanges verbatim + a rolling Flash-Lite summary of older turns.
- JSONL usage logging for every Gemini call. `tools/analyze_usage.py` aggregates it.
- Health endpoint on `localhost:8765`.
- 180 unit tests covering store layers, safety, drafts, routing, RAG, memory, streaming, and the LLM Protocol.

Phase 3 will add proactive scheduled jobs (morning brief, evening check-in, weekly review), Google Calendar integration, voice/Tasker triggers, and domain-specific helpers (recipe rotation, exercise selection).

## Architecture in one diagram

```
                          ┌──────────────────┐
                          │  Discord guild   │
                          └────────┬─────────┘
                                   │ on_message
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                         SheelaClient (bot.py)                    │
│                                                                  │
│  Persona ──┐  ChannelRouter ──┐  ConversationManager ──┐         │
│            ▼                  ▼                        ▼         │
│        system_prompt + channel_context + summary + history       │
│            │                                                     │
│            ▼                                                     │
│       GeminiProvider.respond(tools=[vault_*])  ── auto-FC loop ──┤
│            │                                            │        │
│            ▼                                            │        │
│       stream_to_discord (edits placeholder)             │        │
│                                                         │        │
│            ┌────────────────────────────────────────────┘        │
│            ▼                                                     │
│       VaultTools                                                 │
│         ├─ vault_read   ──► VaultReader (lazy git pull)          │
│         ├─ vault_list   ──► VaultIndexer (_index.json)           │
│         ├─ vault_search ──► HybridSearcher (sqlite-vec + FTS5)   │
│         └─ vault_write  ──► VaultWriter ──► DraftScheduler ──► git
│                                            (safety gates)        │
└──────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                          SQLite (sheela.db):
                          - conversations, summaries (memory/)
                          - rag_chunks, rag_embeddings, rag_fts (rag/)
                          - rag_metadata
```

## Local development

Requires Python 3.12+. Recommended: [uv](https://github.com/astral-sh/uv).

```bash
git clone git@github.com:nandanvinjamury/SheelaBot.git Warden
cd Warden
uv venv
uv pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env: set DISCORD_BOT_TOKEN, DISCORD_GUILD_ID, GEMINI_API_KEY, and
# point VAULT_REPO_PATH / SHEELA_ROUTING_PATH at local paths.

uv run python -m sheela          # run the bot
uv run pytest                    # run all tests
uv run pytest --cov=sheela --cov=tools  # with coverage report
```

For local runs, the default paths (`/home/sheela/...`) won't exist. Override in `.env`:

```
VAULT_REPO_PATH=C:/dev/Sheela/Vault
SHEELA_ROUTING_PATH=C:/dev/Sheela/Warden/deploy/routing.yaml.example
SHEELA_DATA_DIR=C:/dev/Sheela/_local/data
SHEELA_LOG_DIR=C:/dev/Sheela/_local/logs
SHEELA_DB_PATH=C:/dev/Sheela/_local/data/sheela.db
SHEELA_VAULT_INDEX_PATH=C:/dev/Sheela/_local/data/vault_index.json
SHEELA_DRAFTS_DIR=C:/dev/Sheela/_local/data/drafts
```

## Environment variables

See [.env.example](.env.example) for the full annotated list. The essentials:

| Var | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | yes | Free tier is fine. |
| `DISCORD_BOT_TOKEN` | yes | Discord Developer Portal. |
| `DISCORD_GUILD_ID` | yes | Bot only responds in this guild; DMs always ignored. |
| `LLM_PROVIDER` | no | `gemini` (default), `anthropic`, `ollama_local`. |
| `ANTHROPIC_API_KEY` | no | Only when `LLM_PROVIDER=anthropic`. |
| `VAULT_REPO_PATH` | no | Default `/home/sheela/vault`. |
| `SHEELA_ROUTING_PATH` | no | Default `/home/sheela/.config/sheela-routing.yaml`. |
| `SHEELA_DB_PATH` | no | Default `/home/sheela/data/sheela.db`. |
| `SHEELA_DRAFTS_DIR` | no | Default `/home/sheela/data/drafts`. |
| `SHEELA_TZ` | no | Default `America/New_York`. Used for `{date}` template + daily-note safety check. |
| `RAG_INDEX_ON_STARTUP` | no | `0` (default) or `1`. Set to `1` once to do the initial embedding pass; subsequent restarts auto-incremental. |
| `SHEELA_HEALTH_PORT` | no | Default `8765`. Loopback-only. |
| `SHEELA_LOG_MODE` | no | `console` (local) or `file` (VM/systemd). |

## Channel routing config

[deploy/routing.yaml.example](deploy/routing.yaml.example) maps each Discord channel to:

- `description` — short context block prepended to the system prompt
- `vault_paths_to_load` — files read into context proactively (parallel, missing files skipped)
- `vault_paths_writable_without_confirm` — channel-specific allowlist for vault writes (additive on top of the global allowlist)
- `tone_hint` — short voice/register guidance

`{date}` expands to today's date in `SHEELA_TZ`. On the VM, the live config is at `/home/sheela/.config/sheela-routing.yaml`. Edit it and `sudo systemctl restart sheela.service` to pick up changes — no redeploy needed.

## Deploying to the VM

The bot runs as a systemd service on Ubuntu 24.04 ARM (Oracle Cloud Always Free). Phase 1 provisioned the VM, created the `sheela` user, and cloned the vault to `/home/sheela/vault`.

First-time deploy needs `SSH_KEY` (default `~/.ssh/sheela_vm_key`) and `VM_IP` set:

```bash
VM_IP=1.2.3.4 ./deploy/deploy.sh
```

The script:

1. SSHes to the VM as `ubuntu`
2. Updates `/home/sheela/bot/` (`git clone` first time, `git fetch + reset --hard origin/main` thereafter)
3. Installs Python deps via `pip install -e .` in the venv at `/home/sheela/bot/venv/`
4. Seeds `/home/sheela/.config/sheela-routing.yaml` from `deploy/routing.yaml.example` if it doesn't already exist
5. Installs/reloads the systemd unit; restarts the service
6. Tails recent journal logs

## Bootstrapping RAG (one-time)

After the first deploy, `vault_search` returns "not initialized" until you do the initial embedding pass:

```bash
# On the VM
sudo -u sheela nano /home/sheela/.config/sheela.env  # set RAG_INDEX_ON_STARTUP=1
sudo systemctl restart sheela.service
# watch the log — should see "rag build done mode=full indexed=N"
sudo journalctl -u sheela.service -f
```

Once `last_indexed_sha` is stored in `sheela.db`, every subsequent restart auto-runs an incremental update. You can flip `RAG_INDEX_ON_STARTUP` back to `0` (or leave it on — no effect once the SHA exists).

## Bootstrapping logrotate (one-time)

```bash
# On the VM
sudo install -m 644 /home/sheela/bot/deploy/sheela-logrotate.conf /etc/logrotate.d/sheela
sudo logrotate -d /etc/logrotate.d/sheela           # dry-run sanity check
```

Ubuntu's `/etc/cron.daily/logrotate` picks it up automatically; weekly rotation with 4 generations kept, `copytruncate` so the bot's open file descriptors keep working without a restart.

## Logs and observability

```
/home/sheela/logs/sheela.log          structured JSON, one line per event
/home/sheela/logs/api-usage.jsonl     one line per Gemini call (input/output tokens, latency, channel, model)
```

Also via systemd: `sudo journalctl -u sheela.service -f`.

**Aggregate usage** with the bundled CLI:

```bash
# On the VM
sudo -u sheela /home/sheela/bot/venv/bin/sheela-usage --days 7
# Or directly:
sudo -u sheela /home/sheela/bot/venv/bin/python /home/sheela/bot/tools/analyze_usage.py \
    --days 7 --group-by channel hour model
```

**Health endpoint** on localhost (loopback-only):

```bash
curl -s http://127.0.0.1:8765/health | jq
```

Returns `status`, `uptime_seconds`, `last_message_at`, `db_size_bytes`, `vault_last_pull_check`, `memory_channels_active`, `drafts_pending`.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Bot connects but never replies | Check `DISCORD_GUILD_ID`; bot silently ignores other guilds and all DMs. |
| `vault_search` returns "not initialized" | Run the RAG bootstrap (above). |
| Channel preloads aren't loading | Check `/home/sheela/.config/sheela-routing.yaml` paths match the actual vault layout (the live vault uses `NN ` Obsidian sort prefixes like `01 Daily/`). |
| `git push` fails on a vault write | SSH key on the VM isn't a deploy key on the vault GitHub repo. Test: `sudo -u sheela ssh -T git@github.com`. |
| Drafts pile up in `/home/sheela/data/drafts/` | Inspect `journalctl -u sheela.service` for `commit/push failed`. Most often a push conflict; the bot retries with `pull --rebase` automatically. |
| `sqlite-vec` extension fails to load on the VM | Confirm ARM wheel: `/home/sheela/bot/venv/bin/pip show sqlite-vec`. If missing, `pip install --no-binary :all: sqlite-vec` builds from source. |
| Bot remembers things it shouldn't | Verify per-channel isolation: `sqlite3 /home/sheela/data/sheela.db 'SELECT channel_id, COUNT(*) FROM conversations WHERE archived=0 GROUP BY channel_id;'` |
| Bot forgets things it shouldn't | Check whether compaction happened too eagerly: `sqlite3 sheela.db 'SELECT channel_id, substr(summary,1,200) FROM summaries;'`. |
| Health endpoint not responding | Check `journalctl` for `health server failed to bind` (port in use). Override `SHEELA_HEALTH_PORT`. |
| `bot.py` config drift after a `.env` change | Restart the service: `sudo systemctl restart sheela.service`. Pydantic-settings reads at process start. |

## Diagnostic SQL one-liners

```bash
# Conversation row count per channel
sqlite3 /home/sheela/data/sheela.db \
    "SELECT channel_id, archived, COUNT(*) FROM conversations GROUP BY channel_id, archived;"

# Latest summary per channel
sqlite3 /home/sheela/data/sheela.db \
    "SELECT channel_id, turn_count, substr(summary,1,200) FROM summaries;"

# RAG chunk count
sqlite3 /home/sheela/data/sheela.db \
    "SELECT COUNT(*), substr(MIN(file_path),1,40), substr(MAX(file_path),1,40) FROM rag_chunks;"

# RAG last indexed SHA
sqlite3 /home/sheela/data/sheela.db \
    "SELECT * FROM rag_metadata;"
```

## Layout

```
Warden/
├── sheela/                  # the package — entry: python -m sheela
│   ├── __main__.py          # wires every component, runs the bot
│   ├── config.py            # pydantic-settings Settings
│   ├── persona.py           # PERSONA / RULES / MY_SHEELA loader
│   ├── health.py            # localhost:8765 JSON endpoint
│   ├── llm/
│   │   ├── base.py          # LLMProvider Protocol + Message/ResponseChunk
│   │   ├── gemini.py        # google-genai SDK, auto FC, backoff, fallback
│   │   ├── router.py        # Flash / Flash-Lite / Pro routing
│   │   ├── usage.py         # api-usage.jsonl writer
│   │   └── {anthropic,ollama_local}.py  # stubs
│   ├── memory/
│   │   ├── store.py         # conversations + summaries tables
│   │   ├── conversations.py # sliding window + compaction
│   │   └── summarizer.py    # Sheela-POV summarization prompt
│   ├── rag/
│   │   ├── store.py         # sqlite-vec + FTS5 storage
│   │   ├── embeddings.py    # text-embedding-004
│   │   ├── hybrid.py        # reciprocal rank fusion
│   │   ├── chunking.py      # split by ## sections
│   │   └── indexer.py       # walk vault, embed, store; incremental via git diff
│   ├── tools/
│   │   ├── vault_read.py    # lazy git pull + async reads
│   │   ├── vault_write.py   # safety + draft + commit + push
│   │   ├── vault_tools.py   # LLM-facing functions
│   │   ├── safety.py        # allowlist / confirm / deny globs
│   │   ├── drafts.py        # 30s debounce, restart-safe
│   │   └── git.py           # async subprocess wrappers
│   ├── vault/
│   │   ├── contract.py      # frontmatter parse, type inference
│   │   └── index.py         # vault_index.json metadata
│   ├── discord_bot/
│   │   ├── bot.py           # on_message, error nets, health server, shutdown
│   │   ├── routing.py       # channel → context loader
│   │   └── streaming.py     # in-place Discord message edits
│   └── utils/
│       └── logging.py       # structlog config (console + JSON-file)
├── tools/
│   └── analyze_usage.py     # sheela-usage CLI
├── tests/                   # 180 unit tests
└── deploy/
    ├── sheela.service       # systemd unit
    ├── deploy.sh            # SSH-based deploy
    ├── routing.yaml.example # channel context template
    └── sheela-logrotate.conf
```

## Phase 3 preview

Phase 2 makes Sheela usable as a reactive assistant — she answers when spoken to. Phase 3 makes her proactive:

- **Scheduled jobs** — 7am morning brief, 9pm evening check-in, Saturday weekly review. Each delivered to `#daily` with optional TTS.
- **Google Calendar integration** — read-only at first (so Sheela can plan around real commitments); event creation requires user confirmation.
- **Voice/Tasker** — hotword-triggered Q&A in the car or on phone; replies played via TTS.
- **Domain helpers** — recipe rotation respecting the 14-day no-repeat rule, exercise selection from `/Exercise/`, contact-cadence nudges from `/People/`.

Phase 4 (later, speculative) — Personal CRM dashboards, tighter financial summarization, AppBlock-aware tooling.
