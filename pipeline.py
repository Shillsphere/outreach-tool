#!/usr/bin/env python3
"""
AI Outreach Video Pipeline
Generates personalized sales videos and sends via email.

Each video:
  clip1 (lipsync canvas, 5.2s) → ElevenLabs TTS → Sync.so → synced_intro.mp4
  + clip2.mov (bridge/credibility, 16.9s)
  + clip3.mp4 (demo screen recording — drop in folder when ready)
  + clip4.mov (CTA, 10.1s)
  → final.mp4 (~58s) → fal.ai upload → HubSpot email

Called by the /outreach Claude Code skill. Can also be run directly.

Usage:
  python pipeline.py \
    --first-name Marcus --last-name Webb \
    --company "Rexel USA" \
    --email mwebb@rexel.com \
    --intro-line "saw Rexel just expanded into the Southeast — congrats on that" \
    --hubspot-id 12345
"""

import os
import sys
import json
import asyncio
import argparse
import subprocess
import smtplib
import re
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx

# ── Configuration — update these ──────────────────────────────────────────────

VOICE_ID       = "Y9HJE3fwnnAzKFcfaWSZ"   # Parker's ElevenLabs voice clone
CHYRON_TEXT    = "Parker & James"          # TODO: update partner's first name

BASE_DIR    = Path(__file__).parent
CLIP1       = BASE_DIR / "clip1forsync.so.mov"   # Sync.so canvas (5.2s)
CLIP2       = BASE_DIR / "clip2.mov"              # Bridge (16.9s)
CLIP3       = BASE_DIR / "clip3.mp4"             # Demo — drop in when ready
CLIP4       = BASE_DIR / "clip4.mov"              # CTA (10.1s)
OUTPUT_DIR  = BASE_DIR / "output"

PROJECT_ROOT = BASE_DIR

# ── Env Loading ───────────────────────────────────────────────────────────────

def load_env():
    for path in [
        PROJECT_ROOT / ".env",
    ]:
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    if key and key not in os.environ:
                        os.environ[key] = value.strip()

load_env()

def require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        print(f"\n❌ Missing env var: {key}", file=sys.stderr)
        print(f"   Add it to: .env in the project folder", file=sys.stderr)
        sys.exit(1)
    return val


# ── Stage 1: Convert clip1 to MP4 (Sync.so needs H264) ───────────────────────

def prepare_clip1(work_dir: Path) -> Path:
    """Convert clip1.mov to H264 MP4 for Sync.so compatibility."""
    out = work_dir / "clip1_prepared.mp4"
    if out.exists():
        return out
    subprocess.run([
        "ffmpeg", "-y", "-i", str(CLIP1),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-ar", "44100",
        str(out),
    ], check=True, capture_output=True)
    return out


# ── Stage 2: ElevenLabs TTS ───────────────────────────────────────────────────

async def generate_tts(script: str, output_path: Path) -> Path:
    """Generate personalized intro audio via ElevenLabs voice clone."""
    api_key = require_env("ELEVENLABS_API_KEY")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": script,
                "model_id": "eleven_turbo_v2",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.85},
            },
        )
        resp.raise_for_status()

    output_path.write_bytes(resp.content)
    size_kb = len(resp.content) // 1024

    # Warn if audio is likely longer than clip1 (5.2s ≈ ~80KB for speech)
    if size_kb > 100:
        print(f"  [TTS] ⚠ Audio is {size_kb}KB — intro line may be too long, Sync.so will cut off")
    else:
        print(f"  [TTS] Generated: {output_path.name} ({size_kb}KB)")

    return output_path


# ── Stage 3: Upload to fal.ai ─────────────────────────────────────────────────

