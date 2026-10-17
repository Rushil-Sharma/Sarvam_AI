"""Kasauti — हिंदी-focused regression harness for Sarvam speech models.

One request = one test case:
  text --(Bulbul TTS)--> clean audio --(+noise @ SNR)--> test audio
       --(STT baseline model)-->  transcript A --> WER/CER + LLM judge
       --(STT candidate model)--> transcript B --> WER/CER + LLM judge

Both STT models hear the *same* audio, so any difference is the model, not the input.
Stdlib only (no deps) so it runs anywhere: Vercel, CI, a laptop.

Hindi suite covers 8 hard real-world categories:
  hinglish   — code-mixed Hinglish everyday speech
  numbers    — OTPs, amounts, dates, phone numbers
  banking    — UPI, account, NEFT/RTGS transactions
  medical    — drug names, dosages, symptoms in Hindi
  addresses  — city names, PIN codes, landmarks
  govt       — Aadhaar, PAN, GST IDs, ration card
  colloquial — idioms, regional slang, informal speech
  formal     — news-style Hindi, official language
"""
import base64
import io
import json
import math
import os
import random
import re
import struct
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

API = "https://api.sarvam.ai"

# ---------------------------------------------------------------- Hindi test suite
# 30 carefully curated Hindi cases — the hardest real-world sentences a production
# STT system must get right for Indian users.
SUITE = [
    # ── hinglish (code-mix) ─────────────────────────────────────────────────────
    {"id": 1,  "lang": "hi-IN", "cat": "hinglish",
     "text": "कल सुबह 10:30 बजे मीटिंग है, प्लीज़ कन्फर्म कर देना।"},
    {"id": 2,  "lang": "hi-IN", "cat": "hinglish",
     "text": "मेरा UPI पेमेंट फेल हो गया, ट्रांजैक्शन ID चेक करो।"},
    {"id": 3,  "lang": "hi-IN", "cat": "hinglish",
     "text": "यार, deadline कल है और मेरा laptop crash हो गया है।"},
    {"id": 4,  "lang": "hi-IN", "cat": "hinglish",
     "text": "मुझे airport drop करना है, Uber book करोगे क्या?"},

    # ── numbers (OTP / amount / date / phone) ────────────────────────────────────
    {"id": 5,  "lang": "hi-IN", "cat": "numbers",
     "text": "आपका OTP है 8 3 7 4 1 2, किसी को न बताएं।"},
    {"id": 6,  "lang": "hi-IN", "cat": "numbers",
     "text": "आपका बिल ₹2,450 है और ड्यू डेट 15 नवंबर है।"},
    {"id": 7,  "lang": "hi-IN", "cat": "numbers",
     "text": "मेरे खाते से पाँच हज़ार रुपये कट गए हैं लेकिन रिचार्ज नहीं हुआ।"},
    {"id": 8,  "lang": "hi-IN", "cat": "numbers",
     "text": "फ़ोन नंबर है 9 8 7 6 5 4 3 2 1 0, सेव कर लो।"},
    {"id": 9,  "lang": "hi-IN", "cat": "numbers",
     "text": "ट्रेन 12 बजकर 45 मिनट पर प्लेटफ़ॉर्म नंबर 7 से जाएगी।"},

    # ── banking & finance ────────────────────────────────────────────────────────
    {"id": 10, "lang": "hi-IN", "cat": "banking",
     "text": "NEFT से एक लाख पचास हज़ार रुपये ट्रांसफ़र करने हैं।"},
    {"id": 11, "lang": "hi-IN", "cat": "banking",
     "text": "आपका account number 00 1 2 3 4 5 6 7 8 9 है।"},
    {"id": 12, "lang": "hi-IN", "cat": "banking",
     "text": "EMI हर महीने की 5 तारीख को ₹3,200 कटेगी।"},
    {"id": 13, "lang": "hi-IN", "cat": "banking",
     "text": "IFSC कोड है SBIN 0 0 0 1 2 3 4, ध्यान से नोट करें।"},

    # ── medical ──────────────────────────────────────────────────────────────────
    {"id": 14, "lang": "hi-IN", "cat": "medical",
     "text": "Pantoprazole 40 mg खाना खाने से आधे घंटे पहले लेनी है।"},
    {"id": 15, "lang": "hi-IN", "cat": "medical",
     "text": "बुखार 103 डिग्री है, Paracetamol दे दो और डॉक्टर को बुलाओ।"},
    {"id": 16, "lang": "hi-IN", "cat": "medical",
     "text": "मुझे सीने में दर्द और साँस लेने में तकलीफ़ हो रही है।"},
    {"id": 17, "lang": "hi-IN", "cat": "medical",
     "text": "Metformin 500 mg दिन में दो बार, खाने के साथ लेनी है।"},

    # ── addresses & places ───────────────────────────────────────────────────────
    {"id": 18, "lang": "hi-IN", "cat": "addresses",
     "text": "मुझे Connaught Place से IGI Airport जाना है।"},
    {"id": 19, "lang": "hi-IN", "cat": "addresses",
     "text": "पिन कोड है 1 1 0 0 0 1, दिल्ली के करोल बाग़ का।"},
    {"id": 20, "lang": "hi-IN", "cat": "addresses",
     "text": "हमारा दफ़्तर Bandra Kurla Complex, मुंबई में है।"},

    # ── government IDs ───────────────────────────────────────────────────────────
    {"id": 21, "lang": "hi-IN", "cat": "govt",
     "text": "Aadhaar नंबर है 2 4 3 5 8 8 1 2 3 4 5 6, किसी को न दें।"},
    {"id": 22, "lang": "hi-IN", "cat": "govt",
     "text": "PAN card नंबर ABCDE 1 2 3 4 F है, form में भरें।"},
    {"id": 23, "lang": "hi-IN", "cat": "govt",
     "text": "GST नंबर 29 A A A C P 1 2 3 4 A 1 Z 5 है।"},

    # ── colloquial & idioms ──────────────────────────────────────────────────────
    {"id": 24, "lang": "hi-IN", "cat": "colloquial",
     "text": "यार, अब की बार तो नानी याद आ जाएगी उसे।"},
    {"id": 25, "lang": "hi-IN", "cat": "colloquial",
     "text": "वो आदमी तो हाथ का मैल है, इस पर भरोसा मत करो।"},
    {"id": 26, "lang": "hi-IN", "cat": "colloquial",
     "text": "अरे भाई, चार पैसे कमाने हों तो मेहनत तो करनी ही पड़ेगी।"},

    # ── formal / news-style Hindi ─────────────────────────────────────────────────
    {"id": 27, "lang": "hi-IN", "cat": "formal",
     "text": "भारतीय रिज़र्व बैंक ने रेपो दर में 25 आधार अंकों की वृद्धि की।"},
    {"id": 28, "lang": "hi-IN", "cat": "formal",
     "text": "सर्वोच्च न्यायालय ने याचिकाकर्ता की अपील खारिज कर दी।"},
    {"id": 29, "lang": "hi-IN", "cat": "formal",
     "text": "केंद्र सरकार ने आयकर की नई व्यवस्था में महत्वपूर्ण बदलाव किए हैं।"},
    {"id": 30, "lang": "hi-IN", "cat": "formal",
     "text": "प्रधानमंत्री ने नई दिल्ली में अंतर्राष्ट्रीय व्यापार सम्मेलन का उद्घाटन किया।"},
]

