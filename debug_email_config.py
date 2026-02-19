
import os
import smtplib
import imaplib
from dotenv import load_dotenv

# 1. Check raw .env file
print("--- Raw .env Content (Masked) ---")
if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f:
            if "PASSWORD" in line:
                print(f"{line.split('=')[0]}=****")
            else:
                print(line.strip())
else:
    print("FATAL: .env file not found!")

print("\n--- Pydantic Settings Load ---")
try:
    from config.settings import get_settings
    import importlib
    import config.settings
    importlib.reload(config.settings)
    
    settings = config.settings.get_settings()
    
    # Check Gmail
    print(f"[GMAIL] USER: '{settings.email_user}'")
    print(f"[GMAIL] PASS: '{'****' if settings.email_password else 'EMPTY'}'")
    
    # Check Outlook
    print(f"[OUTLOOK] USER: '{settings.outlook_user}'")
    print(f"[OUTLOOK] PASS: '{'****' if settings.outlook_password else 'EMPTY'}'")

    print("\n--- Testing Outlook Connectivity ---")
    
    # Test IMAP (Reading)
    imap_host = "outlook.office365.com"
    print(f"Connecting to IMAP {imap_host}...")
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(settings.outlook_user, settings.outlook_password)
        print("SUCCESS: IMAP Login successful!")
        mail.logout()
    except Exception as e:
        print(f"FAILED: IMAP Login failed: {e}")
        print("TIP: If you're using live.ca/hotmail, ensure you've enabled IMAP in Outlook.com settings AND generated an App Password.")

    # Test SMTP (Sending)
    print(f"\nConnecting to SMTP {settings.outlook_host}:{settings.outlook_port}...")
    try:
        server = smtplib.SMTP(settings.outlook_host, settings.outlook_port)
        server.starttls()
        server.login(settings.outlook_user, settings.outlook_password)
        print("SUCCESS: SMTP Login successful!")
        server.quit()
    except Exception as e:
        print(f"FAILED: SMTP Login failed: {e}")

except Exception as e:
    print(f"Error loading settings: {e}")
