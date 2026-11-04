"""Her calistiginda Pinterest ve X icin Buffer'a 1'er gonderi zamanlar.

Gorsel: tasarimlar/<urun>/<ad>[__sezon].jpg  (en az paylasilan, sezondakiler once)
Metin:  config/metinler.yaml               (en az kullanilan)
Kayit:  gecmis.csv

Ortam degiskenleri:
  BUFFER_API_KEY   zorunlu (X icin; PINTEREST_DOGRUDAN yoksa Pinterest icin de)
  PINTEREST_DOGRUDAN=1  Pinterest'e Buffer'siz, API v5 ile hemen pin at (pinterest.py)
  CANLI=1          gercekten gonder (yoksa sadece ne yapacagini yazar)
  GITHUB_REPOSITORY, GITHUB_REF_NAME  gorsel linki icin (Actions otomatik verir)
"""
import csv
import datetime as dt
import os
import re
import subprocess
import sys
import time
import urllib.parse
from collections import Counter
from pathlib import Path

import requests
import yaml

import pinterest
from pin_gorsel import pin_yap

KOK = Path(__file__).parent
TASARIM = KOK / "tasarimlar"
GECMIS = KOK / "gecmis.csv"
ALANLAR = ["tarih", "platform", "urun", "gorsel", "metin_id", "pano", "zaman_utc", "buffer_id", "durum"]
UZANTILAR = {".jpg", ".jpeg", ".png", ".webp"}
YONLER = {"left", "right", "back", "front"}  # ham urun gorselleri (Left.png vb.) paylasilmaz
API = "https://api.buffer.com"


def yukle(ad):
    return yaml.safe_load((KOK / "config" / ad).read_text(encoding="utf-8"))


def gql(sorgu, degisken=None):
    r = requests.post(
        API,
        json={"query": sorgu, "variables": degisken or {}},
        headers={"Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}"},
        timeout=60,
    )
    r.raise_for_status()
    veri = r.json()
    if veri.get("errors"):
        raise RuntimeError(veri["errors"])
    return veri["data"]


def sezon_acik(sezon, bugun):
    b = dt.date(bugun.year, *map(int, sezon["baslangic"].split("-")))
    s = dt.date(bugun.year, *map(int, sezon["bitis"].split("-")))
    return b <= bugun <= s if b <= s else (bugun >= b or bugun <= s)  # yil donumu


def gecmisi_oku():
    if not GECMIS.exists():
        return []
    with GECMIS.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def gecmise_yaz(satirlar):
    yeni = not GECMIS.exists()
    with GECMIS.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ALANLAR)
        if yeni:
            w.writeheader()
        w.writerows(satirlar)


def gorsel_adaylari(urunler, acik, gecmis, izinli=None):
    """Paylasim sirasina dizili (sezon_onceligi, paylasim_sayisi, yol, urun, sezon) listesi."""
    sayac = Counter(g["gorsel"] for g in gecmis if g["platform"] == "pinterest")
    adaylar = []
    for urun in urunler:
        for p in sorted((TASARIM / urun).glob("*")):
            if p.suffix.lower() not in UZANTILAR:
                continue
            if YONLER & set(re.split(r"[^a-z]+", p.stem.lower())):
                continue
            sezon = p.stem.split("__")[1] if "__" in p.stem else None
            if sezon and sezon not in acik:
                continue
            yol = p.relative_to(KOK).as_posix()
            if izinli is not None and yol not in izinli:  # panel: GitHub'da olmayan yerel dosya
                continue
            # once sezondakiler, sonra en az paylasilan, sonra ada gore
            adaylar.append((0 if sezon else 1, sayac[yol], yol, urun, sezon))
    # sezonluk gorsel ile genel gorsel donusumlu gitsin: en az paylasilan once
    adaylar.sort(key=lambda a: (a[1], a[0], a[2]))
    return adaylar


def gorsel_sec(urunler, sezonlar, acik, gecmis, istenen=""):
    adaylar = gorsel_adaylari(urunler, acik, gecmis)
    if istenen:
        adaylar = [a for a in adaylar if a[2] == istenen]
    if not adaylar:
        sys.exit("Paylasilacak gorsel yok (tasarimlar/ bos ya da hepsi sezon disi).")
    _, _, yol, urun, sezon = adaylar[0]
    return yol, urun, sezon