# Human-readable category labels (used by the UI)
CAT_LABELS = {
    "hinglish":   "Hinglish कोड-मिक्स",
    "numbers":    "नंबर / OTP / राशि",
    "banking":    "बैंकिंग व वित्त",
    "medical":    "चिकित्सा",
    "addresses":  "पते व स्थान",
    "govt":       "सरकारी ID",
    "colloquial": "बोलचाल / मुहावरे",
    "formal":     "औपचारिक हिंदी",
}


# ---------------------------------------------------------------- HTTP helpers
def _key():
    k = (os.environ.get("SARVAM_API_KEY") or os.environ.get("Sarvam_API_key") or "").strip()
    if not k:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return k


def _post(path, body=None, headers=None, timeout=45):
    h = {"api-subscription-key": _key()}
    h.update(headers or {})
    req = urllib.request.Request(API + path, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"{path} HTTP {e.code}: {detail}")


def _post_json(path, payload, extra_headers=None, timeout=45):
    h = {"Content-Type": "application/json"}
    h.update(extra_headers or {})
    return _post(path, json.dumps(payload).encode(), h, timeout)


def _post_multipart(path, fields, filename, filedata, mime="audio/wav"):
    b = "----kasauti" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
              f"Content-Type: {mime}\r\n\r\n".encode())
    out.write(filedata)
    out.write(f"\r\n--{b}--\r\n".encode())
    return _post(path, out.getvalue(), {"Content-Type": f"multipart/form-data; boundary={b}"})


