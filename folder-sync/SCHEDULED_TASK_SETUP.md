# Panopto Synchronization - Windows Scheduled Task Setup

## Quick Setup Guide

### 1. Test the Batch File First
Before setting up the scheduled task, test that everything works:

```cmd
cd "C:\path\to\panopto-recordings"
folder-sync\run_panopto_sync_enhanced.bat
```

### 2. Set Up Windows Task Scheduler

1. **Open Task Scheduler**:
   - Press `Win + R`, type `taskschd.msc`, press Enter
   - Or search for "Task Scheduler" in Start menu

2. **Create Basic Task**:
   - Click "Create Basic Task..." in the right panel
   - Name: `Panopto Synchronization`
   - Description: `Automated Panopto folder synchronization check`

3. **Set Trigger** (recommended: Daily at 6:00 AM):
   - Choose "Daily"
   - Set time: 6:00 AM (or your preferred time)
   - Recur every: 1 days

4. **Set Action**:
   - Choose "Start a program"
   - Program/script: `C:\path\to\panopto-recordings\folder-sync\run_panopto_sync_enhanced.bat`
   - Start in: `C:\path\to\panopto-recordings\folder-sync`

5. **Finish and Open Properties**:
   - Check "Open the Properties dialog for this task when I click Finish"
   - **Security options**: 
     - ✅ Run whether user is logged on or not
     - ✅ Run with highest privileges
   - **Settings**:
     - ✅ Allow task to be run on demand
     - ✅ Stop the task if it runs longer than: 2 hours
     - ✅ If the task fails, restart every: 15 minutes (up to 3 times)

### 3. Monitor Your Scheduled Task

- **Logs**: Check the `scheduled_logs` folder for detailed run logs
- **Email**: You'll receive beautiful HTML email reports automatically
- **Task Scheduler**: View the task's history and last run results

## Files You Need (Keep These)

### Core Files:
- `folder-sync/panopto_windows_safe.py` - Main Python script (Windows-compatible)
- `folder-sync/run_panopto_sync_enhanced.bat` - Batch file for scheduled task
- `folder-sync/email_config.py` - Email configuration (reads secrets from `.env`)
- `.env` - Credentials and configuration (never commit this)
- `pt_class_groups.xlsx` - Class groups data (repo root)
- `requirements.txt` - Python dependencies
- `auth/panopto_tokens.json` - OAuth tokens (auto-generated)

### Folders:
- `prod-venv/` - Python virtual environment (create at the repo root)
- `logs/` - Regular script logs
- `scheduled_logs/` - Scheduled task logs (auto-created)

## Recommended Schedule

- **Daily**: 6:00 AM (off-peak hours)
- **Weekly**: Monday at 8:00 AM
- **Avoid**: Business hours when Panopto API might be busy

## Troubleshooting

1. **Test manually first**: Run the batch file to ensure it works
2. **Check logs**: Look in `scheduled_logs` folder for errors
3. **Verify permissions**: Task should run with highest privileges
4. **Email notifications**: You'll get reports even if something fails

Your system is now ready for automated Panopto synchronization! 🚀