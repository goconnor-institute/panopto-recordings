"""
Email Configuration for Panopto Synchronization Reports

Instructions:
1. Set SEND_EMAIL_REPORTS = True to enable email notifications
2. Configure your email provider settings below
3. For Gmail users:
   - Use your Gmail address for EMAIL_FROM
   - Use an "App Password" (not your regular password) for EMAIL_PASSWORD
   - Enable 2-factor authentication and generate an app password at:
     https://myaccount.google.com/apppasswords

Security Note: Actual credentials live in .env (EMAIL_FROM, EMAIL_PASSWORD, EMAIL_TO)
so this file is safe to commit. Keep .env itself out of version control.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# Enable/Disable email reports
SEND_EMAIL_REPORTS = True  # Set to True to enable email reports

# Email Server Configuration
EMAIL_SMTP_SERVER = "smtp.gmail.com"  # Gmail SMTP server (change for other providers)
EMAIL_SMTP_PORT = 587  # TLS port (587 for Gmail, 25/465 for others)

# Email Credentials (loaded from .env - see .env.example)
EMAIL_FROM = os.getenv("EMAIL_FROM", "")  # Your email address
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")  # Your email password or app password
EMAIL_TO = [addr.strip() for addr in os.getenv("EMAIL_TO", "").split(",") if addr.strip()]  # Where to send the reports

# Common Email Provider Settings:
#
# Gmail:
#   SMTP_SERVER = "smtp.gmail.com"
#   SMTP_PORT = 587
#   Use App Password (not regular password)
#
# Outlook/Hotmail:
#   SMTP_SERVER = "smtp-mail.outlook.com"  
#   SMTP_PORT = 587
#
# Yahoo:
#   SMTP_SERVER = "smtp.mail.yahoo.com"
#   SMTP_PORT = 587
#
# IOE/Institutional Email:
#   Contact your IT department for SMTP settings
#   Often: smtp.yourinstitution.edu, port 587 or 25