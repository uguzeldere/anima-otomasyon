"""Etsy Open API v3 yardimcilari.

Okuma (ilanlar, resimler, arama): sadece ETSY_KEYSTRING + ETSY_SHARED_SECRET.
Yazma (baslik/etiket): OAuth token. Token sifreli olarak durum/etsy_token.enc'de durur
(public repo), anahtari ETSY_TOKEN_ANAHTAR secret'inda. Ilk token: python etsy_giris.py
"""
import json
import os
import time
from pathlib import Path

import requests
from cryptography.fernet import Fernet

KOK = Path(__file__).parent
API = "https://openapi.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
TOKEN_DOSYA = KOK / "durum" / "etsy_token.enc"
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


# ---- OAuth token (sifreli dosyada) ----

def _fernet():
    return Fernet(os.environ["ETSY_TOKEN_ANAHTAR"].encode())


def token_kaydet(veri):
    TOKEN_DOSYA.parent.mkdir(exist_ok=True)
    veri["alindi"] = int(time.time())
    TOKEN_DOSYA.write_bytes(_fernet().encrypt(json.dumps(veri).encode()))


def erisim_tokeni():
    """Refresh token ile yeni access token alir; yeni refresh token'i dosyaya yazar."""
    if not TOKEN_DOSYA.exists():
        raise RuntimeError("Etsy token yok. Bir kere lokal calistir: python etsy_giris.py")
    eski = json.loads(_fernet().decrypt(TOKEN_DOSYA.read_bytes()))
    r = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": os.environ["ETSY_KEYSTRING"],
        "refresh_token": eski["refresh_token"],
    }, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Etsy token yenilenemedi ({r.status_code}): {r.text[:300]}. Tekrar: python etsy_giris.py")
    yeni = r.json()
    token_kaydet(yeni)
    return yeni["access_token"]


def ilan_guncelle(token, listing_id, **alanlar):
    return _istek("PATCH", f"/shops/{SHOP_ID}/listings/{listing_id}", token=token, json=alanlar)
