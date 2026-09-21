# Zoho Workflow Agents

Three marketplace catalog agents over one shared Zoho integration package.

| Agent | Catalog id | Endpoint | Workflow |
| --- | --- | --- | --- |
| Zoho Email Meeting Agent | `zoho_email_meeting_agent` | `POST /api/zoho-email-meeting-agent` | Meeting-request email to calendar event, confirmation email, Projects task |
| Zoho Support Ticket Agent | `zoho_support_ticket_agent` | `POST /api/zoho-support-ticket-agent` | High-priority Desk ticket to private Desk note, Projects task, ticket reply |
| Zoho New Customer Agent | `zoho_new_customer_agent` | `POST /api/zoho-new-customer-agent` | Supplied customer details to welcome email, intro call, Desk follow-up ticket |

These three workflows require no CRM access. The general Agent Builder's CRM tool
is a separate optional integration, not a dependency of these catalog agents.

## Transports

Two ways to reach Zoho. The services expose the same methods for both, so the
three agents are transport-agnostic and need no changes either way.

| | MCP connection (recommended) | Direct REST |
| --- | --- | --- |
| Authentication | `ZOHO_MCP_URL` | `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_DC` |
| Routing | Calendar UID, Projects IDs, sender and Desk department as applicable | Same routing values |
| Authorization | Held by the connection, shared by all users | Per-deployment OAuth refresh token |
| Desk org id | Not needed | `ZOHO_ORG_ID` required |
| Selected when | `ZOHO_MCP_URL` is set | Otherwise |

Force one with `ZOHO_BACKEND=mcp` or `ZOHO_BACKEND=rest`.

### What the MCP connection must publish

The agents need these capabilities. Tool *names* differ per connection, so they
are resolved at runtime from `tools/list` rather than hard-coded, and arguments
are bound to each tool's own `inputSchema`.

| Capability | Zoho service | Needed by |
| --- | --- | --- |
| Send an email | Mail | Email Meeting (required), New Customer (required) |
| List / search messages | Mail | Email Meeting (optional, for mailbox reads) |
| Read one message | Mail | Email Meeting (optional, for mailbox reads) |
| Create an event | Calendar | Email Meeting (required), New Customer (required) |
| List events | Calendar | optional |
| Discover mail accounts | Mail | Mail sender/account selection |
| Create a task | Projects | Email Meeting and Support Ticket (required) |
| Read a ticket | Desk | Support Ticket (required for live runs) |
| List tickets | Desk | Support Ticket (optional, for Desk reads) |
| Send a ticket reply | Desk | Support Ticket (required) |
| Add a private ticket comment | Desk | Support Ticket (required) |
| Create a ticket with contact details | Desk | New Customer (required) |

So the minimum to add in the Zoho MCP console is **Mail, Calendar, Projects,
Desk**. Cliq is not required. Onboarding preflights ticket-creation capability
before any writes. Other write failures are reported per action; subsequent
actions may still run. Earlier writes are not rolled back, and any failed
action makes the overall Support or New Customer result unsuccessful.

Check any connection, before running an agent:

```bash
cd server
python -m agents.Zoho_workflow_agents.discover_mcp --schemas
```

It lists published tools with their argument names, then shows, per agent, which
capabilities resolve and which are missing. If auto-resolution picks the wrong
tool, pin it: `ZOHO_MCP_TOOL_MAIL_SEND=<exact tool name>`. The command prints
every override key.

### Audited connection

The read-only connection audit found the following tools already enabled:

| Workflow | Already enabled tools used by the workflow |
| --- | --- |
| Meeting | `ZohoCalendar_add_event`, `ZohoMail_sendEmail`, `ZohoMail_getMailAccounts`, `ZohoProjects_create_a_task` |
| Support | `ZohoDesk_getTicket`, ticket list/search tools, `ZohoDesk_sendReply`, `ZohoDesk_createTicketComment`, `ZohoProjects_create_a_task` |
| New Customer | `ZohoMail_sendEmail`, `ZohoMail_getMailAccounts`, `ZohoCalendar_add_event`, `ZohoDesk_createTicket` |

Also published: `ZohoDesk_createTicketComment`, `ZohoDesk_searchTickets`,
`ZohoDesk_getTickets`, `ZohoDesk_listOfTickets`, and Cliq user/bot/chat tools.
They need not be removed, but these workflows do not need the Cliq alternatives.

