"""
Email Template Builder for Panopto Sync Reports

Reads email_template.html and populates it with dynamic content.
"""

import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Template directory (same directory as this file)
TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FILE = os.path.join(TEMPLATE_DIR, "email_template.html")


def _load_template():
    """Load the HTML template from file"""
    with open(TEMPLATE_FILE, 'r', encoding='utf-8') as f:
        return f.read()


def _build_status_section(groups_with_differences, total_sessions_copied):
    """Build the status badge section"""
    if groups_with_differences == 0:
        return """
            <div style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 25px;">
                <h3 style="margin: 0; font-size: 20px;">&#x2705; All Systems Synchronized</h3>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">All class groups are perfectly in sync. No action required!</p>
            </div>"""
    elif total_sessions_copied > 0:
        return f"""
            <div style="background: linear-gradient(135deg, #fa709a 0%, #fee140 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 25px;">
                <h3 style="margin: 0; font-size: 20px;">&#x1F504; Synchronization in Progress</h3>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">Successfully copied {total_sessions_copied} sessions. Some groups still need attention.</p>
            </div>"""
    else:
        return f"""
            <div style="background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%); color: #8B4513; padding: 20px; border-radius: 8px; text-align: center; margin-bottom: 25px;">
                <h3 style="margin: 0; font-size: 20px;">&#x1F4CB; Status Report</h3>
                <p style="margin: 5px 0 0 0; opacity: 0.9;">{groups_with_differences} groups have differences that require attention.</p>
            </div>"""


def _build_differences_section(differences_summary):
    """Build the differences/attention section"""
    if not differences_summary:
        return ""

    html = """
            <div style="margin-bottom: 30px;">
                <h3 style="color: #667eea; font-size: 20px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0;">
                    &#x26A0;&#xFE0F; Groups Requiring Attention
                </h3>
                <div style="background: #fff8dc; border-left: 4px solid #ffa500; padding: 20px; border-radius: 0 8px 8px 0;">
            """

    for class_group_id, diff_info in differences_summary.items():
        html += f"""
                    <div style="margin-bottom: 15px; padding: 15px; background: white; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                        <div style="font-weight: bold; color: #333; font-size: 16px; margin-bottom: 8px;">
                            &#x1F4DA; Class Group {class_group_id}
                        </div>
                        <div style="display: flex; gap: 20px; font-size: 14px;">
                            <span style="color: #e74c3c;"><a href="{diff_info['ioe_folder_link']}" style="text-decoration:none; color: #e74c3c;">&#x1F4E4; IOE Only: <strong>{diff_info['ioe_only']}</strong></a></span>
                            <span> | </span>
                            <span style="color: #3498db;"><a href="{diff_info['bc_folder_link']}" style="text-decoration:none; color: #3498db;">&#x1F4E5; BC Only: <strong>{diff_info['bc_only']}</strong></a></span>
                        </div>
                    </div>
                """

    html += "</div></div>"
    return html


def _build_copy_item(copy_result):
    """Build HTML for a single copied session item"""
    success = copy_result['copy_result']['success']
    icon = "&#x2705;" if success else "&#x274C;"
    color = "#28a745" if success else "#dc3545"
    raw_date = copy_result.get('created_date', 'Unknown Date')
    try:
        created_date = datetime.fromisoformat(raw_date.replace('Z', '+00:00')).strftime('%b %d, %Y at %H:%M')
    except (ValueError, AttributeError):
        created_date = raw_date
    session_name = copy_result['session_name']
    name_display = session_name[:60] + ('...' if len(session_name) > 60 else '')

    html = f"""
                        <div style="padding: 8px 12px; margin: 5px 0; background: white; border-radius: 4px; border-left: 3px solid {color};">
                            <span style="color: {color};">{icon}</span>
                            <span style="margin-left: 10px; font-size: 14px;">Copied: {name_display}</span>
                            <span style="font-size: 12px; color: #999;">({created_date})</span>
                        """

    if not success:
        html += f"""<br><span style="color: #dc3545; font-size: 12px; margin-left: 25px;">Error: {copy_result['copy_result']['error']}</span>"""

    html += "</div>"
    return html


