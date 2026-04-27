# qobuz-dl
Search, explore and download Lossless and Hi-Res music from [Qobuz](https://www.qobuz.com/).
[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=VZWSWVGZGJRMU&source=url)

> **Status (2026-04):** Email/password login was disabled by Qobuz
> server-side in April 2026. This branch replaces it with **token-based
> login** (`user_id` + `user_auth_token` captured from `play.qobuz.com`).
>
> Downloads have been verified end-to-end on a Studio account
> (2026-04-26, FLAC 16/44.1). Some accounts may hit
> `InvalidAppSecretError` from a partial Qobuz signing rollout
> (MD5 → SHA-256 keyed by an HKDF-derived value); the CLI exits cleanly
> with code 3 and a pointer back here in that case rather than
> tracebacking. If you hit this, please open an issue with your account
> region/tier so we can confirm scope.

## Features

* Download FLAC and MP3 files from Qobuz
* Explore and download music directly from your terminal with **interactive** or **lucky** mode
* Download albums, tracks, artists, playlists and labels with **download** mode
* Download music from last.fm playlists (Spotify, Apple Music and Youtube playlists are also supported through this method)
* Queue support on **interactive** mode
* Effective duplicate handling with own portable database
* Support for albums with multiple discs
* Support for M3U playlists
* Downloads URLs from text file
* Extended tags
* And more

## Getting started

> You'll need an **active subscription**

#### Install qobuz-dl with pip
##### Linux / MAC OS
```
pip3 install --upgrade qobuz-dl
```
##### Windows
```
pip3 install windows-curses
pip3 install --upgrade qobuz-dl
```
#### Capture your token from play.qobuz.com
Email/password login was disabled by Qobuz in April 2026. You now need
to copy a `user_id` and `user_auth_token` from a logged-in browser
session.

1. Open <https://play.qobuz.com> in your browser and log in.
2. Open DevTools (F12) → **Console** tab.
3. Paste and press Enter:
   ```js
   JSON.parse(localStorage.getItem('localuser'))
   ```
4. Copy the `id` and `user_auth_token` fields from the result.

(Fallback if the console is disabled: **Application** → **Local Storage**
→ `https://play.qobuz.com` → click the `localuser` row. The value is a
JSON blob with the same `id` and `user_auth_token` fields.)

#### Run qobuz-dl and paste your token
##### Linux / MAC OS
```
qobuz-dl
```
##### Windows
```
qobuz-dl.exe
```
The first run will prompt for `user_id` and `user_auth_token` and
store them at `~/.config/qobuz-dl/config.ini` (mode `0600` on POSIX).

> If something fails, run `qobuz-dl -r` to reset your config file.
> Run `qobuz-dl --show-config` to inspect the current config (secrets
> are redacted by default; pass `--show-secrets` to reveal them).

## Examples

### Download mode
Download URL in 24B<96khz quality
```
qobuz-dl dl https://play.qobuz.com/album/qxjbxh1dc3xyb -q 7
```
Download multiple URLs to custom directory
```
qobuz-dl dl https://play.qobuz.com/artist/2038380 https://play.qobuz.com/album/ip8qjy1m6dakc -d "Some pop from 2020"
```
Download multiple URLs from text file
```
qobuz-dl dl this_txt_file_has_urls.txt
```
Download albums from a label and also embed cover art images into the downloaded files
```
qobuz-dl dl https://play.qobuz.com/label/7526 --embed-art
```
Download a Qobuz playlist in maximum quality
```
qobuz-dl dl https://play.qobuz.com/playlist/5388296 -q 27
```
Download all the music from an artist except singles, EPs and VA releases
```
qobuz-dl dl https://play.qobuz.com/artist/2528676 --albums-only
```

#### Last.fm playlists
> Last.fm has a new feature for creating playlists: you can create your own based on the music you listen to or you can import one from popular streaming services like Spotify, Apple Music and Youtube. Visit: `https://www.last.fm/user/<your profile>/playlists` (e.g. https://www.last.fm/user/vitiko98/playlists) to get started.

Download a last.fm playlist in the maximum quality
```
qobuz-dl dl https://www.last.fm/user/vitiko98/playlists/11887574 -q 27
```

Run `qobuz-dl dl --help` for more info.

### Interactive mode
Run interactive mode with a limit of 10 results
```
qobuz-dl fun -l 10
```
Type your search query
```
Logging...
Logged: OK
Membership: Studio


Enter your search: [Ctrl + c to quit]
- fka twigs magdalene
```
`qobuz-dl` will bring up a nice list of releases. Now choose whatever releases you want to download (everything else is interactive).

Run `qobuz-dl fun --help` for more info.

### Lucky mode
Download the first album result
```
qobuz-dl lucky playboi carti die lit
```
Download the first 5 artist results
```
qobuz-dl lucky joy division -n 5 --type artist
```
Download the first 3 track results in 320 quality
```
qobuz-dl lucky eric dolphy remastered --type track -n 3 -q 5
```
Download the first track result without cover art
```
qobuz-dl lucky jay z story of oj --type track --no-cover
```

Run `qobuz-dl lucky --help` for more info.

### Other
Reset your config file
```
qobuz-dl -r
```

By default, `qobuz-dl` will skip already downloaded items by ID with the message `This release ID ({item_id}) was already downloaded`. To avoid this check, add the flag `--no-db` at the end of a command. In extreme cases (e.g. lost collection), you can run `qobuz-dl -p` to completely reset the database.

## Usage
```
usage: qobuz-dl [-h] [-r] {fun,dl,lucky} ...

The ultimate Qobuz music downloader.
See usage examples on https://github.com/vitiko98/qobuz-dl

optional arguments:
  -h, --help      show this help message and exit
  -r, --reset     create/reset config file
  -p, --purge     purge/delete downloaded-IDs database

commands:
  run qobuz-dl <command> --help for more info
  (e.g. qobuz-dl fun --help)

  {fun,dl,lucky}
    fun           interactive mode
    dl            input mode
    lucky         lucky mode
```

## Module usage
Using `qobuz-dl` as a module is straightforward. The only thing you need
is `QobuzDL` from `core` plus a `user_id` + `user_auth_token` pair
captured from `play.qobuz.com` (see the *Getting started* section).

```python
import logging
from qobuz_dl.core import QobuzDL

logging.basicConfig(level=logging.INFO)

user_id = "3394846"
user_auth_token = "your-token-here"

qobuz = QobuzDL()
qobuz.get_tokens()  # populate qobuz.app_id and qobuz.secrets from bundle.js
qobuz.initialize_client_with_token(
    user_id, user_auth_token, qobuz.app_id, qobuz.secrets
)

qobuz.handle_url("https://play.qobuz.com/album/va4j3hdlwaubc")
```

> The pre-2026 `Client(email, pwd, app_id, secrets)` constructor and
> `QobuzDL.initialize_client(email, pwd, ...)` were removed in 0.9.10.0.
> Call `Client.from_token(...)` / `QobuzDL.initialize_client_with_token(...)`.

Attributes, methods and parameters have been named as self-explanatory as possible.

## A note about Qo-DL
`qobuz-dl` is inspired in the discontinued Qo-DL-Reborn. This tool uses two modules from Qo-DL: `qopy` and `spoofer`, both written by Sorrow446 and DashLt.
## Disclaimer
* This tool was written for educational purposes. I will not be responsible if you use this program in bad faith. By using it, you are accepting the [Qobuz API Terms of Use](https://static.qobuz.com/apps/api/QobuzAPI-TermsofUse.pdf).
* `qobuz-dl` is not affiliated with Qobuz
