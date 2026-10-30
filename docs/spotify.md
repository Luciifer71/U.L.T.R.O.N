# Spotify Premium

Optional Windows integration using Spotify's Web API and OAuth PKCE. No Client Secret is needed. Named songs default to Spotify only after connecting; explicitly asking for YouTube still uses YouTube. Without authorization, the existing Spotify app-search behavior remains available.

## Connect once

Create a Spotify developer app, select **Web API**, and register this exact redirect URI:

```text
http://127.0.0.1:8888/callback
```

From the repository root, with Ultron stopped:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/spotify.txt
.\.venv\Scripts\python.exe .\run_ultron.py spotify connect
```

Enter the app's **Client ID** at the prompt and approve access in the browser within two minutes. Never upload Client Secrets or authorization tokens. Credentials are stored in Windows Credential Manager, outside the repository and support bundles. Only a nonsecret enabled marker and device preference are stored under `%LOCALAPPDATA%\Ultron\spotify`.

Open Spotify on your laptop and start a track once so it is available to Spotify Connect. Then run:

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py spotify doctor
.\start-qwen3-trial.cmd
```

The doctor makes read-only checks; an authenticated account can still have zero available devices. A Premium account and permitted app user are required. Development-mode limits and Spotify rate limits apply.

## Try it

- “Play Save Your Tears by The Weeknd.”
- “Pause Spotify.” / “Resume Spotify.”
- “Next song.” / “Previous song.”
- “Queue Sunflower by Post Malone.”
- “Set Spotify volume to 40 percent.”
- “What is playing on Spotify?”
- “Play Sunflower by Post Malone on YouTube.”

Playback, pause and resume are reported as verified only when Spotify returns the requested state for the selected device. Queue, skip and volume replies acknowledge the request without claiming an observed result. Ambiguous song matches require a more specific title/artist; no arbitrary first result is chosen.

## Device preference and disconnect

The active device is used by default, or the sole available device. To keep playback on a particular device:

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py spotify devices
.\.venv\Scripts\python.exe .\run_ultron.py spotify device --name "Exact device name"
```

If that device is unavailable, Ultron asks you to open/select it instead of switching to another device. Spotify device IDs can change; select it again if needed. This connector controls the Spotify app; it does not stream audio itself, start the app automatically, or support arbitrary albums/playlists yet.

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py spotify disconnect
```

This removes local credentials and returns unnamed-provider music requests to YouTube. You can also revoke app access in Spotify account settings. Access tokens refresh automatically; revoked authorization requires reconnecting. Do not reconnect repeatedly for rate-limit errors—wait and retry.

References: [PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow), [redirect URIs](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri), [playback](https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback).
