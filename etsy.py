"""Etsy Open API v3 yardimcilari.

Okuma (ilanlar, resimler, arama): sadece ETSY_KEYSTRING + ETSY_SHARED_SECRET.
Yazma (baslik/etiket): OAuth refresh token (ETSY_REFRESH_TOKEN). Ilk token: python etsy_giris.py
"""
import os
import subprocess
import time
from pathlib import Path

import requests

KOK = Path(__file__).parent
API = "https://openapi.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
SHOP_ID = 45455594


def _anahtar():
    return f"{os.environ['ETSY_KEYSTRING']}:{os.environ['ETSY_SHARED_SECRET']}"


def _istek(metod, yol, token=None, **kw):
    h = {"x-api-key": _anahtar()}
    if token:
        h["Authorization"] = f"Bearer {token}"
    for deneme in range(4):
        r = requests.request(metod, f"{API}{yol}", headers=h, timeout=60, **kw)
        if r.status_code == 429:  # hiz siniri
            time.sleep(2 ** deneme)
            continue
        if not r.ok:
            raise RuntimeError(f"Etsy {metod} {yol} -> {r.status_code}: {r.text[:300]}")
        return r.json()
    raise RuntimeError(f"Etsy hiz siniri: {yol}")


def aktif_ilanlar():
    return _istek("GET", f"/shops/{SHOP_ID}/listings/active", params={"limit": 100})["results"]


def ilan_resimleri(listing_id):
    return [r["url_fullxfull"] for r in sorted(
        _istek("GET", f"/listings/{listing_id}/images")["results"], key=lambda r: r["rank"])]


def arama_etiketleri(kelime, adet=25):
    """Etsy aramasinda ust siradaki ilanlarin etiketleri (rakip/trend fikri icin)."""
    sonuc = _istek("GET", "/listings/active", params={"keywords": kelime, "sort_on": "score", "limit": adet})
    return [t.lower() for l in sonuc["results"] for t in l.get("tags", [])]


# ---- OAuth token ----
# Refresh token ETSY_REFRESH_TOKEN'da durur (lokal: .env, Actions: repo secret).
# Etsy her yenilemede yeni refresh token verir; yenisi hemen geri yazilir.

ENV = KOK / ".env"


def refresh_kaydet(token):
    if os.environ.get("GITHUB_ACTIONS"):
        # GH_TOKEN: secrets yazma yetkili PAT (GH_SECRET_TOKEN secret'i)
        subprocess.run(["gh", "secret", "set", "ETSY_REFRESH_TOKEN", "-R", os.environ["GITHUB_REPOSITORY"]],
                       input=token, text=True, check=True, capture_output=True)
    else:
        satirlar = [l for l in ENV.read_text(encoding="utf-8").splitlines() if not l.startswith("ETSY_REFRESH_TOKEN=")]
        ENV.write_text("\n".join(satirlar + [f"ETSY_REFRESH_TOKEN={token}"]) + "\n", encoding="utf-8")
    os.environ["ETSY_REFRESH_TOKEN"] = token


def erisim_tokeni():
    """Refresh token ile yeni access token alir; yeni refresh token'i saklar."""
    eski = os.environ.get("ETSY_REFRESH_TOKEN")
    if not eski:
        raise RuntimeError("ETSY_REFRESH_TOKEN yok. Bir kere lokal calistir: python etsy_giris.py")
    r = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": os.environ["ETSY_KEYSTRING"],
        "refresh_token": eski,
    }, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Etsy token yenilenemedi ({r.status_code}): {r.text[:300]}. Tekrar: python etsy_giris.py")
    yeni = r.json()
    refresh_kaydet(yeni["refresh_token"])
    return yeni["access_token"]


def ilan_guncelle(token, listing_id, **alanlar):
    return _istek("PATCH", f"/shops/{SHOP_ID}/listings/{listing_id}", token=token, json=alanlar)
