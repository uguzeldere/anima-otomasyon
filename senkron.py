"""Etsy -> repo senkronu. Her gun GitHub Actions calistirir.

1. Etsy'deki aktif ilanlari okur.
2. SEO: hic duzenlenmemis ya da SEO_GUN gunden eski ilanlarin basligini ve 13 etiketini
   Claude Haiku ile yeniden yazar (Etsy aramasinda ust siradaki ilanlarin etiketlerine bakarak)
   ve Etsy'ye uygular. Eski hali durum/seo_kayit.json'da saklanir (geri alma icin).
3. Yeni ilan: resimlerini tasarimlar/<kisa_ad>/ altina indirir, urunu ve pin/tweet metinlerini
   config/urunler_oto.yaml + config/metinler_oto.yaml'a yazar. paylas.py bunlari da kullanir.

Ortam: ETSY_KEYSTRING, ETSY_SHARED_SECRET, ETSY_TOKEN_ANAHTAR, ANTHROPIC_API_KEY, BUFFER_API_KEY
CANLI=1 olmadan hicbir sey yazmaz/degistirmez, sadece ne yapacagini gosterir.
"""
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from typing import List

import anthropic
import requests
import yaml
from pydantic import BaseModel

import etsy
from paylas import KOK, TASARIM, gql, yukle

MODEL = "claude-haiku-5-5"
SEO_GUN = 30  # ayni ilan en erken bu kadar gun sonra yeniden duzenlenir
SEO_KAYIT = KOK / "durum" / "seo_kayit.json"
URUN_OTO = KOK / "config" / "urunler_oto.yaml"
METIN_OTO = KOK / "config" / "metinler_oto.yaml"

client = anthropic.Anthropic()


class Seo(BaseModel):
    baslik: str
    etiketler: List[str]


class Metin(BaseModel):
    baslik: str
    aciklama: str
    tweet: str


class SezonMetin(BaseModel):
    sezon: str
    metinler: List[Metin]


class YeniUrun(BaseModel):
    kisa_ad: str
    ad: str
    panolar: List[str]
    genel: List[Metin]
    sezonluk: List[SezonMetin]


def sor(model_sinifi, sistem, metin, resim=None):
    icerik = ([{"type": "image", "source": {"type": "url", "url": resim}}] if resim else []) + [{"type": "text", "text": metin}]
    try:
        r = client.messages.parse(model=MODEL, max_tokens=16000, system=sistem,
                                  messages=[{"role": "user", "content": icerik}], output_format=model_sinifi)
    except ValueError as e:  # yarim/bozuk JSON (pydantic ValidationError da ValueError)
        raise RuntimeError(f"Claude cevabi gecersiz: {str(e)[:200]}")
    if r.stop_reason != "end_turn" or r.parsed_output is None:
        raise RuntimeError(f"Claude cevabi kullanilamadi (stop_reason={r.stop_reason})")
    return r.parsed_output


# ---------- SEO ----------

SEO_SISTEM = """You are an Etsy SEO writer for ANIMA commonsouls, a small print-on-demand mug shop
(hand-drawn whimsical fluffy animals with short funny handwritten text, 11oz/15oz accent mugs, US buyers).
Write a new listing title and exactly 13 tags.
Title: max 140 characters, most important search phrase first, natural readable English, no keyword stuffing,
no ALL CAPS, use each of these characters at most once: % : & +
Tags: exactly 13, each 20 characters or less, lowercase, only letters, numbers, spaces, hyphen and apostrophe.
Use multi-word long-tail phrases buyers actually search (gift + recipient + occasion + style + product).
Prefer phrases that appear often in the competitor tags, but only if they truly fit this product.
Keep what the product fundamentally is: if the current title says custom, personalized, photo, set, or a size,
that must stay in the new title (near the start) and in the tags. Never drop the main product type.
Never claim things the product is not (material, color, size, personalization)."""


def tag_temizle(etiketler):
    temiz = []
    for t in etiketler:
        t = re.sub(r"[^a-z0-9 '\-]", "", t.lower()).strip()
        t = re.sub(r"\s+", " ", t)
        if 0 < len(t) <= 20 and t not in temiz:
            temiz.append(t)
    return temiz[:13]


def baslik_temizle(b):
    b = re.sub(r"\s+", " ", b).strip()
    for c in "%:&+":  # Etsy: bu karakterler en fazla bir kez
        ilk = b.find(c)
        if ilk >= 0:
            b = b[:ilk + 1] + b[ilk + 1:].replace(c, "")
    b = re.sub(r"\s+", " ", b)
    return b[:140].rstrip(" ,-|")


