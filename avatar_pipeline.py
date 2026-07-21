#!/usr/bin/env python3
"""
Avatar Pipeline — Automated AI Colleague Video Generator

End-to-end automation:
  1. Generate common AI virtual colleague phrases using Gemini or Claude Haiku
  2. Create avatar videos using Azure Batch Avatar Synthesis API
  3. Download the finished MP4 videos to a local folder

Usage:
  python avatar_pipeline.py                          # Full pipeline (Gemini, 10 phrases)
  python avatar_pipeline.py --llm haiku              # Use Claude Haiku instead
  python avatar_pipeline.py --num-phrases 5          # Generate 5 phrases
  python avatar_pipeline.py --dry-run                # Generate phrases only, skip Azure
  python avatar_pipeline.py --mode combined          # All phrases in one video
  python avatar_pipeline.py --output-dir ./my_vids   # Custom output directory
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import requests
from anthropic import Anthropic
from dotenv import load_dotenv

# ──────────────────────────────────────────────
# Constants & Defaults
# ──────────────────────────────────────────────
DEFAULT_NUM_PHRASES = 10
DEFAULT_AVATAR_CHARACTER = "lisa"
DEFAULT_AVATAR_STYLE = "graceful-standing"
DEFAULT_VOICE = "en-US-JennyMultilingualNeural"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "avatar_videos"
DEFAULT_POLL_INTERVAL = 10  # seconds
AZURE_API_VERSION = "2024-08-01"

HAIKU_MODEL = "claude-haiku-4-5"
GEMINI_MODEL = "gemini-2.0-flash"

# ──────────────────────────────────────────────
# Stage 1: Generate Phrases (Gemini or Haiku)
# ──────────────────────────────────────────────

def _build_phrase_prompt(num_phrases: int, topic: str = "", existing_phrases: list[str] | None = None) -> str:
    """Build the shared prompt for phrase generation.

    Args:
        num_phrases: How many new phrases to generate.
        topic: Optional topic/scenario to focus on.
        existing_phrases: Previously generated phrases to avoid repeating.
    """
    topic_instruction = ""
    if topic:
        topic_instruction = f"""\nFocus specifically on this topic/scenario: \"{topic}\"
Generate phrases that an AI virtual colleague would say related to this topic."""
    else:
        topic_instruction = """\nCover a variety of categories such as:
- Greetings (morning, afternoon, welcome back)
- Meeting-related (reminders, joining, wrapping up)
- Task assistance (offering help, status updates, task completion)
- Encouragement and motivation
- Sign-offs and end-of-day messages
- Casual friendly interactions"""

    # Build deduplication context so the LLM avoids repeating old phrases
    dedup_instruction = ""
    if existing_phrases:
        dedup_list = "\n".join(f"  - \"{p}\"" for p in existing_phrases[:50])  # cap at 50 to fit context
        dedup_instruction = f"""\n\nIMPORTANT — The following phrases have ALREADY been generated. Do NOT repeat or closely paraphrase any of them:
{dedup_list}

Generate completely NEW and DIFFERENT phrases."""

    return f"""You are helping build an AI virtual colleague avatar. 
Generate exactly {num_phrases} UNIQUE phrases that an AI virtual colleague would say to users in a professional workplace setting.
{topic_instruction}

Requirements:
- Each phrase should be 1-3 sentences long
- Sound natural, warm, and professional — not robotic
- Suitable for text-to-speech avatar video
- Each phrase must be DIFFERENT from the others — no repetition
- Be creative and varied in tone and content

For each phrase, also indicate the gesture level:
- "HM" = hand movement (expressive, gesturing)
- "LBHM" = little bit hand movement (subtle gestures)
- "NHM" = no hand movement (still/calm delivery)

