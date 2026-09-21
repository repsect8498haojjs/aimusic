# 🎵 AI ACE-Step OS

One tool, one job: full-song music generation with vocals.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/abhayraj01op/AI_ACEStep_OS/blob/main/colab/AI_ACEStep_OS.ipynb)

## Why this is its own notebook now
This used to be bundled with Kokoro and Qwen3-TTS in one "AI Music OS"
notebook — three separate multi-GB installs in a single run. When one
broke, it was hard to tell which, and they competed for the same disk
space and install time. This notebook does exactly one thing, so a
failure here is unambiguous — it's ACE-Step, not "something in three
tools."

## What it is
**ACE-Step 1.5** — full songs, WITH vocals, up to 10 minutes, 50+
languages, MIT licensed (commercial use is fine), and under 4GB VRAM.

## Real bugs fixed in this version (found from live debugging)
- **uv's package cache now lives on Google Drive** (`UV_CACHE_DIR`), not
  the Colab VM's local disk. A large ML dependency cache (torch+CUDA
  etc.) filling up local disk was a real, previously-invisible cause of
  installs hanging or failing partway through.
- **Long silent installs no longer look like a hang.** `uv sync` and the
  model download can legitimately run 20-40 minutes with a progress
  display that renders as nothing at all through Colab's plain-text
  output. A heartbeat prints every 30 seconds regardless, and the
  command's real output is captured and shown directly in the failure
  message if it fails — not a "check output above" that can get lost.
- **Fixed a real startup crash**: `ValueError: Key backend:
  'module://matplotlib_inline.backend_inline' is not a valid value`.
  Colab sets that backend for its own notebook plotting, and it leaked
  into ACE-Step's separate, isolated `uv` environment, which doesn't have
  the Jupyter-only package that value requires. Fixed by explicitly
  setting `MPLBACKEND=Agg` for ACE-Step's own process.

## ⚡ One-Click Start
1. Push this project to your own GitHub repo, update `REPO_URL` in Step 1.
2. Colab → Runtime → Change runtime type → T4 GPU → Run All.
3. First run: ~20-40 minutes.
4. Step 3 gives you the link.

## What persists / Colab free-tier note
The repo, dependencies, and models persist on Google Drive. This
notebook runs a Gradio app tunneled to a public URL — same free-tier
caveat as the other web-app notebooks in this set (Colab's FAQ flags
"bypassing the notebook UI via a web UI" for possible disconnection on
the free tier). Keep sessions reasonably short, or use a positive Colab
compute-unit balance to remove the restriction.

## Security
The tunnel URL has no authentication. Don't share it.