def seo_yap(ilan):
    # en uzun (en spesifik) 3 etiket; "coffee mug" gibi genel sorgular rakip bilgisi vermez
    sorgular = sorted(ilan.get("tags", []), key=len, reverse=True)[:3] or [" ".join(ilan["title"].split()[:4])]
    rakip = Counter()
    for s in sorgular:
        rakip.update(etsy.arama_etiketleri(s))
    populer = ", ".join(f"{t} ({n})" for t, n in rakip.most_common(40))
    metin = (f"Current title: {ilan['title']}\nCurrent tags: {', '.join(ilan.get('tags', []))}\n"
             f"Description:\n{ilan.get('description', '')}\n\n"
             f"Competitor tags from top Etsy search results (tag (count)):\n{populer}")
    s = sor(Seo, SEO_SISTEM, metin)
    return baslik_temizle(s.baslik), tag_temizle(s.etiketler)


def seo_zamani(kayit, lid, bugun):
    son = kayit.get(str(lid), {}).get("tarih")
    return not son or (bugun - dt.date.fromisoformat(son)).days >= SEO_GUN


# ---------- yeni urun ----------

URUN_SISTEM = """You write Pinterest and X (Twitter) marketing copy for ANIMA commonsouls, a small Etsy mug shop
(hand-drawn whimsical fluffy animals with short funny handwritten text). Audience: US/English, gift buyers and coffee lovers.
For the product given, return:
- kisa_ad: short folder name, lowercase a-z and hyphens only, 1-3 words (e.g. "cat", "sleepy-fox")
- ad: short product name (e.g. "Sooo Meow Cat Mug")
- panolar: 2-4 board names chosen ONLY from the given Pinterest board list, best fit first
- genel: 8 evergreen posts
- sezonluk: posts for seasons that truly fit this product (choose only from the given season names; may be empty),
  3-4 posts per chosen season
Each post: baslik (Pinterest title, max 100 chars, keyword-rich but natural),
aciklama (Pinterest description, 150-450 chars, includes 2-3 search phrases naturally),
tweet (X text, max 200 chars, playful, 0-2 emojis, no hashtags spam, no link).
Vary the angle across posts (gift idea, morning mood, office, cozy, humor, recipient). Be original."""


def kisa_ad_temizle(ad, mevcut):
    ad = re.sub(r"[^a-z0-9-]", "", ad.lower().replace(" ", "-")).strip("-") or "urun"
    aday, i = ad, 2
    while aday in mevcut or (TASARIM / aday).exists():
        aday, i = f"{ad}-{i}", i + 1
    return aday


def urun_yap(ilan, panolar, sezonlar, mevcut_adlar):
    resimler = etsy.ilan_resimleri(ilan["listing_id"])
    metin = (f"Title: {ilan['title']}\nTags: {', '.join(ilan.get('tags', []))}\n"
             f"Description:\n{ilan.get('description', '')}\n\n"
             f"Pinterest boards: {json.dumps(panolar)}\nSeason names: {json.dumps(sezonlar)}")
    u = sor(YeniUrun, URUN_SISTEM, metin, resim=resimler[0] if resimler else None)
    kisa = kisa_ad_temizle(u.kisa_ad, mevcut_adlar)
    gecerli_pano = [p for p in u.panolar if p in panolar] or []
    metinler = {"genel": [m.model_dump() for m in u.genel]}
    for s in u.sezonluk:
        if s.sezon in sezonlar and s.metinler:
            metinler[s.sezon] = [m.model_dump() for m in s.metinler]
    urun = {"ad": u.ad, "listing_id": ilan["listing_id"], "etsy_link": ilan["url"].split("?")[0], "panolar": gecerli_pano}
    return kisa, urun, metinler, resimler


def resimleri_indir(kisa, resimler):
    klasor = TASARIM / kisa
    klasor.mkdir(parents=True, exist_ok=True)
    for i, url in enumerate(resimler[:10], 1):  # ilk 10 resim yeter
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        (klasor / f"etsy-{i}.jpg").write_bytes(r.content)


# ---------- ana akis ----------

def oku_yaml(yol):
    return yaml.safe_load(yol.read_text(encoding="utf-8")) or {} if yol.exists() else {}


