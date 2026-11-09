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

On Windows, a named-song playback request can launch Spotify Desktop automatically when no playback device is available. U.L.T.R.O.N. then waits up to 15 seconds for Spotify Connect device discovery. The Spotify application must be installed and authorized with the connected Premium account.

Run the read-only connection diagnostic:

```powershell
.\.venv\Scripts\python.exe .\run_ultron.py spotify doctor
.\start-ultron.cmd
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

Common variations also work while Spotify is connected: “Next” / “Skip”, “Go back to the previous track”, “Stop the music”, “Play some music” (resumes the current track), “What's playing right now?”, “Turn Spotify volume to 40 percent” and “Spotify volume up” / “Make Spotify quieter” (10-point steps). A bare “Volume up” still controls system volume. Requests with anything extra, such as “Skip this song and delete files” or “Don't skip”, are not treated as Spotify commands.

Playback, pause and resume are reported as verified only when Spotify returns the requested state for the selected device. Queue, skip and volume replies acknowledge the request without claiming an observed result. Ambiguous song matches require a more specific title/artist; no arbitrary first result is chosen.

## Playback reliability

Named tracks are started using their album context and the selected track offset. This addresses a Spotify Desktop case where direct track playback returned an HTTP acknowledgement without starting music.

Playback, pause and resume require observed Spotify playback state before they are reported as verified. Next, previous, queue and volume commands acknowledge successful API requests without claiming that the resulting state was independently observed.

Spotify Connect device availability can fluctuate during startup. If automatic discovery fails, check `spotify doctor` and `spotify devices`. An HTTP acknowledgement alone does not prove that playback started.

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

Natural variants include “Can you set the volume of Spotify to 40%?” and “Open Spotify and search for Save Your Tears by The Weeknd and play it.” The latter opens the app before requesting playback; Spotify Connect still needs to report an available device. “Play the song now” asks for a title instead of searching for a track called “now.” Use “resume Spotify” for the current Spotify track.

Support ZIPs include a bounded read-only Spotify doctor result (connection status, available/active device counts and whether playback is active). No Spotify device names, IDs, track names or credentials are included in that diagnostic.
