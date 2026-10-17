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
matches require a more specific filename or an exact-path request. There is no
implicit “choose the first one” behavior or conversational candidate-selection
state yet. The workflow supports one requested file at a time.

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
