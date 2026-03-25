# /outreach — AI Video Outreach Skill

Generates personalized sales videos for contacts in HubSpot and sends them via email.

Each video = personalized lipsync intro (Parker's voice) + credibility bridge + demo + CTA.
Total runtime per contact: ~3-5 minutes (Sync.so is the bottleneck).

---

## First-Time Setup (do this once)

Before running, make sure these env vars are set in the repo at:
`creative-factory/engine/saas/api/.env`

```
# Already set (from Parker):
ELEVENLABS_API_KEY=...
SYNC_API_KEY=...
FAL_KEY=...

# You need to add these:
HUBSPOT_TOKEN=your_hubspot_private_app_token
OUTREACH_FROM_EMAIL=you@yourdomain.com
OUTREACH_FROM_NAME=Parker          # or "Parker & James" — whatever you want signed
OUTREACH_GMAIL_APP_PASSWORD=your_gmail_app_password
```

**HubSpot Private App token:**
HubSpot → Settings → Integrations → Private Apps → Create app
Required scopes: `crm.objects.contacts.read`, `crm.objects.contacts.write`, `crm.objects.emails.write`

**Gmail App Password:**
Gmail → Google Account → Security → 2-Step Verification → App Passwords
Generate one for "Mail" → copy the 16-char password

**HubSpot setup:**
Create a list in HubSpot called `"Video Outreach Queue"`.
Add contacts to this list when ready to send. The skill pulls from this list.

---

## How to Run

Just type: `/outreach`

Or with options:
- `/outreach --dry-run` — preview scripts without generating or sending
- `/outreach --limit 5` — process only first 5 contacts (good for testing)
- `/outreach --contact "Marcus Webb"` — run for one specific contact by name

---

## What You Do As Claude When This Skill Is Invoked

### Step 1 — Check setup

Read the env file at `creative-factory/engine/saas/api/.env` and verify these vars exist:
- ELEVENLABS_API_KEY
- SYNC_API_KEY
- FAL_KEY
- HUBSPOT_TOKEN
- OUTREACH_FROM_EMAIL
- OUTREACH_GMAIL_APP_PASSWORD

If any are missing, tell the user exactly which ones and what to do. Stop here until fixed.

Also check that `aiautomationvideo/clip1forsync.so.mov`, `clip2.mov`, `clip4.mov` all exist.
If clip3.mp4 is missing, warn the user: "Demo clip not found — videos will be sent without the demo section."

### Step 2 — Pull contacts from HubSpot

Use the HubSpot API to fetch contacts from the "Video Outreach Queue" list.

```
GET https://api.hubapi.com/crm/v3/lists/search
Authorization: Bearer {HUBSPOT_TOKEN}
```

Search for list named "Video Outreach Queue", get its listId, then:

```
GET https://api.hubapi.com/crm/v3/lists/{listId}/memberships
```

For each contact ID, fetch details:
```
GET https://api.hubapi.com/crm/v3/objects/contacts/{contactId}
     ?properties=firstname,lastname,email,company,hs_lead_status
Authorization: Bearer {HUBSPOT_TOKEN}
```

Build a list of contacts: `[{first_name, last_name, email, company, hubspot_contact_id}]`

If the list is empty, tell the user: "No contacts in 'Video Outreach Queue'. Add contacts in HubSpot and re-run."

Show the user the contact list and ask for confirmation before proceeding (unless --dry-run, in which case just show and stop).

### Step 3 — Get Apollo signals

For each contact, use the Apollo MCP tools to find ONE specific, real signal about them or their company. The signal should be concrete and recent — not a generic compliment.

Good signals (in priority order):
1. Recent hiring signal — "saw you're hiring a [title]" (suggests growth/ops pain)
2. Recent news — acquisition, expansion, new location, funding
3. Tech stack — "noticed you're running [ERP name]" (shows research)
4. Company milestone — employee count growth, anniversary, award

Bad signals (do NOT use):
- "love what you're doing" — sounds like mail merge
- "your company looks great" — generic
- "I came across your profile" — lazy

If Apollo has no signal for a contact, use the company industry/size to write a relevant line.
Example fallback: "noticed you're doing distribution at [that scale] — we work with a few companies in that space"

### Step 4 — Write personalized intro lines

Write one intro line per contact. Rules:
- 1 sentence max
- Under 10 words ideally (remember: this is spoken over a 5.2s clip)
- Start with their first name or lead with the signal
- Do NOT say "I love what you're doing" or "We came across your profile"
- Do NOT end with a question — it's a statement, then the video cuts to the bridge

Examples:
- "Marcus — saw Rexel just expanded into the Southeast, congrats on that."
- "Tom — noticed you're hiring a warehouse ops manager right now."
- "Linda — you're on SAP B1, we built specifically for that setup."
- "Dave — saw the Eaton acquisition went through, big move."

Show all generated lines to the user. Ask: "Look good? Type 'yes' to generate or edit any lines first."

Wait for confirmation. If the user edits lines, use the edited versions.

### Step 5 — Generate videos

For each contact, run the pipeline. Process them one at a time (Sync.so is sequential).

For each contact, run:
```bash
cd /path/to/repo && python aiautomationvideo/pipeline.py \
  --first-name "{first_name}" \
  --last-name "{last_name}" \
  --company "{company}" \
  --email "{email}" \
  --intro-line "{intro_line}" \
  --hubspot-id "{hubspot_contact_id}"
```

Show a running count: "Generating 3/12 — Tom Briggs @ Eaton Corp..."

If a contact fails (Sync.so error, email bounce, etc.), log the failure and continue with the next contact. Do not abort the whole batch.

### Step 6 — Report results

When all contacts are processed, show a summary:

```
Outreach complete — 12 contacts

✅ Sent (10):
   Marcus Webb — Rexel USA
   Tom Briggs — Eaton Corp
   ...

❌ Failed (2):
   Linda Park — Graybar (Sync.so timeout — retry with /outreach --contact "Linda Park")
   Dave Chen — Grainger (Email bounce — check address in HubSpot)
```

For failures, give a specific fix action, not just "it failed."

---

## Cost Reference

Per contact:
- ElevenLabs TTS: ~$0.02
- Sync.so lipsync: ~$0.07
- fal.ai upload: ~$0.00
- Total: ~$0.09/contact

Batch of 50: ~$4.50
Batch of 200: ~$18.00

---

## Common Issues

**"Sync.so FAILED"** — Usually a video format issue. The clip1 conversion step handles most cases.
Retry once. If it fails again, skip that contact and note it.

**"ELEVENLABS_API_KEY not set"** — Env file not loaded. Check the path to the .env file.

**"clip3 not found"** — Demo video hasn't been dropped in yet. Videos send without the demo section.
Tell the user to drop `clip3.mp4` into `aiautomationvideo/` and re-run for missed contacts.

**Gmail auth failed** — App password is wrong or 2FA isn't enabled on the Gmail account.
User needs to go to: Google Account → Security → App Passwords.

**HubSpot list not found** — The list must be named exactly `"Video Outreach Queue"` in HubSpot.
