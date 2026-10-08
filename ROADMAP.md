# Yol Haritası

Her faz, kendi başına kullanılabilir bir çıktı üretecek şekilde sıralandı. Projenin kalbi **Faz 2 (kalite motoru)**;
menüler ve GUI onun üstüne kurulur. Ayrıntılı teknik gerekçeler için [docs/kalite.md](docs/kalite.md) ve
[docs/dvd-spec.md](docs/dvd-spec.md).

---

## Faz 0 — Temel ve keşif

Amaç: Geliştirme ortamını taşınabilir kurmak ve "iyi DVD" nedir, ölçülebilir hale getirmek.

- [ ] Araç zinciri: FFmpeg, VapourSynth (+ eklentiler), dvdauthor/spumux, mplex, xorriso, mpv (dvdnav ile), Wine + HCEnc (opsiyonel)
- [ ] Bu zinciri tek komutla kuran **Docker imajı / devcontainer** (PC değiştirince sıfırdan kurulum derdi olmasın)
- [ ] Python proje iskeleti (`uv`, `pyproject.toml`, ruff, pytest)
- [ ] **Test korpusu**: kalite açısından zor kısa klipler (karanlık sahne/banding, film greni, hızlı hareket, ince detay, 2.39:1 letterbox, animasyon), her biri 30–60 sn
- [ ] **Referans DVD analizi**: elimizdeki birkaç orijinal DVD'yi söküp ölç — bitrate eğrisi, GOP yapısı, quant matrisleri, pulldown bayrakları, çözünürlük/yumuşaklık, ses formatı, menü yapısı. `dvd analyze` aracının ilk hali.
- [ ] **Cihaz matrisi**: test edilecek oynatıcılar (masaüstü DVD oynatıcı, PS2/PS3, TV'nin USB oynatıcısı, VLC/mpv) ve hangisinin PAL/NTSC/DVD-9 desteklediği

**Bitti kriteri:** Docker imajı başka PC'de ayağa kalkıyor; bir ticari DVD'nin teknik profili raporlanabiliyor.

---

## Faz 1 — Uçtan uca MVP (menüsüz)

Amaç: `film.mkv → oynatılabilir VIDEO_TS + ISO`. Kalite henüz ikincil; boru hattı uçtan uca çalışsın.

- [ ] Kaynak analizi (ffprobe): çözünürlük, fps, renk uzayı, HDR, ses/altyazı/bölüm izleri
- [ ] Basit video encode (FFmpeg `mpeg2video`, 2-pass VBR, anamorfik 16:9)
- [ ] AC-3 ses encode, 48 kHz
- [ ] Bölümleri MKV'den al, bölüm noktalarında I-frame zorla
- [ ] `dvdauthor` ile tek başlıklı VIDEO_TS, `xorriso` ile ISO
- [ ] `dvd build film.mkv --disc dvd5` CLI'ı
- [ ] Otomatik doğrulama: mpv/dvdnav ile açılıyor mu, süre doğru mu

**Bitti kriteri:** Bir filmi tek komutla ISO'ya çevirip gerçek bir DVD oynatıcıda izleyebiliyoruz.

---

## Faz 2 — Kalite motoru ⭐

Amaç: Ticari DVD görüntü kalitesine ulaşmak ve bunu **ölçerek** kanıtlamak.

**Ön işleme (VapourSynth)**
- [ ] Siyah bant tespiti ve kırpma (crop), ardından bantları **16 piksellik macroblock sınırlarına hizalı** pad etme
- [ ] Yüksek kaliteli küçültme (Spline36 / SSIM downsampler / Lanczos + uygun anti-alias) — kernel'ları korpusla karşılaştır
- [ ] BT.709 → BT.601 renk matrisi dönüşümü ve doğru bitstream bayrakları
- [ ] Yüksek bit derinliğinde işlem, sonda 8-bit'e **kontrollü dithering**; deband (f3kdb/neo_f3kdb)
- [ ] Opsiyonel: hafif denoise / gren yönetimi (gren bitrate yer; kontrollü azaltma vs. koruma)
- [ ] HDR/UHD kaynaklar için tonemapping (BT.2020 PQ → SDR)

**Encode**
- [ ] Encoder soyutlaması: `ffmpeg-mpeg2video` (varsayılan), `hcenc` (Wine, muhtemelen en iyi kalite), `x262` (deneysel)
- [ ] FFmpeg için ayarlanmış parametre seti (trellis, RD makroblok kararı, non-linear quant, intra VLC, DC precision, özel quant matrisleri)
- [ ] **NTSC soft pulldown**: 23.976p progresif encode + RFF/TFF bayrak enjektörü (DGPulldown benzeri, kendimiz yazacağız)
- [ ] **PAL**: 25 fps speedup (ses pitch düzeltmeli/düzeltmesiz seçeneği)
- [ ] VBV / maksimum bitrate / GOP uyumluluğunun encode sonrası denetimi

**Bütçe ve ölçüm**
- [ ] **Bitrate planlayıcı**: disk kapasitesi − ses − altyazı − menüler − mux overhead → video ortalama/tepe bitrate
- [ ] Kalite metrikleri: VMAF / SSIM / PSNR (referans = aynı kaynağın kayıpsız küçültülmüş hali)
- [ ] **A/B karşılaştırma aracı**: aynı karede yan yana / kaydırmalı karşılaştırma görselleri, HTML rapor
- [ ] Hazır profiller: `film-dvd9-max`, `film-dvd5`, `dizi-bolum`, `animasyon`

**Bitti kriteri:** Korpusta ve en az bir tam filmde, sonuç kör karşılaştırmada referans ticari DVD'lerle aynı ligde; metrikler raporlanıyor.

---

## Faz 3 — Ses, altyazı, bölümler

- [ ] Çoklu ses izi (max 8): AC-3 2.0/5.1 (≤448 kbps), LPCM; kaynakta uygun AC-3 varsa yeniden encode etmeden passthrough
- [ ] TrueHD/DTS-HD/Atmos → 5.1 AC-3; doğru downmix ve dialnorm
- [ ] **Kendi altyazı render'ımız**: SRT/ASS → 4 renkli DVD subpicture; anti-alias için 2 ara renk (emphasis), kontur, gölge, Türkçe karakter desteği, Pango ile metin şekillendirme
- [ ] PGS (Blu-ray altyazı) → yeniden ölçekle + 4 renge kuantize (opsiyonel: OCR ile metne çevirip yeniden render)
- [ ] Zorunlu (forced) altyazılar, varsayılan dil seçimi
- [ ] Bölüm düzenleme: MKV'den içe aktar, sahne değişimine göre otomatik öner, isim ver

**Bitti kriteri:** Çok dilli, altyazılı, bölümlü film diski; altyazılar orijinal DVD'lerdeki kadar temiz.

---

## Faz 4 — Menü motoru v1

Amaç: Menüleri koddan değil, **bildirimsel bir proje dosyasından** üretmek.

- [ ] Menü modeli (YAML/JSON): sayfalar, arka plan, butonlar, eylemler, navigasyon
- [ ] Render: arka plan görseli + buton highlight subpicture'ları (normal / seçili / aktif — 3 durum, 4'er renk + saydamlık)
- [ ] Buton navigasyon grafiğini (yukarı/aşağı/sol/sağ) konuma göre otomatik hesapla, elle düzeltilebilsin
- [ ] Standart menü seti: Ana menü, Bölüm seçimi (thumbnail'lı, sayfalı), Ses, Altyazı
- [ ] Şablon sistemi: font, renk paleti, yerleşim; şablonu bir kez yaz, her filme uygula
- [ ] 16:9 menülerde letterbox / pan-scan subpicture varyantları
- [ ] Menü önizleme: PNG çıktısı + mpv'de gerçek test

**Bitti kriteri:** Şablondan üretilen, tam navigasyonlu statik menüler gerçek oynatıcıda doğru çalışıyor.

---

## Faz 5 — Diziler ve çoklu başlık

- [ ] Bir diskte çok bölüm: aynı VTS içinde birden çok başlık
- [ ] **Hepsini Oynat** (PGC zinciri veya GPRM mantığı ile), bölüm seçim menüsü
- [ ] **Disk seti planlayıcı**: "Sezon 1, 22 bölüm, DVD-9, kalite hedefi X" → kaç disk, hangi bölüm hangi diskte
- [ ] Set boyunca tutarlı menü tasarımı (Disk 1/4 vb.)
- [ ] Bölüm içi intro/outro bölüm işaretleri

**Bitti kriteri:** Bir sezonu tek komutla, tutarlı menülü disk setine çevirebiliyoruz.

---

## Faz 6 — Gelişmiş menüler

- [ ] Hareketli menüler: video arka plan + döngü sesi, döngü noktası
- [ ] Hareketli bölüm thumbnail'ları
- [ ] Menüler arası geçiş videoları
- [ ] First Play: intro/logo videosu, ardından ana menü
- [ ] Sahne seçimi sonrası dönüş, "kaldığın yerden devam" (oturum içinde, GPRM ile)
- [ ] Gizli içerik (easter egg) butonları
- [ ] Ses/altyazı menüsünde seçili olanı gösterme (SPRM okuyarak)

---

## Faz 7 — Kendi authoring motorumuz (dibine kadar)

Amaç: `dvdauthor`'un sınırlarından kurtulmak; IFO/VOB'u kendimiz yazmak.

- [ ] IFO/BUP okuyucu (referans DVD'leri tam ayrıştırma — Faz 0 analizinin derinleşmiş hali)
- [ ] IFO yazıcı: VMG, VTS, PGC, program/cell tabloları, VM komutları
- [ ] VOB multiplexer: NAV pack (PCI/DSI) üretimi, VOBU sınırları, doğru zaman damgaları
- [ ] Seamless branching, çoklu açı (multi-angle)
- [ ] DVD-9 **katman geçişi** yerleşimi (cell sınırı, sahne değişimi / sessiz an)
- [ ] VM komut derleyicisi: okunabilir bir mini dilden DVD VM komutlarına
- [ ] **Uyumluluk doğrulayıcı**: bitrate tepeleri, VBV, GOP, tablo tutarlılığı, sınırlar

**Bitti kriteri:** dvdauthor olmadan üretilen diskler aynı cihaz matrisinde çalışıyor.

---

## Faz 8 — Grafik arayüz

- [ ] Yerel web uygulaması (Python backend + tarayıcı arayüzü)
- [ ] Proje yönetimi: kaynak ekle, izleri seç, bölümleri düzenle, disk bütçesini canlı gör
- [ ] **WYSIWYG menü editörü**: sürükle-bırak buton, metin, görsel, highlight renkleri
- [ ] **DVD VM simülatörü**: menüleri yakmadan tarayıcıda kumandayla gezer gibi test et
- [ ] Encode kuyruğu, ilerleme, A/B kalite raporları

---

## Faz 9 — Yakma ve son dokunuşlar

- [ ] `growisofs` ile yakma, DVD+R DL book type ayarı, yakma sonrası doğrulama
- [ ] Kapak / disk etiketi baskı şablonları (DVD kutu ölçülerinde)
- [ ] Proje arşivi: bir diski yeniden üretmek için gereken her şey

---

## Faz sonrası fikir havuzu

- Blu-ray'den DVD'ye özel "mastering" profilleri (film türüne göre)
- Hedef cihaza göre profil (CRT TV için dikey low-pass, modern TV için daha keskin)
- Bölüm başına otomatik kalite kontrolü, sorunlu sahneleri yüksek bitrate ile yeniden encode etme (segment re-encode)
