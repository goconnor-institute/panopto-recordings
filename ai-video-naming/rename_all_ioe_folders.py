#!/usr/bin/env python3
"""
Batch Panopto Session Renamer
------------------------------
Loops through pt_class_groups.xlsx and runs rename_panopto_folder.py
for every IOE folder listed.

Usage:
    python rename_all_ioe_folders.py                            # normal run (skips already-renamed)
    python rename_all_ioe_folders.py --force                    # re-rename everything
    python rename_all_ioe_folders.py --use-week-nums            # override: force week nums for all rows
    python rename_all_ioe_folders.py --same-day-same-topic      # override: force same-day-same-topic for all rows
    python rename_all_ioe_folders.py --max-days 5               # override: force max-days for all rows
    python rename_all_ioe_folders.py --dry-run                  # preview without renaming
    python rename_all_ioe_folders.py --start 10                 # resume from row 10 (1-based)
    python rename_all_ioe_folders.py --start 10 --end 20        # process rows 10-20 inclusive
    python rename_all_ioe_folders.py --only 201907              # process a single class group ID

Week numbers are controlled per-row via the "Use Week Num" column in
pt_class_groups.xlsx (1 = yes, 0/blank = no).  The --use-week-nums flag
overrides this and forces week numbers for every row.

Same-day-same-topic and max-days are controlled per-row via "Same Day Same Topic"
and "Max Days" columns.  The CLI flags override these for all rows.

Rows with "Skip Rename" set to 1 still get date/week-number formatting applied,
but skip caption download and AI topic generation (new name uses the original
session name instead of an AI-generated topic).

A class group can have an IOE folder, a BC folder, or both (same Panopto
instance). IOE is always renamed when present; rows with only a BC folder are
renamed directly against that BC folder instead of being skipped.
"""

import subprocess
import sys
import os
import json
import argparse
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

import pandas as pd
from dotenv import load_dotenv

from rename_email_template_builder import build_html_report, build_plain_text_report

load_dotenv(override=True)

CLASS_GROUPS_FILE = os.getenv("CLASS_GROUPS_FILE", "pt_class_groups.xlsx")
LOG_DIR = "scheduled_logs"

PANOPTO_SERVER = os.getenv("PANOPTO_SERVER", "")
EMAIL_SMTP_SERVER = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO = [addr.strip() for addr in os.getenv("EMAIL_TO", "").split(",") if addr.strip()]


