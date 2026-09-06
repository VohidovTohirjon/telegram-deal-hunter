"""Saqlangan transkriptlarga post-processing qo'llab qayta baholash."""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

from run_bench import wer, kw_hit  # noqa: E402
sys.path.insert(0, BASE)
from xalyava.stt import normalize_transcript  # noqa: E402


def main():
    results = json.load(open(os.path.join(BASE, "results.json")))
    manifest = json.load(open(os.path.join(BASE, "manifest.json")))
    refs = {(m["key"], m["voice"], m["fx"]): m["ref"] for m in manifest}
    print(f"{'MODEL':30} {'WER':>6} {'WER+pp':>7} {'KW':>5} {'KW+pp':>6} {'s/klip':>7}")
    table = []
    for name, r in results.items():
        wers, kws = [], []
        for row in r["rows"]:
            ref = refs.get((row["key"], row["voice"], row["fx"]))
            if ref is None:
                continue
            hyp_pp = normalize_transcript(row["hyp"])
            wers.append(wer(ref, hyp_pp))
            k = kw_hit(row["key"], hyp_pp)
            if k is not None:
                kws.append(k)
        wer_pp = round(sum(wers) / len(wers), 3) if wers else 1.0
        kw_pp = round(sum(kws) / len(kws), 3) if kws else 0.0
        table.append((name, r["avg_wer"], wer_pp, r["kw_acc"], kw_pp,
                      r["sec_per_clip"]))
        print(f"{name:30} {r['avg_wer']:>6} {wer_pp:>7} "
              f"{r['kw_acc']:>5} {kw_pp:>6} {r['sec_per_clip']:>7}")
    json.dump({t[0]: {"wer": t[1], "wer_pp": t[2], "kw": t[3], "kw_pp": t[4],
                      "sec": t[5]} for t in table},
              open(os.path.join(BASE, "final_scores.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
