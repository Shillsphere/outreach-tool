# Outreach Video Tool — Setup Guide

This tool generates a personalized video for each contact in your HubSpot
"Video Outreach Queue" list and sends it via email. Takes ~3-5 min per contact.

---

## Step 1 — Install Claude Code (if not already)

```
npm install -g @anthropic-ai/claude-code
```

Then open this project folder in Claude Code.

---

## Step 2 — Get your API keys

You need 2 things. Both are free.

### A. HubSpot Private App Token
1. Go to HubSpot → Settings (gear icon, top right)
2. Integrations → Private Apps → **Create a private app**
3. Name it anything (e.g. "Outreach Tool")
4. Under Scopes, enable:
   - `crm.objects.contacts.read`
   - `crm.objects.contacts.write`
   - `crm.objects.emails.write`
5. Click Create → copy the token (starts with `pat-na1-...`)

### B. Gmail App Password
(This is how the tool sends emails from your Gmail)
1. Go to myaccount.google.com → Security
2. Make sure 2-Step Verification is ON
3. Search "App Passwords" → select Mail → Generate
4. Copy the 16-character password

---

## Step 3 — Configure your env file

In the project folder, duplicate `.env.template` and rename the copy to `.env`.

Fill in all 7 values:

```
# Parker sends you these 3:
ELEVENLABS_API_KEY=paste-here
SYNC_API_KEY=paste-here
FAL_KEY=paste-here

# You set these up yourself (steps above):
HUBSPOT_TOKEN=paste-your-hubspot-token-here
OUTREACH_FROM_EMAIL=you@gmail.com
OUTREACH_FROM_NAME=Parker
OUTREACH_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

---

## Step 4 — Set up HubSpot

1. In HubSpot, go to **Contacts → Lists**
2. Create a new list called exactly: `Video Outreach Queue`
3. Add contacts to this list whenever you want to send them a video

That list is your queue — add contacts, run the tool, done.

---

## Step 5 — Configure Apollo MCP in Claude Code

If you haven't already, make sure Apollo is connected as an MCP server in Claude Code.
Ask Parker if you're not sure — he'll know if it's set up.

---

## Step 6 — Run it

Open Claude Code in this project folder and type:

```
/outreach
```

Claude will:
1. Check everything is set up
2. Pull contacts from your HubSpot list
3. Use Apollo to find a signal for each person
4. Show you the personalized intro lines to review
5. Wait for your OK before generating anything
6. Generate + send videos one by one
7. Tell you what sent and what failed

### Other commands:
```
/outreach --dry-run       preview scripts only, nothing sent
/outreach --limit 5       test with first 5 contacts
/outreach --contact "Marcus Webb"    run for one person
```

---

## Cost per batch

| Contacts | Cost |
|----------|------|
| 10       | ~$0.90 |
| 50       | ~$4.50 |
| 200      | ~$18.00 |

---

## When the demo clip is added

Parker will drop `clip3.mp4` into this folder when it's ready.
Once it's there, the tool picks it up automatically — no changes needed.

Until then, videos send as: intro + credibility bridge + CTA (~32s).

---

## Troubleshooting

**"HUBSPOT_TOKEN not set"** → Check Step 3, make sure you saved the file

**"Gmail auth failed"** → App password is wrong — regenerate it in Google Account settings

**Sync.so failed on one contact** → Retry with `/outreach --contact "First Last"`

**HubSpot list not found** → List must be named exactly `Video Outreach Queue` (no quotes, exact spacing)
