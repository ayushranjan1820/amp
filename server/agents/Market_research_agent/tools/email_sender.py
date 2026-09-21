import os
import resend
from typing import List, Optional

def send_research_email(
    recipients: List[str],
    subject: str,
    html_content: str,
    from_name: str = "ET-Labs Market Research"
) -> dict:
    """
    Send the market research report via email using Resend.
    
    Resend provides:
    - High deliverability (proper SPF/DKIM/DMARC)
    - Free tier: 100 emails/day, 3000 emails/month
    - Professional email delivery that avoids spam folders
    
    Args:
        recipients: List of email addresses to send to
        subject: Email subject line
        html_content: HTML formatted email body
        from_name: Sender display name
    
    Returns:
        dict with success status and message
    """
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
        
        try:
            from cost_tracker import log_cost_event
            log_cost_event(
                event_type="email_send",
                agent_name="Market Research Agent",
                metadata={"recipients": recipients, "subject": subject}
            )
        except Exception:
            pass
        
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

def format_research_as_html(
    query: str,
    summary: str,
    sources: List[dict]
) -> str:
    """
    Format the research report as professional HTML email.
    """
    sources_html = ""
    for i, source in enumerate(sources, 1):
        sources_html += f"""
        <tr>
            <td style="padding: 12px; border-bottom: 1px solid #e5e7eb;">
                <strong style="color: #1f2937;">{i}. {source.get('title', 'Untitled')}</strong><br>
                <a href="{source.get('url', '#')}" style="color: #D85604; text-decoration: none; font-size: 14px;">
                    {source.get('url', '')}
                </a>
                <p style="color: #6b7280; font-size: 14px; margin-top: 8px;">
                    {source.get('snippet', '')[:200]}...
                </p>
            </td>
        </tr>
        """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #374151; max-width: 800px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #D85604 0%, #E88D14 100%); padding: 30px; border-radius: 12px 12px 0 0;">
            <h1 style="color: white; margin: 0; font-size: 24px;">Market Research Report</h1>
            <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 14px;">Powered by ET-Labs AI Agent</p>
        </div>
        
        <div style="background: #f9fafb; padding: 25px; border: 1px solid #e5e7eb; border-top: none;">
            <div style="background: white; padding: 20px; border-radius: 8px; border-left: 4px solid #D85604;">
                <h2 style="color: #1f2937; margin: 0 0 10px 0; font-size: 16px;">Research Query</h2>
                <p style="color: #4b5563; margin: 0; font-style: italic;">"{query}"</p>
            </div>
        </div>
        
        <div style="background: white; padding: 25px; border: 1px solid #e5e7eb; border-top: none;">
            {summary}
        </div>
        
        <div style="background: #f9fafb; padding: 25px; border: 1px solid #e5e7eb; border-top: none; border-radius: 0 0 12px 12px;">
            <h2 style="color: #1f2937; margin: 0 0 20px 0; font-size: 18px;">
                Sources & References
            </h2>
            <table style="width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden;">
                {sources_html}
            </table>
        </div>
        
        <div style="text-align: center; padding: 20px; color: #9ca3af; font-size: 12px;">
            <p>This report was generated by ET-Labs AI Agent Marketplace</p>
            <p style="margin: 5px 0 0 0;">&copy; 2026 ET-Labs. All rights reserved.</p>
        </div>
    </body>
    </html>
    """
    
    return html
