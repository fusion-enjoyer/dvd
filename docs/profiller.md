# Profiller (Preset Sistemi)

Tek bir "kalite" ayarı yerine **katmanlı profiller**: her katman bir grup ayarı belirler, sonuncusu öncekileri ezer.
Kullanıcı çoğu zaman sadece 3–4 seçim yapar; ileri ayarlar her zaman elle değiştirilebilir.

```
Nihai ayarlar = Standart  →  Medya  →  İçerik tipi  →  İzleme ortamı  →  Ses düzeni  →  Kullanıcı değişiklikleri
```

> Aşağıdaki sayısal değerler **başlangıç tahminidir**; Faz 2'de korpus, referans DVD'ler ve gerçek cihaz testleriyle kalibre edilecek.

## 1. Standart

| | PAL | NTSC |
|---|---|---|
| Çözünürlük | 720×576 | 720×480 |
| 23.976 film kaynağı | %4 hızlandırılır → 25p (pitch düzeltme seçmeli) | 23.976p + soft pulldown, orijinal hız |
| 25p / 50i kaynak | Doğal | 29.97'ye dönüşüm gerekir (önerilmez) |
| 29.97 / 59.94i kaynak (ABD yayını) | Dönüşüm gerekir (önerilmez) | Doğal |
| Altyazı zamanları | Hızlanmaya göre otomatik ölçeklenir | Değişmez |

Uygulama kaynağın kare hızına bakıp **önerilen standardı** gösterir, karar kullanıcıdadır.

## 2. Medya

| | DVD-5 | DVD-9 |
|---|---|---|
| Kapasite | 4.70 GB | 8.54 GB |
| Katman geçişi | — | Otomatik seçilir, elle değiştirilebilir |
| Uyarı | Uzun filmde düşük bitrate uyarısı | Eski oynatıcılarda DL uyumluluğu notu |

## 3. İçerik tipi

| Profil | Kaynak | Ön işleme eğilimi |
|---|---|---|
| **Modern film** | Dijital çekim, temiz | Standart küçültme, hafif deband |
| **Grenli film** | 35 mm, belirgin gren | Grenin bir kısmını kontrollü azalt (gren MPEG-2'de çok bit yer), kalanını koru |
| **Eski film / restorasyon** | Yoğun gren, yumuşak | Daha güçlü denoise, aşırı keskinleştirme yok |
| **2D animasyon** | Düz renk alanları, keskin çizgiler | Güçlü deband, çizgi koruyan küçültme, gren yok |
| **3D/CGI animasyon** | Gradyanlar | Güçlü deband + dither |
| **Dizi (progresif)** | WEB-DL / BD diziler | Modern film ile aynı, bölüm başına bütçe |
| **Yayın kaynağı (interlaced)** | 1080i TV kaydı, konser | Deinterlace (QTGMC) ya da interlaced encode |
| **4:3 içerik** | Eski diziler | 4:3 disk/başlık bayrağı, pillarbox yok |

## 4. İzleme ortamı

| Ayar | Modern TV | Projeksiyon | Tüplü TV (CRT) | Bilgisayar | Konsol | Taşınabilir / Araç | Evrensel |
|---|---|---|---|---|---|---|---|
| Keskinlik | Orta | Orta-düşük | Düşük | Yüksek | Orta | Orta | Orta |
| Dikey low-pass (titreme önleme) | Yok | Yok | **Var** (özellikle menü/altyazıda) | Yok | Yok | Yok | Hafif (menü/altyazı) |
| Deband / gren | Normal | **Güçlü** (büyük ekranda her şey görünür) | Hafif | Normal | Normal | Hafif | Normal |
| Video tepe bitrate | 9.0 Mbps | 9.0 Mbps | 9.0 Mbps | 9.5 Mbps | ~8.0 Mbps | ~7.5 Mbps | ~8.0 Mbps |
| Menü/altyazı güvenli alan | %95 | %95 | **%85–90** (overscan) | %100 | %90 | %90 | %90 |
| Altyazı boyutu | Normal | Normal | Büyük | Normal | Normal | Büyük | Normal |
| Menü karmaşıklığı | Tam | Tam | Tam | Tam | Uyumlu mod | Uyumlu mod | Uyumlu mod |

- **Konsol** (PS2/PS3/Xbox): eski konsollar yüksek bitrate tepelerine ve yazılabilir medyaya karşı hassas → tepe sınırı düşük, VM hileleri sınırlı.
- **Uyumlu mod**: hareketli menü döngüleri, karmaşık GPRM mantığı ve seamless hileleri yerine en güvenli yapılar.
- **Evrensel**: diski kimin nerede izleyeceği belli değilse.

## 5. Ses düzeni

| Profil | Varsayılan |
|---|---|
| **TV hoparlörü / Soundbar** | Stereo AC-3 (Pro Logic II uyumlu downmix), konuşma netliği öncelikli |
| **5.1 sistem** | 5.1 AC-3 448 kbps, orijinal dinamik |
| **Gece modu** | Dinamik aralık sıkıştırması daha güçlü, normalize |
| **Hepsi** | 5.1 + stereo iz birlikte (disk bütçesinden yer alır) |

## Kullanıcı profilleri

- Herhangi bir kombinasyon **kendi profilim** olarak kaydedilebilir ("Salon TV'si", "Yazlık CRT").
- Profiller dışa/içe aktarılabilir (tek dosya), PC değiştirince taşınır.
- Projede hangi profil katmanının hangi ayarı belirlediği görülebilir ("bu değer *Projeksiyon* profilinden geliyor").
