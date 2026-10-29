# YouTube playback (optional, Windows)

Search and playback are separate operations:

- “Search YouTube for relaxing piano music” opens ordinary search results.
- “Play Never Gonna Give You Up by Rick Astley on YouTube” searches, selects a
  matching video and attempts playback in an Ultron-controlled Microsoft Edge window.

## Setup

With Ultron stopped, run from the project directory:

```powershell
.\setup-youtube-playback.cmd
.\start-qwen3-trial.cmd
```

The setup installs the Playwright Python package into the existing virtual
environment. It uses installed Microsoft Edge; it does not install/replace Edge,
download songs, or require a paid API. Existing features work without this package.

The browser profile is isolated at
`%LOCALAPPDATA%\Ultron\youtube-browser`. It does not reuse your normal Edge/Chrome
profile, Google API credentials, or Gmail session. This profile is outside the
repository and support ZIP allowlist. It can retain cookies from manual consent.
No consent, sign-in, purchase or subscription buttons are clicked automatically.
The managed browser remains open for playback and closes when the brain stops.
The next playback request reuses its page and replaces the previous video.

## Selection and verification

Selection requires all meaningful requested title/artist words in the result title
and channel. Unrequested karaoke, cover, reaction and remix versions are excluded.
Matching artist-channel uploads rank above other uploads. Official videos rank above
lyric videos. Multiple official uploads from the requested artist use YouTube
result order; unknown-channel ties still ask for a more specific version. This is conservative
text matching, not musical identity recognition; misleading video metadata remains
a limitation.

Success requires the selected watch URL, advancing media time across observations,
a ready, unpaused, unmuted video with nonzero volume, and no visible ad-playing marker.
This verifies browser player state, not physical speaker output. Ads, autoplay
restrictions, consent pages, account requirements, network errors and YouTube DOM
changes can block verification. The bounded attempt reports failure instead of
claiming that opening search results played a song. It does not bypass these gates.

Only explicit single “play ... on YouTube” requests use this path. Other phrasing
may use existing planning/search behavior. Playback controls for this managed
browser and multi-step browser workflows are not implemented yet. Music from
speakers may be picked up by the microphone; headphones reduce that interference.

## Validation

Offline tests cover authorization grounding, title matching, ambiguity, URL limits,
ads/mute/stalled playback, cancellation, and execution-ledger reporting. CI also
uses a real Chromium browser with intercepted local HTML and a generated video
stream. That fixture tests browser integration without contacting YouTube.
It cannot establish that today's live YouTube markup or your Edge setup works.

After setup, say the example playback request above once. Check that the requested
video starts and Ultron reports playback verification. If blocked, inspect the
dedicated browser window and share a normal support ZIP with what you observed.

## Browser choice

Edge remains the default because it is available on most Windows installations.
To use installed Chrome, set this before launching Ultron from the same PowerShell:

```powershell
$env:ULTRON_BROWSER_CHANNEL = "chrome"
.\start-qwen3-trial.cmd
```

Use `msedge` to select Edge again. Both launch with Chromium sandboxing enabled;
there is no automatic fallback to an unsandboxed browser. Chrome uses a separate
`%LOCALAPPDATA%\Ultron\youtube-browser-chrome` profile, preserving the existing
Edge automation profile and all normal browser profiles. This selection affects
managed playback only; ordinary website searches use the existing system handling.
