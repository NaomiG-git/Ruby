
import imaplib
import smtplib

user = "grindlay@live.ca"
pw = "mvqxwenlflbjreqn"

print(f"Testing hardcoded creds for {user}...")

try:
    print("Trying IMAP...")
    mail = imaplib.IMAP4_SSL("outlook.office365.com")
    mail.login(user, pw)
    print("IMAP SUCCESS!")
    mail.logout()
except Exception as e:
    print(f"IMAP FAILED: {e}")

try:
    print("\nTrying SMTP...")
    server = smtplib.SMTP("smtp.office365.com", 587)
    server.starttls()
    server.login(user, pw)
    print("SMTP SUCCESS!")
    server.quit()
except Exception as e:
    print(f"SMTP FAILED: {e}")
