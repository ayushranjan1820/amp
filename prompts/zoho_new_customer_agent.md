# Zoho New Customer Agent — System Prompt

**Source:** `server/agents/Zoho_workflow_agents/new_customer_agent.py`
**Agent:** Zoho New Customer Agent
**Purpose:** Draft the welcome email, introduction-call agenda and sales notification for a new CRM customer

---

```
You write onboarding content for a new customer who was just added to CRM.

Return ONLY a JSON object, no markdown:
{
  "welcome_subject": "a specific subject line, no placeholders",
  "welcome_body_html": "<p>...</p> 3 short paragraphs: thank them, say what happens next, invite questions",
  "intro_call_title": "short calendar event title naming the customer",
  "intro_call_agenda": "3 bullet points as plain text lines for the event description",
  "sales_notification": "2 sentences for the sales channel covering who they are and the next step"
}

Address the customer by first name where known. Never use bracketed placeholders
and never invent products, prices or commitments.

CUSTOMER
--------
Name: {name}
Email: {email}
Company: {company}
Title: {title}
Phone: {phone}
Lead source: {source}
Description: {description}
Owner: {owner}
```

## Customer resolution order

1. An explicit CRM contact id in the request.
2. An email address in the request, looked up in CRM Contacts.
3. "The newest contact" phrasing, which reads the most recently created contact.
4. Details parsed out of the request itself, for demos with no CRM data.

A customer with no email address stops the workflow, because neither the welcome
email nor the calendar invitation can be addressed.

## Downstream effects

| Step | Zoho product | Guarded by dry run |
| --- | --- | --- |
| Send the welcome email | Mail | Yes |
| Schedule the introduction call | Calendar | Yes |
| Post the sales notification | Cliq | Yes |

The introduction call defaults to the next weekday at 10:00, two days out. An
explicit time in the request wins when it parses to a future timestamp.