Return ONLY a valid JSON array with objects having "category", "phrase", and "gesture" keys.
Example format:
[
  {{"category": "greeting", "phrase": "Good morning! I hope you had a great start to your day. Let me know if there's anything I can help you with.", "gesture": "LBHM"}},
  {{"category": "meeting", "phrase": "Just a friendly reminder — your team standup starts in 10 minutes. I've got your notes ready if you need them.", "gesture": "HM"}}
]
{dedup_instruction}
Generate exactly {num_phrases} UNIQUE phrases. Return ONLY the JSON array, no extra text."""


def _parse_phrases(raw_text: str, source: str) -> list[dict]:
    """Parse JSON array of phrases from LLM response text."""
    json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
    if not json_match:
        print(f"  ⚠ Could not parse JSON from {source} response. Raw output:")
        print(f"  {raw_text[:500]}")
        sys.exit(1)
    return json.loads(json_match.group())


def generate_phrases_gemini(num_phrases: int, topic: str = "", existing_phrases: list[str] | None = None) -> list[dict]:
    """
    Call Google Gemini to generate common AI virtual colleague phrases.

    Returns a list of dicts: [{"category": "...", "phrase": "...", "gesture": "..."}, ...]
    """
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n  ❌ Missing GEMINI_API_KEY in .env file!")
        print("     Get one at: https://aistudio.google.com/apikey")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    prompt = _build_phrase_prompt(num_phrases, topic=topic, existing_phrases=existing_phrases)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    raw_text = response.text.strip()
    phrases = _parse_phrases(raw_text, "Gemini")
    return phrases


def generate_phrases_haiku(num_phrases: int, topic: str = "", existing_phrases: list[str] | None = None) -> list[dict]:
    """
    Call Claude Haiku via Azure AI Foundry to generate AI colleague phrases.

    Returns a list of dicts: [{"category": "...", "phrase": "...", "gesture": "..."}, ...]
    """
    # Support both Azure AI Foundry and direct Anthropic API
    azure_endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT")
    azure_api_key = os.getenv("AZURE_VOICELIVE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    # Allow overriding the model/deployment name via env var
    model_name = os.getenv("HAIKU_MODEL_NAME", HAIKU_MODEL)

    prompt = _build_phrase_prompt(num_phrases, topic=topic, existing_phrases=existing_phrases)

    if azure_endpoint and azure_api_key:
        # Azure AI Foundry: use direct HTTP request
        url = azure_endpoint.rstrip("/") + "/anthropic/v1/messages"
        masked_key = azure_api_key[:6] + "..." + azure_api_key[-4:]
        print(f"  Using Azure AI Foundry: {azure_endpoint}")
        print(f"  Model/Deployment: {model_name}")
        print(f"  API Key: {masked_key}")
        print(f"  URL: {url}")

        payload = {
            "model": model_name,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }

        # Try different auth header formats (Azure services vary)
        auth_headers_to_try = [
            {"x-api-key": azure_api_key},
            {"api-key": azure_api_key},
            {"Ocp-Apim-Subscription-Key": azure_api_key},
        ]

        response = None
        for auth_header in auth_headers_to_try:
            headers = {
                **auth_header,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            }
            header_name = list(auth_header.keys())[0]
            print(f"\n  🔑 Trying auth header: {header_name}...")
            response = requests.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                print(f"    ✅ Success with header: {header_name}")
                break
            elif response.status_code == 401:
                print(f"    ❌ 401 with {header_name} — trying next...")
                continue
            else:
                # Non-auth error, stop trying
                break

        if response.status_code != 200:
            print(f"\n  ❌ Azure AI Foundry request failed ({response.status_code}):")
            print(f"     {response.text[:500]}")
            sys.exit(1)

        data = response.json()
        raw_text = data["content"][0]["text"].strip()

    elif anthropic_key and anthropic_key != "sk-ant-your-key-here":
        # Direct Anthropic API
        print(f"  Using direct Anthropic API")
        client = Anthropic(api_key=anthropic_key)

        message = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()

    else:
        print("\n  ❌ Missing credentials for Claude Haiku!")
        print("     Set AZURE_VOICELIVE_ENDPOINT + AZURE_VOICELIVE_API_KEY in .env")
        print("     OR set ANTHROPIC_API_KEY for direct Anthropic access.")
        sys.exit(1)
    phrases = _parse_phrases(raw_text, "Haiku")
    return phrases


def generate_phrases(num_phrases: int, llm: str = "gemini", topic: str = "", existing_phrases: list[str] | None = None) -> list[dict]:
    """
    Generate phrases using the selected LLM.

    Args:
        num_phrases: Number of phrases to generate
        llm: Which LLM to use — 'gemini' or 'haiku'
        topic: Optional topic/scenario to focus phrase generation on
        existing_phrases: Previously generated phrases to avoid repeating
    """
    print(f"\n{'='*60}")
    print(f"  STAGE 1: Generating {num_phrases} phrases with {llm.capitalize()}")
    if topic:
        print(f"  Topic: {topic}")
    if existing_phrases:
        print(f"  Avoiding {len(existing_phrases)} existing phrases")
    print(f"{'='*60}\n")

    if llm == "haiku":
        phrases = generate_phrases_haiku(num_phrases, topic=topic, existing_phrases=existing_phrases)
    else:
        phrases = generate_phrases_gemini(num_phrases, topic=topic, existing_phrases=existing_phrases)

    print(f"  ✅ Generated {len(phrases)} phrases:\n")
    for i, p in enumerate(phrases, 1):
        gesture = p.get('gesture', 'NHM')
        print(f"  {i:>2}. [{p['category']}] [{gesture}] {p['phrase'][:75]}{'...' if len(p['phrase']) > 75 else ''}")

    return phrases


def load_existing_phrases(output_dir: Path) -> list[dict]:
    """Load previously generated phrases from phrases.json if it exists."""
    filepath = output_dir / "phrases.json"
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, list):
                print(f"  📂 Loaded {len(existing)} existing phrases from {filepath}")
                return existing
        except (json.JSONDecodeError, IOError) as e:
            print(f"  ⚠ Could not load existing phrases: {e}")
    return []


def save_phrases(phrases: list[dict], output_dir: Path, merge_existing: bool = True) -> Path:
    """Save generated phrases to a JSON file, merging with existing ones.

    Args:
        phrases: New phrases to save.
        output_dir: Directory containing phrases.json.
        merge_existing: If True, append to existing phrases (dedup by phrase text).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "phrases.json"

    all_phrases = []
    if merge_existing and filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, list):
                all_phrases = existing
        except (json.JSONDecodeError, IOError):
            pass

    # Deduplicate: keep existing phrases, add only truly new ones
    existing_texts = {p.get("phrase", "").strip().lower() for p in all_phrases}
    new_count = 0
    for p in phrases:
        phrase_key = p.get("phrase", "").strip().lower()
        if phrase_key and phrase_key not in existing_texts:
            all_phrases.append(p)
            existing_texts.add(phrase_key)
            new_count += 1

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_phrases, f, indent=2, ensure_ascii=False)
    print(f"\n  💾 Phrases saved to: {filepath}")
    print(f"     Total: {len(all_phrases)} ({new_count} new, {len(all_phrases) - new_count} existing)")
    return filepath