# ---------------------------------------------------------------- Sarvam calls
def tts(text, lang, model):
    payload = {"text": text, "language_code": lang, "model": model,
               "speech_sample_rate": 16000, "output_audio_codec": "wav"}
    t = time.time()
    r = _post_json("/text-to-speech", payload)
    return base64.b64decode(r["audios"][0]), round(time.time() - t, 2)


def stt(wav_bytes, lang, model):
    t = time.time()
    r = _post_multipart("/speech-to-text", {"model": model, "language_code": lang}, "case.wav", wav_bytes)
    return r.get("transcript", ""), round(time.time() - t, 2)


_JUDGE_MODELS = [m for m in [os.environ.get("JUDGE_MODEL"), "sarvam-105b", "sarvam-m"] if m]
_judge_ok = None


def judge(reference, hypothesis, lang):
    """LLM-as-judge: does the transcript preserve *meaning*?

    Special focus for Hindi:
    - Devanagari ↔ Roman transliteration is acceptable
    - Number words (पाँच हज़ार ↔ 5000) are equivalent
    - Amount formatting (₹2,450 ↔ दो हज़ार चार सौ पचास) is fine
    - Wrong digits in OTP/phone/Aadhaar = major error
    - Wrong drug name or dosage = major error
    """
    global _judge_ok
    prompt = (
        "You grade Hindi speech-to-text output. Compare the REFERENCE (what was spoken) with the TRANSCRIPT.\n"
        "Rules for Hindi:\n"
        "- Devanagari and Roman transliteration of the same word are EQUIVALENT (e.g. 'meeting' == 'मीटिंग').\n"
        "- Number words and digits are EQUIVALENT (e.g. 'पाँच हज़ार' == '5000', '₹2,450' == 'दो हज़ार चार सौ पचास').\n"
        "- Punctuation and casing differences are IGNORED.\n"
        "- PENALISE: wrong digit in OTP/phone/Aadhaar/PAN, wrong drug name or dosage, wrong place name, "
        "dropped or changed meaning, wrong amount.\n"
        f"Language: {lang}\nREFERENCE: {reference}\nTRANSCRIPT: {hypothesis}\n\n"
        'Do not explain. Reply ONLY with compact JSON: '
        '{"score": <0-10 integer>, "pass": <true if score>=7>, "issue": "<max 15 words, English>"}'
    )
    models = ([_judge_ok] if _judge_ok else _JUDGE_MODELS[:1]) * 2
    last = None
    for m in models:
        try:
            r = _post_json("/v1/chat/completions",
                           {"model": m, "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0, "max_tokens": 1500},
                           {"Authorization": "Bearer " + _key()}, timeout=18)
            msg = r["choices"][0]["message"]
            txt = "\n".join(v for v in msg.values() if isinstance(v, str))
            txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
            found = re.findall(r"\{[^{}]*\"score\"[^{}]*\}", txt, flags=re.S)
            if not found:
                raise ValueError("no JSON verdict in reply: " + txt.strip()[:80])
            data = json.loads(found[0])
            score = int(float(data.get("score", 0)))
            pv = data.get("pass", score >= 7)
            if isinstance(pv, str):
                pv = pv.strip().lower() in ("true", "yes", "1")
            _judge_ok = m
            return {"score": score, "pass": bool(pv),
                    "issue": str(data.get("issue", ""))[:120], "model": m}
        except Exception as e:
            last = str(e)
    return {"score": None, "pass": None, "issue": f"judge error: {last}"[:160], "model": None}


# ---------------------------------------------------------------- audio + metrics
def add_noise(wav_bytes, snr_db, seed=7):
    """Mix white noise at a target SNR (dB). Same seed => identical audio for every model."""
    if snr_db is None:
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes)) as w:
            params = w.getparams()
            frames = w.readframes(w.getnframes())
    except Exception:
        return wav_bytes
    if params.sampwidth != 2 or not frames:
        return wav_bytes
    n = len(frames) // 2
    s = struct.unpack(f"<{n}h", frames)
    p_sig = sum(x * x for x in s) / max(n, 1)
    sigma = math.sqrt(p_sig / (10 ** (snr_db / 10))) if p_sig else 0
    rng = random.Random(seed)
    g = rng.gauss
    noisy = [max(-32768, min(32767, int(x + g(0, sigma)))) for x in s]
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(struct.pack(f"<{n}h", *noisy))
    return out.getvalue()


