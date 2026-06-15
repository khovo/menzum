# Al-Madih Backend — API Documentation

Backend base URL (production): **`https://menzum.vercel.app`**

This document describes **every HTTP endpoint** the Al-Madih backend exposes, so the Flutter
mobile app (Al-Madih app) can connect to this backend instead of building a new one.

> ✅ **Mobile support is now built in.** As of this revision the backend has:
> - **JWT auth that works outside Telegram** via a "Login with Telegram" handshake
>   (`auth-start` → user taps a deep link in Telegram → `auth-poll` returns a 90-day JWT).
> - A **real audio streaming endpoint** (`/api/webapp/audio`) with Range/seek support.
> - `audio_url` + `thumb_url` on every track so the app knows how to play and illustrate it.
> - The existing Telegram Mini App (`initData`) auth **still works unchanged** — both auth
>   methods are accepted in parallel on every endpoint, so the bot is unaffected.
>
> ⚙️ **One setup step before it works:** set a `JWT_SECRET` environment variable in the bot's
> Vercel project (any long random string). Without it the JWT endpoints return `503` (the
> Telegram bot keeps working regardless). See [Section 9](#9-backend-readiness--setup).

---

## Table of contents
1. [Architecture in one minute](#1-architecture-in-one-minute)
2. [Authentication](#2-authentication)
3. [The mobile login flow (step by step)](#3-the-mobile-login-flow-step-by-step)
4. [Quick reference — all endpoints](#4-quick-reference--all-endpoints)
5. [Auth endpoints](#5-auth-endpoints)
6. [Catalog / search / library](#6-catalog--search--library)
7. [Audio & PDF playback](#7-audio--pdf-playback)
8. [Images, admin, data models](#8-images-admin-data-models)
9. [Backend readiness & setup](#9-backend-readiness--setup)

---

## 1. Architecture in one minute

- **One MongoDB DB (`MenzumaDB`) shared by:** the **bot project** (`https://menzum.vercel.app`,
  the API host) and the **Mini App frontend** (`https://almadih.vercel.app`). The Flutter app
  talks only to `https://menzum.vercel.app`.
- **Audio & PDFs live on Telegram's servers.** The DB stores a Telegram `file_id` per item.
  The backend resolves `file_id` → bytes on demand and **streams them through the backend**;
  `file_id` and the bot token are never exposed to clients.
- All `/api/webapp/*` endpoints send **CORS** `Access-Control-Allow-Origin: *` and allow the
  `Authorization` and `Range` headers (irrelevant for native mobile, handy for web).

---

## 2. Authentication

Every user endpoint accepts **either** of these headers (dual auth — pick one):

| Scheme | Header | Who uses it |
|--------|--------|-------------|
| **Mobile JWT** | `Authorization: Bearer <jwt>` | The Flutter app (after Telegram login) |
| **Telegram Mini App** | `Authorization: tma <initData>` | The in-Telegram Mini App (unchanged) |

Both resolve to the same Telegram `user_id`, so the endpoints behave identically.

**JWT format:** HS256, signed with `JWT_SECRET`. Payload: `{ "uid": <telegram_user_id>, "iat": …, "exp": … }`.
Lifetime **90 days**. Refresh anytime via [`/api/webapp/auth-refresh`](#auth-refresh). Store the
token securely on device (e.g. flutter_secure_storage).

There is **no** password/email login. Identity always comes from Telegram (either the Mini App
signature or the login deep link below). The admin analytics endpoint uses a separate static
`Bearer <ADMIN_TOKEN>` and is **not** for the app.

---

## 3. The mobile login flow (step by step)

```
┌─ App ─────────────┐         ┌─ Backend ───────────┐        ┌─ Telegram ─────────┐
│ 1. POST auth-start│ ───────▶│ create nonce        │        │                    │
│    ◀── nonce +    │         │ (login_sessions)    │        │                    │
│        deep_link  │         └─────────────────────┘        │                    │
│ 2. open deep_link │ ───────────────────────────────────────▶ user taps "Start" │
│                   │         ┌─ Bot links nonce ───┐ ◀──────── /start login_<n>  │
│ 3. poll auth-poll │ ───────▶│ status: linked      │        │                    │
│    ◀── token+user │         │ → issue 90-day JWT  │        │                    │
│ 4. use Bearer JWT │         └─────────────────────┘        └────────────────────┘
└───────────────────┘
```

1. `POST /api/webapp/auth-start` → get `{ nonce, deep_link }`.
2. Open `deep_link` (`https://t.me/Almadihbot?start=login_<nonce>`) — it launches Telegram and
   the user taps **Start**. The bot replies "✅ Login successful! return to the app."
3. `POST /api/webapp/auth-poll` with the `nonce` every ~2–3s. While waiting you get
   `{ status: "pending" }`; once the user has tapped Start you get `{ token, user }`.
4. Send `Authorization: Bearer <token>` on all subsequent requests. Nonce expires in 10 min.

---

## 4. Quick reference — all endpoints

Base: `https://menzum.vercel.app`

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/webapp/auth-start` | none | Begin login → returns nonce + Telegram deep link |
| POST | `/api/webapp/auth-poll` | none | Exchange nonce → JWT once the user has logged in |
| POST | `/api/webapp/auth-refresh` | JWT or initData | Get a fresh 90-day JWT |
| POST | `/api/webapp/auth` | initData (body) | Mini App startup validation (unchanged) |
| GET | `/api/webapp/featured` | JWT or initData | Paged catalog (latest tracks) — incl. `audio_url` |
| GET | `/api/webapp/search` | JWT or initData | Search tracks + PDFs — incl. `audio_url` |
| GET | `/api/webapp/library` | JWT or initData | Favorites + listening stats — incl. `audio_url` |
| GET | `/api/webapp/audio` | JWT or initData | **Stream a track's audio bytes** (Range/seek) |
| POST | `/api/webapp/play` | JWT or initData | Toggle favorite, or push track to Telegram chat |
| GET | `/api/webapp/pdfs` | JWT or initData | Paged PDF list |
| POST | `/api/webapp/pdfs` | JWT or initData | Favorite / deliver a PDF |
| GET | `/api/webapp/pdf-view` | JWT or initData | Stream PDF bytes / get stream URL |
| GET | `/api/webapp/thumb` | none (public) | Track cover image (proxied bytes) |
| GET | `/api/webapp/admin-stats` | `Bearer ADMIN_TOKEN` | Analytics (admin only — not for app) |

Conventions: JSON `{ "ok": true, ... }` on success, `{ "ok": false, "error": "…" }` on failure.
Pagination is cursor-based (`?cursor=<next_cursor>`, page size 20, max 50 via `?limit=`). All IDs
are 24-char Mongo ObjectId hex strings.

---

## 5. Auth endpoints

### POST `/api/webapp/auth-start` — begin login (no auth)
**Request:** `POST https://menzum.vercel.app/api/webapp/auth-start` (no body needed)

**Response 200**
```json
{
  "ok": true,
  "nonce": "ab12cd34ef56a7b8",
  "deep_link": "https://t.me/Almadihbot?start=login_ab12cd34ef56a7b8",
  "expires_in": 600
}
```

### POST `/api/webapp/auth-poll` — exchange nonce for a token (no auth)
**Request**
```json
{ "nonce": "ab12cd34ef56a7b8" }
```
**Response 200 — still waiting:** `{ "ok": true, "status": "pending" }`

**Response 200 — logged in:**
```json
{
  "ok": true,
  "status": "linked",
  "token": "<JWT, valid 90 days>",
  "user": { "id": 123456789, "first_name": "Ahmed", "username": "ahmed", "photo_url": null }
}
```
**Errors:** `404` unknown/used nonce · `410` expired (start over) · `503` `JWT_SECRET` not set.

<a name="auth-refresh"></a>
### POST `/api/webapp/auth-refresh` — refresh the token
**Request:** `POST …/auth-refresh` with `Authorization: Bearer <current jwt>` (or `tma <initData>`).
**Response 200:** `{ "ok": true, "token": "<new 90-day JWT>" }`

### POST `/api/webapp/auth` — Mini App startup (unchanged; for the web Mini App)
Takes `initData` in the **body** and returns the user profile. The mobile app does **not** need
this — use `auth-poll`'s `user` object. (Kept for the existing Mini App.)
```json
// request
{ "initData": "query_id=...&user=%7B...%7D&auth_date=...&hash=..." }
// response
{ "ok": true, "user": { "id": 123, "first_name": "Ahmed", "favorites_count": 12, "baraka_points": 0 } }
```

---

## 6. Catalog / search / library

All three accept `Authorization: Bearer <jwt>` (or `tma <initData>`) and now return
**`audio_url`** (how to play) and **`thumb_url`** (cover image, or `null`) on every track.

### GET `/api/webapp/featured?cursor=<optional>&limit=20`
```json
{
  "ok": true,
  "tracks": [
    {
      "id": "64a1b2c3d4e5f6a7b8c9d0e1",
      "name": "Husni Sultan - Ya Nabi",
      "is_favorite": false,
      "has_thumb": true,
      "audio_url": "https://menzum.vercel.app/api/webapp/audio?id=64a1b2c3d4e5f6a7b8c9d0e1&action=stream",
      "thumb_url": "https://menzum.vercel.app/api/webapp/thumb?id=64a1b2c3d4e5f6a7b8c9d0e1"
    }
  ],
  "has_more": true,
  "next_cursor": "64a1b2c3d4e5f6a7b8c9d0e1"
}
```

### GET `/api/webapp/search?q=husni&type=all&cursor=&limit=20`
`type` = `all` (default) | `audio` | `pdf`. Audio items include `audio_url`/`thumb_url` and
`type:"audio"`; PDF items have `type:"pdf"` (open them via `/pdf-view`). Same `tracks` array shape
as above plus a `type` field per item.

### GET `/api/webapp/library`
```json
{
  "ok": true,
  "stats": { "total_plays": 47, "total_favorites": 12,
             "most_played": [ { "track_id": "64a1…", "name": "…", "play_count": 6 } ] },
  "favorites": [
    { "id": "64a1…", "name": "Husni Sultan - Ya Nabi", "is_favorite": true, "has_thumb": true,
      "audio_url": "https://menzum.vercel.app/api/webapp/audio?id=64a1…&action=stream",
      "thumb_url": "https://menzum.vercel.app/api/webapp/thumb?id=64a1…" }
  ],
  "pdf_favorites": [ { "id": "64b2…", "name": "Diwan al-Burdah", "is_favorite": true, "type": "pdf" } ]
}
```

---

## 7. Audio & PDF playback

### GET `/api/webapp/audio?id=<track_id>&action=stream` — **stream audio** ⭐
Auth: `Bearer <jwt>` (or `tma <initData>`). This is what `audio_url` points to. Returns the raw
audio bytes; the bot token is never exposed.

- `Content-Type`: `audio/mpeg` (or `audio/ogg` / `audio/mp4` / `audio/wav` by file type).
- `Accept-Ranges: bytes`; forwards your `Range` header → `206 Partial Content` for seeking.
- `GET` streams; `HEAD` returns headers only (duration/size probing).
- Errors: `400` bad id · `404` track/file not found · `401` bad/missing auth.

**Flutter (just_audio) example — the player must send the auth header:**
```dart
final player = AudioPlayer();
await player.setAudioSource(AudioSource.uri(
  Uri.parse(track.audioUrl),
  headers: { 'Authorization': 'Bearer $jwt' },
));
await player.play();
```
> The audio endpoint is auth-protected, so a bare `<audio src>` without headers won't work —
> use a player that supports request headers (just_audio does).

### POST `/api/webapp/play` — favorite, or push to Telegram chat (unchanged)
Used by the bot/Mini App. For the mobile app, use it only for `action:"favorite"`; prefer the
`audio` endpoint above for playback (`action:"play"` sends the file into the user's Telegram chat,
not into the app).
```json
// request
{ "track_id": "64a1…", "action": "favorite" }
// response
{ "ok": true, "action": "favorite", "is_favorite": true }
```

### GET `/api/webapp/pdfs` / POST `/api/webapp/pdfs`
- `GET …/pdfs?cursor=&limit=20` → `{ ok, pdfs:[{id,title,file_name,is_favorite}], has_more, next_cursor }`.
- `POST …/pdfs` body `{ "action": "favorite"|"deliver", "pdf_id": "64b2…" }` → toggle favorite, or
  send the PDF into the user's Telegram chat.

### GET `/api/webapp/pdf-view?id=<id>[&action=stream]`
- `action=stream` → streams the PDF bytes (`application/pdf`, Range supported) — use this in-app.
- without `action` → `{ ok:true, url:"https://menzum.vercel.app/api/webapp/pdf-view?id=…&action=stream" }`
  (now points at our own proxied stream URL — the bot token is **no longer** exposed).

---

## 8. Images, admin, data models

### GET `/api/webapp/thumb?id=<track_id>` — cover image (public)
Streams the cover **bytes** through the backend (no auth, no token leak). Use the `thumb_url`
field directly as an image source (`Image.network(track.thumbUrl)`). Returns `404` when a track
has no cover → show a placeholder.

### GET `/api/webapp/admin-stats` — analytics (admin only)
`Authorization: Bearer <ADMIN_TOKEN>`. **Do not ship `ADMIN_TOKEN` in the app.** Returns
`{ ok, stats: { totalUsers, totalFiles, totalPlays, activeUsers, userGrowth[], trendingTracks[] } }`.

### Data models
- **Track:** `id`, `name`, `is_favorite`, `has_thumb`, `audio_url`, `thumb_url`. (`file_id` is server-side only.)
- **PDF:** `id`, `title`, `file_name`, `is_favorite`.
- **User:** `_id` = Telegram user id (int); `first_name`, `joined_at`, `last_active`, `favorites`,
  `pdf_favorites`, `total_plays`, `listen_history` (capped 50), `baraka_points`.
- **login_sessions** (internal): `_id` = nonce, `status` (`pending`/`linked`), `user_id`,
  `first_name`, `username`, timestamps. Used only by the login handshake.
- **Playlists:** exist in the DB/bot but still have **no HTTP API** (not exposed to the app yet).

---

## 9. Backend readiness & setup

**Status: ready for the mobile app.** Both former blockers are resolved (JWT auth + audio
streaming), CORS is open, and the bot-token leak is fixed.

### Required one-time setup
1. **Set `JWT_SECRET`** in the bot's Vercel project (Settings → Environment Variables) to a long
   random string, then redeploy. Until this is set, `auth-poll`/`auth-refresh` return `503` and
   `Bearer` tokens won't verify (the Telegram bot and Mini App keep working).
2. Make sure `BOT_USERNAME` matches the real bot (defaults to `Almadihbot`) so the login
   `deep_link` is correct.

### What works now
| Capability | Status |
|-----------|--------|
| Login outside Telegram (JWT) | ✅ `auth-start` → `auth-poll` → `Bearer` |
| Token refresh (90-day) | ✅ `auth-refresh` |
| Browse / search / favorites | ✅ with `audio_url` + `thumb_url` |
| Audio playback in-app | ✅ `GET /audio?...&action=stream` (Range/seek) |
| PDF viewing in-app | ✅ `GET /pdf-view?...&action=stream` |
| Cover images | ✅ `thumb_url` (public, proxied) |
| CORS | ✅ `*` + Authorization/Range allowed |
| Bot token leakage | ✅ fixed (thumb & pdf-view proxy bytes) |
| Existing Telegram bot/Mini App | ✅ unchanged (initData still accepted) |

### Still not exposed (optional future work)
- **Playlists** over HTTP (bot-only today).
- **Categories/genres** (no such field exists; tracks only have a name).
- **Rate limiting** on user endpoints (advisable before a public launch).

---

*Generated from the source in this repository (`api/webapp/*.js`, `api/index.py`, `handlers/`).
Regenerate when the backend changes so the mobile team stays in sync.*
