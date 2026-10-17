#!/usr/bin/env python3
"""Kasauti CI gate — हिंदी-focused regression harness.

Runs the full 30-case Hindi suite (baseline STT vs candidate STT, same audio)
and exits 1 if the candidate regresses in any of 8 Hindi-specific categories.
Drop it into any CI pipeline — see .github/workflows/kasauti.yml.

  python harness.py --url https://<your-deployment>.vercel.app --snr 10 --threshold 0.05
  python harness.py --local            # call Sarvam directly (needs SARVAM_API_KEY)
  python harness.py --local --cat banking  # run only one category
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ANSI colours
try:
    import os as _os
    _colour = _os.name != "nt" or "ANSICON" in _os.environ or "WT_SESSION" in _os.environ
except Exception:
    _colour = False

def _c(code, text): return f"\033[{code}m{text}\033[0m" if _colour else text
def red(t):    return _c("1;31", t)
def green(t):  return _c("1;32", t)
def yellow(t): return _c("1;33", t)
def cyan(t):   return _c("36",   t)
def bold(t):   return _c("1",    t)
def dim(t):    return _c("2",    t)

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


def remote_runner(url, args):
    def run(case):
        q = urllib.parse.urlencode({
            "id": case["id"], "tts": args.tts, "base": args.base,
            "cand": args.cand, "snr": args.snr or "clean", "audio": 0, "diff": 0
        })
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/run?{q}", timeout=120) as r:
            return json.loads(r.read().decode())
    with urllib.request.urlopen(f"{url.rstrip('/')}/api/run?suite=1", timeout=30) as r:
        suite = json.loads(r.read().decode())["suite"]
    return suite, run


def local_runner(args):
    sys.path.insert(0, str(Path(__file__).parent / "api"))
    import run as core  # noqa: E402
    snr = float(args.snr) if args.snr else None
    suite = core.SUITE
    if args.cat:
        suite = [c for c in suite if c["cat"] == args.cat]
        if not suite:
            sys.exit(f"Unknown category '{args.cat}'. Valid: {list(CAT_LABELS)}")
    return suite, lambda c: core.run_case(c, args.tts, args.base, args.cand, snr, want_audio=False, want_diff=False)


def gate(results, threshold):
    by_cat = defaultdict(lambda: {"b_wer": [], "c_wer": [], "b_pass": 0, "c_pass": 0, "n": 0, "errors": 0})
    for r in results:
        cat = r.get("case", {}).get("cat", "unknown")
        if r.get("error"):
            by_cat[cat]["errors"] += 1
            continue
        if r.get("baseline", {}).get("error") or r.get("candidate", {}).get("error"):
            by_cat[cat]["errors"] += 1
            continue
        s = by_cat[cat]
        s["n"] += 1
        s["b_wer"].append(r["baseline"]["wer"])
        s["c_wer"].append(r["candidate"]["wer"])
        bj = r["baseline"]["judge"].get("pass")
        cj = r["candidate"]["judge"].get("pass")
        if bj is not None and cj is not None:
            s["b_pass"] += bool(bj)
            s["c_pass"] += bool(cj)

    rows, failed = [], False
    for cat, s in sorted(by_cat.items()):
        if s["n"] == 0:
            rows.append((cat, 0, None, None, s["b_pass"], s["c_pass"], "error", s["errors"]))
            continue
        bw = sum(s["b_wer"]) / s["n"]
        cw = sum(s["c_wer"]) / s["n"]
        regress = (cw - bw) > threshold or s["c_pass"] < s["b_pass"]
        failed |= regress
        rows.append((cat, s["n"], bw, cw, s["b_pass"], s["c_pass"],
                     "REGRESSION" if regress else "ok", s["errors"]))
    return rows, failed


def print_header(base, cand, tts, snr):
    snr_str = f"{snr} dB" if snr else "clean"
    print()
    print(bold("╔══════════════════════════════════════════════════════════════╗"))
    print(bold("║") + "  कसौटी  — हिंदी STT Regression Gate                        " + bold("║"))
    print(bold("╚══════════════════════════════════════════════════════════════╝"))
    print(f"  {dim('Baseline:')}  {cyan(base)}")
    print(f"  {dim('Candidate:')} {cyan(cand)}")
    print(f"  {dim('TTS:')}       {cyan(tts)}")
    print(f"  {dim('Noise:')}     {cyan(snr_str)}")
    print()


def main():
    ap = argparse.ArgumentParser(description="Kasauti — Hindi STT regression gate")
    ap.add_argument("--url", help="deployed Kasauti URL")
    ap.add_argument("--local", action="store_true", help="run locally via Sarvam API")
    ap.add_argument("--tts",  default="bulbul:v3")
    ap.add_argument("--base", default="saaras:v3")
    ap.add_argument("--cand", default="saaras:v4")
    ap.add_argument("--snr",  default="10", help="noise SNR in dB, or '' for clean audio")
    ap.add_argument("--threshold", type=float, default=0.05,
                    help="max allowed WER increase per category (default 0.05)")
    ap.add_argument("--cat",  default="", help="run only one category (e.g. banking)")
    ap.add_argument("--workers", type=int, default=4, help="parallel workers (default 4)")
    ap.add_argument("--out",  default="kasauti_report.json")
    args = ap.parse_args()

    if not args.local and not args.url:
        ap.error("Provide --local or --url <deployment>")

    suite, run = local_runner(args) if args.local else remote_runner(args.url, args)

    print_header(args.base, args.cand, args.tts, args.snr)
    print(f"  {len(suite)} test cases queued, {args.workers} parallel workers…\n")

    # run with live feedback
    results = []
    lock_printed = []
    def run_and_print(case):
        r = run(case)
        if not r.get("case"):
            r["case"] = case
        done = len(lock_printed) + 1
        lock_printed.append(1)
        cat = case["cat"]
        label = CAT_LABELS.get(cat, cat)
        txt = case["text"][:40] + ("…" if len(case["text"]) > 40 else "")
        if r.get("error"):
            status = red("ERR")
        else:
            b, k = r.get("baseline", {}), r.get("candidate", {})
            if b.get("error") or k.get("error"):
                status = yellow("WARN")
            else:
                delta = (k.get("wer", 0) or 0) - (b.get("wer", 0) or 0)
                status = red(f"Δ+{delta:.3f}") if delta > args.threshold else green(f"Δ{delta:+.3f}")
        print(f"  [{done:>2}/{len(suite)}] {status}  {dim(label):<22}  {txt}")
        return r

    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(run_and_print, suite))

    Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    rows, failed = gate(results, args.threshold)

    # ─── Category summary table ───────────────────────────────────────────────
    print()
    print(bold("  CATEGORY SUMMARY"))
    print("  " + "─" * 78)
    hdr = (f"  {'केटेगरी':<24} {'n':>3}  {'WER base':>8}  {'WER cand':>8}  "
           f"{'Δ WER':>7}  {'judge b':>7}  {'judge c':>7}  verdict")
    print(dim(hdr))
    print("  " + "─" * 78)

    for row in rows:
        cat, n, bw, cw, bp, cp, verdict, errs = row
        label = CAT_LABELS.get(cat, cat)
        if verdict == "error":
            print(f"  {label:<24} {n:>3}  {'—':>8}  {'—':>8}  {'—':>7}  "
                  f"{'—':>7}  {'—':>7}  {yellow('ERR x' + str(errs))}")
            continue
        d = (cw - bw)
        d_str = f"{d:+.3f}"
        bj = f"{bp}/{n}"
        cj = f"{cp}/{n}"
        v_str = red("REGRESSION") if verdict == "REGRESSION" else green("ok")
        d_col = red(d_str) if d > args.threshold else green(d_str)
        line = (f"  {label:<24} {n:>3}  {bw:>8.3f}  {cw:>8.3f}  "
                f"{d_col:>7}  {bj:>7}  {cj:>7}  {v_str}")
        print(line)

    print("  " + "─" * 78)

    # ─── Error summary ────────────────────────────────────────────────────────
    errs = [r for r in results if r.get("error") or
            r.get("baseline", {}).get("error") or r.get("candidate", {}).get("error")]
    if errs:
        print(f"\n  {yellow(f'{len(errs)} case(s) had errors')} — see {args.out} for details")

    # ─── Final gate ───────────────────────────────────────────────────────────
    print()
    if failed:
        print(bold(red("  ✗ GATE: FAIL — candidate regressed, release blocked")))
    else:
        print(bold(green("  ✓ GATE: PASS — no category regressed beyond threshold")))
    print(f"  Report written to {args.out}\n")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
