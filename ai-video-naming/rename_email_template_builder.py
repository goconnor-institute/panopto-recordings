"""
Email Template Builder for Panopto Batch Rename Reports

Reads rename_email_template.html and populates it with dynamic content.
"""

import os
from datetime import datetime

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "rename_email_template.html")


def _load_template():
    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
        return f.read()


def _build_status_section(failed):
    if failed == 0:
        return """
            <div style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 25px;">
                <h3 style="margin: 0; font-size: 20px;">&#x2705; All Folders Renamed Successfully</h3>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">No failures to report. Nice one!</p>
            </div>"""
    return f"""
            <div style="background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 25px;">
                <h3 style="margin: 0; font-size: 20px;">&#x26A0;&#xFE0F; {failed} Folder(s) Failed</h3>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">See details below and check the attached log for errors.</p>
            </div>"""


def _build_failed_section(failed_rows):
    if not failed_rows:
        return ""

    html = """
            <div style="margin-bottom: 30px;">
                <h3 style="color: #667eea; font-size: 20px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0;">
                    &#x26A0;&#xFE0F; Folders Requiring Attention
                </h3>
                <div style="background: #fff8dc; border-left: 4px solid #ffa500; padding: 20px; border-radius: 0 8px 8px 0;">
            """

    for row in failed_rows:
        link = row.get('folder_link')
        name_html = (f"<a href=\"{link}\" style=\"color: #333; text-decoration: none;\">{row['shortname']} &#x1F517;</a>"
                     if link else row['shortname'])
        html += f"""
                    <div style="margin-bottom: 10px; padding: 12px 15px; background: white; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <div style="font-weight: bold; color: #333; font-size: 15px;">
                            &#x1F4DA; {name_html}
                        </div>
                        <div style="font-size: 13px; color: #999; margin-top: 4px;">
                            Class Group {row['class_group']} &middot; Folder {row['folder_id']}
                        </div>
                    </div>
                """

    html += "</div></div>"
    return html


def build_html_report(summary, panopto_server, summary_file_path=None, log_file_path=None):
    """Build the full HTML email report from the template file and dynamic data."""
    template = _load_template()
    now = datetime.now()

    failed = summary["failed"]
    failed_rows = [d for d in summary["details"] if d["status"] == "❌ failed"]

    summary_file_status = '&#x2705; Saved (not attached)' if summary_file_path and os.path.exists(summary_file_path) else '&#x274C; Not Available'
    log_file_status = '&#x2705; Attached' if log_file_path and os.path.exists(log_file_path) else '&#x274C; Not Available'

    replacements = {
        '{{report_datetime}}': now.strftime('%B %d, %Y at %H:%M:%S'),
        '{{total_folders}}': str(summary["total_folders"]),
        '{{processed}}': str(summary["processed"]),
        '{{succeeded}}': str(summary["succeeded"]),
        '{{failed}}': str(failed),
        '{{failed_color}}': '#FF6B6B' if failed > 0 else '#90EE90',
        '{{skipped_no_sessions}}': str(summary["skipped_no_sessions"]),
        '{{status_section}}': _build_status_section(failed),
        '{{failed_section}}': _build_failed_section(failed_rows),
        '{{panopto_server}}': panopto_server,
        '{{execution_time}}': now.strftime('%Y-%m-%d %H:%M:%S'),
        '{{summary_file_status}}': summary_file_status,
        '{{log_file_status}}': log_file_status,
    }

    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    return html


def build_plain_text_report(summary, panopto_server):
    """Build a plain text fallback version of the email report."""
    now = datetime.now()
    failed_rows = [d for d in summary["details"] if d["status"] == "❌ failed"]

    text = f"""
PANOPTO BATCH RENAME REPORT
Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}

EXECUTIVE SUMMARY
================
• Folders in Sheet: {summary['total_folders']}
• Processed: {summary['processed']}
• Succeeded: {summary['succeeded']}
• Failed: {summary['failed']}
• No Sessions: {summary['skipped_no_sessions']}

"""

    if failed_rows:
        text += "FOLDERS REQUIRING ATTENTION\n" + "=" * 27 + "\n"
        for row in failed_rows:
            text += f"• {row['shortname']} (Class Group {row['class_group']}): {row.get('folder_link', row['folder_id'])}\n"
        text += "\n"

    text += f"""
SYSTEM INFORMATION
==================
• Panopto Server: {panopto_server}
• Script Version: Batch IOE Folder Renamer
• Execution Time: {now.strftime('%Y-%m-%d %H:%M:%S')}

This is an automated report from the Panopto Batch Rename System.
"""

    return text
