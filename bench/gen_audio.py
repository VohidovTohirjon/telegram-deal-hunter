"""STT benchmark uchun o'zbekcha test audiolar yaratish (Edge TTS 2 ovoz + ffmpeg variantlari)."""
import asyncio
import json
import os
import subprocess

import edge_tts

BASE = os.path.dirname(os.path.abspath(__file__))
AUDIO = os.path.join(BASE, "audio")
os.makedirs(AUDIO, exist_ok=True)

SENTENCES = {
    "s1_hdmi": "Menga arzon HDMI kabel kerak, yangi bo'lsin.",
    "s2_iphone": "iPhone o'n beshning narxi qancha ekan, ishlatilganini qidirib bering.",
    "s3_noutbuk": "Assalomu alaykum, menga Toshkent shahrida ishlatilgan noutbuk kerak, byudjetim besh million so'm atrofida.",
    "s4_quloqchin": "Simsiz quloqchin izlayapman, AirPods yoki JBL bo'lsa ham bo'ladi.",
    "s5_robot": "Robot changyutgich arzonga bormi, uyga kerak edi.",
    "s6_playstation": "PlayStation besh qidiryapman, ikkita joystigi bilan bo'lsin.",
    "s7_uzun": "Bugun ob-havo yaxshi ekan, mayli, xullas menga bitta yaxshi televizor kerak edi, ellik besh dyuymli bo'lsa zo'r bo'lardi, Samsung yoki LG farqi yo'q.",
    "s8_mavhum": "Hmm nima desam ekan, bilmadim, shunchaki ko'rmoqchi edim o'zi.",
}

VOICES = {
    "madina": "uz-UZ-MadinaNeural",
    "sardor": "uz-UZ-SardorNeural",
}

# qo'shimcha akustik variantlar (tabiiy sharoitni taqlid qilish)
FX = {
    "toza": None,
    "tez": "asetrate=24000*1.1,aresample=16000,atempo=1.05",
    "shovqin": None,  # maxsus ishlanadi
}


async def tts(text, voice, path):
    await edge_tts.Communicate(text, voice).save(path)


def main():
    manifest = []
    for key, text in SENTENCES.items():
        for vkey, voice in VOICES.items():
            mp3 = os.path.join(AUDIO, f"{key}__{vkey}.mp3")
            if not os.path.exists(mp3):
                asyncio.run(tts(text, voice, mp3))
            # toza va tez variantlar
            for fxname, af in FX.items():
                wav = os.path.join(AUDIO, f"{key}__{vkey}__{fxname}.wav")
                if not os.path.exists(wav):
                    if fxname == "shovqin":
                        subprocess.run([
                            "ffmpeg", "-y", "-loglevel", "error", "-i", mp3,
                            "-filter_complex",
                            "anoisesrc=colour=pink:amplitude=0.05:duration=120[n];"
                            "[0:a][n]amix=inputs=2:duration=first,aresample=16000",
                            "-ac", "1", wav], check=True)
                    else:
                        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3]
                        if af:
                            cmd += ["-af", af]
                        cmd += ["-ar", "16000", "-ac", "1", wav]
                        subprocess.run(cmd, check=True)
                manifest.append({"file": wav, "ref": text, "voice": vkey,
                                 "fx": fxname, "key": key})
    with open(os.path.join(BASE, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"{len(manifest)} ta namuna tayyor")


if __name__ == "__main__":
    main()