The audited connection now publishes `ZohoMail_listEmails` and
`ZohoMail_getMessageContent`. The Meeting mailbox path was verified live with a
controlled self-email. The adapter supplies the required list `fields` and
preserves sender/subject metadata when content-only responses omit it. Verify
these tool schemas separately for other connections; listing does not currently
provide free-text mailbox search.

For setup, optionally enable Projects **Get Portals** and **Get Projects List**,
Calendar **List Calendars**, and Mail **Get All Folders / Get Email Metadata** as
needed. These are discovery aids, not automatic provisioning by the workflows.
No CRM tools need to be enabled. Discovery confirms tool availability, not write
permission or successful delivery.

## Layout

```
config.py          Transport choice, data-center resolution, settings, dry-run flags
zoho_auth.py       REST: refresh-token grant, authorize URL, code exchange
zoho_client.py     REST: authenticated async HTTP client, 401 retry, error normalization
zoho_mcp.py        MCP: JSON-RPC client, capability resolution, schema-driven arg binding
discover_mcp.py    CLI: what a connection publishes and how it maps
services/          One typed wrapper per product, REST and MCP, same methods
base_workflow.py   Shared orchestration: write gate, LLM extraction, response envelope
email_meeting_agent.py | support_ticket_agent.py | new_customer_agent.py
tests/             Unit tests against mocked Zoho REST and MCP transports (no network)
```

Agents never call `httpx` directly. They go through a service, which goes through
`ZohoClient` (REST) or `ZohoMCPClient` (MCP). That is what lets one set of agents
serve both transports, and what makes the tests able to run a whole workflow
against a stub of either.

## Writes are off by default

Every create, send and reply passes through `guarded_write`. While dry run is on
it is described, not executed, and the run reports exactly what it would have
called. Two flags gate real writes, and **both** are required:

```
ZOHO_DRY_RUN=false
ZOHO_CONFIRM_WRITES=true
```

Setting only `ZOHO_DRY_RUN=false` keeps the agent in dry run. This is deliberate:
these workflows send mail to customers and create live calendar events and tasks.

Live New Customer runs require `ZOHO_DESK_DEPARTMENT_ID` before the first write,
plus `desk.create_ticket` capability for MCP or `ZOHO_ORG_ID` for REST. The Desk
ticket uses an inline contact email: Desk reuses the matching contact or creates
one according to portal permissions. This is a follow-up record, not a delivered
team chat notification. Desk's own ticket notification rules may still apply.
Preflight does not establish write permissions or prevent other partial failures.

Live Support runs require a real Desk ticket record, customer email and
`ZOHO_FROM_ADDRESS` before any writes. Use an authorized sender from Desk's reply
composer, which may differ from the connected Mail address. The escalation
comment is explicitly private (`isPublic=false`). MCP ticket reads omit the
optional `include` parameter because the audited endpoint rejected `contacts`.

## Setup, MCP

1. In the Zoho MCP console create a connection and enable **Authorization via
   Connection**, so tool executions for all users go through that single
   authorization.
2. Add the Zoho services listed above to the connection: Mail, Calendar, Projects,
   Desk. A connection with no services publishes no tools, and every
   workflow step will report that.
3. Copy the connection URL ending in `/message` into `ZOHO_MCP_URL`. Treat it as
   a credential: it embeds the connection key, so keep it in `server/.env` or the
   agent's configuration panel, never in a tracked file.
4. Run the discovery command above and confirm every required capability resolves.

No separate OAuth client id, secret or refresh token is needed for this
pre-authorized connection. Authorization does not select destinations; provide
the routing settings below. If a different connection exposes a required Desk
orgId without supplying it, configure that value in its tool connection.

### Create prerequisites and provide routing values

Use a test mailbox, test project, Desk department and controlled recipients first.
The Zoho user authorizing the connection must have access to each destination.

