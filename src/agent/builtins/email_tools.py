"""Built-in email tools."""

import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config.settings import get_settings
from src.agent.tools import FunctionTool


def send_email(to_email: str, subject: str, body: str, account: str = "gmail") -> str:
    """Send an email to a recipient.
    
    Args:
        to_email: Content recipient email address.
        subject: The email subject line.
        body: The email body content (text).
        account: The email account to use ('gmail' or 'outlook'). Defaults to 'gmail'.
    """
    settings = get_settings()
    creds = settings.get_email_credentials(account)
    
    if not creds["user"] or not creds["password"]:
        return f"Error: {account.title()} credentials not configured."

    msg = MIMEMultipart()
    msg['From'] = creds["user"]
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(creds["host"], creds["port"])
        server.starttls()
        server.login(creds["user"], creds["password"])
        text = msg.as_string()
        server.sendmail(creds["user"], to_email, text)
        server.quit()
        return f"Email sent successfully to {to_email} via {account.title()}"
    except Exception as e:
        return f"Error sending email via {account.title()}: {e}"


def read_recent_emails(limit: int = 5, account: str = "gmail", folder: str = "INBOX") -> str:
    """Read recent emails from a specific folder and return them with internal IDs.
    
    Args:
        limit: Number of recent emails to fetch (default: 5).
        account: The email account to use ('gmail' or 'outlook'). Defaults to 'gmail'.
        folder: The folder to read from (e.g., 'INBOX', 'Spam', '[Gmail]/Promotions'). Defaults to 'INBOX'.
    """
    settings = get_settings()
    creds = settings.get_email_credentials(account)
    
    if not creds["user"] or not creds["password"]:
        return f"Error: {account.title()} credentials not configured."

    if "office365" in creds["host"]:
        imap_host = "outlook.office365.com"
    else:
        imap_host = creds["host"].replace('smtp.', 'imap.')
    
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(creds["user"], creds["password"])
        
        # Select folder
        status, _ = mail.select(folder)
        if status != 'OK':
            # Try to list folders to help the user/agent
            return f"Error: Folder '{folder}' not found in {account.title()}. Use list_email_folders to see valid names."

        status, messages = mail.search(None, 'ALL')
        if status != 'OK':
            return "No messages found."

        email_ids = messages[0].split()
        if not email_ids:
            return f"Folder '{folder}' is empty."
            
        latest_ids = email_ids[-limit:]
        
        results = []
        for e_id in reversed(latest_ids):
            decoded_id = e_id.decode()
            _, msg_data = mail.fetch(e_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = str(msg["subject"])
                    from_ = str(msg["from"])
                    results.append(f"[ID: {decoded_id}] From: {from_}\nSubject: {subject}\n---")
        
        mail.logout()
        
        if not results:
            return f"No recent emails found in {folder}."
            
        return f"Recent emails from {account.title()} [{folder}] (Total: {len(email_ids)}):\n\n" + "\n".join(results)

    except Exception as e:
        return f"Error reading emails from {account.title()} ({folder}): {e}"


def delete_email(email_id: str, account: str = "gmail", folder: str = "INBOX") -> str:
    """Delete an email by its internal ID from a specific folder.
    
    Args:
        email_id: The ID of the email to delete.
        account: The email account to use.
        folder: The folder where the email is located. Defaults to 'INBOX'.
    """
    settings = get_settings()
    creds = settings.get_email_credentials(account)
    
    if not creds["user"] or not creds["password"]:
        return f"Error: {account.title()} credentials not configured."

    if "office365" in creds["host"]:
        imap_host = "outlook.office365.com"
    else:
        imap_host = creds["host"].replace('smtp.', 'imap.')
    
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(creds["user"], creds["password"])
        mail.select(folder)

        # Mark for deletion
        mail.store(email_id, '+FLAGS', '\\Deleted')
        mail.expunge()
        mail.logout()
        
        return f"Successfully deleted email {email_id} from {account.title()} [{folder}]"
    except Exception as e:
        return f"Error deleting email {email_id} via {account.title()}: {e}"


def list_email_folders(account: str = "gmail") -> str:
    """List all available folders/mailboxes for the given account.
    
    Args:
        account: The email account to use ('gmail' or 'outlook').
    """
    settings = get_settings()
    creds = settings.get_email_credentials(account)
    
    if not creds["user"] or not creds["password"]:
        return f"Error: {account.title()} credentials not configured."

    if "office365" in creds["host"]:
        imap_host = "outlook.office365.com"
    else:
        imap_host = creds["host"].replace('smtp.', 'imap.')
        
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(creds["user"], creds["password"])
        
        status, folders = mail.list()
        mail.logout()
        
        if status != 'OK':
            return "Error listing folders."
            
        folder_names = []
        for f in folders:
            # Format usually looks like: (Flags) "/" "Folder Name"
            # We want the folder name
            parts = f.decode().split(' "/" ')
            if len(parts) > 1:
                name = parts[1].strip('"')
                folder_names.append(name)
        
        return f"Available folders for {account.title()}:\n" + "\n".join(folder_names)
    except Exception as e:
        return f"Error listing folders for {account.title()}: {e}"


EMAIL_TOOLS = [
    FunctionTool(send_email),
    FunctionTool(read_recent_emails),
    FunctionTool(delete_email),
    FunctionTool(list_email_folders),
]