# ──────────────────────────────────────────────
# Stage 2: Create Avatar Videos (Azure Batch)
# ──────────────────────────────────────────────

def build_azure_headers(subscription_key: str) -> dict:
    """Build headers for Azure REST API calls."""
    return {
        "Ocp-Apim-Subscription-Key": subscription_key,
        "Content-Type": "application/json",
    }


def get_azure_endpoint(region: str) -> str:
    """Build the Azure TTS Avatar API base URL."""
    return f"https://{region}.api.cognitive.microsoft.com"


def _wrap_ssml(text: str, voice: str) -> str:
    """Wrap plain text in SSML tags for Azure TTS Avatar.

    Using SSML ensures the audio track is properly generated and embedded
    in the output video (PlainText mode has known issues with silent output).
    """
    # Escape XML special characters in the text
    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<speak version='1.0' xml:lang='en-US'>"
        f"<voice name='{voice}'>{escaped}</voice>"
        f"</speak>"
    )


def submit_avatar_job(
    endpoint: str,
    headers: dict,
    job_id: str,
    text: str,
    avatar_character: str,
    avatar_style: str,
    voice: str,
) -> bool:
    """
    Submit a single batch avatar synthesis job.
    Returns True if submission was successful.
    """
    url = f"{endpoint}/avatar/batchsyntheses/{job_id}?api-version={AZURE_API_VERSION}"

    # Use SSML for reliable audio output (PlainText can produce silent videos)
    ssml_content = _wrap_ssml(text, voice)

    payload = {
        "inputKind": "SSML",
        "avatarConfig": {
            "talkingAvatarCharacter": avatar_character,
            "talkingAvatarStyle": avatar_style,
            "videoFormat": "mp4",
            "videoCodec": "hevc",
            "subtitleType": "soft_embedded",
            "bitrateKbps": 2000,
            "customized": False,
        },
        "inputs": [
            {"content": ssml_content}
        ],
    }

    print(f"    📋 Payload: inputKind=SSML, voice={voice}, codec=hevc, bitrate=2000kbps")
    response = requests.put(url, json=payload, headers=headers)

    if response.status_code in (200, 201):
        print(f"    ✅ Job submitted: {job_id}")
        return True
    else:
        print(f"    ❌ Job submission failed ({response.status_code}): {response.text[:500]}")
        return False


