"""Yerel paylasim paneli: http://127.0.0.1:8765

Panel paylasimi kendisi yapmaz, GitHub'daki Paylas isini `gh` ile baslatir.
Boylece Buffer anahtari, pin gorseli ve gecmis.csv tek yerde kalir.
Calistirma: Panel.bat
"""
import datetime as dt
import json
import mimetypes
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
import paylas  # noqa: E402

PORT = 8765
GH = r"D:\Projeler\tools\gh\gh.exe"
IZINLI_HOST = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
SAYFA = Path(__file__).parent / "index.html"
SIRA_BOYU = 12

kilit = threading.Lock()
son_cekme = 0.0


def komut(*a):
    return subprocess.run(a, cwd=KOK, capture_output=True, text=True, encoding="utf-8", errors="replace")


def guncelle(zorla):
    """Otomasyonun commit'lerini al. Sik yenilemede GitHub'i yormamak icin 30 sn'de bir."""
    global son_cekme
    with kilit:
        if not zorla and time.time() - son_cekme < 30:
            return ""
        son_cekme = time.time()
        r = komut("git", "pull", "--ff-only", "--quiet")
    return "" if r.returncode == 0 else "GitHub'dan güncellenemedi, kayıtlar eski olabilir."


def son_calisma():
    r = komut(GH, "run", "list", "--workflow", "paylas.yml", "--limit", "1",
              "--json", "status,conclusion,createdAt,url,displayTitle")
    try:
        return (json.loads(r.stdout) or [None])[0]
    except json.JSONDecodeError:
        return None


def durum(zorla=False):
    uyari = guncelle(zorla)
    buf, urun_ayar, sezonlar, _ = paylas.ayarlar()
    simdi = dt.datetime.now(dt.timezone.utc)
    gecmis = paylas.gecmisi_oku()
    izinli = set(komut("git", "-c", "core.quotepath=off", "ls-files", "tasarimlar").stdout.splitlines())
    adaylar = paylas.gorsel_adaylari(urun_ayar["urunler"], paylas.acik_sezonlar(sezonlar, simdi), gecmis, izinli)
    ideal = {}
    for platform, saatler in buf["manuel_saat_utc"].items():
        dolu = {g["zaman_utc"] for g in gecmis if g["platform"] == platform}
        ideal[platform] = paylas.zaman_metni(paylas.bos_zaman(saatler, simdi, dolu))
    return {
        "uyari": uyari,
        "gecmis": gecmis[::-1],
        "sira": [{"yol": a[2], "urun": a[3], "sezon": a[4], "adet": a[1]} for a in adaylar[:SIRA_BOYU]],
        "ideal": ideal,
        "calisma": son_calisma(),
    }


def paylas_baslat(mod, gorsel):
    if mod not in ("ideal", "hemen"):
        raise ValueError("Geçersiz zamanlama")
    r = komut(GH, "workflow", "run", "paylas.yml", "--ref", "main", "-f", f"zamanlama={mod}", "-f", f"gorsel={gorsel}")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300] or "Paylas başlatılamadı")


class Isleyici(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def gonder(self, kod, govde, tip="application/json; charset=utf-8"):
        self.send_response(kod)
        self.send_header("Content-Type", tip)
        self.send_header("Content-Length", str(len(govde)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(govde)

    def json(self, kod, veri):
        self.gonder(kod, json.dumps(veri, ensure_ascii=False).encode("utf-8"))

    def host_iyi(self):
        return self.headers.get("Host") in IZINLI_HOST

    def do_GET(self):
        if not self.host_iyi():
            return self.gonder(403, b"{}")
        u = urlparse(self.path)
        if u.path == "/":
            return self.gonder(200, SAYFA.read_bytes(), "text/html; charset=utf-8")
        if u.path == "/api/durum":
            try:
                return self.json(200, durum("zorla" in u.query))
            except Exception as e:
                return self.json(500, {"hata": str(e)[:300]})
        if u.path == "/gorsel":
            return self.gorsel(parse_qs(u.query).get("yol", [""])[0])
        self.gonder(404, b"{}")

    def gorsel(self, yol):
        dosya = (KOK / yol).resolve()
        kok = (KOK / "tasarimlar").resolve()
        if kok not in dosya.parents or dosya.suffix.lower() not in paylas.UZANTILAR or not dosya.is_file():
            return self.gonder(404, b"{}")
        self.gonder(200, dosya.read_bytes(), mimetypes.guess_type(dosya.name)[0] or "image/jpeg")

    def do_POST(self):
        # Ozel baslik: baska bir site tarayicidan bu adrese istek atamasin
        if not self.host_iyi() or self.headers.get("X-Anima") != "1" or self.path != "/api/paylas":
            return self.gonder(403, b"{}")
        try:
            veri = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            paylas_baslat(veri.get("zamanlama"), str(veri.get("gorsel", "")))
            self.json(200, {"tamam": True})
        except Exception as e:
            self.json(400, {"hata": str(e)[:300]})


if __name__ == "__main__":
    sunucu = ThreadingHTTPServer(("127.0.0.1", PORT), Isleyici)
    adres = f"http://127.0.0.1:{PORT}"
    print(f"Panel açık: {adres}  (kapatmak için bu pencereyi kapat)")
    threading.Timer(0.5, webbrowser.open, [adres]).start()
    sunucu.serve_forever()
