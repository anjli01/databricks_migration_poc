# 🤖 AI Colleague Avatar Video Pipeline

Automated pipeline that generates common AI virtual colleague phrases using **Claude Haiku**, creates talking avatar videos via **Azure Text-to-Speech Avatar**, and downloads the MP4 files locally.

## Architecture

```
Claude Haiku API  →  Azure Batch Avatar Synthesis  →  Download MP4s
  (phrases)              (video creation)              (local folder)
```

## Prerequisites

1. **Python 3.10+**
2. **Anthropic API Key** — [Get one here](https://console.anthropic.com/)
3. **Azure Speech Service** (Standard S0 tier) in a supported region:
   - East US 2, West US 2, Southeast Asia, West Europe, or North Europe

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env with your actual keys
```

### 3. Run the pipeline

```bash
# Full pipeline — generate 10 phrases, create individual avatar videos
python avatar_pipeline.py

# Generate only 3 phrases
python avatar_pipeline.py --num-phrases 3

# Dry run — generate phrases only, no Azure calls
python avatar_pipeline.py --dry-run

# All phrases combined into one video
python avatar_pipeline.py --mode combined

# Custom output directory
python avatar_pipeline.py --output-dir ~/Videos/avatars
```

## CLI Options

| Option | Default | Description |
|---|---|---|
| `--num-phrases N` | `10` | Number of phrases to generate (1–10) |
| `--avatar-character` | `lisa` | Azure avatar character |
| `--avatar-style` | `graceful-standing` | Avatar style |
| `--voice` | `en-US-JennyMultilingualNeural` | Azure TTS voice (multilingual) |
| `--output-dir` | `./avatar_videos` | Output directory for MP4 files |
| `--mode` | `individual` | `individual` or `combined` |
| `--poll-interval` | `10` | Seconds between Azure status checks |
| `--dry-run` | `false` | Only generate phrases, skip video creation |

## Output

Videos are saved to the `avatar_videos/` folder (next to the script) by default:

```
avatar_videos/
├── phrases.json                  # Generated phrases (for reference)
├── phrase_01_greeting.mp4        # Individual videos
├── phrase_02_meeting.mp4
├── phrase_03_task_assistance.mp4
└── ...
```

## How It Works

1. **Stage 1** — Calls Claude Haiku to generate workplace phrases (greetings, meeting reminders, encouragement, etc.)
2. **Stage 2** — Submits each phrase to Azure's Batch Avatar Synthesis API using the `lisa` avatar in `graceful-standing` style with `en-US-JennyMultilingualNeural` voice
3. **Stage 3** — Polls Azure for job completion, then downloads the MP4 files

## Troubleshooting

- **"Missing Azure credentials"** — Make sure your `.env` file has valid `AZURE_SPEECH_KEY` and `AZURE_SPEECH_REGION`
- **Job submission fails with 403** — Verify your Speech resource is on the S0 tier and in a supported avatar region
- **Job fails with "InvalidAvatar"** — Check that the avatar character/style combination is valid