def send_batch_email_report(summary, log_file, summary_file):
    """Send an HTML email summarising the batch rename run, styled like the folder-sync report."""
    if not EMAIL_FROM or not EMAIL_PASSWORD or not EMAIL_TO:
        print("\n⚠️  Email not configured (EMAIL_FROM/EMAIL_PASSWORD/EMAIL_TO) - skipping email report")
        return False

    status_emoji = "✅" if summary["failed"] == 0 else "⚠️"
    subject = (f"{status_emoji} Panopto Batch Rename Report - "
               f"{datetime.now().strftime('%b %d, %Y at %H:%M')}")

    html_body = build_html_report(summary, PANOPTO_SERVER, summary_file, log_file)
    plain_text = build_plain_text_report(summary, PANOPTO_SERVER)

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(EMAIL_TO)
        msg['Subject'] = subject
        msg.attach(MIMEText(plain_text, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        for path in (log_file,):
            if path and os.path.exists(path):
                with open(path, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(path)}')
                    msg.attach(part)

        server = smtplib.SMTP(EMAIL_SMTP_SERVER, EMAIL_SMTP_PORT)
        server.starttls()
        server.login(EMAIL_FROM, EMAIL_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        server.quit()
        print(f"\n📧 Email report sent to {', '.join(EMAIL_TO)}")
        return True
    except Exception as e:
        print(f"\n⚠️  Failed to send email report: {e}")
        return False


def _has_value(val):
    return pd.notna(val) and str(val).strip() != "" and str(val).strip().lower() != "nan"


def pick_folder(row):
    """Pick which folder to rename for a row: IOE Folder ID if present, otherwise
    BC Folder ID (a class group can have an IOE folder, a BC folder, or both - they're
    on the same Panopto instance). IOE is preferred when both exist; the folder-sync
    script propagates renamed IOE session names to the linked BC session separately,
    so only IOE-only-or-BC-only rows need direct renaming here.

    Returns (folder_id, source, folder_link) where source is "IOE" or "BC",
    or (None, None, None) if neither folder is set.
    """
    ioe_id = row.get("IOE Folder ID")
    if _has_value(ioe_id):
        folder_id = str(ioe_id).strip()
        link = str(row.get("IOE Folder Link", "")).strip()
        if not _has_value(link):
            link = f"https://{PANOPTO_SERVER}/Panopto/Pages/Sessions/List.aspx?folderID={folder_id}"
        return folder_id, "IOE", link

    bc_id = row.get("BC Folder ID")
    if _has_value(bc_id):
        folder_id = str(bc_id).strip()
        link = str(row.get("BC Folder Link", "")).strip()
        if not _has_value(link):
            link = f"https://{PANOPTO_SERVER}/Panopto/Pages/Sessions/List.aspx?folderID={folder_id}"
        return folder_id, "BC", link

    return None, None, None


def load_class_groups(filepath):
    """Load the class groups spreadsheet and return rows with a valid IOE or BC Folder ID.

    A class group can have an IOE folder, a BC folder, or both. Rows with only a
    BC folder are kept and renamed directly against that BC folder (see pick_folder).

    Rows marked "Skip Rename" (1) are kept - they still get date/week-number
    formatting applied, just without caption download or AI topic generation.
    """
    df = pd.read_excel(filepath)
    has_ioe = df["IOE Folder ID"].notna() & (df["IOE Folder ID"].astype(str).str.strip() != "")
    has_bc = df["BC Folder ID"].notna() & (df["BC Folder ID"].astype(str).str.strip() != "")
    bc_only = int((~has_ioe & has_bc).sum())
    df = df[has_ioe | has_bc].reset_index(drop=True)

    if bc_only:
        print(f"🔗 {bc_only} folder(s) have only a BC folder - will rename directly against BC")

    skip_ai = int((df.get("Skip Rename", 0) == 1).sum())
    if skip_ai:
        print(f"🚫 {skip_ai} folder(s) marked 'Skip Rename' - will apply date/week formatting only (no AI topic)")
    return df


def run_rename(folder_id, shortname, extra_args):
    """
    Call rename_panopto_folder.py for a single folder.
    Returns (success: bool, message: str).
    """
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rename_panopto_folder.py")
    cmd = [
        sys.executable,
        script_path,
        "--non-interactive",
        "--folder-url", folder_id,
    ] + extra_args

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,  # 30 min per folder
            env=env,
        )
        output = result.stdout + result.stderr
        success = result.returncode == 0
        return success, output
    except subprocess.TimeoutExpired:
        return False, "⏰ Timed out after 10 minutes"
    except Exception as e:
        return False, f"❌ Error: {e}"


def main():
    parser = argparse.ArgumentParser(
        description="Batch-rename Panopto sessions for all IOE folders in pt_class_groups.xlsx"
    )
    parser.add_argument("--force", "-f", action="store_true",
                        help="Force re-rename already processed sessions")
    parser.add_argument("--use-week-nums", "-w", action="store_true",
                        help="Override: force week numbers for all rows (default: per-row from spreadsheet)")
    parser.add_argument("--same-day-same-topic", "-s", action="store_true",
                        help="Override: force same-day-same-topic for all rows (default: per-row from spreadsheet)")
    parser.add_argument("--max-days", "-m", type=int, default=None,
                        help="Override: force max-days for all rows (default: per-row from spreadsheet)")
    parser.add_argument("--dry-run", action="store_true",
                        help="List folders that would be processed without renaming")
    parser.add_argument("--start", type=int, default=1,
                        help="Start from this row number (1-based, default: 1)")
    parser.add_argument("--end", type=int, default=None,
                        help="End at this row number inclusive (1-based, default: last row)")
    parser.add_argument("--only", type=str, default=None,
                        help="Process only the folder matching this Class Group ID")
    parser.add_argument("--no-email", action="store_true",
                        help="Skip sending the email report at the end")
    args = parser.parse_args()

    # ── Load spreadsheet ──────────────────────────────────────────────
    if not os.path.exists(CLASS_GROUPS_FILE):
        print(f"❌ Class groups file not found: {CLASS_GROUPS_FILE}")
        sys.exit(1)

    df = load_class_groups(CLASS_GROUPS_FILE)
    total = len(df)
    print("=" * 70)
    print("🎬 BATCH PANOPTO SESSION RENAMER")
    print(f"📋 Loaded {total} IOE folders from {CLASS_GROUPS_FILE}")
    if args.force:
        print("🔄 FORCE MODE enabled")
    if args.use_week_nums:
        print("📆 WEEK NUMBER MODE: forced ON for all rows")
    else:
        print("📆 WEEK NUMBERS: per-row from 'Use Week Num' column")
    if args.same_day_same_topic:
        print("🔁 SAME-DAY MODE: forced ON for all rows")
    else:
        print("🔁 SAME-DAY MODE: per-row from 'Same Day Same Topic' column")
    if args.max_days:
        print(f"📆 MAX DAYS: forced to {args.max_days} for all rows")
    else:
        print("📆 MAX DAYS: per-row from 'Max Days' column")
    print("=" * 70)

    # ── Filter by --only if provided ──────────────────────────────────
    if args.only:
        mask = df["Class Group ID"].astype(str) == str(args.only)
        df = df[mask].reset_index(drop=True)
        if df.empty:
            print(f"❌ No folder found with Class Group ID: {args.only}")
            sys.exit(1)
        print(f"🔍 Filtering to Class Group ID: {args.only}")

    # ── Apply --start / --end range ───────────────────────────────────
    start_idx = max(0, args.start - 1)
    end_idx = args.end if args.end else len(df)
    if start_idx > 0 or args.end:
        print(f"⏩ Processing rows {args.start}–{end_idx} of {len(df)}")

    # ── Dry-run mode ──────────────────────────────────────────────────
    if args.dry_run:
        print(f"\n{'#':>4}  {'Class Group':>12}  {'Src':>3}  {'Folder ID':<38}  {'Wk#':>3}  {'SDT':>3}  {'MDy':>3}  {'AI':>3}  Shortname")
        print("-" * 128)
        for idx, row in df.iloc[start_idx:end_idx].iterrows():
            num = start_idx + idx + 1
            use_wk = "YES" if args.use_week_nums or row.get("Use Week Num", 0) == 1 else "no"
            use_sdt = "YES" if args.same_day_same_topic or row.get("Same Day Same Topic", 0) == 1 else "no"
            max_d = args.max_days or (int(row["Max Days"]) if pd.notna(row.get("Max Days", None)) and row.get("Max Days", 0) else "")
            skip_ai = "no" if row.get("Skip Rename", 0) == 1 else "YES"
            folder_id, folder_source, _ = pick_folder(row)
            print(f"{num:>4}  {str(row.get('Class Group ID', '')):>12}  {folder_source or '':>3}  "
                  f"{folder_id or '':<38}  {use_wk:>3}  {use_sdt:>3}  {str(max_d):>3}  {skip_ai:>3}  {row.get('Shortname', '')}")
        print(f"\n📊 {end_idx - start_idx} folders would be processed.")
        return

    # ── Build base extra args (per-row week nums added in loop) ───────
    extra_args = []
    if args.force:
        extra_args.append("--force")

    # ── Prepare logging ───────────────────────────────────────────────
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(LOG_DIR, f"batch_rename_{timestamp}.log")

    summary = {
        "timestamp": timestamp,
        "total_folders": total,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped_no_sessions": 0,
        "details": [],
    }

    # ── Process each folder ───────────────────────────────────────────
    rows_to_process = df.iloc[start_idx:end_idx]
    count = len(rows_to_process)

    for i, (_, row) in enumerate(rows_to_process.iterrows()):
        folder_id, folder_source, folder_link = pick_folder(row)
        shortname = str(row.get("Shortname", "Unknown"))
        class_group = str(row.get("Class Group ID", ""))
        num = start_idx + i + 1

        if not folder_id:
            print(f"\n{'─' * 70}")
            print(f"[{i + 1}/{count}] ({num}/{total}) {shortname}")
            print("  ❌ No IOE or BC folder ID - skipping")
            summary["processed"] += 1
            summary["failed"] += 1
            summary["details"].append({
                "row": num, "class_group": class_group, "shortname": shortname,
                "folder_id": None, "folder_link": None, "status": "❌ failed",
            })
            continue

        # Decide week numbers: CLI override OR per-row column
        use_week = args.use_week_nums or row.get("Use Week Num", 0) == 1
        use_sdt = args.same_day_same_topic or row.get("Same Day Same Topic", 0) == 1
        max_days = args.max_days or (int(row["Max Days"]) if pd.notna(row.get("Max Days", None)) and row.get("Max Days", 0) else None)
        skip_ai_topic = row.get("Skip Rename", 0) == 1

        row_args = list(extra_args)
        if use_week:
            row_args.append("--use-week-nums")
        if use_sdt:
            row_args.append("--same-day-same-topic")
        if max_days:
            row_args.extend(["--max-days", str(max_days)])
        if skip_ai_topic:
            row_args.append("--no-ai-topic")

        print(f"\n{'─' * 70}")
        print(f"[{i + 1}/{count}] ({num}/{total}) {shortname}")
        print(f"  📂 Folder ID: {folder_id} ({folder_source})")
        print(f"  📆 Week numbers: {'YES' if use_week else 'no'}")
        print(f"  🔁 Same-day-same-topic: {'YES' if use_sdt else 'no'}")
        if max_days:
            print(f"  📆 Max days: {max_days}")
        if skip_ai_topic:
            print("  🚫 Skip Rename: date/week formatting only, no AI topic")

        success, output = run_rename(folder_id, shortname, row_args)

        # Determine outcome from output
        no_sessions = "No sessions found" in output or "Found 0 sessions" in output
        already_done = output.count("Already renamed") > 0 and "Renamed!" not in output

        status = "✅ success" if success else "❌ failed"
        if no_sessions:
            status = "⏭️ no sessions"
            summary["skipped_no_sessions"] += 1
        elif success:
            summary["succeeded"] += 1
        else:
            summary["failed"] += 1

        summary["processed"] += 1
        summary["details"].append({
            "row": num,
            "class_group": class_group,
            "shortname": shortname,
            "folder_id": folder_id,
            "folder_source": folder_source,
            "folder_link": folder_link,
            "status": status,
        })

        print(f"  {status}")

        # Write incremental log
        with open(log_file, "a", encoding="utf-8") as lf:
            lf.write(f"\n{'=' * 70}\n")
            lf.write(f"[{num}/{total}] {shortname} ({folder_id})\n")
            lf.write(f"Status: {status}\n")
            lf.write(output)
            lf.write("\n")

    # ── Final summary ─────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("📊 BATCH RENAME SUMMARY")
    print(f"  Processed:    {summary['processed']}")
    print(f"  Succeeded:    {summary['succeeded']}")
    print(f"  Failed:       {summary['failed']}")
    print(f"  No sessions:  {summary['skipped_no_sessions']}")
    print(f"  Log file:     {log_file}")
    print("=" * 70)

    # Save JSON summary
    summary_file = os.path.join(LOG_DIR, f"batch_rename_summary_{timestamp}.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"📋 Summary saved: {summary_file}")

    # Email report
    if not args.no_email:
        send_batch_email_report(summary, log_file, summary_file)

    # Exit with error code if any failed
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