def metin_sec(metinler, urun, sezon, acik, platform, gecmis):
    banka = metinler.get(urun, {})
    gruplar = [sezon] if sezon and banka.get(sezon) else ["genel"] + [s for s in acik if banka.get(s)]
    adaylar = [(g, i, m) for g in gruplar for i, m in enumerate(banka.get(g) or [])]
    if not adaylar:
        sys.exit(f"'{urun}' icin metinler.yaml'da metin yok.")
    sayac = Counter(g["metin_id"] for g in gecmis if g["platform"] == platform and g["urun"] == urun)
    g, i, m = min(adaylar, key=lambda a: (sayac[f"{a[0]}:{a[1]}"], a[0] == "genel", a[1]))
    return f"{g}:{i}", m


def pano_sec(isimler, panolar, gecmis, yedek):
    mevcut = {p["name"].strip().lower().replace("’", "'"): p for p in panolar}
    bulunan = []
    for ad in isimler:
        p = mevcut.get(ad.strip().lower().replace("’", "'"))
        if p and p not in bulunan:
            bulunan.append(p)
    if not bulunan:
        bulunan = [mevcut[yedek.lower()]] if yedek.lower() in mevcut else panolar[:1]
    sayac = Counter(g["pano"] for g in gecmis if g["platform"] == "pinterest")
    return min(bulunan, key=lambda p: sayac[p["name"]])


def zaman(saat, simdi):
    h, m = map(int, saat.split(":"))
    t = simdi.replace(hour=h, minute=m, second=0, microsecond=0)
    if t <= simdi + dt.timedelta(minutes=30):
        t += dt.timedelta(days=1)
    return t


def bos_zaman(saatler, simdi, dolu):
    """Saat listesinden, kayitta dolu olmayan ilk zaman. Ayni saate iki gonderi dusmez."""
    adaylar = sorted(zaman(s, simdi) + dt.timedelta(days=g) for s in saatler for g in range(3))
    return next(t for t in adaylar if zaman_metni(t) not in dolu)


def zaman_metni(t):
    return t.isoformat().replace("+00:00", "Z")


def turlar(buf, mod):
    """Her tur tek gorsel: {platform: saat listesi}. None = hemen."""
    if mod == "hemen":
        return [{"pinterest": None, "x": None}]
    if mod == "ideal":
        return [buf["manuel_saat_utc"]]
    saatler = buf["saat_utc"]
    return [{p: [v[i]] for p, v in saatler.items() if i < len(v)}
            for i in range(max(len(v) for v in saatler.values()))]