def poll_job_status(
    endpoint: str,
    headers: dict,
    job_id: str,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    max_wait: int = 600,
) -> dict | None:
    """
    Poll an avatar synthesis job until it completes.
    Returns the job result dict on success, None on failure.
    """
    url = f"{endpoint}/avatar/batchsyntheses/{job_id}?api-version={AZURE_API_VERSION}"
    elapsed = 0

    while elapsed < max_wait:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"    ⚠ Poll error ({response.status_code}): {response.text[:200]}")
            time.sleep(poll_interval)
            elapsed += poll_interval
            continue

        data = response.json()
        status = data.get("status", "Unknown")

        if status == "Succeeded":
            print(f"    ✅ Job {job_id} completed!")
            return data
        elif status == "Failed":
            error = data.get("properties", {}).get("error", {})
            print(f"    ❌ Job {job_id} failed: {error}")
            return None
        else:
            print(f"    ⏳ Job {job_id} status: {status} (waited {elapsed}s)")

        time.sleep(poll_interval)
        elapsed += poll_interval

    print(f"    ⏰ Job {job_id} timed out after {max_wait}s")
    return None


def create_avatar_videos(
    phrases: list[dict],
    avatar_character: str,
    avatar_style: str,
    voice: str,
    mode: str,
    poll_interval: int,
) -> list[dict]:
    """
    Submit avatar synthesis jobs for all phrases and wait for completion.

    Args:
        phrases: List of phrase dicts with 'category' and 'phrase' keys
        mode: 'individual' (one video per phrase) or 'combined' (all in one)
        
    Returns:
        List of dicts with job results and download info
    """
    speech_key = os.getenv("AZURE_SPEECH_KEY")
    speech_endpoint = os.getenv("AZURE_SPEECH_ENDPOINT")
    speech_region = os.getenv("AZURE_SPEECH_REGION")

    if not speech_key:
        # Fallback: use same key as Azure Foundry if from same resource
        speech_key = os.getenv("AZURE_VOICELIVE_API_KEY")

    if not speech_key:
        print("\n  ❌ Missing Azure Speech key!")
        print("     Set AZURE_SPEECH_KEY (or AZURE_VOICELIVE_API_KEY) in your .env file.")
        sys.exit(1)

    if speech_endpoint:
        # Use custom endpoint directly (for Azure AI Services resources)
        endpoint = speech_endpoint.rstrip("/")
        print(f"  Using Speech endpoint: {endpoint}")
    elif speech_region:
        # Build from region (for standalone Speech resources)
        endpoint = get_azure_endpoint(speech_region)
        print(f"  Using Speech region: {speech_region}")
    else:
        print("\n  ❌ Missing Azure Speech endpoint!")
        print("     Set AZURE_SPEECH_ENDPOINT or AZURE_SPEECH_REGION in your .env file.")
        sys.exit(1)

    headers = build_azure_headers(speech_key)

    print(f"\n{'='*60}")
    print(f"  STAGE 2: Creating Avatar Videos via Azure Batch Synthesis")
    print(f"{'='*60}")
    print(f"  Avatar: {avatar_character} ({avatar_style})")
    print(f"  Voice:  {voice}")
    print(f"  Mode:   {mode}")
    print()

    jobs = []

    if mode == "combined":
        # Combine all phrases into a single text block
        combined_text = " ... ".join(p["phrase"] for p in phrases)
        job_id = f"avatar-combined-{uuid.uuid4().hex[:8]}"
        print(f"  📤 Submitting combined job ({len(phrases)} phrases)...")

        if submit_avatar_job(endpoint, headers, job_id, combined_text, avatar_character, avatar_style, voice):
            jobs.append({
                "job_id": job_id,
                "category": "combined",
                "phrase_count": len(phrases),
                "text_preview": combined_text[:100],
            })
    else:
        # One video per phrase
        for i, phrase_data in enumerate(phrases, 1):
            job_id = f"avatar-{phrase_data['category']}-{uuid.uuid4().hex[:8]}"
            gesture = phrase_data.get("gesture", "NHM")
            print(f"  📤 [{i}/{len(phrases)}] [{gesture}] Submitting: {phrase_data['phrase'][:55]}...")

            if submit_avatar_job(
                endpoint, headers, job_id,
                phrase_data["phrase"],
                avatar_character, avatar_style, voice,
            ):
                jobs.append({
                    "job_id": job_id,
                    "category": phrase_data["category"],
                    "phrase": phrase_data["phrase"],
                    "gesture": gesture,
                    "index": i,
                })

            # Small delay between submissions to avoid rate limiting
            if i < len(phrases):
                time.sleep(1)

    # Poll all jobs for completion
    print(f"\n  ⏳ Waiting for {len(jobs)} job(s) to complete...\n")
    results = []

    for job in jobs:
        result = poll_job_status(endpoint, headers, job["job_id"], poll_interval)
        if result:
            # Extract the download URL from the result
            download_url = result.get("outputs", {}).get("result", "")
            job["download_url"] = download_url
            job["status"] = "Succeeded"
            results.append(job)
        else:
            job["status"] = "Failed"
            results.append(job)

    succeeded = sum(1 for r in results if r["status"] == "Succeeded")
    print(f"\n  📊 Results: {succeeded}/{len(results)} jobs succeeded")

    return results


