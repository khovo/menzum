# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Al-Madih** (project name `menzum`) is a Telegram audio/PDF platform for Amharic Islamic content (menzuma/nasheed). It has three parts that share one MongoDB database (`MenzumaDB`):

1. **Python Telegram bot** — webhook-driven, handles all in-chat interaction (search, catalog, favorites, playlists, admin panel, broadcasts).
2. **Node.js webapp API** (`api/webapp/*.js`) — serverless endpoints backing the Telegram Mini App and the admin dashboard.
3. **Next.js frontend** (`webapp/`) — the Telegram Mini App SPA + a secret admin analytics page.

User-facing strings are largely in Amharic; keep new user-facing copy consistent with the existing tone and language.

## Deployment Topology (important — two separate Vercel projects)

This repo is deployed as **two distinct Vercel projects**:

- **Bot project** (repo root, `vercel.json`) → `https://menzum.vercel.app`
  - Builds `api/index.py` with `@vercel/python` and `api/webapp/*.js` with `@vercel/node`.
  - Routing: `/api/webapp/(.*)` → the matching Node function; everything else `/(.*)` → the Python Flask app (the Telegram webhook).
- **Frontend project** (`webapp/`, `webapp/vercel.json` + `webapp/next.config.js`) → `https://almadih.vercel.app`
  - The Next.js app. It is configured at the deployment root (no `basePath`) and calls the bot project's API via `NEXT_PUBLIC_API_BASE` (set to `https://menzum.vercel.app` in the frontend's Vercel project settings).

So the Mini App (almadih.vercel.app) makes cross-origin requests to the API (menzum.vercel.app) — this is why every `api/webapp` handler sets permissive CORS headers.

## Commands

There is **no build/lint/test setup for the Python bot or the Node API** — they are deployed directly by Vercel. There are no automated tests anywhere in the repo.

Frontend (`webapp/`):
```bash
cd webapp
npm install
npm run dev      # next dev on port 3001
npm run build    # next build
npm run lint     # next lint
```

Python bot, local run (rarely needed — production is webhook-only):
```bash
pip install -r requirements.txt
python api/index.py   # Flask dev server on port 5000
```

### Required environment variables
- `BOT_TOKEN` — Telegram bot token (used by both Python and Node sides).
- `MONGO_URL` — MongoDB Atlas connection string.
- `ADMIN_ID` — Telegram user id of the admin (Python bot: gates `/admin`, broadcasts, channel management, content upload).
- `ADMIN_TOKEN` — password for the analytics dashboard (`api/webapp/admin-stats.js`). Server-only — must **not** have a `NEXT_PUBLIC_` prefix.
- `NEXT_PUBLIC_API_BASE` — set in the frontend project to point at the bot project URL.
- `BOT_USERNAME` (optional, defaults to `Almadihbot`).

## Backend Architecture (Python bot)

The Python side is deliberately layered, and the layering is enforced by convention:

- **`api/index.py`** — Vercel entry point. Intentionally "dumb": receives the webhook POST, calls `run_async(process_telegram_update(data))`, returns `"ok"`. **Do not add business logic, DB calls, or Telegram API calls here.**
- **`handlers.py`** — all business logic. `process_telegram_update()` opens a fresh Motor client + aiohttp session per invocation and dispatches to `handle_callback`, `handle_message`, or `handle_inline_query` based on the update type.
- **`db.py`** — every MongoDB operation. All functions take `db` as the first arg and swallow exceptions (logging, returning safe defaults) so a DB hiccup never crashes a handler.
- **`utils.py`** — thin async Telegram API wrappers (one per Telegram method), in-memory caches, the sync→async bridge (`run_async`), and reusable inline-keyboard builders.
- **`config.py`** — single source of truth for env vars and constants (TTLs, `ITEMS_PER_PAGE`, `DB_NAME`).

### Serverless-driven design constraints
Because each webhook hits a cold-or-warm serverless function with a short timeout, the code is shaped around it:

- **`run_async`** creates a fresh event loop per request (intentional for Vercel safety).
- **In-memory caches in `utils.py`** (`MEMBERSHIP_CACHE`, channel list, inline-empty results) persist only across *warm* invocations. They have short TTLs (`config.py`) and explicit `invalidate_*` calls — e.g. after a channel is added/removed, both `invalidate_channels_cache()` and `invalidate_all_membership_cache()` are called.
- **Playlist delivery uses `sendMediaGroup`** (one API call for up to 10 tracks) rather than a loop of `sendAudio` + sleeps, to avoid hitting the function timeout.
- **Broadcast** (`_execute_broadcast`) sends with chunked throttling, a 429-retry, and a consecutive-error circuit breaker.
- **`check_membership` fails open**: network/API errors count as "is a member" so a misconfigured channel can never lock everyone out. It fires all `getChatMember` checks in parallel.

