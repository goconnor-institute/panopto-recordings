# Panopto Recordings Toolkit

Scripts for managing Panopto video sessions at IOE: AI-generated session naming,
transcript downloads, folder synchronization between source and destination
folders, and Moodle course ID lookups.

## Setup

1. Create a virtual environment and install dependencies:
   ```
   python -m venv prod-venv
   prod-venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. Copy `.env.example` to `.env` and fill in your own values (Panopto OAuth app
   credentials, Moodle API key, email credentials for sync reports).
3. Copy `auth/panopto_tokens-example.json` conventions aside — you don't need to
   create this file yourself. Run `python auth/panopto_reauth.py` once to open a
   browser login and generate `auth/panopto_tokens.json`. Every other script
   refreshes it automatically after that.
4. Provide your own `pt_class_groups.xlsx` at the repo root with (at minimum)
   `Shortname`, `Class Group ID`, `IOE Folder ID`, `BC Folder ID` columns — this
   file is intentionally excluded from the repo since it holds institution-specific
   folder IDs.

All scripts expect to be run from the repo root (e.g. `python ai-video-naming/get_panopto_transcript.py ...`),
since file paths in `.env` (`TOKEN_FILE`, `CLASS_GROUPS_FILE`, etc.) resolve relative
to the current working directory.

On Windows consoles, set `PYTHONIOENCODING=utf-8` if you see `UnicodeEncodeError`
from the emoji in the scripts' console output.

## Structure

- `ai-video-naming/` — AI-based session renaming (`rename_panopto_folder.py`,
  `rename_all_ioe_folders.py`), transcript download, session restore.
- `auth/` — OAuth re-authentication helper and the (gitignored) token cache.
- `folder-sync/` — Scheduled sync between IOE (source) and BC (destination)
  Panopto folders, with email reports.
- `export_folder_videos.py` — Dumps all sessions across configured folders to
  an Excel workbook.

## Safety notes

- `rename_panopto_folder.py`, `restore_sessions.py`, and `panopto_windows_safe.py`
  make live, unconfirmed writes to production Panopto (renames, copies) when run
  with `--non-interactive` / as a scheduled task. Test against a scratch folder
  before pointing them at real course content.
- Secrets live only in `.env` (see `.env.example` for the required keys) — never
  commit `.env` or `auth/panopto_tokens.json`.