def _build_rename_item(rename_item):
    """Build HTML for a single renamed session item"""
    success = rename_item['result']['success']
    icon = "&#x270F;&#xFE0F;" if success else "&#x274C;"
    color = "#6f42c1" if success else "#dc3545"

    old_name = rename_item['old_name']
    new_name = rename_item['new_name']
    old_display = old_name[:40] + ('...' if len(old_name) > 40 else '')
    new_display = new_name[:40] + ('...' if len(new_name) > 40 else '')

    html = f"""
                        <div style="padding: 8px 12px; margin: 5px 0; background: #f8f0ff; border-radius: 4px; border-left: 3px solid {color};">
                            <span style="color: {color};">{icon}</span>
                            <span style="margin-left: 10px; font-size: 14px;">Renamed: <span style="text-decoration: line-through; color: #999;">{old_display}</span> &#x2192; <strong>{new_display}</strong></span>
                        """

    if not success:
        html += f"""<br><span style="color: #dc3545; font-size: 12px; margin-left: 25px;">Error: {rename_item['result']['error']}</span>"""

    html += "</div>"
    return html


def _build_sync_details_section(sync_results, rename_results):
    """Build the synchronization details section (copies and renames grouped by class group)"""
    has_sync = sync_results and len(sync_results) > 0
    has_renames = rename_results and len(rename_results) > 0 and any(r.get('results') for r in rename_results)

    if not has_sync and not has_renames:
        return ""

    html = """
            <div style="margin-bottom: 30px;">
                <h3 style="color: #667eea; font-size: 20px; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0;">
                    &#x1F504; Synchronization Details
                </h3>
            """

    # Build a lookup of rename results by class_group_id
    rename_by_group = {}
    if has_renames and rename_results:
        for rr in rename_results:
            gid = rr.get('class_group_id')
            if gid and rr.get('results'):
                rename_by_group[gid] = rr

    # Collect all class group IDs that have either sync or rename activity
    seen_groups = []
    if has_sync:
        for r in sync_results:
            gid = r.get('class_group_id')
            if gid not in seen_groups:
                seen_groups.append(gid)
    for gid in rename_by_group:
        if gid not in seen_groups:
            seen_groups.append(gid)

    for group_id in seen_groups:
        # Find sync result for this group (if any)
        group_sync = None
        if has_sync:
            for r in sync_results:
                if r.get('class_group_id') == group_id:
                    group_sync = r
                    break

        group_rename = rename_by_group.get(group_id)

        # Determine counts
        copied = group_sync['copied_sessions'] if group_sync else 0
        total = group_sync['total_sessions'] if group_sync else 0
        renamed_count = group_rename['renamed_count'] if group_rename else 0
        total_to_rename = group_rename.get('total_to_rename', 0) if group_rename else 0

        # Determine border colour based on sync success
        if total > 0:
            success_rate = (copied / total * 100)
            if success_rate == 100:
                border_color = "#28a745"
            elif success_rate > 0:
                border_color = "#ffc107"
            else:
                border_color = "#dc3545"
                logger.warning(f"Synchronization issue detected for Class Group {group_id}: {copied} copied out of {total} total.")
        elif total_to_rename > 0:
            border_color = "#6f42c1" if renamed_count == total_to_rename else "#ffc107"
        else:
            border_color = "#28a745"

        # Build summary badges
        badges = ""
        if total > 0:
            badge_bg = '#28a745' if copied == total else '#dc3545'
            badges += f"""<span style="background: {badge_bg}; color: white; padding: 4px 12px; border-radius: 20px; font-size: 13px; margin-left: 6px;">&#x1F4CB; Copied: {copied}/{total}</span>"""
        if total_to_rename > 0:
            badge_bg = '#6f42c1' if renamed_count == total_to_rename else '#ffc107'
            badges += f"""<span style="background: {badge_bg}; color: white; padding: 4px 12px; border-radius: 20px; font-size: 13px; margin-left: 6px;">&#x270F;&#xFE0F; Renamed: {renamed_count}/{total_to_rename}</span>"""

        # Get folder name from sync or rename result
        folder_name = None
        if group_sync:
            folder_name = group_sync.get('ioe_folder_name')
        if not folder_name and group_rename:
            folder_name = group_rename.get('ioe_folder_name')
        group_label = f"{folder_name} ({group_id})" if folder_name else f"Class Group {group_id}"

        html += f"""
                <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 15px; border-left: 4px solid {border_color};">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px;">
                        <span style="font-weight: bold; font-size: 16px;">{group_label}</span>
                        <div>{badges}</div>
                    </div>
                """

        html += "<div style='margin-top: 15px;'>"

        # Show copied sessions
        if group_sync and group_sync['results']:
            for copy_result in group_sync['results']:
                html += _build_copy_item(copy_result)

        # Show renamed sessions
        if group_rename and group_rename['results']:
            for rename_item in group_rename['results']:
                html += _build_rename_item(rename_item)

        html += "</div></div>"

    html += "</div>"
    return html


