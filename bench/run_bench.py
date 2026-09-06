"""O'zbek STT benchmark: WER + mahsulot kalit-so'z aniqligi + tezlik."""
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
sys.path.insert(0, ROOT)

VOSK_MODEL = os.path.join(ROOT, "data", "models", "vosk-model-small-uz-0.22")

# har gap uchun qidiruvga kerakli kalit so'zlar
KEYWORDS = {
    "s1_hdmi": ["hdmi", "kabel"],
    "s2_iphone": ["iphone"],
    "s3_noutbuk": ["noutbuk", "toshkent"],
    "s4_quloqchin": ["quloqchin", "airpods", "jbl"],
    "s5_robot": ["robot", "changyutgich"],
    "s6_playstation": ["playstation"],
    "s7_uzun": ["televizor", "samsung", "lg"],
    "s8_mavhum": [],
}

_APOS = re.compile(r"[’'ʻ`´ʼ‘]")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_CYR = re.compile(r"[а-яё]", re.IGNORECASE)


def norm(text):
    from xalyava.analyze import _latinize_cyr
    text = text or ""
    if _CYR.search(text):
        text = _latinize_cyr(text)
    text = _APOS.sub("", text.lower())
    text = _PUNCT.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def wer(ref, hyp):
    r, h = norm(ref).split(), norm(hyp).split()
    # Levenshtein so'z darajasida
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1,
                          d[i-1][j-1] + (r[i-1] != h[j-1]))
    return d[len(r)][len(h)] / max(len(r), 1)


def kw_hit(key, hyp):
    kws = KEYWORDS.get(key, [])
    if not kws:
        return None
    h = norm(hyp)
    return sum(1 for k in kws if k in h) / len(kws)


# ------------------------------------------------------------ engines

def engine_vosk():
    import wave
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    model = Model(VOSK_MODEL)

    def run(path):
        wf = wave.open(path, "rb")
        rec = KaldiRecognizer(model, wf.getframerate())
        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)
        return json.loads(rec.FinalResult()).get("text", "")
    return run


def engine_fwhisper(model_id, language="uz"):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_id, device="cpu", compute_type="int8")

    def run(path):
        segs, _ = model.transcribe(path, language=language, beam_size=5,
                                   vad_filter=False)
        return " ".join(s.text for s in segs)
    return run


ENGINES = {
    "vosk-small-uz": engine_vosk,
    "whisper-small-vanilla": lambda: engine_fwhisper("small"),
    "whisper-small-uz-ft": lambda: engine_fwhisper(
        "aslon1213/whisper-small-uz-with-uzbekvoice-ct2"),
    "whisper-lv3turbo-uz-ft": lambda: engine_fwhisper(
        "hostmepanda/whisper-large-v3-turbo-uzbek-ct2"),
    "whisper-small-uz-ft2": lambda: engine_fwhisper(
        "Bahrom1996/ct2_whisper_small_uzbek"),
    "whisper-medium-uz-ft": lambda: engine_fwhisper(
        "Bahrom1996/ct2_whisper_medum_uzbek"),
}


def main():
    only = sys.argv[1:] or list(ENGINES)
    manifest = json.load(open(os.path.join(BASE, "manifest.json")))
    results = {}
    out_path = os.path.join(BASE, "results.json")
    if os.path.exists(out_path):
        results = json.load(open(out_path))
    for name in only:
        print(f"=== {name} yuklanmoqda...", flush=True)
        t0 = time.time()
        try:
            run = ENGINES[name]()
        except Exception as e:
            print(f"{name} YUKLANMADI: {e}", flush=True)
            continue
        load_s = time.time() - t0
        rows = []
        t_total = 0.0
        for m in manifest:
            t1 = time.time()
            try:
                hyp = run(m["file"])
            except Exception as e:
                hyp = ""
                print("  xato:", m["file"], e, flush=True)
            dt = time.time() - t1
            t_total += dt
            rows.append({
                "key": m["key"], "voice": m["voice"], "fx": m["fx"],
                "wer": round(wer(m["ref"], hyp), 3),
                "kw": kw_hit(m["key"], hyp),
                "hyp": hyp.strip(),
            })
        wers = [r["wer"] for r in rows]
        kws = [r["kw"] for r in rows if r["kw"] is not None]
        results[name] = {
            "load_s": round(load_s, 1),
            "avg_wer": round(sum(wers) / len(wers), 3),
            "kw_acc": round(sum(kws) / len(kws), 3),
            "sec_per_clip": round(t_total / len(rows), 2),
            "rows": rows,
        }
        json.dump(results, open(out_path, "w"), ensure_ascii=False, indent=1)
        print(f"{name}: WER={results[name]['avg_wer']} "
              f"KW={results[name]['kw_acc']} "
              f"t={results[name]['sec_per_clip']}s/klip", flush=True)


def engine_elevenlabs():
    from xalyava.stt import _transcribe_elevenlabs
    return _transcribe_elevenlabs


ENGINES["elevenlabs-scribe"] = engine_elevenlabs


if __name__ == "__main__":
    main()