### Key bot flows / conventions
- **Force-join gating** is enforced *per action* (only on `play_`/`pdf_dl_` callbacks and on actual track delivery), not globally — admins bypass it. The channel list lives in the `settings` collection (`type: "force_channel"`), managed live via the admin panel (no redeploy).
- **Callback data is prefix-routed** in `handle_callback`: `play_`, `pl_add_`, `pl_start/done/cancel`, `pg_` (catalog pagination), `fav_`, `report_`, `broadcast_*`, `admin_ch_*`, `check_subscription`. Doc IDs in callback data are 24-char Mongo ObjectId hex strings.
- **Conversational state** is stored on the user doc (`state` field) via `set_user_state`: `idle`, `playlist_builder`, `admin_add_channel_wait`, `broadcast_wait`, `broadcast_markup_wait`, `broadcast_preview`.
- **Deep links**: playlists get a `pl_<6char>` id; sharing is via `https://t.me/<BOT_USERNAME>?start=pl_xxxxxx`. If a user hits the force-join gate with a pending start param, it's saved (`save_pending_start`) and resumed after they verify.
- **Content ingestion is admin-only via chat**: an admin sending an audio/voice message upserts into `files` (keyed by `display_name` regex); sending a document (`.pdf/.txt/.doc/.docx/.epub`) upserts into `pdfs`. There is no separate upload tool.
- **Broadcast Markup Language (BML)** — admins attach inline keyboards to broadcasts using a custom mini-syntax parsed by `_parse_bml` (`[Label](type:value)` tokens, `|` for side-by-side, and macros like `{trending:5}`, `{latest_tracks:3}`). See `_bml_syntax_guide()`.
- **HTML vs Markdown**: most `utils.py` senders use `parse_mode: Markdown`, but the welcome menu uses custom HTML helpers in `handlers.py` (`_send_html_message`, `_edit_html_message`) to support animated `<tg-emoji>`.

## Node Webapp API Architecture (`api/webapp/`)

- Files prefixed with `_` (`_auth.js`, `_db.js`) are **shared modules, not endpoints** — Vercel won't route to them.
- **`_db.js`** caches the `MongoClient` at module scope for connection pooling across warm invocations. Same DB (`MenzumaDB`) as the Python bot.
- **`_auth.js`** implements Telegram Mini App auth. The frontend sends `Authorization: tma <initData>`; `withAuth(handler)` validates the HMAC-SHA256 signature against `BOT_TOKEN`, rejects stale (>24h) data, and attaches `req.telegramUser`. **Wrap every user-facing endpoint in `withAuth`.** Exceptions: `auth.js` (receives `initData` in the body because it runs before the user object exists) and `thumb.js` (public, images only).
- **`admin-stats.js`** uses a *different* auth model: `Authorization: Bearer <ADMIN_TOKEN>` with constant-time comparison. Note the deliberate `.trim()` on `ADMIN_TOKEN` — Vercel appends trailing newlines to dashboard-set env vars, and `crypto.timingSafeEqual` throws (→ permanent 401) on length mismatch.
- **`play.js`** is the critical bridge: Mini Apps can't play audio, so tapping ▶ calls this endpoint, which looks up `file_id` server-side and uses `sendAudio` to deliver the track to the user's bot chat. `file_id` is **never** exposed to the client. It also writes listening stats (`users.total_plays`, capped `users.listen_history`).
- **`thumb.js`** is a zero-bandwidth image proxy: it resolves the Telegram CDN path and issues a **302 redirect** (never proxies bytes) so image egress is on Telegram's CDN, not Vercel. Returns 404 on any failure so the frontend falls back to a generated gradient.
- **Pagination is cursor-based** (`featured.js`, `search.js`, `pdfs.js`): filter `_id < cursor` using the `_id` index rather than `.skip()`, which would scan/discard at depth. Page size 20, capped at 50.

## Frontend Architecture (`webapp/`)

- Next.js Pages Router. `pages/index.js` is the entire Mini App as a single-page SPA (Home / Search / Library / PDF views switched via React state, not routing). Boot sequence: `useTelegram()` → `POST /api/webapp/auth` → `GET /api/webapp/featured`.
- **`hooks/useTelegram.js`** initializes the Telegram WebApp SDK and provides a dev-mode fallback (dummy user, `initData: 'dev_mode'`) so the UI renders in a normal browser.
- **`pages/admin.js`** is the "Baraka Analytics" dashboard at `/admin`, gated by `ADMIN_TOKEN` (entered as a password, sent as a Bearer token to `admin-stats.js`). Uses `recharts`. Its dark palette is intentionally separate from the bot's UI.
- All API calls go through `API_BASE = process.env.NEXT_PUBLIC_API_BASE || ''`.

## MongoDB Collections (`MenzumaDB`)

- **`users`** — `_id` is the Telegram user id (int). Holds `first_name`, `joined_at`, `last_active`, `favorites` (array of `file_id`), `state` + state metadata (`building_playlist`, `pl_ctrl_msg_id`, `broadcast_*`), `last_menu_msg_id`, `pending_start`, `total_plays`, `listen_history` (capped 50), `pdf_favorites`.
- **`files`** — audio tracks. `display_name`, `file_id`, optional `thumb_file_id`. Searched by case-insensitive regex on `display_name`.
- **`pdfs`** — documents. `title`, `file_id`, `download_count`, `approved_at`.
- **`playlists`** — `_id` is the `pl_<token>` short id. `creator_id`, `tracks` (resolved `{file_id, name}` pairs), `play_count`.
- **`settings`** — config docs; force-join channels are `{type: "force_channel", username, url}`.

## Working Conventions

- The change-log comment blocks at the top of `db.py` / `utils.py` ("CHANGES FROM v2") are how this codebase records evolution — update them when you add notably new functions.
- DB helpers never raise: they log and return a safe default. Preserve this so a single failed query can't crash a webhook handler.
- Keep `api/index.py` thin (see above).
- When adding a Node endpoint that touches user data, wrap it in `withAuth` and set CORS headers (or follow the `withAuth` pattern which sets them for you).
