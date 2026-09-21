import os
import re
import json
from typing import Optional, List, Dict, Any
from .tools.email_sender import send_email, format_email_html
from agents.llm_continuation import sync_call_with_continuation_httpx
from agents.local_llm import get_llm_provider, uses_pwc_genai_credentials


class EmailAgent:
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.pwc_api_key = os.environ.get("PWC_GENAI_API_KEY")
        self.pwc_bearer_token = os.environ.get("PWC_GENAI_BEARER_TOKEN")
        self.pwc_endpoint = os.environ.get("PWC_GENAI_ENDPOINT_URL")
        self.model = ""

        prov = get_llm_provider()
        if prov == "local_llm":
            print("Email Agent - Using Local LLM service")
        elif prov == "ollama_cloud":
            print("Email Agent - Using Ollama Cloud")
        elif self.pwc_api_key and self.pwc_endpoint:
            print("Email Agent - Using PwC GenAI service")
        else:
            print("Email Agent - PwC GenAI credentials not configured")

    def _get_session(self, session_id: str) -> Dict:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "state": "idle",
                "to": [],
                "subject": "",
                "body": "",
                "history": [],
            }
        return self.sessions[session_id]

    def _call_llm(self, prompt: str) -> str:
        try:
            from langfuse_tracer import set_current_agent
            set_current_agent("Email Agent")
        except Exception:
            pass
        if uses_pwc_genai_credentials() and (not self.pwc_api_key or not self.pwc_endpoint):
            raise RuntimeError("LLM service not configured. Set PWC_GENAI_API_KEY and PWC_GENAI_ENDPOINT_URL.")

        headers: Dict[str, str] = {
            "accept": "application/json",
            "API-Key": self.pwc_api_key,
            "Content-Type": "application/json",
        }
        if self.pwc_bearer_token:
            headers["Authorization"] = f"Bearer {self.pwc_bearer_token}"

        request_body = {
            "model": self.model,
            "prompt": prompt,
            "temperature": 0.3,
            "max_tokens": 4096,
        }

        result = sync_call_with_continuation_httpx(
            endpoint_url=self.pwc_endpoint,
            headers=headers,
            request_body=request_body,
            original_prompt=prompt,
        )
        if not result or not isinstance(result, str):
            raise RuntimeError("LLM returned empty response")
        return result

    def _extract_email_payload(self, query: str, history: List[Dict]) -> Dict:
        history_text = ""
        for msg in history[-10:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")[:500]
            history_text += f"{role}: {content}\n"

        prompt = f"""You are a professional email assistant. Extract or compose the email from the user's request.

Conversation so far:
{history_text}

Latest message: {query}

Return ONLY a valid JSON object with these fields — no markdown, no explanation:
{{
  "recipients": ["email@example.com"],
  "subject": "A clear professional subject line",
  "body_html": "<p>Hi,</p><p>Full professional email body in HTML...</p><p>Best regards</p>",
  "ready": true
}}

Rules:
- "recipients": array of email addresses found in the message. Empty array [] if none found.
- "subject": always generate a clear, professional subject even from brief input. Never leave blank.
- "body_html": always compose a complete professional email body in HTML. Use <p>, <ul>/<li>, <strong>, <br>. Include greeting and sign-off. Even from brief input like "about project update", write a full email.
- "ready": true if at least one valid recipient email was found, false otherwise.
- If the user is providing an email address in response to a previous ask, capture it in recipients.
- Output ONLY the JSON object. No other text."""

        raw = self._call_llm(prompt)

        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            raise ValueError(f"LLM did not return valid JSON. Raw: {raw[:200]}")

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM JSON: {e}. Raw: {raw[:200]}")

        recipients = data.get("recipients") or []
        if isinstance(recipients, str):
            recipients = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', recipients)
        else:
            recipients = [r for r in recipients if isinstance(r, str) and re.match(r'[\w.+-]+@[\w-]+\.[\w.-]+', r)]

        return {
            "recipients": recipients,
            "subject": str(data.get("subject") or ""),
            "body_html": str(data.get("body_html") or ""),
            "ready": bool(recipients) and bool(data.get("body_html")),
        }

    def process_query(self, user_input: str, session_id: Optional[str] = None, conversation_history: Optional[List[Dict]] = None) -> Dict[str, Any]:
        thinking_steps: List[Dict] = []
        sid = session_id or "default"
        session = self._get_session(sid)
        session["history"].append({"role": "user", "content": user_input})

        combined_history = (conversation_history or []) + session["history"]

        thinking_steps.append({"type": "thinking", "content": f"Analyzing email request: \"{user_input[:100]}...\""})

        user_lower = user_input.lower().strip()
        if user_lower in ("cancel", "start over", "reset", "new email"):
            self.sessions.pop(sid, None)
            return {"success": True, "response": "Email cancelled. Send me a new email request anytime!", "thinking_steps": thinking_steps, "email_sent": False}

        if session["state"] == "confirming":
            is_declined = any(w in user_lower for w in ["no", "cancel", "don't send", "nah", "stop", "don't", "not yet", "hold", "wait"])
            if is_declined:
                session["state"] = "idle"
                msg = "No problem! Tell me what you'd like to change, or say **cancel** to start over."
                session["history"].append({"role": "assistant", "content": msg})
                return {"success": True, "response": msg, "thinking_steps": thinking_steps, "email_sent": False}

            is_confirmed = any(w in user_lower for w in ["yes", "go ahead", "confirm", "please send", "send it", "shoot", "fire", "do it", "yep", "sure", "ok", "okay"])
            if is_confirmed:
                return self._send_email(session, sid, thinking_steps)

            session["state"] = "idle"

        try:
            thinking_steps.append({"type": "tool_call", "content": "Extracting email details via LLM", "tool_name": "email_composer"})

            direct_emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', user_input)

            payload = self._extract_email_payload(user_input, combined_history)

            if direct_emails and not payload["recipients"]:
                payload["recipients"] = direct_emails

            if payload["recipients"]:
                session["to"] = payload["recipients"]
            if payload["subject"]:
                session["subject"] = payload["subject"]
            if payload["body_html"]:
                session["body"] = payload["body_html"]

            thinking_steps.append({
                "type": "tool_result",
                "content": f"Extracted — To: {', '.join(session['to']) or 'pending'}, Subject: {session['subject'] or 'pending'}",
                "tool_name": "email_composer",
            })

        except Exception as e:
            thinking_steps.append({"type": "tool_result", "content": f"LLM extraction error: {str(e)}", "tool_name": "email_composer"})

            direct_emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', user_input)
            if direct_emails:
                session["to"] = direct_emails

            if not session["to"] and not session["body"]:
                error_msg = "I had trouble understanding your email request. Could you rephrase it? For example:\n\n"
                error_msg += "\"Send an email to john@example.com about the project deadline\""
                session["history"].append({"role": "assistant", "content": error_msg})
                return {"success": False, "response": error_msg, "thinking_steps": thinking_steps, "email_sent": False}

        if not session["to"]:
            session["state"] = "gathering"
            ask_msg = "I've composed the email content. I just need the **recipient email address(es)** to send it.\n\n"
            ask_msg += "Please provide the email address (e.g., john@example.com)."
            thinking_steps.append({"type": "thinking", "content": "Missing recipient — asking user"})
            session["history"].append({"role": "assistant", "content": ask_msg})
            return {"success": True, "response": ask_msg, "thinking_steps": thinking_steps, "email_sent": False}

        if not session["body"]:
            session["state"] = "gathering"
            ask_msg = "I have the recipient but need to know **what you'd like to say**. Please describe the email content."
            session["history"].append({"role": "assistant", "content": ask_msg})
            return {"success": True, "response": ask_msg, "thinking_steps": thinking_steps, "email_sent": False}

        session["state"] = "confirming"
        recipients_display = ", ".join(session["to"])
        body_preview = self._html_to_text_preview(session["body"])

        preview = "Ready to send? Say **yes** to send, or tell me what to change."

        thinking_steps.append({"type": "thinking", "content": "All details ready — showing preview for confirmation"})
        session["history"].append({"role": "assistant", "content": preview})
        return {
            "success": True, "response": preview, "thinking_steps": thinking_steps, "email_sent": False,
            "email_preview": {
                "recipients": session["to"],
                "subject": session["subject"],
                "body": body_preview,
                "status": "preview",
            },
        }

    def _send_email(self, session: Dict, sid: str, thinking_steps: List[Dict]) -> Dict[str, Any]:
        recipients = session.get("to") or []
        subject = session.get("subject") or "(No subject)"
        body = session.get("body") or ""

        if not recipients:
            return {"success": False, "response": "No recipients found. Please provide an email address.", "thinking_steps": thinking_steps, "email_sent": False}

        recipients_display = ", ".join(recipients)
        thinking_steps.append({
            "type": "tool_call",
            "content": f"Sending email to {recipients_display}",
            "tool_name": "email_sender",
        })

        html_content = format_email_html(subject, body)
        result = send_email(recipients=recipients, subject=subject, html_content=html_content)

        if result.get("success"):
            email_id = result.get("email_id", "N/A")
            response_msg = "Email sent successfully! Need to send another? Just ask."

            thinking_steps.append({"type": "tool_result", "content": f"Email delivered (ID: {email_id})", "tool_name": "email_sender"})
            self.sessions.pop(sid, None)
            return {
                "success": True, "response": response_msg, "thinking_steps": thinking_steps,
                "email_sent": True, "email_id": email_id,
                "email_preview": {
                    "recipients": recipients,
                    "subject": subject,
                    "body": self._html_to_text_preview(body),
                    "status": "sent",
                    "email_id": email_id,
                },
            }
        else:
            error = result.get("error", "Unknown error")
            error_msg = f"**Failed to send email:** {error}\n\nPlease check the email configuration and try again."
            thinking_steps.append({"type": "tool_result", "content": f"Send failed: {error}", "tool_name": "email_sender"})
            return {"success": False, "response": error_msg, "thinking_steps": thinking_steps, "email_sent": False}

    def _html_to_text_preview(self, html: str) -> str:
        if not html:
            return ""
        text = re.sub(r'<br\s*/?>', '\n', html)
        text = re.sub(r'<p[^>]*>', '', text)
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'<li[^>]*>', '- ', text)
        text = re.sub(r'</li>', '\n', text)
        text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text)
        text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


email_agent = EmailAgent()
