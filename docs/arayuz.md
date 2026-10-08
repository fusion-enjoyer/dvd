# Arayüz Tasarımı (taslak)

Kaba yerleşim taslakları; görsel tasarım (renk, tipografi) ayrıca yapılacak.

## Genel yapı

- Sol tarafta **adım adım gezinme**: Kaynaklar → Başlıklar → Ses → Altyazı → Bölümler → Menüler → Disk → Çıktı
- Altta her ekranda görünen **disk bütçe çubuğu**
- Üstte proje adı, profil özeti (`PAL · DVD-9 · Grenli film · Modern TV · 5.1`), Build düğmesi

## 1. Ana pencere — Başlık ekranı

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ◉ Interstellar        PAL · DVD-9 · Grenli film · Modern TV · 5.1     [Test] [Build ▶]│
├──────────────┬───────────────────────────────────────────────────────────────────────┤
│ Kaynaklar    │  ┌─────────────────────────────────────┐  Video                       │
│▸Başlıklar    │  │                                     │  Kaynak   1920×1080 23.976    │
│ Ses          │  │          önizleme karesi            │           BT.709  SDR          │
│ Altyazı      │  │      (crop çizgileri görünür)       │  Hedef    720×576 16:9 25p     │
│ Bölümler     │  │                                     │  Aktif    720×432  (2.39:1)    │
│ Menüler      │  └─────────────────────────────────────┘  Crop     ▣ otomatik  [düzelt] │
│ Disk         │  ◀◀ ◀ ▶ ▶▶  00:42:17  ────────●──────────                                │
│ Çıktı        │                                           Ön işleme                    │
│              │  Görünüm: [Kaynak] [Sonuç] [Kaydırmalı]   Küçültme  Spline36   ▾        │
│              │                                           Deband    ■■■□□               │
│              │  [ Bu aralığı test encode et (20 sn) ]    Gren      Azalt (hafif) ▾     │
│              │                                           Encoder   HCEnc ▾  2 geçiş    │
├──────────────┴───────────────────────────────────────────────────────────────────────┤
│ Disk ███████████████████████████████████████░░░░  7.92 / 8.54 GB    Video ort. 7.4 Mbps│
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Disk / Bütçe ekranı

```
┌───────────────────────────────────────────────────────────────────────┐
│ Medya: (•) DVD-9  ( ) DVD-5                Hedef: [Diski doldur ▾]    │
│                                                                       │
│ ████████████████████████████████████▓▓▓▓▓▓▒▒░░  8.54 GB               │
│ █ Video 6.71 GB   ▓ Ses 0.98 GB   ▒ Menü 0.06 GB   ░ Boş/pay 0.31 GB  │
│                                                                       │
│ Video ortalama   7.4 Mbps    Tepe sınırı 9.0 Mbps                     │
│ Tahmini kalite   ●●●●○  "Ticari DVD seviyesi"                         │
│                                                                       │
│ Öneriler                                                              │
│  • 2. ses izi stereo'ya düşürülürse video +0.3 Mbps                   │
│  • DVD-5'te bu film ≈ 3.9 Mbps → belirgin kalite kaybı                │
│                                                                       │
│ Katman geçişi  01:12:44.120  (sahne geçişi, sessiz)   [değiştir]       │
└───────────────────────────────────────────────────────────────────────┘
```

## 3. Menü editörü

```
┌──────────────┬───────────────────────────────────────────────┬──────────────────────┐
│ Menüler      │  ┌─ 720×576 ──────────────────────────────┐   │ Özellikler           │
│ ▸ Ana menü   │  │ ┌ ─ ─ güvenli alan ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐│   │ Buton: "Oynat"       │
│   Bölümler 1 │  │                                        │   │ Eylem  Başlık 1'i    │
│   Bölümler 2 │  │      I N T E R S T E L L A R           │   │        oynat ▾       │
│   Ses        │  │                                        │   │ Highlight  alt çizgi │
│   Altyazı    │  │      ▸ Oynat          ← seçili         │   │ Renkler              │
│ Şablon       │  │        Bölümler                        │   │  Normal  ░ ░ ░ ░     │
│ Sinematik ▾  │  │        Ses ve Altyazı                  │   │  Seçili  ■ ■ □ □     │
│              │  │ └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘│   │  Aktif   ■ □ □ □     │
│ Katmanlar    │  └────────────────────────────────────────┘   │ Navigasyon           │
│  Arka plan   │  Görünüm: [Tasarım] [Navigasyon okları]       │  ↑ —   ↓ Bölümler     │
│  Başlık      │           [Durum: normal/seçili/aktif]        │  ← —   → —            │
│  Butonlar    │  [▶ Kumandayla dene]                          │ Arka plan müziği ▾   │
└──────────────┴───────────────────────────────────────────────┴──────────────────────┘
```

- **Navigasyon okları** görünümü: butonlar arası yukarı/aşağı/sol/sağ bağlantıları oklarla gösterir, sürükleyerek düzeltilir.
- **4 renk sınırı** editörde zorlanır: highlight katmanında 4'ten fazla renk kullanılamaz, uyarı verir.
- **Kumandayla dene**: DVD VM simülatörü; klavye okları + Enter ile gerçek oynatıcı gibi gezilir.

## 4. Disk haritası (v2+)

```
 [Disk takıldı] ──▶ [Logo intro] ──▶ [Ana menü] ──Oynat──▶ [Film] ──bitti──▶ [Ana menü]
                                        │  │
                                        │  └─Bölümler──▶ [Bölüm 1–8] ⇄ [Bölüm 9–16]
                                        └─Ayarlar──▶ [Ses + Altyazı]
```

Diskin tüm davranışı düğüm grafiği olarak; her ok bir buton ya da "bitince" kuralı.

## 5. Build / kuyruk ekranı

```
 Interstellar                                               Toplam ≈ 2 sa 10 dk kaldı
  ✔ Kaynak analizi
  ✔ Ses (2 iz)
  ◐ Video  2. geçiş   ██████████░░░░░░░░  54%   38 fps
  ○ Altyazılar
  ○ Menüler
  ○ Authoring  →  ○ Uyumluluk denetimi  →  ○ ISO  →  ○ Yakma
  [Duraklat] [Log]                              Bitince: [Bildirim gönder ▾]
```

## 6. Analiz ekranı (referans DVD)

- Sol: disk yapısı ağacı (VMG → menüler, VTS → başlıklar → bölümler → cell'ler)
- Orta: bitrate grafiği (zaman ekseni), GOP yapısı şeridi
- Sağ: seçili öğenin ayrıntıları (quant matrisleri, bayraklar, ses formatı, buton listesi ve komutları)
- "Bu diskin ayarlarını profil olarak kaydet" — referans DVD'den profil çıkarma

## 7. Karşılaştırma ekranı

- Aynı kare için: Kaynak (küçültülmüş) | Bizim sonuç | Referans DVD (varsa)
- Kaydırmalı ayırıcı, %200/%400 yakınlaştırma, kare kare ilerleme
- Altta VMAF/SSIM zaman grafiği; en kötü 10 sahneye tek tıkla atlama