| Setting | How to obtain it | Used by |
| --- | --- | --- |
| `ZOHO_BACKEND=mcp` | Choose MCP in the agent configuration | All |
| `ZOHO_MCP_URL` | Copy the authorized server connection URL ending in `/message`; enter privately | All |
| `ZOHO_PROJECTS_PORTAL_ID` | Create/join a Projects portal; run Get Portals and copy its numeric `id` or `id_string`, not its name | Meeting, Support |
| `ZOHO_PROJECTS_PROJECT_ID` | Create a test project in that portal; run Get Projects List for that portal and copy its numeric ID; allow task creation | Meeting, Support |
| `ZOHO_CALENDAR_ID` | Create/select an editable calendar; use its details or List Calendars to copy the calendar UID, not the title | Meeting, New Customer |
| `ZOHO_FROM_ADDRESS` | Meeting/New Customer: connected Mail sender. Support: authorized From address in the Desk reply composer | All |
| `ZOHO_DESK_DEPARTMENT_ID` | Copy the numeric ID of an accessible Desk department; allow ticket/contact creation | New Customer; optional list filter for Support |
| `ZOHO_TIMEZONE` | Set an IANA timezone such as `Asia/Kolkata` | All |
| LLM provider settings | Select the platform's supported provider and enter its credentials privately in configuration | Drafting and extraction |

For Projects, an administrator can also discover IDs with the read-only REST
endpoints `/restapi/portals/` and `/restapi/portal/{portal_id}/projects/` using
appropriate read scopes. Do not substitute sample IDs or create a CRM account.
Set an explicit Calendar UID when selecting a particular calendar. Omitting it
was verified to create an event in this MCP connection's default calendar.
For Support's live-ticket path, create a test Desk ticket with a controlled
customer email and ensure the connection can read and reply to that ticket.

Save settings separately for each agent. Safety and routing fields apply to
both transports; REST credentials are hidden when MCP is selected. Keep the
MCP URL and provider keys out of prompts, screenshots, source control and logs.

### End-to-end UI run

1. Open one of the three Zoho agents and save its configuration above with
   `ZOHO_DRY_RUN=true` and `ZOHO_CONFIRM_WRITES=false`.
2. Click one of its three sample prompts. This fills the editable input; it
   does not submit. Replace all `example.com` addresses with controlled inboxes
   before a live run. Adjust customer details and meeting time.
3. Submit the sample and inspect the plan, recipients, event time/timezone,
   Desk department and task destination. Dry run skips writes; it does not validate
   every write tool's permissions, required arguments or delivery behavior.
4. When the plan is correct, save `ZOHO_DRY_RUN=false` and
   `ZOHO_CONFIRM_WRITES=true`, then submit once. These flags, not the word
   "preview" in a prompt, control whether writes are allowed.
5. Check each step's result and verify the records in Zoho. Meeting should
   create an event, send confirmation and create a Projects task. Support
   escalations should add a private Desk note, create a Projects task and send a
   Desk acknowledgement. New Customer should send welcome mail, schedule an intro
   and create a Desk onboarding follow-up ticket.
6. Keep live mode enabled only for an approved, configured workflow. Otherwise
   restore dry run. Partial successes are not rolled back, and repeating a live
   request can create duplicates. Retry only after checking which actions already
   succeeded.

Pasted support details without a real Desk ticket ID are rejected in live mode
before any writes. Low-priority tickets do not escalate.
For an actual ticket, verify its reply thread and outbound delivery: the audited
MCP sendReply schema defaults `sendImmediately` to false; the adapter explicitly
sets it to true for approved live replies. Do not treat a successful call as proof of email
delivery. Intro calls use the configured scheduling defaults; inspect their time
in the preview. These agents run on chat/API invocation, not background triggers.

### Live verification, 2026-09-14

All three agents executed their live workflows through the application UI using
the configured PwC GenAI provider and controlled self-test mailbox. New Customer
exposed a scheduling defect, corrected as described below. Meeting evidence:

| Independently verified record | Evidence |
| --- | --- |
| Source self-email | `E2E LIVE 20260914-0910 Meeting`, message `1789376655086114800` |
| Calendar event | Same title, 2026-09-15 15:00-15:30 Asia/Kolkata, event `5502591000000003001`; visible in Calendar |
| Delivered confirmation | `Confirmed: E2E LIVE 20260914-0910 Meeting`, message `1789376851383114800`; opened in recipient inbox |
| Projects follow-up | `E2E LIVE 20260914-0910 Prepare agenda`, task `475210000000079172`; visible in Agent Marketplace project |

The live confirmation exposed an inaccurate attachment claim when no location
was supplied. The template is now corrected and regression-tested; the already
delivered test email retains the original wording. No duplicate run was sent.