def _norm_hindi(t):
    """Normalise Hindi text for WER/CER: NFC, drop nukta, collapse punctuation."""
    t = unicodedata.normalize("NFC", t.lower()).replace("\u093c", "")
    # map Devanagari digits to ASCII for fair comparison
    for i, d in enumerate("०१२३४५६७८९"):
        t = t.replace(d, str(i))
    t = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in t)
    return t.split()


def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(ref, hyp):
    r, h = _norm_hindi(ref), _norm_hindi(hyp)
    return round(_lev(r, h) / max(len(r), 1), 3)


def cer(ref, hyp):
    r, h = "".join(_norm_hindi(ref)), "".join(_norm_hindi(hyp))
    return round(_lev(list(r), list(h)) / max(len(r), 1), 3)


# ---------------------------------------------------------------- word-level diff for UI
def word_diff(ref, hyp):
    """Return a list of (word, tag) where tag is 'ok'|'sub'|'del'|'ins'.
    Used by the frontend for per-word highlighting."""
    r, h = _norm_hindi(ref), _norm_hindi(hyp)
    # compute alignment via Levenshtein backtrack
    m, n = len(r), len(h)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            dp[i][j] = min(dp[i-1][j] + 1, dp[i][j-1] + 1, dp[i-1][j-1] + (r[i-1] != h[j-1]))
    # backtrack
    ops = []
    i, j = m, n
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i-1][j-1] + (r[i-1] != h[j-1]):
            ops.append(("ok" if r[i-1] == h[j-1] else "sub", h[j-1]))
            i -= 1; j -= 1
        elif i > 0 and dp[i][j] == dp[i-1][j] + 1:
            ops.append(("del", r[i-1]))
            i -= 1
        else:
            ops.append(("ins", h[j-1]))
            j -= 1
    ops.reverse()
    return ops


# ---------------------------------------------------------------- one test case
def run_case(case, tts_model="bulbul:v3", base="saaras:v3", cand="saaras:v4",
             snr=None, want_audio=True, want_diff=True):
    lang, text = case["lang"], case["text"]
    try:
        clean, t_tts = tts(text, lang, tts_model)
    except Exception as e:
        return {"case": case, "error": f"TTS failed: {e}"}
    audio = add_noise(clean, snr)

    def leg(model):
        try:
            hyp, lat = stt(audio, lang, model)
        except Exception as e:
            return {"model": model, "error": str(e)[:200]}
        j = judge(text, hyp, lang)
        result = {"model": model, "transcript": hyp, "latency_s": lat,
                  "wer": wer(text, hyp), "cer": cer(text, hyp), "judge": j}
        if want_diff:
            result["diff"] = word_diff(text, hyp)
        return result

    with ThreadPoolExecutor(2) as ex:
        a, b = ex.map(leg, [base, cand])
    res = {"case": case, "tts_model": tts_model, "tts_latency_s": t_tts,
           "snr_db": snr, "baseline": a, "candidate": b,
           "cat_label": CAT_LABELS.get(case.get("cat", ""), case.get("cat", ""))}
    if want_audio:
        res["audio_b64"] = base64.b64encode(audio).decode()
    return res


# ---------------------------------------------------------------- Vercel handler
class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _params(self):
        q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        if self.command == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                try:
                    q.update(json.loads(self.rfile.read(n).decode()))
                except Exception:
                    pass
        return q

    def _handle(self):
        p = self._params()
        if p.get("suite") or not (p.get("id") or p.get("text")):
            return self._send(200, {"suite": SUITE, "cat_labels": CAT_LABELS})
        if p.get("text"):
            case = {"id": 0, "lang": p.get("lang", "hi-IN"), "cat": "custom", "text": str(p["text"])[:400]}
        else:
            case = next((c for c in SUITE if str(c["id"]) == str(p["id"])), None)
            if not case:
                return self._send(404, {"error": "unknown case id"})
        snr = p.get("snr")
        snr = None if snr in (None, "", "clean", "none") else float(snr)
        try:
            out = run_case(case, p.get("tts", "bulbul:v3"), p.get("base", "saaras:v3"),
                           p.get("cand", "saaras:v4"), snr,
                           str(p.get("audio", "1")) != "0",
                           str(p.get("diff", "1")) != "0")
            self._send(200, out)
        except Exception as e:
            self._send(500, {"error": str(e)[:300], "case": case})

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
