# DVD-Video Teknik Notları

Çalışma notları; uygulama sırasında referans DVD'ler ve spesifikasyon kaynaklarıyla doğrulanıp genişletilecek.

## Video

| | NTSC | PAL |
|---|---|---|
| Çözünürlük | 720×480, 704×480, 352×480, 352×240 | 720×576, 704×576, 352×576, 352×288 |
| Kare hızı | 29.97 (film: 23.976 + soft pulldown) | 25 |
| En uzun GOP | 18 kare (36 alan) | 15 kare (30 alan) |

- Codec: MPEG-2 Main Profile @ Main Level (MPEG-1 de geçerli ama kullanmayacağız), 4:2:0, 8-bit.
- En-boy: 4:3 veya 16:9 (16:9 yalnızca 720/704 genişlikte). 16:9 → anamorfik; oynatıcı 4:3 TV için letterbox/pan-scan yapar.
- Video tepe bitrate: 9.8 Mbps. **Tüm akışlar dahil mux sınırı: 10.08 Mbps.**
- VBV tampon boyutu: 224 KB (1.835.008 bit).
- Kapalı GOP'lar (cell/bölüm sınırlarında zorunlu, seamless için önemli).

## Ses

| Format | Notlar |
|---|---|
| AC-3 (Dolby Digital) | 1.0–5.1, en fazla 448 kbps. Pratikte standart. |
| LPCM | 48/96 kHz, 16/20/24 bit; çok yer kaplar (stereo 16-bit 48 kHz = 1.536 Mbps) |
| MPEG-1 Layer II | Özellikle PAL bölgelerinde geçerli |
| DTS | Opsiyonel (oynatıcı desteği garanti değil), 754/1509 kbps |

- Örnekleme hızı 48 kHz (veya 96 kHz LPCM). 44.1 kHz **geçersiz**.
- Başlık başına en fazla 8 ses izi.

## Altyazı (subpicture)

- 2-bit RLE bitmap: her altyazı karesinde **4 renk** (arka plan, dolgu, emphasis1, emphasis2).
- Bu 4 renk, PGC'deki **16 renklik palet (CLUT)** içinden seçilir; her rengin 16 kademeli saydamlığı (contrast) var.
- Anti-alias için tipik kullanım: arka plan saydam, dolgu beyaz, emphasis1 kontur (siyah), emphasis2 dolgu-kontur arası geçiş.
- Başlık başına en fazla 32 subpicture akışı. 16:9 başlıklarda bir akış için wide / letterbox / pan-scan varyantları olabilir.
- Altyazılar **metin değil resimdir**: font, authoring sırasında seçilip resme dönüştürülür. Bu yüzden istenen her font kullanılabilir; sınır font değil, 4 renk ve 720 piksel genişliktir.
- 16:9 başlıklarda subpicture 720 piksel genişliğinde saklanır ama ekranda yatayda gerilerek gösterilir → render ederken yatayda sıkıştırarak telafi edilmeli (ticari DVD altyazılarının "tuhaf" görünmesinin bir sebebi).
- "Forced" bayrağı: altyazı kapalıyken bile gösterilen satırlar (yabancı dil diyaloğu).

## Disk yapısı

```
VIDEO_TS/
  VIDEO_TS.IFO / .BUP   VMG (Video Manager): First Play PGC, başlık tablosu, VMG menüleri
  VIDEO_TS.VOB          VMG menü video içeriği
  VTS_01_0.IFO / .BUP   VTS 1 (Video Title Set) bilgisi: PGC'ler, programlar, cell'ler, menüler
  VTS_01_0.VOB          VTS 1 menü içeriği
  VTS_01_1.VOB ...      VTS 1 başlık içeriği (her VOB dosyası ≤ 1 GB)
```

- Dosya sistemi: UDF 1.02 + ISO 9660 köprü. Dosyalar sıralı ve bitişik yerleşmeli (`xorriso -as mkisofs -dvd-video`).
- **VTS**: aynı video/ses/altyazı özelliklerini paylaşan başlıklar grubu. En fazla 99 VTS, 99 başlık.
- **PGC (Program Chain)**: oynatma birimi. Pre-komutlar → programlar (bölüm noktaları) → cell'ler → post-komutlar.
- **Cell**: VOB içindeki kesintisiz bir aralık; cell komutları ve katman geçişi cell sınırında olur.
- **VOBU**: ~0.4–1 sn'lik birim, her biri bir **NAV pack** ile başlar (PCI: buton/highlight bilgisi, DSI: arama/seamless bilgisi).

## Domain'ler

| Domain | İçerik |
|---|---|
| FP (First Play) | Disk takıldığında çalışan ilk PGC |
| VMGM | Ana (VMG) menüler — "Title menu" |
| VTSM | VTS menüleri — "Root", Bölüm, Ses, Altyazı, Açı menüleri |
| VTS | Başlıkların kendisi (film, bölümler) |

## Sanal makine (DVD VM)

- **16 GPRM** (genel amaçlı 16-bit register) — oturum boyunca durum tutmak için (güç kapanınca sıfırlanır).
- **24 SPRM** (sistem register'ları) — seçili ses (SPRM1), altyazı (SPRM2), açı (SPRM3), başlık/bölüm, seçili buton (SPRM8), vb.
- Komut tipleri: Link/Jump/Call (gezinme), Set (aritmetik, GPRM/SPRM ataması), If-koşullu komutlar.
- Komutlar: PGC pre/post komutları, cell komutları, buton komutları (her buton tek bir komut).
- Bu, menü "mantığı"nın (Hepsini Oynat, kaldığın yerden devam, seçili dili gösterme) kurulduğu yer.

## Menüler

- Menü = arka plan videosu (tek kare + still süresi, ya da döngü videosu) + **subpicture overlay** (buton highlight'ları).
- Buton başına: dikdörtgen alan, yukarı/aşağı/sol/sağ komşuları, bir komut, otomatik eylem bayrağı.
- 3 renk seti: normal (seçili değil), seçili (select), aktif (activate). Her biri 4 renk + saydamlık.
- Menü sayfası başına en fazla 36 buton (16:9'da varyantlar nedeniyle daha az kullanılabilir).
- Hareketli menü: arka plan MPEG-2 videosu + ses, sonda post-komutla kendine geri döner (döngü).

## DVD-9 katman geçişi

- İki katman: PTP (paralel) veya OTP (karşıt yollu); film diskleri genelde OTP.
- Geçiş noktası bir **cell sınırında** olmalı; oynatıcı burada kısa bir duraksama yapabilir → sahne geçişi / sessiz an seçilir.
- Katman 0 en az disk yarısı kadar dolu olmalı; geçiş noktası ECC blok sınırına hizalanır.

## Kaynaklar (doğrulanacak / okunacak)

- dvdauthor, libdvdread, libdvdnav kaynak kodları (IFO yapıları ve VM için en somut referans)
- mpucoder'ın DVD-Video yapı notları (IFO alan alan dökümü)
- DGPulldown kaynağı (pulldown bayrak düzenleme)
- ISO/IEC 13818-2 (MPEG-2 Video), 13818-1 (Program Stream)
