# ANIMA commonsouls – Otomatik paylaşım

Sen tasarım yaparsın, bu repo Pinterest ve X'e paylaşır (Buffer üzerinden).

## Nasıl çalışır

- Pazartesi–Cuma her gün 12:00 UTC'de (15:00 İstanbul) GitHub Actions çalışır.
- `tasarimlar/` içinden en az paylaşılmış görseli seçer. Sezonu açık olanlar önce gelir.
- `config/metinler.yaml` içinden en az kullanılmış metni seçer.
- Buffer'a 2 gönderi zamanlar:
  - Pinterest: ertesi gün 01:00 UTC (ABD akşamı), doğru panoya, Etsy linkiyle
  - X: 16:00 UTC (ABD öğlen), görsel + kısa metin + link
- Ne paylaştığını `gecmis.csv` dosyasına yazar.

## Senin işin: yeni tasarım eklemek

1. Mockup görselini GitHub'da `tasarimlar/<urun>/` klasörüne sürükle-bırak → **Commit changes**.
   - Dosya adı: küçük harf, Türkçe karakter yok, boşluk yerine tire. Örnek: `cozy-desk-2.jpg`
   - Sadece belli sezonda paylaşılsın istersen adın sonuna `__sezon` ekle:
     `xmas-tree__christmas.jpg`, `heart__valentines.jpg`, `dad-gift__fathers.jpg`,
     `flowers__mothers.jpg`, `spooky__halloween.jpg` (tarihler `config/sezonlar.yaml`'da)
2. **Yeni ürünse:** Claude'a "yeni ürün: …" de. `config/urunler.yaml` ve `config/metinler.yaml` dosyalarına ürünü ve metinlerini ekler.

Hepsi bu kadar.

## Etsy senkronu (otomatik, `senkron.py`)

Her gün 09:00 UTC'de "Etsy Senkron" çalışır:
- **Yeni ilan** (Printify → Etsy): resimlerini `tasarimlar/<ad>/` altına indirir, ürünü ve pin/tweet metinlerini (Claude Haiku) `config/urunler_oto.yaml` + `config/metinler_oto.yaml` dosyalarına yazar.
- **SEO:** her ilanın başlığını ve 13 etiketini Etsy aramasında üst sıradaki ilanların etiketlerine bakarak yeniden yazar ve Etsy'ye uygular. Aynı ilana en erken 30 günde bir dokunur. Eski hâli `durum/seo_kayit.json`'da durur (geri almak için).
- Dokunulmasın istenen ilan: `config/urunler.yaml` → `atla:` listesine ilan numarasını ekle.
- Printify'da ürünü yeniden "Publish" edersen başlık/etiket ezilebilir.

Kurulum (bir kere): Etsy uygulamasında Callback URL `http://localhost:3003/callback`, lokal `python etsy_giris.py`, sonra `.env` içindeki tüm anahtarları GitHub secret yap.

## Ayar dosyaları (Excel'in karşılığı)

| Dosya | İçerik |
|---|---|
| `config/urunler.yaml` | Ürünler, Etsy linkleri, hangi panolara gideceği |
| `config/sezonlar.yaml` | Özel günler (Takvim sekmesi) ve sezon panoları |
| `config/metinler.yaml` | İngilizce pin başlıkları, açıklamalar, tweet'ler |
| `config/buffer.yaml` | Buffer kanal ID'leri, paylaşım saatleri |
| `gecmis.csv` | Paylaşım kaydı (Excel'de açılabilir) |

## Bir kerelik kurulum

1. GitHub'da **public** repo aç, bu klasörü yükle.
2. Repo → **Settings → Secrets and variables → Actions**
   - **Secrets** sekmesi → New secret: `BUFFER_API_KEY` = Buffer API anahtarı
   - **Variables** sekmesi → New variable: `CANLI` = `0` (deneme). Gerçek paylaşım için `1`.
3. **Actions** sekmesi → "Paylas" → **Run workflow** → çıktıda ne paylaşacağını gör.
4. Her şey doğruysa `CANLI` değerini `1` yap.

## Durdurmak

Actions → Paylas → sağ üstte **…** → **Disable workflow**. Ya da `CANLI` = `0`.

## Notlar

- Buffer ücretsiz planı kanal başına en fazla 10 bekleyen gönderi alır. Kuyrukta 8 varsa script o gün atlar.
- Görseller herkese açık link üzerinden Buffer'a gider (repo public olmasının sebebi bu). Anahtarlar kodda değil, Secrets'ta.
- Lokal deneme: `.env` dosyasına `BUFFER_API_KEY=...` yaz, `python paylas.py`.
