# Personal Running Coach

An AI-powered personal running training application for two profiles, running locally on a Raspberry Pi via Docker. Provides structured training plans, Strava integration, detailed run history, and Garmin FIT file export — comparable to premium apps like Runna, with no subscription fees.

## Features

- AI-generated multi-week training plans via Google Gemini (free tier)
- Strava activity sync (OAuth + bulk export import)
- Structured workout detail with step-by-step instructions
- Garmin FIT file export for Forerunner 970 and compatible watches
- Post-run analysis with AI coaching feedback
- Weather-aware coaching notes via Open-Meteo (no API key required)
- Two independent profiles — no login required on your home network
- Runs entirely on Raspberry Pi 4+ (ARM64) via Docker Compose

## Prerequisites

- Raspberry Pi 4 or later (ARM64 architecture)
- Docker and Docker Compose installed on the Pi
- A Google account (for free Gemini API key)
- A Strava account (optional, for activity sync)

## Setup

### 1. Clone the repository

```bash
git clone <repo-url> personal-running-coach
cd personal-running-coach
```

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values (see sections below).

### 3. Get a Gemini API key (free)

1. Go to [ai.google.dev](https://ai.google.dev/)
2. Click "Get API key" and sign in with your Google account
3. Create a new API key
4. Paste it into `.env` as `GEMINI_API_KEY`

The free tier provides 15 requests per minute and 1,000 per day — more than enough for personal use.

### 4. Create a Strava API app (optional)

If you want automatic Strava activity sync:

1. Go to [strava.com/settings/api](https://www.strava.com/settings/api)
2. Create a new application
3. Set the **Authorization Callback Domain** to your Pi's local IP address (e.g. `192.168.1.x`)
4. Set the **Callback URL** to:
   ```
   http://<pi-ip>:3000/api/v1/profiles/1/strava/callback
   ```
   (repeat for profile 2 with `/profiles/2/strava/callback`)
5. Copy the **Client ID** and **Client Secret** into `.env`

You can also skip Strava OAuth entirely and use the bulk export import instead (see below).

### 5. Generate a secret key

```bash
openssl rand -hex 32
```

Paste the output into `.env` as `SECRET_KEY`.

### 6. Start the application

```bash
docker compose up -d
```

The first build will take a few minutes. Once running, access the app at:

```
http://<pi-ip>:3000
```

Replace `<pi-ip>` with your Raspberry Pi's local IP address (e.g. `192.168.1.42`).

## Uploading a Strava Bulk Export

If you have years of Strava history, you can import it all at once without needing OAuth:

1. In Strava, go to **Settings → My Account → Download or Delete Your Account**
2. Click **Request Your Archive** and wait for the email
3. Download the ZIP file
4. In the app, go to **Settings → Strava → Upload Export ZIP** for your profile
5. Select the downloaded ZIP — the app will import all running activities and calculate your initial fitness baseline

This is the recommended way to get started if you have existing Strava data.

## Exporting a Workout to Your Garmin Watch

1. Open any scheduled workout in the app
2. Click **Download for Garmin**
3. Connect your Forerunner 970 (or compatible watch) via USB
4. Copy the downloaded `.fit` file to the `GARMIN/NEWFILES` folder on the watch
5. Eject the watch — the workout will appear in your **Training** menu

## Backups

The app automatically backs up the database daily. Backups are stored in the `backups` Docker volume, which maps to:

```
./data/backups/
```

The 30 most recent daily backups are retained automatically. You can also trigger a manual backup from **Settings → Data → Backup Now**.

## Updating

```bash
docker compose pull
docker compose up -d --build
```

Your data is stored in named Docker volumes and will survive updates.

## Resource Usage

Designed to run comfortably within Raspberry Pi constraints:
- Idle RAM: ~200–400 MB
- Maximum RAM: < 1 GB
- CPU: minimal during normal operation; brief spikes during AI plan generation