def yaz_yaml(yol, veri, baslik):
    yol.write_text(baslik + yaml.safe_dump(veri, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")


def ilan_isle(ilan, d):
    """Tek ilan: gerekirse SEO, yeni ise urun ekleme. d: ortak durum sozlugu."""
    lid = ilan["listing_id"]
    print(f"\n== {lid} {ilan['title'][:70]}")

    if seo_zamani(d["kayit"], lid, d["bugun"]):
        baslik, etiketler = seo_yap(ilan)
        print(f"  SEO baslik: {ilan['title']}\n          -> {baslik}")
        print(f"  SEO etiket: {', '.join(etiketler)}")
        if len(etiketler) < 10 or len(baslik) < 20:
            print("  ATLANDI: Claude cevabi eksik (etiket < 10 ya da baslik cok kisa).")
        elif d["canli"]:
            d["token"] = d["token"] or etsy.erisim_tokeni()
            etsy.ilan_guncelle(d["token"], lid, title=baslik, tags=etiketler)
            d["kayit"][str(lid)] = {"tarih": d["bugun"].isoformat(),
                                    "eski": {"title": ilan["title"], "tags": ilan.get("tags", [])},
                                    "yeni": {"title": baslik, "tags": etiketler}}
            ilan["title"], ilan["tags"] = baslik, etiketler
            print("  OK Etsy guncellendi")

    if lid not in d["bilinen"]:
        if d["panolar"] is None:
            buf = yukle("buffer.yaml")
            kanallar = gql("""query($o: OrganizationId!) { channels(input: {organizationId: $o}) {
                id metadata { ... on PinterestMetadata { boards { name } } } } }""",
                           {"o": buf["organization_id"]})["channels"]
            d["panolar"] = [b["name"] for b in next(
                k for k in kanallar if k["id"] == buf["channels"]["pinterest"])["metadata"]["boards"]]
            d["sezonlar"] = list(yukle("sezonlar.yaml"))
        kisa, urun, metinler, resimler = urun_yap(ilan, d["panolar"], d["sezonlar"], set(d["tum"]))
        print(f"  YENI URUN: {kisa} ({urun['ad']}), {len(resimler)} resim, panolar={urun['panolar']}, "
              f"metin gruplari={list(metinler)}")
        if d["canli"]:
            resimleri_indir(kisa, resimler)
            d["oto_urun"][kisa] = urun
            d["oto_metin"][kisa] = metinler
            d["tum"][kisa] = urun
            d["bilinen"].add(lid)


def kaydet(d):
    SEO_KAYIT.parent.mkdir(exist_ok=True)
    SEO_KAYIT.write_text(json.dumps(d["kayit"], ensure_ascii=False, indent=2), encoding="utf-8")
    yaz_yaml(URUN_OTO, {"urunler": d["oto_urun"]}, "# OTOMATIK (senkron.py). Elle duzenleme: urunler.yaml'a tasi.\n")
    yaz_yaml(METIN_OTO, d["oto_metin"], "# OTOMATIK (senkron.py, Claude Haiku).\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    elle = yukle("urunler.yaml")
    oto_urun = oku_yaml(URUN_OTO).get("urunler") or {}
    tum = {**elle["urunler"], **oto_urun}
    d = {
        "canli": os.environ.get("CANLI") == "1",
        "bugun": dt.date.today(),
        "kayit": json.loads(SEO_KAYIT.read_text(encoding="utf-8")) if SEO_KAYIT.exists() else {},
        "oto_urun": oto_urun,
        "oto_metin": oku_yaml(METIN_OTO),
        "tum": tum,
        "bilinen": {u.get("listing_id") for u in tum.values() if u.get("listing_id")},
        "token": None, "panolar": None, "sezonlar": None,
    }
    atla = set(elle.get("atla") or [])
    ilanlar = [l for l in etsy.aktif_ilanlar() if l["listing_id"] not in atla]
    print(f"Aktif ilan: {len(ilanlar)} (atlanan: {len(atla)})")

    hatalar = []
    try:
        for ilan in ilanlar:
            try:
                ilan_isle(ilan, d)
            except Exception as e:  # bir ilan hata verirse digerleri devam etsin
                hatalar.append(ilan["listing_id"])
                print(f"  HATA: {e}")
    finally:
        if d["canli"]:
            kaydet(d)  # yarida kalsa bile yapilan degisiklikler kayda gecsin
    if not d["canli"]:
        print("\nDENEME modu: hicbir sey degistirilmedi. Gercek calisma icin CANLI=1.")
    if hatalar:
        sys.exit(f"Hata veren ilanlar: {hatalar}")


if __name__ == "__main__":
    main()
