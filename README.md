# Kasauti · कसौटी

**The Hindi speech-model regression gate.**  
*कसौटी = the touchstone. If your Hindi STT can't pass these 30 cases, it isn't ready to ship.*

[![CI](https://github.com/<your-org>/kasauti/actions/workflows/kasauti.yml/badge.svg)](https://github.com/<your-org>/kasauti/actions/workflows/kasauti.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![No dependencies](https://img.shields.io/badge/dependencies-none-green.svg)](#)

---

Everyone is shipping a new TTS / STT model. Nobody catches that Tuesday's deploy broke OTP recognition, mangled a drug name, or confused ₹2,450 with ₹24,500.

**Kasauti** replays the same 30 hard, real-world **Hindi** sentences through your *old* and *new* speech stack and blocks the release if anything got worse — in the browser or as a CI step.

---

## Table of Contents

- [Why Kasauti?](#why-kasauti)
- [How it works](#how-it-works)
- [Test suite — 30 Hindi cases, 8 categories](#test-suite)
- [Quick start](#quick-start)
  - [Web dashboard (Vercel)](#1-web-dashboard-vercel)
  - [CLI / local](#2-cli--local)
  - [CI (GitHub Actions)](#3-ci-github-actions)
- [Project structure](#project-structure)
- [Configuration reference](#configuration-reference)
- [Scoring: WER, CER, LLM judge](#scoring)
- [Extending the suite](#extending-the-suite)
- [Architecture](#architecture)
- [Author](#author)
- [License](#license)

---

## Why Kasauti?

| Problem | Kasauti's answer |
|---|---|
| You can't tell if a new model broke Hindi specifically | 30 Hindi-only cases across 8 real-world categories |
| WER misses semantic errors (₹2,450 vs दो हज़ार…) | Hindi-aware LLM judge scores *meaning*, not just characters |
| Different test audio = unfair comparison | Both models hear **byte-identical** noisy audio (fixed seed) |
| CI doesn't know about speech quality | `harness.py` exits `1` on regression — blocks the PR |
| Setting up recordings is expensive | No mic needed — Sarvam **Bulbul** TTS generates the test audio |
| Hard to see *what* changed | Per-word diff (substituted / deleted / inserted) in the dashboard |

---

## How it works

```
Hindi text
    │
    ▼
Bulbul TTS  ──►  clean .wav
                      │
              add_noise(SNR, seed=7)   ◄── same seed = identical audio
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
   Saaras baseline          Saaras candidate
   (e.g. saaras:v3)         (e.g. saaras:v4)
          │                       │
    WER · CER               WER · CER
    LLM judge               LLM judge
          │                       │
          └───────────┬───────────┘
                      ▼
            per-category gate
                      │
              PASS  or  FAIL
              (exit 0)  (exit 1)
```

Key design choices:

- **No recordings needed.** Test audio is synthesised by Sarvam **Bulbul** and degraded with white noise at a chosen SNR (15 dB office / 10 dB street / 5 dB crowded bus).
- **Same-audio A/B.** Both STT models get byte-identical noisy audio (fixed random seed), so any WER delta is the model, not the microphone.
- **Meaning-aware scoring.** A Sarvam LLM judge checks whether the transcript preserved intent — `पाँच हज़ार` == `5000` is fine; a wrong OTP digit is a hard failure.
- **Per-word diff.** The dashboard highlights exactly which words were substituted, deleted, or inserted, so you can see what broke at a glance.
- **Zero dependencies.** `api/run.py` and `harness.py` use Python stdlib only — they run on Vercel, GitHub Actions, or a laptop with no `pip install`.

---

## Test suite

30 carefully curated Hindi sentences targeting the hardest production failure modes:

| # | Category | Description | Example |
|---|---|---|---|
| 1–4 | **Hinglish कोड-मिक्स** | Everyday code-switched speech | *कल 10:30 बजे मीटिंग है, please confirm कर देना* |
| 5–9 | **नंबर / OTP / राशि** | OTPs, amounts, dates, phone numbers | *आपका OTP है 8 3 7 4 1 2, किसी को न बताएं* |
| 10–13 | **बैंकिंग व वित्त** | NEFT, account numbers, IFSC, EMI | *NEFT से एक लाख पचास हज़ार रुपये ट्रांसफ़र करने हैं* |
| 14–17 | **चिकित्सा** | Drug names, dosages, symptoms | *Pantoprazole 40 mg खाना खाने से आधे घंटे पहले लेनी है* |
| 18–20 | **पते व स्थान** | City names, PIN codes, landmarks | *पिन कोड है 1 1 0 0 0 1, दिल्ली के करोल बाग़ का* |
| 21–23 | **सरकारी ID** | Aadhaar, PAN, GST | *Aadhaar नंबर है 2 4 3 5 8 8 1 2 3 4 5 6* |
| 24–26 | **बोलचाल / मुहावरे** | Hindi idioms, regional slang | *यार, अब की बार तो नानी याद आ जाएगी उसे* |
| 27–30 | **औपचारिक हिंदी** | News-style, official Hindi | *भारतीय रिज़र्व बैंक ने रेपो दर में 25 आधार अंकों की वृद्धि की* |

> **Why these categories?** They cover the four places Hindi STT most commonly fails in production: (1) numbers and IDs where a single wrong digit matters, (2) code-mix where Devanagari and Roman tokens coexist, (3) low-frequency vocabulary (drug names, legal terms), and (4) formal register where pronunciation differs from colloquial norms.

---

## Quick start

### Prerequisites

```bash
export SARVAM_API_KEY=sk-...    # get yours at https://dashboard.sarvam.ai
# Python 3.9+ — no pip install needed
```

### 1. Web dashboard (Vercel)

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/<your-org>/kasauti)

1. Click **Deploy with Vercel** above (or `vercel deploy` from the repo root).
2. Add `SARVAM_API_KEY` as an environment variable in the Vercel dashboard.
3. Open the deployed URL — the dashboard loads the 30-case suite automatically.

The dashboard gives you:
- **Live progress bar** as cases run in parallel (4 workers)
- **Stats strip** — regression count, judge pass rate, avg WER, avg latency
- **Category filter tabs** — drill into one category
- **Per-word diff highlighting** — yellow = substituted, red = deleted, blue = inserted
- **Audio playback** — hear the noisy test audio for each case
- **PASS / FAIL verdict** with per-category breakdown
- **"अपना वाक्य आज़माएं"** — test any Hindi sentence ad hoc

### 2. CLI / local

```bash
# Full 30-case suite
python harness.py --local --base saaras:v3 --cand saaras:v4 --snr 10 --threshold 0.05

# One category only
python harness.py --local --cat banking --snr 10
python harness.py --local --cat medical --snr 5

# Against a deployed Vercel URL
python harness.py --url https://<your-deployment>.vercel.app --snr 10

# Clean audio (no noise)
python harness.py --local --snr ""

# Output: colored terminal table + kasauti_report.json
```

**Example terminal output:**

```
╔══════════════════════════════════════════════════════════════╗
║  कसौटी  — हिंदी STT Regression Gate                         ║
╚══════════════════════════════════════════════════════════════╝
  Baseline:  saaras:v3
  Candidate: saaras:v4
  Noise:     10 dB

  [ 1/30] Δ+0.000  Hinglish कोड-मिक्स       कल सुबह 10:30 बजे मीटिंग…
  [ 2/30] Δ+0.000  Hinglish कोड-मिक्स       मेरा UPI पेमेंट फेल हो…
  ...

  CATEGORY SUMMARY
  ──────────────────────────────────────────────────────────────────────────────
  केटेगरी                 n   WER base  WER cand    Δ WER  judge b  judge c  verdict
  ──────────────────────────────────────────────────────────────────────────────
  Hinglish कोड-मिक्स      4      0.121     0.094   -0.027      3/4      4/4  ok
  नंबर / OTP / राशि       5      0.203     0.188   -0.015      4/5      5/5  ok
  बैंकिंग व वित्त          4      0.187     0.162   -0.025      3/4      4/4  ok
  ...

  ✓ GATE: PASS — no category regressed beyond threshold
```

### 3. CI (GitHub Actions)

The repo ships with `.github/workflows/kasauti.yml`. It runs on every PR and blocks merge on regression:

```yaml
# .github/workflows/kasauti.yml
name: kasauti-speech-regression
on:
  pull_request:
  workflow_dispatch:
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Run Kasauti suite
        env:
          SARVAM_API_KEY: ${{ secrets.SARVAM_API_KEY }}
        run: python harness.py --local --base saaras:v3 --cand saaras:v4 --snr 10 --threshold 0.05
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: kasauti-report, path: kasauti_report.json }
```

**Setup:**  
Go to your repo → *Settings → Secrets and variables → Actions* → add `SARVAM_API_KEY`.

---

## Project structure

```
kasauti/
├── index.html                  # Web dashboard (single-file, no build step)
├── api/
│   └── run.py                  # Vercel serverless handler + all core logic
│                               #   SUITE          — 30 Hindi test cases
│                               #   tts()          — Bulbul TTS call
│                               #   stt()          — Saaras STT call
│                               #   judge()        — LLM-as-judge
│                               #   add_noise()    — white noise at target SNR
│                               #   wer() / cer()  — Hindi-aware metrics
│                               #   word_diff()    — per-word alignment
│                               #   run_case()     — one end-to-end test
│                               #   handler        — Vercel HTTP handler
├── harness.py                  # CLI / CI runner (stdlib only)
├── vercel.json                 # Vercel config (60 s function timeout)
├── requirements.txt            # intentionally empty — zero dependencies
├── .github/
│   └── workflows/
│       └── kasauti.yml         # GitHub Actions CI gate
├── LICENSE                     # MIT
└── README.md                   # this file
```

---

## Configuration reference

### `harness.py` flags

| Flag | Default | Description |
|---|---|---|
| `--local` | — | Call Sarvam API directly (needs `SARVAM_API_KEY`) |
| `--url` | — | Run against a deployed Kasauti URL |
| `--base` | `saaras:v3` | Baseline STT model |
| `--cand` | `saaras:v4` | Candidate STT model to evaluate |
| `--tts` | `bulbul:v3` | TTS model for audio generation |
| `--snr` | `10` | Noise level in dB (`""` for clean audio) |
| `--threshold` | `0.05` | Max allowed WER increase per category before FAIL |
| `--cat` | — | Run only one category (e.g. `banking`, `medical`) |
| `--workers` | `4` | Parallel workers |
| `--out` | `kasauti_report.json` | JSON report output path |

### API query parameters (`/api/run`)

| Param | Description |
|---|---|
| `suite=1` | Return the test suite (no evaluation) |
| `id=<n>` | Run case by ID |
| `text=<str>` | Run a custom sentence |
| `lang=<code>` | Language code for custom text (default `hi-IN`) |
| `base=<model>` | Baseline STT model |
| `cand=<model>` | Candidate STT model |
| `tts=<model>` | TTS model |
| `snr=<dB\|clean>` | Noise level |
| `audio=0` | Skip base64 audio in response (faster for CI) |
| `diff=0` | Skip word-level diff (faster) |

### SNR levels

| SNR | Scenario |
|---|---|
| clean | No noise — ideal conditions |
| 15 dB | Quiet office |
| 10 dB | Busy street (default) |
| 5 dB | Crowded bus / market |

---

## Scoring

### Word Error Rate (WER)

Hindi-aware WER with:
- **NFC normalisation** and nukta removal (`\u093c`)
- **Devanagari digit → ASCII mapping** (`०` → `0`, …, `९` → `9`) so `पाँच` and `5` can be compared correctly by the judge (WER still treats them as different tokens, but the judge doesn't penalise this)
- Punctuation and symbol stripping before tokenisation

```
WER = Levenshtein(reference_words, hypothesis_words) / len(reference_words)
```

A WER increase of more than `--threshold` (default 0.05) in any category = **FAIL**.

### LLM judge (0–10)

The judge is instructed to:

- **Ignore:** Devanagari ↔ Roman transliteration, number-word ↔ digit equivalence (पाँच हज़ार == 5000), punctuation, casing
- **Penalise:** wrong digit in OTP / phone / Aadhaar / PAN, wrong drug name or dosage, wrong place name, wrong amount, dropped meaning

Score ≥ 7 → `pass`. If the candidate's judge pass count drops below the baseline's in any category → **FAIL**.

If the judge API fails, the judge score is `null` and is never counted as a regression (fail-safe).

### Regression logic (per category)

```python
regress = (candidate_avg_wer - baseline_avg_wer) > threshold
       OR (candidate_judge_passes < baseline_judge_passes)
```

Both conditions are checked independently. Either one triggers a FAIL.

---

## Extending the suite

Add entries to `SUITE` in [`api/run.py`](api/run.py):

```python
{"id": 31, "lang": "hi-IN", "cat": "banking",
 "text": "मेरे खाते में ₹50,000 की FD बनानी है, 1 साल के लिए।"},
```

**Guidelines for good Hindi test cases:**
- Use **Devanagari script** (Saaras outputs Devanagari; Roman Hinglish gives misleadingly high WER)
- Pick sentences where a single wrong word/digit meaningfully changes the meaning
- Cover at least one of: number, named entity, technical term, or low-frequency vocabulary
- Keep it under ~80 characters so TTS doesn't split into multiple chunks

To add a new category, also add it to `CAT_LABELS` in `api/run.py`:
```python
CAT_LABELS["agriculture"] = "कृषि व खेती"
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    index.html                        │
│  (single-file SPA, no build, no framework)           │
│  • fetches /api/run?suite=1 on load                  │
│  • 4 parallel fetch workers per run                  │
│  • renders word-diff, score rings, cat tabs          │
└────────────────────┬────────────────────────────────┘
                     │ HTTP  /api/run?...
┌────────────────────▼────────────────────────────────┐
│               api/run.py  (Vercel function)          │
│                                                      │
│  handler.do_GET / do_POST                            │
│       │                                              │
│       ├── tts(text, lang, model)                     │
│       │       └── POST /text-to-speech  → wav bytes  │
│       │                                              │
│       ├── add_noise(wav, snr_db, seed=7)             │
│       │       └── pure Python, no scipy              │
│       │                                              │
│       ├── stt(wav, lang, model)  × 2  (ThreadPool)   │
│       │       └── POST /speech-to-text → transcript  │
│       │                                              │
│       ├── wer() / cer()  — Hindi-aware Levenshtein   │
│       ├── word_diff()    — alignment for UI          │
│       └── judge(ref, hyp, lang)                      │
│               └── POST /v1/chat/completions           │
│                       (sarvam-105b → sarvam-m)       │
└─────────────────────────────────────────────────────┘

External APIs (all Sarvam):
  https://api.sarvam.ai/text-to-speech       Bulbul TTS
  https://api.sarvam.ai/speech-to-text       Saaras STT
  https://api.sarvam.ai/v1/chat/completions  LLM judge
```

**Deployment:** Vercel serverless function — `vercel.json` sets a 60 s timeout (two parallel STT calls + judge can take ~30 s on noisy input).

**No database, no state.** Every request is fully self-contained. The JSON report is written locally by `harness.py` only.

---

## Author

**Rushil Sharma**  
International Institute of Information Technology, Hyderabad (IIIT-H)  
Built at Sarvam Campus '26 · IIT Hyderabad

---

## License

[MIT](LICENSE) © 2026 Rushil Sharma

---

*Built on Sarvam [Bulbul](https://sarvam.ai) (TTS) · [Saaras](https://sarvam.ai) (STT) · Sarvam LLM (judge)*
