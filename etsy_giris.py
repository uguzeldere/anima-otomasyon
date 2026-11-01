"""Etsy'ye bir kerelik giris (OAuth). Lokal calistir: python etsy_giris.py

Tarayici acilir, Etsy'de "Allow" dersin, refresh token .env'e (ETSY_REFRESH_TOKEN) yazilir.
Sonra GitHub'a: gh secret set -f .env
Etsy uygulama ayarlarinda Callback URL olarak su ekli olmali: http://localhost:3003/callback
"""
import base64
import hashlib
import http.server
import os
import secrets
import urllib.parse
import webbrowser
from pathlib import Path

import requests

import etsy

YONLENDIRME = "http://localhost:3003/callback"
ENV = Path(__file__).parent / ".env"


def env_yukle():
    for satir in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in satir and not satir.startswith("#"):
            k, v = satir.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    env_yukle()
    dogrulayici = secrets.token_urlsafe(48)
    meydan = base64.urlsafe_b64encode(hashlib.sha256(dogrulayici.encode()).digest()).rstrip(b"=").decode()
    durum = secrets.token_urlsafe(16)
    url = "https://www.etsy.com/oauth/connect?" + urllib.parse.urlencode({
        "response_type": "code", "redirect_uri": YONLENDIRME, "scope": "listings_r listings_w",
        "client_id": os.environ["ETSY_KEYSTRING"], "state": durum,
        "code_challenge": meydan, "code_challenge_method": "S256",
    })
    gelen = {}

    class Karsila(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            gelen.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Tamam, bu sekmeyi kapatabilirsin.".encode())

        def log_message(self, *a):
            pass

    print("Tarayicida Etsy acilacak, 'Allow Access' de.\n", url)
    webbrowser.open(url)
    with http.server.HTTPServer(("localhost", 3003), Karsila) as s:
        while "code" not in gelen and "error" not in gelen:
            s.handle_request()
    if gelen.get("state") != durum or "code" not in gelen:
        raise SystemExit(f"Giris basarisiz: {gelen}")

    r = requests.post(etsy.TOKEN_URL, data={
        "grant_type": "authorization_code", "client_id": os.environ["ETSY_KEYSTRING"],
        "redirect_uri": YONLENDIRME, "code": gelen["code"], "code_verifier": dogrulayici,
    }, timeout=60)
    r.raise_for_status()
    etsy.refresh_kaydet(r.json()["refresh_token"])
    print("OK. Refresh token .env'e kaydedildi.")


if __name__ == "__main__":
    main()