Support and New Customer use Desk instead of Cliq. `ZohoDesk_createTicket` is now
enabled. Department `276454000000010772` accepted an inline email-only contact
for onboarding and reused the controlled contact. The sample Desk ticket #100
was not modified.

| Independently verified Support record | Evidence |
| --- | --- |
| Controlled High-priority fixture | `E2E LIVE 20260914-1010 Support`, ticket #101, `276454000000387040` |
| Private escalation note | Comment `276454000000390001`; Desk displays Private |
| Projects follow-up | Task `475210000000081004`, displayed as AM1-T6 |
| Desk acknowledgement | Thread `276454000000391001`; email `Re:[## 101 ##] E2E LIVE 20260914-1010 Support` visible in recipient inbox from `support@pwcet.zohodesk.in` |

The first Support attempt failed on the initial read with an invalid `include`
argument and made no writes. Removing that optional argument allowed the second
attempt to complete. Sender preflight and MCP argument binding are regression-tested.

| Independently verified New Customer record | Evidence |
| --- | --- |
| Welcome email | `Welcome to E2E LIVE 20260914-1045 Customer!`, visible in recipient inbox |
| Introduction event | `5502591000000004001`, `Introduction to E2E LIVE 20260914-1045 Customer`, visible in Calendar |
| Desk follow-up | Ticket #102, `276454000000392001`, `Onboarding follow-up: E2E LIVE 20260914-1045 Customer` |

The onboarding run initially scheduled 10:00 rather than the requested 15:00.
The resolver now recognizes explicit `YYYY-MM-DD at HH:MM`, space-separated and
ISO `T` date/time forms before the fallback; regression tests cover all three.
The existing event was edited in place to 2026-09-16 15:00-15:30 Asia/Kolkata and
verified in Calendar. A private correction note on #102 supersedes the original
description's 10:00 time. No duplicate onboarding run was submitted after the fix.
Calendar creation was verified; separate attendee-invitation delivery was not.

The three browser agent configurations are approved for live writes; global
defaults remain protected. These live checks cover MCP, while REST is covered
by mocked regression tests rather than live execution.

### Account readiness

A signed-in Projects account does not guarantee a provisioned Mail mailbox.
If Mail opens the Create Mail Account page and MCP `ZohoMail_getMailAccounts`
returns an internal error, complete the intended mailbox setup or reconnect MCP
to an existing mailbox account, then repeat the read-only account check. Do not
test sending email to diagnose this error. Select the intended Desk department
and verify Desk tool access before enabling live workflows.

Projects browser URLs may contain a portal name rather than its numeric ID.
Use Get Portals discovery or inspect the numeric `/portal/{id}` segment of
authenticated Projects network requests. Do not copy session cookies or tokens.

### Application dependencies

No new library is required for these UI/catalog changes. For a fresh Windows
installation, install Python 3.11-3.13 and a current Node.js LTS compatible with
Vite (22.12+), then run `setup.bat --skip-browsers` from the repository root.
It installs the existing backend/frontend dependencies; Chromium is not needed
for these Zoho workflows. Configure the platform's MongoDB connection
`CORE_SYSTEM_MONGO_DB` and chosen LLM provider privately, then run `start.bat`.
Existing installations do not need setup repeated just to change Zoho settings.

## Setup, direct REST

1. Create an app at <https://api-console.zoho.com>. A **Self Client** is enough
   for a demo; use **Server-based** for a deployment with a redirect URI.
2. Grant only the product scopes your workflow needs. Do not use the legacy
   `config.all_scopes()` union for a CRM-free account:
   - Mail: `ZohoMail.messages.ALL`, `ZohoMail.accounts.READ`, `ZohoMail.folders.READ`
   - Calendar: `ZohoCalendar.event.ALL`, `ZohoCalendar.calendar.READ`
   - Projects: `ZohoProjects.tasks.CREATE`; for ID discovery only, `ZohoProjects.portals.READ`, `ZohoProjects.projects.READ`
   - Desk: `Desk.tickets.READ`, `Desk.tickets.UPDATE`, `Desk.tickets.CREATE`, `Desk.contacts.READ`, `Desk.contacts.WRITE`, `Desk.basic.READ`