async def upload_to_fal(file_path: Path, content_type: str) -> str:
    """Upload file to fal.ai storage, return public URL."""
    fal_key = require_env("FAL_KEY")

    async with httpx.AsyncClient(timeout=180) as client:
        init = await client.post(
            "https://rest.alpha.fal.ai/storage/upload/initiate",
            headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
            json={"file_name": file_path.name, "content_type": content_type},
        )
        init.raise_for_status()
        data = init.json()

        with open(file_path, "rb") as f:
            put = await client.put(
                data["upload_url"],
                content=f.read(),
                headers={"Content-Type": content_type},
            )
        if put.status_code not in (200, 201):
            raise RuntimeError(f"fal.ai upload failed: {put.status_code}")

    url = data["file_url"]
    print(f"  [FAL] {file_path.name} → uploaded")
    return url


# ── Stage 4: Sync.so Lipsync ──────────────────────────────────────────────────

async def syncso_lipsync(video_url: str, audio_url: str, output_path: Path) -> Path:
    """Lipsync audio onto clip1 via Sync.so. Polls until complete."""
    sync_key = require_env("SYNC_API_KEY")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        create = await client.post(
            "https://api.sync.so/v2/generate",
            headers={"x-api-key": sync_key, "Content-Type": "application/json"},
            json={
                "model": "lipsync-2",
                "input": [
                    {"type": "video", "url": video_url},
                    {"type": "audio", "url": audio_url},
                ],
                "options": {"sync_mode": "cut_off"},
            },
        )
        if create.status_code not in (200, 201):
            raise RuntimeError(f"Sync.so create failed: {create.status_code} {create.text[:300]}")

        gen_id = create.json().get("id")
        print(f"  [SYNC] Job {gen_id} — polling every 10s...")

        while True:
            await asyncio.sleep(10)
            poll = await client.get(
                f"https://api.sync.so/v2/generate/{gen_id}",
                headers={"x-api-key": sync_key},
            )
            data = poll.json()
            status = data.get("status", "")
            print(f"  [SYNC] {status}")

            if status == "COMPLETED":
                synced_url = data.get("outputUrl")
                if not synced_url:
                    raise RuntimeError("Sync.so completed but no outputUrl")
                dl_resp = await client.get(synced_url, follow_redirects=True)
                output_path.write_bytes(dl_resp.content)
                print(f"  [SYNC] Done → {output_path.name}")
                return output_path

            elif status in ("FAILED", "REJECTED"):
                raise RuntimeError(f"Sync.so {status}: {data.get('error', '')}")


# ── Stage 5: FFmpeg Concat + Loudnorm ─────────────────────────────────────────

def concat_and_normalize(intro_path: Path, work_dir: Path, output_path: Path) -> Path:
    """
    Concat: synced_intro + clip2 + [clip3 if exists] + clip4
    Scale all to 720x1280, re-encode to H264/AAC, then loudnorm to -14 LUFS.
    """
    clips_to_join = [intro_path, CLIP2]

    if CLIP3.exists():
        clips_to_join.append(CLIP3)
        print("  [CONCAT] clip3 (demo) included ✅")
    else:
        print("  [CONCAT] ⚠ clip3 not found — sending without demo section")

    clips_to_join.append(CLIP4)

    tmpdir = work_dir / "tmp"
    tmpdir.mkdir(exist_ok=True)

    # Re-encode each to 720x1280 H264/AAC
    encoded = []
    for i, clip in enumerate(clips_to_join):
        out = tmpdir / f"seg_{i:02d}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(clip),
            "-vf", "scale=720:1280:force_original_aspect_ratio=decrease,"
                   "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            str(out),
        ], check=True, capture_output=True)
        encoded.append(out)

    # Concat list
    concat_list = tmpdir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p}'" for p in encoded))

    concat_raw = tmpdir / "concat_raw.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list), "-c", "copy", str(concat_raw),
    ], check=True, capture_output=True)

    # Loudnorm — pass 1: analyze
    pass1 = subprocess.run([
        "ffmpeg", "-i", str(concat_raw),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ], capture_output=True, text=True)

    stats_match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', pass1.stderr, re.DOTALL)
    if stats_match:
        s = json.loads(stats_match.group())
        ln = (f"loudnorm=I=-14:TP=-1.5:LRA=11"
              f":measured_I={s['input_i']}:measured_LRA={s['input_lra']}"
              f":measured_TP={s['input_tp']}:measured_thresh={s['input_thresh']}"
              f":offset={s['target_offset']}:linear=true")
    else:
        ln = "loudnorm=I=-14:TP=-1.5:LRA=11"

    # Pass 2: apply
    subprocess.run([
        "ffmpeg", "-y", "-i", str(concat_raw),
        "-af", ln, "-c:v", "copy", "-c:a", "aac", "-ar", "44100",
        str(output_path),
    ], check=True, capture_output=True)

    mb = output_path.stat().st_size // 1024 // 1024
    print(f"  [FFMPEG] Final: {output_path.name} ({mb}MB)")
    return output_path


