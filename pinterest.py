"""Pinterest API v5 ile dogrudan pin (Buffer'siz yol).

Bir kerelik giris (lokal):  python pinterest.py giris
  Pinterest uygulama ayarlarinda Redirect URI olarak su ekli olmali: http://localhost:3003/callback
  Refresh token .env'e (PINTEREST_REFRESH_TOKEN) yazilir. Sonra: gh secret set -f .env
Test (lokal):  python pinterest.py panolar

Ortam: PINTEREST_APP_ID, PINTEREST_APP_SECRET, PINTEREST_REFRESH_TOKEN
       PINTEREST_API (istege bagli; Trial erisimde sandbox gerekirse https://api-sandbox.pinterest.com/v5)
"""
import base64
import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests

import etsy  # .env / GH secret yazma yardimcisi ortak

YONLENDIRME = "http://localhost:3003/callback"
YETKI = "boards:read,pins:read,pins:write,user_accounts:read"


def api():
    return os.environ.get("PINTEREST_API", "https://api.pinterest.com/v5").rstrip("/")


def _token_istegi(veri):
    r = requests.post("https://api.pinterest.com/v5/oauth/token", data=veri, timeout=60,
                      auth=(os.environ["PINTEREST_APP_ID"], os.environ["PINTEREST_APP_SECRET"]))
    if not r.ok:
        raise RuntimeError(f"Pinterest token hatasi ({r.status_code}): {r.text[:300]}. Tekrar: python pinterest.py giris")
    return r.json()


def erisim_tokeni():
    """Refresh token ile access token alir; yeni refresh token gelirse saklar."""
    eski = os.environ.get("PINTEREST_REFRESH_TOKEN")
    if not eski:
        raise RuntimeError("PINTEREST_REFRESH_TOKEN yok. Bir kere lokal calistir: python pinterest.py giris")
    yeni = _token_istegi({"grant_type": "refresh_token", "refresh_token": eski})
    if yeni.get("refresh_token") and yeni["refresh_token"] != eski:
        etsy.refresh_kaydet(yeni["refresh_token"], "PINTEREST_REFRESH_TOKEN")
    return yeni["access_token"]


def _istek(metod, yol, token, **kw):
    r = requests.request(metod, f"{api()}{yol}", headers={"Authorization": f"Bearer {token}"}, timeout=120, **kw)
    if not r.ok:
        raise RuntimeError(f"Pinterest {metod} {yol} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def panolar(token):
    """[{name, id}] (Buffer'daki pano listesiyle ayni bicim)."""
    sonuc, imlec = [], None
    while True:
        d = _istek("GET", "/boards", token, params={"page_size": 100, **({"bookmark": imlec} if imlec else {})})
        sonuc += [{"name": b["name"], "id": b["id"]} for b in d.get("items", [])]
        imlec = d.get("bookmark")
        if not imlec:
            return sonuc


def pin_ac(token, pano_id, gorsel, baslik, aciklama, link):
    """Yerel gorseli yukleyip hemen pin acar, pin id doner."""
    veri = base64.b64encode(Path(gorsel).read_bytes()).decode()
    d = _istek("POST", "/pins", token, json={
        "board_id": pano_id,
        "title": baslik[:100],
        "description": aciklama[:800],
        "link": link,
        "alt_text": baslik[:500],
        "media_source": {"source_type": "image_base64", "content_type": "image/jpeg", "data": veri},
    })
    return d["id"]


def giris():
    durum = secrets.token_urlsafe(16)
    url = "https://www.pinterest.com/oauth/?" + urllib.parse.urlencode({
        "client_id": os.environ["PINTEREST_APP_ID"], "redirect_uri": YONLENDIRME,
        "response_type": "code", "scope": YETKI, "state": durum,
    })
    gelen = {}

    class Karsila(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            gelen.update({k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Tamam, bu sekmeyi kapatabilirsin.".encode())

        def log_message(self, *a):
            pass

    print("Tarayicida Pinterest acilacak, 'Give access' de.\n", url)
    webbrowser.open(url)
    with http.server.HTTPServer(("localhost", 3003), Karsila) as s:
        while "code" not in gelen and "error" not in gelen:
            s.handle_request()
    if gelen.get("state") != durum or "code" not in gelen:
        raise SystemExit(f"Giris basarisiz: {gelen}")
    t = _token_istegi({"grant_type": "authorization_code", "code": gelen["code"],
                       "redirect_uri": YONLENDIRME, "continuous_refresh": "true"})
    etsy.refresh_kaydet(t["refresh_token"], "PINTEREST_REFRESH_TOKEN")
    print("OK. Refresh token .env'e kaydedildi.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for satir in etsy.ENV.read_text(encoding="utf-8").splitlines():
        if "=" in satir and not satir.startswith("#"):
            k, v = satir.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    komut = sys.argv[1] if len(sys.argv) > 1 else ""
    if komut == "giris":
        giris()
    elif komut == "panolar":
        for p in panolar(erisim_tokeni()):
            print(p["id"], p["name"])
    else:
        print(__doc__)
