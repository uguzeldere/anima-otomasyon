"""Mockup'tan dikey Pinterest gorseli (1000x1500) uretir.

sablon/pin.html icine foto + yazi doldurulur, headless Chrome/Edge ile ekran goruntusu alinir.

Lokal deneme:
  python pin_gorsel.py tasarimlar/bear/holding-1.jpg "Gift for Dad" bear
"""
import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

KOK = Path(__file__).parent
SABLON = KOK / "sablon" / "pin.html"

# urun -> (zemin, vurgu)
RENKLER = {
    "bear": ("#1a1310", "#f2b33d"),
    "giraffe": ("#8c1420", "#ffd27a"),
    "halloween": ("#1d1230", "#ff8a2a"),
}
VARSAYILAN_RENK = ("#1a1310", "#f2b33d")

TARAYICILAR = [
    os.environ.get("TARAYICI", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
]


def tarayici():
    for t in TARAYICILAR:
        if t and (Path(t).exists() or shutil.which(t)):
            return shutil.which(t) or t
    sys.exit("Chrome/Edge bulunamadi (TARAYICI ortam degiskeni ile yol verilebilir).")


def parcala(baslik):
    """Basligi buyuk (Anton) ve el yazisi (Pacifico) kismina ayirir.
    'Christmas Gift for Coffee Lovers' -> ('Christmas Gift', 'for Coffee Lovers')"""
    for ayrac in (" – ", " - ", " | "):
        baslik = baslik.split(ayrac)[0]
    kelimeler = baslik.split()
    for bag in ("for", "with", "to", "&"):
        if bag in [k.lower() for k in kelimeler[1:]]:
            i = [k.lower() for k in kelimeler].index(bag, 1)
            return " ".join(kelimeler[:i]), " ".join(kelimeler[i:])
    if len(kelimeler) <= 3:
        return baslik, ""
    yari = (len(kelimeler) + 1) // 2
    return " ".join(kelimeler[:yari]), " ".join(kelimeler[yari:])


def boyutlar(ana, el):
    # uzun yazi -> kucuk font (Anton dar, ~0.45em/karakter)
    ana_px = max(84, min(150, int(880 / max(1, len(ana) * 0.47))))
    el_px = max(50, min(78, int(880 / max(1, len(el) * 0.5)))) if el else 0
    return ana_px, el_px


def pin_yap(kaynak, baslik, urun="bear", hedef=None, parcalar=None):
    ana, el = parcalar or parcala(baslik)
    ana_px, el_px = boyutlar(ana, el)
    zemin, vurgu = RENKLER.get(urun, VARSAYILAN_RENK)
    sayfa = (SABLON.read_text(encoding="utf-8")
             .replace("{{FOTO}}", Path(kaynak).resolve().as_uri())
             .replace("{{ANA}}", html.escape(ana)).replace("{{EL}}", html.escape(el))
             .replace("{{ANA_PX}}", str(ana_px)).replace("{{EL_PX}}", str(el_px))
             .replace("{{ZEMIN}}", zemin).replace("{{VURGU}}", vurgu))

    hedef = Path(hedef or Path(kaynak).with_suffix(".pin.jpg"))
    hedef.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as gecici:
        gecici_html = SABLON.parent / f"_gecici_{os.getpid()}.html"  # fontlar goreli yoldan yuklensin
        png = Path(gecici) / "pin.png"
        gecici_html.write_text(sayfa, encoding="utf-8")
        try:
            subprocess.run(
                [tarayici(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
                 "--force-device-scale-factor=1", "--window-size=1000,1500",
                 "--allow-file-access-from-files", "--virtual-time-budget=3000",
                 f"--user-data-dir={gecici}/profil", f"--screenshot={png}", gecici_html.resolve().as_uri()],
                check=True, capture_output=True, timeout=120,
            )
        finally:
            gecici_html.unlink(missing_ok=True)
        Image.open(png).convert("RGB").crop((0, 0, 1000, 1500)).save(
            hedef, "JPEG", quality=90, optimize=True, progressive=True)
    return hedef


if __name__ == "__main__":
    print(pin_yap(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or ["bear"])))