# ── Stage 6: Thumbnail ────────────────────────────────────────────────────────

def extract_thumbnail(video_path: Path) -> Path:
    """Extract frame at 7s (start of bridge section) as email thumbnail."""
    thumb = video_path.with_suffix(".jpg")
    subprocess.run([
        "ffmpeg", "-y", "-ss", "7", "-i", str(video_path),
        "-vframes", "1", "-q:v", "2", str(thumb),
    ], check=True, capture_output=True)
    print(f"  [THUMB] {thumb.name}")
    return thumb


# ── Stage 7: Send Email ───────────────────────────────────────────────────────

EMAIL_HTML = """\
<div style="font-family:Arial,sans-serif;font-size:15px;color:#222;max-width:560px;line-height:1.6;">
  <p>Hi {first_name},</p>
  <p>
    <a href="{video_url}" style="display:block;text-decoration:none;">
      <img src="{thumbnail_url}" width="560"
           style="display:block;border-radius:8px;border:1px solid #ddd;">
    </a>
    <a href="{video_url}"
       style="display:block;text-align:center;margin:8px 0 20px;color:#666;
              font-size:13px;text-decoration:none;">
      &#9654; Watch (0:58)
    </a>
  </p>
  <p>
    We just finished an automation for an electrical distributor similar to {company}
    — it handles their entire PO intake workflow automatically.
    Saving them about 14 hours a week.
  </p>
  <p>
    Recorded a quick 58-second breakdown showing exactly what we built.
    If it looks relevant, just reply and I'll put together a breakdown
    of what we'd automate first for you.
  </p>
  <p>{sender_name}</p>
</div>
"""


