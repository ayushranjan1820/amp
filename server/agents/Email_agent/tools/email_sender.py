import os
import resend
from typing import List, Optional


def send_email(
    recipients: List[str],
    subject: str,
    html_content: str,
    from_name: str = "ET-Labs AI Agent"
) -> dict:
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")

    if not api_key:
        return {
            "success": False,
            "error": "RESEND_API_KEY not configured. Please add your Resend API key to send emails."
        }

    if not recipients:
        return {
            "success": False,
            "error": "No recipients specified"
        }

    try:
        resend.api_key = api_key

        params = {
            "from": f"{from_name} <{from_email}>",
            "to": recipients,
            "subject": subject,
            "html": html_content
        }

        email_response = resend.Emails.send(params)

        return {
            "success": True,
            "message": f"Email sent successfully to {', '.join(recipients)}",
            "email_id": email_response.get("id") if isinstance(email_response, dict) else str(email_response)
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to send email: {str(e)}"
        }


def format_email_html(subject: str, body: str) -> str:
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #374151; max-width: 700px; margin: 0 auto; padding: 0; background-color: #f3f4f6;">
        <div style="background: linear-gradient(135deg, #D85604 0%, #E88D14 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 22px;">{subject}</h1>
            <p style="color: rgba(255,255,255,0.85); margin: 8px 0 0 0; font-size: 13px;">Sent via ET-Labs AI Agent</p>
        </div>
        <div style="background: white; padding: 30px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
            {body}
        </div>
        <div style="text-align: center; padding: 20px; color: #9ca3af; font-size: 12px;">
            <p>Sent by ET-Labs AI Agent Marketplace</p>
        </div>
    </body>
    </html>
    """