def ayarlar():
    buf, urun_ayar, sezonlar, metinler = ayarlar()
    simdi = dt.datetime.now(dt.timezone.utc)
    acik = acik_sezonlar(sezonlar, simdi)
    gecmis = gecmisi_oku()
    urunler = urun_ayar["urunler"]
    mod = os.environ.get("ZAMANLAMA") or "otomatik"
    istenen = os.environ.get("GORSEL") or ""
    repo = os.environ.get("GITHUB_REPOSITORY", "KULLANICI/REPO")
    dal = os.environ.get("GITHUB_REF_NAME", "main")

    dogrudan = os.environ.get("PINTEREST_DOGRUDAN") == "1"
    if dogrudan:
        ptoken = pinterest.erisim_tokeni()
        panolar = pinterest.panolar(ptoken)
    else:
        kanallar = gql(
            """query($o: OrganizationId!) { channels(input: {organizationId: $o}) {
                 id service metadata { ... on PinterestMetadata { boards { name serviceId } } } } }""",
            {"o": buf["organization_id"]},
        )["channels"]
        panolar = [{"name": b["name"], "id": b["serviceId"]} for b in
                   next(k for k in kanallar if k["id"] == buf["channels"]["pinterest"])["metadata"]["boards"]]
    for tur in turlar(buf, mod):
        yol, urun, sezon = gorsel_sec(urunler, sezonlar, acik, gecmis, istenen)
        gorsel_url = raw_url(yol, repo, dal)
        link = urun_ayar["urunler"][urun].get("etsy_link") or urun_ayar["magaza_link"]
        # Share & Save: ilan linkleri de magaza alt alan adindan gitsin (www.etsy.com/listing/.. -> animacommonsouls.etsy.com/listing/..)
        link = link.replace("https://www.etsy.com/listing/", "https://animacommonsouls.etsy.com/listing/")

        # sezon gorseli once sezon panosuna gider
        pano_adlari = (sezonlar[sezon].get("panolar", []) if sezon else []) + urunler[urun].get("panolar", [])
        pano = pano_sec(pano_adlari, panolar, gecmis, urun_ayar["yedek_pano"])

        print(f"Acik sezonlar: {acik or '-'}")
        print(f"Gorsel: {yol}  ({urun}, sezon={sezon or '-'})")
        print(f"Link: {link}")

        kayitlar = []
        for platform, saatler in tur.items():
            kanal = buf["channels"][platform]
            metin_id, m = metin_sec(metinler, urun, sezon, acik, platform, gecmis)
            pin_hemen = dogrudan and platform == "pinterest"  # API v5'te zamanlama yok, hemen atilir
            dolu = {g["zaman_utc"] for g in gecmis if g["platform"] == platform}
            if pin_hemen:
                ne_zaman = simdi
            elif saatler is None:  # pin gorseli yayinlanana kadar gecmis olmasin
                ne_zaman = simdi + dt.timedelta(minutes=6)
            else:
                ne_zaman = bos_zaman(saatler, simdi, dolu)
            girdi = {
                "channelId": kanal,
                "schedulingType": "automatic",
                "mode": "customScheduled",
                "dueAt": zaman_metni(ne_zaman),
                "needsApproval": False,
                "assets": [{"image": {"url": gorsel_url}}],
                "source": "anima-otomasyon",
            }
            # Etsy Stats'ta trafik kaynagi gorunsun
            plink = f"{link}{'&' if '?' in link else '?'}utm_source={platform}&utm_medium=social&utm_campaign=anima-otomasyon"
            if platform == "pinterest":
                # dikey 1000x1500 pin gorseli (sablon/pin.html)
                pin_dosya = KOK / "pinler" / urun / f"{Path(yol).stem}--{metin_id.replace(':', '-')}.jpg"
                pin_rel = pin_dosya.relative_to(KOK).as_posix()
                if not pin_dosya.exists():
                    parcalar = (m["pin_ana"], m.get("pin_el", "")) if m.get("pin_ana") else None
                    pin_yap(KOK / yol, m["baslik"], urun, pin_dosya, parcalar)
                    print(f"  pin gorseli: {pin_rel}")
                    if canli and not pin_hemen:  # dogrudan yolda gorsel dosyadan yuklenir, link gerekmez
                        yayinla(pin_dosya, raw_url(pin_rel, repo, dal))
                girdi["assets"] = [{"image": {"url": raw_url(pin_rel, repo, dal)}}]
                girdi["text"] = m["aciklama"]
                girdi["metadata"] = {"pinterest": {"boardServiceId": pano["id"], "title": m["baslik"][:100], "url": plink}}
            else:
                girdi["text"] = f"{m['tweet']}\n\n{plink}"

            print(f"\n[{platform}] {ne_zaman:%Y-%m-%d %H:%M} UTC  metin={metin_id}" + (f"  pano={pano['name']}" if platform == "pinterest" else ""))
            print("  " + (m["baslik"] + " | " if platform == "pinterest" else "") + girdi["text"].replace("\n", " "))

            kayit = dict(tarih=simdi.date().isoformat(), platform=platform, urun=urun, gorsel=yol, metin_id=metin_id,
                         pano=pano["name"] if platform == "pinterest" else "", zaman_utc=girdi["dueAt"], buffer_id="", durum="deneme")
            if canli and pin_hemen:
                pid = pinterest.pin_ac(ptoken, pano["id"], pin_dosya, m["baslik"], m["aciklama"], plink)
                kayit.update(buffer_id=f"pin:{pid}", durum="paylasildi")
                print(f"  OK pin_id={pid}")
            elif canli:
                n = bekleyen_sayisi(buf["organization_id"], kanal)
                if n >= buf["kuyruk_siniri"]:
                    print(f"  ATLANDI: Buffer kuyrugunda {n} gonderi var (sinir {buf['kuyruk_siniri']}).")
                    continue
                sonuc = gql(OLUSTUR, {"i": girdi})["createPost"]
                if "post" not in sonuc:
                    raise RuntimeError(f"Buffer hatasi ({platform}): {sonuc.get('message')}")
                kayit.update(buffer_id=sonuc["post"]["id"], durum="zamanlandi")
                print(f"  OK buffer_id={sonuc['post']['id']}")
            kayitlar.append(kayit)

        gecmis.extend(kayitlar)  # sonraki tur ayni gorsel, metin ve saati secmesin
        if canli:
            gecmise_yaz(kayitlar)  # tur tur yaz: sonraki tur hata alsa da kayit kalir

    if not canli:
        print("\nDENEME modu: hicbir sey gonderilmedi. Gercek paylasim icin CANLI=1.")


if __name__ == "__main__":
    main()