def build_html_report(
    total_groups,
    groups_synchronized,
    total_sessions_copied,
    total_sessions_renamed,
    groups_with_differences,
    differences_summary,
    sync_results,
    rename_results,
    panopto_server,
    results_file_path=None,
    scheduled_run_log=None
):
    """Build the full HTML email report from the template file and dynamic data.
    
    Returns the complete HTML string ready for sending.
    """
    template = _load_template()

    now = datetime.now()
    attention_color = '#FFB347' if groups_with_differences > 0 else '#90EE90'

    # Build dynamic sections
    status_section = _build_status_section(groups_with_differences, total_sessions_copied)
    differences_section = _build_differences_section(differences_summary)
    sync_details_section = _build_sync_details_section(sync_results, rename_results)

    results_file_status = '&#x2705; Attached' if results_file_path and os.path.exists(results_file_path) else '&#x274C; Not Available'
    log_file_status = '&#x2705; Attached' if scheduled_run_log and os.path.exists(scheduled_run_log) else '&#x274C; Not Available'

    # Replace all placeholders in the template
    replacements = {
        '{{report_datetime}}': now.strftime('%B %d, %Y at %H:%M:%S'),
        '{{total_groups}}': str(total_groups if total_groups else 0),
        '{{groups_synchronized}}': str(groups_synchronized),
        '{{total_sessions_copied}}': str(total_sessions_copied),
        '{{total_sessions_renamed}}': str(total_sessions_renamed),
        '{{attention_color}}': attention_color,
        '{{groups_with_differences}}': str(groups_with_differences),
        '{{status_section}}': status_section,
        '{{differences_section}}': differences_section,
        '{{sync_details_section}}': sync_details_section,
        '{{panopto_server}}': panopto_server,
        '{{execution_time}}': now.strftime('%Y-%m-%d %H:%M:%S'),
        '{{results_file_status}}': results_file_status,
        '{{log_file_status}}': log_file_status,
    }

    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    return html


def build_plain_text_report(
    total_groups,
    groups_synchronized,
    total_sessions_copied,
    total_sessions_renamed,
    groups_with_differences,
    differences_summary,
    panopto_server
):
    """Build a plain text fallback version of the email report."""
    now = datetime.now()

    text = f"""
PANOPTO SYNCHRONIZATION REPORT
Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}

EXECUTIVE SUMMARY
================
\u2022 Groups Processed: {total_groups}
\u2022 Groups Synchronized: {groups_synchronized}  
\u2022 Sessions Copied: {total_sessions_copied}
\u2022 Sessions Renamed: {total_sessions_renamed}
\u2022 Groups Needing Attention: {groups_with_differences}

"""

    if differences_summary:
        text += "GROUPS REQUIRING ATTENTION\n" + "=" * 26 + "\n"
        for class_group_id, diff_info in differences_summary.items():
            text += f"\u2022 {class_group_id}: {diff_info['ioe_only']} IOE-only, {diff_info['bc_only']} BC-only sessions\n"
        text += "\n"

    text += f"""
SYSTEM INFORMATION
==================
\u2022 Panopto Server: {panopto_server}
\u2022 Script Version: Windows-Safe Automated Synchronization  
\u2022 Execution Time: {now.strftime('%Y-%m-%d %H:%M:%S')}

This is an automated report from the Panopto Synchronization System.
"""

    return text