3. Generate a refresh token with `access_type=offline`. It is long lived; the
   hourly access token is refreshed automatically and written back to the
   environment for the rest of the request.
4. Set `ZOHO_DC` to your account region: `us`, `eu`, `in`, `au`, `jp`, `ca`,
   `cn` or `sa`. Zoho serves every product from region-specific hosts, so a
   mismatch shows up as 404s rather than auth errors. `ZOHO_ACCOUNTS_BASE_URL`
   overrides the accounts host directly if you need to.
5. For the support workflow, set `ZOHO_ORG_ID` (Desk → Setup → Developer Space →
   API). Desk answers 404 without it.

Credentials can live in `server/.env` or be entered per agent in the marketplace
configuration panel. The panel is the better choice for multi-tenant use, since
the marketplace injects them into the environment only for that request.

### Desk follow-up setup

New Customer requires `ZOHO_DESK_DEPARTMENT_ID` for either transport, plus
`ZOHO_ORG_ID` for REST. No Cliq channel, webhook or organization setup is needed.
Enable the Desk create-ticket tool with inline `contact` support for MCP.

## Making the agents appear in the catalog

The catalog lives in MongoDB; `agents_catalog.json` only seeds it on first run.
After pulling these changes, merge the three agents into the live catalog:

```bash
cd server
python sync_catalog_agents.py zoho_email_meeting_agent \
    zoho_support_ticket_agent zoho_new_customer_agent
```

That replaces only those three records, including any admin edits to them;
other agents are left alone. Add `--dry-run` first to see what would change,
then re-run without it. Restart a separately running backend after the sync
and refresh the browser. Old CRM fields or old samples indicate a stale live
catalog or client cache; editing the JSON alone does not update an existing DB.

Use this script rather than `seed_catalog.py`. There are two catalog documents in
this codebase and they are not the same one:

| | Served by `/api/agents` | Legacy |
| --- | --- | --- |
| Module | `agents_catalog_db` | `catalog_store`, `seed_catalog.py` |
| URI env | `CORE_SYSTEM_MONGO_DB` | `MONGODB_URI` |
| Database | `core_system` | `agents_platform` |
| Document | `_id: "main"` | `_id: "default"` |

`sync_catalog_agents.py` writes to the first one. Seeding the second changes
nothing that the marketplace displays.

## Demo script

Run with `ZOHO_DRY_RUN=true` for the first pass. Each agent reports the full plan
with a status line per step, so the demo shows the whole workflow without
touching a customer.

**Email to meeting.** Paste a request into the chat:

```
From: Priya Sharma <priya@example.com>
Subject: Can we meet about the data migration?

Could we get 45 minutes next Tuesday at 3pm to walk through the migration plan?
```

Or, with a connected mailbox: `Process my latest email about a meeting and book it`.

**Support ticket triage.** `Triage the latest high priority ticket in Zoho Desk`,
or paste a ticket:

```
Subject: Production outage on checkout
Priority: Urgent
Customer: Asha Rao
Email: asha@example.com

Checkout has been down since 09:00 for every customer.
```

A ticket below High priority returns a short "no action taken" explanation, which
is worth showing too.

**New customer onboarding.** Supply details directly; there is no contact lookup:

```text
Name: Ira Bose
Email: ira@example.com
Company: Example Manufacturing
Title: Operations Manager
Source: Website

Send a welcome email, schedule an introduction call and notify the sales channel.
```

## Tests

```bash
cd server
python -m pytest agents/Zoho_workflow_agents/tests -q
```

No network access is used. `tests/conftest.py` provides a mocked Zoho transport
that records every request, so assertions cover the exact payloads sent to each
product API, the dry-run gate, token refresh and the 401 retry.

## Reuse from custom agents

The same services back five Agent Builder tools: `tool_zoho_mail`,
`tool_zoho_calendar`, `tool_zoho_crm`, `tool_zoho_desk` and `tool_zoho_cliq`.
They are action-based, read the same `ZOHO_*` keys, and respect `ZOHO_DRY_RUN`,
so a custom agent behaves like these three.

## Not included

Production event triggers. These agents run on chat or HTTP invocation, not on
Zoho webhooks. Adding real triggers means a webhook endpoint per product, event
persistence, and idempotency keyed on the Zoho event, thread, ticket or contact
id so a retry cannot send a second email or create a duplicate task.
