# Find and open a local file

Supported examples:

- “Play the movie Supergirl from my Downloads folder.”
- “Can you access my Downloads folder and play the movie Supergirl?”
- “Open report.pdf from my Documents folder.”
- “Open vacation photo from my Pictures folder.”

These direct requests use a deterministic workflow without model inference or
manual indexing. The named folder is mandatory. Supported folder aliases are
Downloads, Documents, Desktop, Videos, Music and Pictures. On Windows, configured
user-folder paths are read from the user's folder settings, including redirected
folders, then checked against Ultron's existing resource policy.

The workflow searches filenames recursively within that folder, with limits of
5,000 entries and a three-second scan budget. File contents are not read. Protected
locations, symlinks and junctions are excluded. An unreadable or incomplete scan
cannot establish a unique match and therefore does not open a file.

An explicit filename extension requires a complete filename match. Otherwise,
the title must match contiguous words (spaces, dots, hyphens and underscores separate words): “Supergirl” can match
`Supergirl.2026.1080p.mkv`, but “super well” is not corrected to “Supergirl”. Multiple
matches produce up to five numbered choices. For a single-file request, say
“open the second one” or “play number 2” within 60 seconds. The displayed numbers
refer to that particular list, sorted by path, not to a fresh search. A choice is
single-use; an unrelated request, cancellation, restart or expiry clears it.
This is one local user's session, not a multi-user or speaker-authenticated service.
The selected file's identity and access policy are checked again before opening.
A media-only play request cannot select a document.

You can also use up to five ordered actions, for example “open Calculator, then
play Supergirl from Downloads.” Every step must be a recognized app launch or
scoped file opening; scripts, search queries and inferred steps are excluded.
All steps are prepared before any executes. If execution fails, later steps are
reported as not started; earlier side effects are not rolled back. Dispatch of a
file does not wait for its application to finish loading. An ambiguous file in a
multi-step request rejects the entire batch; no numbered follow-up resumes it.

Play requests accept common audio/video extensions. Open requests also accept
common documents and images. Scripts, executables, shortcuts and unknown file
types are excluded from this workflow. Existing explicit resource operations
remain separate. A selected file is rechecked before OS dispatch; changes detected
since discovery require a new request. This is not an atomic file-system operation.

The OS default application receives the file. “Dispatched” means the OS accepted
that request; it does not mean a player is ready, playback started or sound is
verified. No new media player, paid API, download or full-drive index is required.

Automated tests cover parsing, scope, ambiguous and missing files, incomplete
scans, changed files and dispatch through a test adapter. Actual playback on a
user's desktop remains a live integration check.
