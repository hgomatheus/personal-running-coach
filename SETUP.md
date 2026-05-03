# Raspberry Pi Deployment Guide

This guide walks you through deploying the Personal Running Coach app on a Raspberry Pi 4 using Docker Compose.

---

## Prerequisites

- **Raspberry Pi 4** with 4 GB RAM or more (recommended)
- **Raspberry Pi OS (64-bit)** — Bookworm or later
- Internet connection during setup
- A keyboard, monitor, or SSH access to the Pi

---

## 1. Install Docker

Use the official Docker convenience script:

```bash
curl -fsSL https://get.docker.com | sh
```

Add your user to the `docker` group so you can run Docker commands without `sudo`:

```bash
sudo usermod -aG docker $USER
```

Log out and back in (or run `newgrp docker`) for the group change to take effect.

Enable Docker to start automatically on boot:

```bash
sudo systemctl enable docker
sudo systemctl start docker
```

Verify the installation:

```bash
docker --version
docker compose version
```

---

## 2. Clone the Repository

```bash
git clone https://github.com/your-username/personal-running-coach.git
cd personal-running-coach
```

---

## 3. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Open `.env` in a text editor:

```bash
nano .env
```

Fill in each variable as described below:

### `GEMINI_API_KEY`

The API key for Google Gemini, used by the AI coach to generate and adapt training plans.

1. Go to [https://aistudio.google.com](https://aistudio.google.com)
2. Sign in with your Google account
3. Click **Get API key** → **Create API key**
4. Copy the key and paste it as the value

```
GEMINI_API_KEY=AIza...your_key_here
```

The free tier (15 requests/min, 1,000 requests/day) is sufficient for normal use.

### `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`

Credentials for your personal Strava API application, used to sync your runs.

1. Go to [https://www.strava.com/settings/api](https://www.strava.com/settings/api)
2. Fill in the application details:
   - **Application Name**: Personal Running Coach (or any name you like)
   - **Category**: Other
   - **Club**: leave blank
   - **Website**: `http://localhost`
   - **Authorization Callback Domain**: your Pi's IP address (e.g. `192.168.1.50`)
3. Click **Create** and copy the **Client ID** and **Client Secret**

```
STRAVA_CLIENT_ID=12345
STRAVA_CLIENT_SECRET=abc123...your_secret_here
```

### `SECRET_KEY`

A random secret used to encrypt stored Strava tokens. Generate one with:

```bash
openssl rand -hex 32
```

Paste the output as the value:

```
SECRET_KEY=a3f8c2...your_generated_key_here
```

### `APP_BASE_URL`

The URL at which the app is accessible on your local network. Replace `<pi-ip-address>` with your Pi's actual IP (see [Step 6](#6-access-the-app) for how to find it):

```
APP_BASE_URL=http://192.168.1.50:3000
```

This is used to construct the Strava OAuth callback URL.

### `LOG_LEVEL`

Controls the verbosity of application logs. The default is fine for normal use:

```
LOG_LEVEL=INFO
```

Other options: `DEBUG`, `WARNING`, `ERROR`.

---

## 4. Start the Application

Build and start all services in the background:

```bash
docker compose up -d
```

The first build will take a few minutes as Docker downloads base images and installs dependencies. Subsequent starts are much faster.

Check that all containers are running:

```bash
docker compose ps
```

You should see `backend` and `frontend` both with status `Up`.

To follow the live logs from all services:

```bash
docker compose logs -f
```

Press `Ctrl+C` to stop following logs (the app keeps running).

---

## 5. Wait for the Health Check

The frontend waits for the backend to pass its health check before starting. This takes up to 30 seconds on first boot. Once both containers show `Up (healthy)` in `docker compose ps`, the app is ready.

---

## 6. Access the App

Find your Pi's IP address:

```bash
hostname -I
```

The first address shown is your Pi's local network IP (e.g. `192.168.1.50`).

Open a browser on any device connected to the same WiFi network and go to:

```
http://<pi-ip>:3000
```

For example: `http://192.168.1.50:3000`

> **Tip:** You can bookmark this URL on your phone or tablet for quick access.

---

## 7. Upload Your Strava Bulk Export

If you want to import your full Strava run history without waiting for the live sync to catch up, you can upload a Strava data export ZIP during onboarding or from the Settings screen.

### Step 1 — Request your Strava archive

1. Log in to Strava on the web
2. Go to **Settings** → **My Account**
3. Scroll to **Download or Delete Your Account**
4. Click **Request Your Archive**
5. Strava will send you an email when the archive is ready (usually within a few minutes to a few hours)

### Step 2 — Download the ZIP

Click the download link in the email from Strava. Save the ZIP file to your device.

### Step 3 — Upload to the app

1. Open the app and go to **Settings** → **Strava Integration**
2. Under **Bulk Import**, click **Choose File** and select the ZIP you downloaded
3. Click **Upload**
4. The app will parse the archive, import all your running activities, and calculate your initial VDOT and pace zones

The import summary will show how many activities were imported, how many were skipped as duplicates, and your calculated VDOT score.

---

## 8. Updating the App

To pull the latest code and rebuild:

```bash
git pull && docker compose build && docker compose up -d
```

Your data is stored in named Docker volumes and is not affected by rebuilds.

---

## 9. Troubleshooting

### Port 3000 is already in use

Another process is using port 3000. Find and stop it:

```bash
sudo lsof -i :3000
sudo kill <PID>
```

Then retry `docker compose up -d`.

### Permission denied when running Docker commands

Your user is not in the `docker` group yet. Run:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Then retry the command.

### Containers are not starting or keep restarting

Check the logs for error messages:

```bash
docker compose logs backend
docker compose logs frontend
```

Common causes:
- Missing or incorrect values in `.env` — double-check all variables are set
- `APP_BASE_URL` does not match your Pi's actual IP address
- The Pi ran out of disk space — check with `df -h`

### App is accessible on the Pi but not from other devices

Make sure your Pi's firewall (if enabled) allows inbound connections on port 3000:

```bash
sudo ufw allow 3000/tcp
```

---

## 10. Stopping the App

To stop all running containers:

```bash
docker compose down
```

This stops and removes the containers but preserves all data in the named volumes. Run `docker compose up -d` to start again.

To stop the app and also remove all stored data (irreversible):

```bash
docker compose down -v
```

> **Warning:** The `-v` flag deletes all Docker volumes, including your database, logs, and backups. Only use this if you want a completely clean slate.