def send_email(contact: dict, video_url: str, thumbnail_url: str) -> None:
    """Send via Gmail SMTP. Requires OUTREACH_FROM_EMAIL + OUTREACH_GMAIL_APP_PASSWORD."""
    from_email    = require_env("OUTREACH_FROM_EMAIL")
    from_name     = os.environ.get("OUTREACH_FROM_NAME", "Parker")
    app_password  = require_env("OUTREACH_GMAIL_APP_PASSWORD")

    subject = f"quick video for {contact['company']} — ERP automation"
    html    = EMAIL_HTML.format(
        first_name    = contact["first_name"],
        company       = contact["company"],
        video_url     = video_url,
        thumbnail_url = thumbnail_url,
        sender_name   = from_name,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{from_name} <{from_email}>"
    msg["To"]      = contact["email"]
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(from_email, app_password)
        smtp.sendmail(from_email, contact["email"], msg.as_string())

    print(f"  [EMAIL] Sent → {contact['email']}")


# ── Stage 8: Log to HubSpot ───────────────────────────────────────────────────

def log_to_hubspot(contact: dict, video_url: str) -> None:
    """Log sent email as an engagement on the HubSpot contact record."""
    token      = os.environ.get("HUBSPOT_TOKEN")
    contact_id = contact.get("hubspot_contact_id")

    if not token or not contact_id:
        print("  [HUBSPOT] Skipped — no token or contact ID")
        return

    subject = f"quick video for {contact['company']} — ERP automation"
    body = {
        "properties": {
            "hs_timestamp":      str(int(time.time() * 1000)),
            "hs_email_direction": "EMAIL",
            "hs_email_status":   "SENT",
            "hs_email_subject":  subject,
            "hs_email_text":     f"Personalized video sent: {video_url}",
        },
        "associations": [{
            "to": {"id": contact_id},
            "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 9}],
        }],
    }

    resp = httpx.post(
        "https://api.hubapi.com/crm/v3/objects/emails",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )

    if resp.status_code in (200, 201):
        print(f"  [HUBSPOT] Logged to contact {contact_id}")
    else:
        print(f"  [HUBSPOT] Log failed: {resp.status_code} {resp.text[:150]}")


# ── Full Pipeline ─────────────────────────────────────────────────────────────

async def process_contact(contact: dict) -> dict:
    """
    Run the full pipeline for one contact.

    Required keys: first_name, company, email, intro_line
    Optional keys: last_name, hubspot_contact_id
    """
    first_name = contact["first_name"]
    company    = contact["company"]
    slug       = f"{company.lower().replace(' ', '_')}_{first_name.lower()}"

    print(f"\n{'='*60}")
    print(f"  {first_name} — {company}")
    print(f"  Intro: \"{contact['intro_line']}\"")
    print(f"{'='*60}")

    work_dir = OUTPUT_DIR / slug
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Convert clip1 to MP4 for Sync.so
        clip1_mp4 = prepare_clip1(work_dir)

        # TTS
        audio_path = work_dir / "intro_audio.mp3"
        await generate_tts(contact["intro_line"], audio_path)

        # Upload clip1 + audio in parallel
        print("  [FAL] Uploading clip1 + audio...")
        clip1_url, audio_url = await asyncio.gather(
            upload_to_fal(clip1_mp4, "video/mp4"),
            upload_to_fal(audio_path, "audio/mpeg"),
        )

        # Lipsync
        intro_synced = work_dir / "intro_synced.mp4"
        await syncso_lipsync(clip1_url, audio_url, intro_synced)

        # Concat + normalize
        final_path = work_dir / "final.mp4"
        concat_and_normalize(intro_synced, work_dir, final_path)

        # Thumbnail
        thumb_path = extract_thumbnail(final_path)

        # Upload final video + thumbnail in parallel
        print("  [FAL] Uploading final video + thumbnail...")
        video_url, thumbnail_url = await asyncio.gather(
            upload_to_fal(final_path, "video/mp4"),
            upload_to_fal(thumb_path, "image/jpeg"),
        )

        # Send email
        send_email(contact, video_url, thumbnail_url)

        # Log to HubSpot
        log_to_hubspot(contact, video_url)

        print(f"\n  ✅ {first_name} @ {company}")
        print(f"     {video_url}")
        return {"status": "success", "video_url": video_url, "contact": contact}

    except Exception as e:
        print(f"\n  ❌ Failed: {e}")
        return {"status": "failed", "error": str(e), "contact": contact}


# ── CLI ───────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-name",    required=True)
    parser.add_argument("--last-name",     default="")
    parser.add_argument("--company",       required=True)
    parser.add_argument("--email",         required=True)
    parser.add_argument("--intro-line",    required=True,
                        help="Personalized 1-sentence intro (spoken by lipsync)")
    parser.add_argument("--hubspot-id",    default="",
                        help="HubSpot contact ID for activity logging")
    args = parser.parse_args()

    contact = {
        "first_name":         args.first_name,
        "last_name":          args.last_name,
        "company":            args.company,
        "email":              args.email,
        "intro_line":         args.intro_line,
        "hubspot_contact_id": args.hubspot_id,
    }

    result = await process_contact(contact)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