# ──────────────────────────────────────────────
# Stage 3: Download Videos
# ──────────────────────────────────────────────

def download_videos(results: list[dict], output_dir: Path) -> list[Path]:
    """
    Download completed avatar videos to the output directory.

    Returns list of downloaded file paths.
    """
    print(f"\n{'='*60}")
    print(f"  STAGE 3: Downloading Videos")
    print(f"{'='*60}")
    print(f"  Output directory: {output_dir}\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for job in results:
        if job["status"] != "Succeeded" or not job.get("download_url"):
            print(f"  ⏭ Skipping {job['job_id']} (status: {job['status']})")
            continue

        # Build filename from phrase text + gesture suffix
        if job.get("category") == "combined":
            filename = "all_phrases_combined.mp4"
        else:
            phrase_text = job.get("phrase", "unknown")
            gesture = job.get("gesture", "NHM")

            # Clean phrase for filename: keep first ~60 chars, make filesystem-safe
            clean_phrase = phrase_text[:60].strip()
            clean_phrase = re.sub(r'[<>:"/\\|?*]', '', clean_phrase)
            clean_phrase = clean_phrase.rstrip('.')

            filename = f"{clean_phrase}-{gesture}.mp4"

        filepath = output_dir / filename

        # Same phrase+gesture = same filename → overwrite (re-download fresh)
        # Different phrase = different filename → creates new file, never deletes old ones
        if filepath.exists():
            print(f"  🔄 Overwriting (same phrase): {filename}")

        print(f"  📥 Downloading: {filename}...")

        try:
            response = requests.get(job["download_url"], stream=True)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            size_mb = filepath.stat().st_size / (1024 * 1024)
            print(f"    ✅ Saved: {filepath} ({size_mb:.1f} MB)")
            downloaded.append(filepath)

        except Exception as e:
            print(f"    ❌ Download failed: {e}")

    return downloaded


# ──────────────────────────────────────────────
# Main Pipeline
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated AI Colleague Avatar Video Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python avatar_pipeline.py                        # Full pipeline, 10 phrases
  python avatar_pipeline.py --num-phrases 3        # Only 3 phrases
  python avatar_pipeline.py --dry-run              # Phrases only, no Azure
  python avatar_pipeline.py --topic "greetings"    # Generate greeting phrases only
  python avatar_pipeline.py --topic "helping users with reports"  # Custom topic
  python avatar_pipeline.py --mode combined        # All phrases in one video
  python avatar_pipeline.py --output-dir ~/Videos  # Custom output folder
        """,
    )

    parser.add_argument(
        "--llm", type=str, choices=["gemini", "haiku"], default="haiku",
        help="Which LLM to use for phrase generation (default: gemini)",
    )
    parser.add_argument(
        "--num-phrases", type=int, default=DEFAULT_NUM_PHRASES,
        metavar="N",
        help="Number of phrases to generate (default: 10, no upper limit)",
    )
    parser.add_argument(
        "--topic", type=str, default="",
        help="Topic or scenario for phrase generation (e.g., 'greetings', 'helping with reports')",
    )
    parser.add_argument(
        "--avatar-character", type=str, default=DEFAULT_AVATAR_CHARACTER,
        help=f"Azure avatar character name (default: {DEFAULT_AVATAR_CHARACTER})",
    )
    parser.add_argument(
        "--avatar-style", type=str, default=DEFAULT_AVATAR_STYLE,
        help=f"Avatar style (default: {DEFAULT_AVATAR_STYLE})",
    )
    parser.add_argument(
        "--voice", type=str, default=DEFAULT_VOICE,
        help=f"Azure TTS voice name (default: {DEFAULT_VOICE})",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save videos (default: ./avatar_videos)",
    )
    parser.add_argument(
        "--mode", type=str, choices=["individual", "combined"], default="individual",
        help="'individual' = one video per phrase, 'combined' = all in one video (default: individual)",
    )
    parser.add_argument(
        "--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between Azure status polls (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only generate phrases (skip Azure avatar creation and download)",
    )

    return parser.parse_args()


def main():
    """Run the full avatar pipeline."""
    # Load environment variables from .env file (next to this script)
    env_path = Path(__file__).parent / ".env"

    if env_path.exists():
        print(f"\n  Loading .env from: {env_path}")
        try:
            with open(env_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value:
                            os.environ[key] = value
            # Debug: confirm which keys were loaded
            loaded_keys = []
            for k in ["AZURE_VOICELIVE_ENDPOINT", "AZURE_VOICELIVE_API_KEY",
                       "ANTHROPIC_API_KEY", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]:
                if os.getenv(k):
                    loaded_keys.append(k)
            print(f"  ✅ Loaded env vars: {', '.join(loaded_keys)}")
        except Exception as e:
            print(f"  ⚠ Failed to read .env: {e}")
    else:
        print(f"\n  ⚠ Warning: .env file not found at: {env_path}")
        print(f"    Make sure the .env file exists in the same folder as this script.\n")

    args = parse_args()

    print("\n" + "🤖" * 30)
    print("  AI Colleague Avatar Video Pipeline")
    print("🤖" * 30)
    print(f"\n  Config:")
    print(f"    LLM:       {args.llm}")
    print(f"    Phrases:   {args.num_phrases}")
    print(f"    Topic:     {args.topic or '(general)'}")
    print(f"    Avatar:    {args.avatar_character} ({args.avatar_style})")
    print(f"    Voice:     {args.voice}")
    print(f"    Mode:      {args.mode}")
    print(f"    Output:    {args.output_dir}")
    print(f"    Dry run:   {args.dry_run}")

    # ── Load existing phrases for deduplication ──
    existing_data = load_existing_phrases(args.output_dir)
    existing_phrase_texts = [p.get("phrase", "") for p in existing_data if p.get("phrase")]

    # ── Stage 1: Generate phrases ──
    phrases = generate_phrases(
        args.num_phrases,
        llm=args.llm,
        topic=args.topic,
        existing_phrases=existing_phrase_texts if existing_phrase_texts else None,
    )
    save_phrases(phrases, args.output_dir)

    if args.dry_run:
        print(f"\n  🏁 Dry run complete! Phrases saved to {args.output_dir}/phrases.json")
        print(f"     Re-run without --dry-run to create avatar videos.\n")
        return

    # ── Stage 2: Create avatar videos ──
    results = create_avatar_videos(
        phrases=phrases,
        avatar_character=args.avatar_character,
        avatar_style=args.avatar_style,
        voice=args.voice,
        mode=args.mode,
        poll_interval=args.poll_interval,
    )

    # ── Stage 3: Download videos ──
    succeeded_jobs = [r for r in results if r["status"] == "Succeeded"]
    if not succeeded_jobs:
        print("\n  ❌ No videos were successfully generated. Check Azure logs above.")
        sys.exit(1)

    downloaded = download_videos(results, args.output_dir)

    # ── Summary ──
    print(f"\n{'='*60}")
    print(f"  ✅ PIPELINE COMPLETE")
    print(f"{'='*60}")
    print(f"  Phrases generated:  {len(phrases)}")
    print(f"  Videos created:     {len(succeeded_jobs)}")
    print(f"  Videos downloaded:  {len(downloaded)}")
    print(f"  Output directory:   {args.output_dir}")
    print(f"\n  Files:")
    for fp in downloaded:
        print(f"    📹 {fp.name}")
    print()


if __name__ == "__main__":
    main()
