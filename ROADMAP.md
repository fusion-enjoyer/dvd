# Yol Haritası

Hedef: **Windows masaüstü uygulaması.** Her faz kendi başına kullanılabilir bir çıktı üretir; her özellik önce motora
(CLI ile test edilebilir), sonra arayüze eklenir. Projenin kalbi **Faz 2 (kalite motoru)**.

İlgili belgeler: [özellik listesi](docs/ozellikler.md) · [profiller](docs/profiller.md) · [arayüz](docs/arayuz.md) ·
[kalite](docs/kalite.md) · [DVD teknik notları](docs/dvd-spec.md) · [mimari](docs/mimari.md) · [kararlar](docs/kararlar.md)

---

## Faz 0 — Temel ve keşif

- [x] Arayüz teknolojisi: Python + PySide6
- [x] Kalan açık kararları kapat (lisans, ISO üretimi, yakma yöntemi)
- [x] Windows geliştirme ortamı: Python + `uv`, VapourSynth, FFmpeg, HCEnc, dvdauthor/spumux Windows derlemeleri (VapourSynth eklentileri Faz 2'de)
- [x] `tools/` sürüm listesi: hangi .exe hangi sürüm, nereden indirilir (repoya .exe girmez)
- [x] **HCEnc ↔ VapourSynth köprüsü** prototip denemesi: named pipe + `DvdSource.dll`, 2 geçiş çalışıyor
- [x] Araç zinciri elle denendi: VapourSynth → HCEnc → FFmpeg (AC-3, mux) → dvdauthor → VIDEO_TS (Türkçe yolda)
- [ ] **Test korpusu**: zor kısa klipler (karanlık sahne/banding, film greni, hızlı hareket, ince detay, 2.39:1, 2D animasyon, interlaced yayın), 30–60 sn
- [ ] **Referans DVD seti**: elimizdeki orijinal DVD'lerden farklı türlerde 5–10 tane seç, ripleyip sakla
- [ ] **Referans analizi (elle)**: bitrate eğrisi, GOP, matrisler, pulldown, ses formatları, menü yapısı — bulguları `docs/referans/` altına yaz
- [ ] **Cihaz matrisi**: test edeceğimiz oynatıcılar/TV'ler, her birinin PAL/NTSC/DVD-9 desteği ([docs/cihazlar.md](docs/cihazlar.md); Sony DVP-NS38 eklendi, özellikleri ilk test diskiyle doğrulanacak)

**Bitti kriteri:** Windows'ta araç zinciri elle çalışıyor; referans DVD'lerin teknik profili belgelenmiş.

---

## Faz 1 — Uçtan uca MVP

Amaç: Tek film → oynatılabilir ISO. Kalite ikincil; boru hattı uçtan uca çalışsın.

**Motor + CLI**
- [x] Proje modeli ve proje dosyası (`*.dvd.yaml`, `dvd new`, `dvd check`)
- [x] Kaynak analizi (ffprobe): `dvd probe`; HDR, interlaced, değişken kare hızı ve dikey video tespiti
- [x] Basit video encode (2 geçiş VBR, anamorfik 16:9 / 4:3, PAL / NTSC): BestSource → VapourSynth → HCEnc
- [x] AC-3 ses, 48 kHz; SRT → subpicture (basit render)
  - [x] AC-3 ses (PAL hızlanmasında perde korunur)
  - [x] SRT → subpicture: dosya ya da gömülü metin izi, Türkçe kodlama tespiti, Qt ile 4 renkli render, anamorfik düzeltme, spumux
- [x] Bölümleri içe aktar, I-frame zorla (bölüm, en yakın VOBU başına düşüyor; sapma < 0.4 sn)
- [x] dvdauthor ile menüsüz VIDEO_TS → ISO
  - [x] VIDEO_TS (`dvd build`)
  - [x] ISO (kendi UDF 1.02 + ISO 9660 yazıcımız, K10): `dvd build` ve `dvd iso`
- [x] Bitrate planlayıcı v0
- [ ] Sony DVP-NS38'de ilk gerçek disk testi

**Arayüz**
- [x] Uygulama iskeleti: ana pencere, sol gezinme, alttaki disk bütçe çubuğu (`dvd gui`, Basit/Profesyonel mod)
- [x] Sürükle-bırak kaynak, iz seçimi, profil seçimi, Build, ilerleme
  - [x] Sürükle-bırak / dosya seç, otomatik proje, profil seçimi, disk önizleme karesi
  - [x] Ses ve altyazı izi seçimi (dil, varsayılan iz, SRT ekleme; Pro modda kanal ve bitrate)
  - [x] Build ve ilerleme ekranı (arka planda çalışır, aşama aşama ilerleme, uyarılar Türkçe)

**Paketleme**
- [x] İlk Windows kurulum paketi (araçlar dahil): `scripts/package.py` → `dist/DVDStudyo-Setup-x.y.z.exe` (146 MB, kullanıcı başına kurulum, yönetici izni gerekmez)

**Bitti kriteri:** Uygulamaya MKV sürükleyip ISO alıyoruz, gerçek bir DVD oynatıcıda izliyoruz.

---

## Faz 2 — Kalite motoru ⭐

**Ön işleme (VapourSynth)**
- [x] Siyah bant tespiti + crop, bantları 16 piksel macroblock sınırına hizalı pad (24 kare örneklenir, karanlık kareler atlanır; şekil korunur, gerekirse kaynaktan birkaç piksel fazla kırpılır)
- [ ] Küçültme kernel'ları karşılaştırması (Spline36 / Lanczos / SSIM downsampler / linear-light)
- [x] BT.709 → BT.601 renk dönüşümü + doğru bayraklar: 16-bit matris dönüşümü (aralık dahil); akışta PAL 5/5/5, NTSC 6/6/6 renk açıklaması, denetim uyuşmazlığı uyarır
- [ ] Yüksek bit derinliğinde işlem, deband, kontrollü dithering
  - [x] Altyapı: 16-bit zincir (ölçekleme, matris, deband, bantlar), sonda tek dither adımı; deband vszip ile, kademe profil katmanlarından (`video.overrides` ile elle)
  - [ ] Kademe ve dither türünü test korpusuyla ölç ve ayarla (ripler gelince)
- [ ] Denoise / gren yönetimi, deinterlace (QTGMC), HDR → SDR tonemapping
  - [x] HDR → SDR: HDR10 (PQ) ve HLG, BT.2390 eğrisi en parlak kanala uygulanır (renk tonu kaymaz), tepe MaxCLL / mastering display'den; küçültmeden sonra float'ta, ek eklenti yok. Önizlemede kaynak da aynı şekilde gösterilir
  - [ ] Ton eşleme değerlerini HDR kliplerle kalibre et; Dolby Vision profil 5; denoise/gren; deinterlace
- [ ] Kişisel videolar: değişken kare hızı, 50/60 fps → interlaced encode, dikey video yerleşimi, telefon HDR'ı
  - [x] 50p → PAL 25i, 59.94/60p → NTSC 29.97i (iki kaynak karesi bir DVD karesinin iki alanı, üst alan önce; renk alan başına 4:2:0); 30p → NTSC 29.97 (%0.1 yavaşlatma, ses eşlenir); HCEnc ve FFmpeg
  - [x] Değişken kare hızı: ortalama hız en yakın standart hıza oturtulur, kaynak zaman damgalarına göre sabit hıza çevrilir (BestSource), ses senkronu korunur
  - [x] Dikey video: döndürme bilgisi okunur, 4:3 karede yan bantlar; bantlar siyah ya da bulanık görüntü (`side_fill`, telefon profilinde varsayılan bulanık); dikey videoda proje telefon profiliyle açılır
  - [x] Telefon HDR'ı: HLG ve HLG/HDR10 tabanlı Dolby Vision (profil 8) ton eşlemeyle
  - [ ] 30/60 fps → PAL kare hızı dönüşümü

**Encode**
- [ ] Encoder sürücüleri: HCEnc, FFmpeg (ayarlı parametre seti), x262 (deneysel)
  - [x] HCEnc ve FFmpeg (DVD bayrakları düzeltilmiş, uyumluluk denetiminden geçiyor); `video.overrides: {encoder: ffmpeg}`, HCEnc yoksa otomatik FFmpeg
  - [ ] x262 (deneysel); HCEnc ↔ FFmpeg kalite karşılaştırması korpusla
- [x] NTSC soft pulldown bayrak enjektörü (kendimiz yazacağız): `video/pulldown.py`, FFmpeg encode'una bağlı; denetim GOP'u alan sayısıyla da ölçüyor
- [x] PAL speedup (ses pitch seçenekli): `audio_pitch: keep | raise` (kullanıcı profilinde)
- [x] Encode sonrası uyumluluk denetimi (VBV, tepe bitrate, GOP)
  - [x] Video akışı: MP@ML, boyut, kare hızı, progressive_sequence, GOP uzunluğu, ardışık B, 1 sn tepe, VBV simülasyonu (`dvd verify`, her build'de)
  - [x] VOB düzeyinde mux bitrate'i (10.08 Mbps, ses dahil): 2048 baytlık paketler, bildirilen mux hızı, 1 sn tepe, decode zamanından geç gelen paketler (`dvd verify x.mpg`, her build'de)

**Profiller**
- [x] Katmanlı profil sistemi: standart → medya → içerik tipi → izleme ortamı → ses düzeni → kullanıcı (`src/dvd/profiles.py`, `dvd profile show`; deband/dither/kernel, tepe bitrate, altyazı boyutu ve güvenli alan, ses düzeni)
- [ ] İçerik tipi ve izleme ortamı profillerinin değerlerini korpus + cihaz matrisiyle kalibre et
- [x] Kullanıcı profili kaydet / dışa aktar (`dvd profile save|list|export|import`)

**Ölçüm ve arayüz**
- [x] VMAF / SSIM / PSNR, en kötü sahneler listesi: SSIMULACRA2 + XPSNR (vszip, süreç içinde), en kötü saniyeler; `dvd measure`
- [ ] **Test encode** (seçili aralık) ve **karşılaştırma ekranı** (kaynak / sonuç / referans DVD)
  - [x] Test encode: `dvd trial --at 42:17 --seconds 20 [--kbps N]`, en kötü karenin A/B PNG'leri
  - [x] Arayüzde karşılaştırma: Kaynak / Diskte / Kaydırmalı, filmde gezinme, "Bu aralığı test encode et (20 sn)" ve sonucun puanları
  - [x] Yakınlaştırma (Sığdır / %100 / %200 / %400, sürükleyerek kaydırma), kare kare ilerleme (‹ › ve ← →); disk karesi 720 piksel genişliğinde, kaynak kendi çözünürlüğüne yakın gösterilir
  - [ ] Referans DVD ile üçlü karşılaştırma (ripler gelince)
- [x] Başlık ekranı: crop düzeltme, ön işleme ayarları, önizleme
  - [x] Önizleme (kaynak ve disk görüntüsü aynı geometride), tespit edilen crop ve ön işleme değerleri
  - [x] Crop'u ve ön işleme ayarlarını arayüzden düzenleme: crop Otomatik / Kırpma yok / Elle (4 kenar, 2 piksel adım); küçültme, deband, dither, encoder için "Profilden" ya da elle değer; her değişiklik kaydedilir, önizleme yenilenir

**Bitti kriteri:** Kör karşılaştırmada sonuç, referans ticari DVD'lerle aynı ligde; metrikler raporlanıyor.

---

## Faz 3 — Ses, altyazı, bölümler

- [x] Çoklu ses izi, AC-3 passthrough, HD ses → 5.1 AC-3, stereo downmix, DRC/gece modu, delay: DVD'ye uyan AC-3 bit bit kopyalanır; stereo downmix Dolby Pro Logic II matrisiyle; gece modu sıkıştırıcı; gecikme iz başına (ms) ve dosyanın kendi ses/görüntü kayması otomatik korunur
- [x] Altyazı render motoru: istenen font, anamorfik düzeltme, akıllı kenar yumuşatma (4 renk), Türkçe kodlama tespiti, stil editörü ve stil şablonları: hazır stiller (Varsayılan, Büyük, Sarı, İnce, Kalın), kendi stillerim (`%APPDATA%\DVD Studyo\styles`), iz başına stil seçimi, canlı önizlemeli düzenleyici
- [ ] ASS, PGS, VobSub girişi; forced altyazılar; letterbox bandına altyazı
  - [x] ASS/SSA/WebVTT dosyaları (metin olarak, kendi stilimizle çizilir); Blu-ray PGS: kendi .sup okuyucumuz, resim görüntüyle aynı crop/ölçekle DVD karesine taşınır, 4 renge indirilir; PGS'teki tek tek forced işaretleri diske geçer; PGS'te letterbox bandındaki altyazı bantta kalır
  - [ ] VobSub (DVD) ve DVB resim altyazıları; renkli PGS'te rengi koruma; metin altyazıyı letterbox bandına yerleştirme seçeneği
- [ ] Bölüm zaman çizelgesi: elle düzenleme, otomatik öneri, thumbnail karesi seçimi
  - [x] Bölümler sayfası: kaynaktan / aralıkla / elle / yok; elle listede zaman düzenleme, silme, önizlemedeki kareye ekleme; her bölümün karesi; sahne geçişlerine göre öneri (her N dakikada bir nokta, ±15 sn içindeki en belirgin kesmeye kaydırılır)
  - [ ] Bölüm menüsü için ayrı thumbnail karesi seçimi (Faz 4 menüleriyle)
- [x] İlgili arayüz ekranları (Ses, Altyazı, Bölümler)

**Bitti kriteri:** Çok dilli, altyazılı, bölümlü film diski; altyazılar ticari DVD'ler kadar temiz.

---

## Faz 4 — Menü motoru ve editör v1

- [ ] Menü modeli: sayfalar, öğeler, butonlar, eylemler, navigasyon
- [ ] Render: arka plan + 3 durumlu highlight subpicture'ları (4 renk sınırı)
- [ ] Otomatik navigasyon grafiği + elle düzenleme
- [ ] Standart menü seti: Ana, Bölümler (sayfalı), Ses, Altyazı, Ayarlar
- [ ] Şablon sistemi + ilk hazır şablonlar (Minimal, Sinematik, 2000'ler DVD'si)
- [ ] First Play zinciri (intro → menü), başlık bitince davranışı
- [ ] **TMDB entegrasyonu**: otomatik eşleştirme, Türkçe başlık/özet, arka plan/afiş/saydam logo seçici, menü şablonlarına bağlama
- [ ] **Menü editörü v1**: tuval, katmanlar, özellikler paneli, güvenli alan kılavuzları, navigasyon okları görünümü
- [ ] **DVD VM simülatörü v1**: menüleri yakmadan klavyeyle gezme

**Bitti kriteri:** Editörde tasarlanan statik menüler gerçek oynatıcıda doğru çalışıyor.

---

## Faz 5 — Diziler

- [ ] Sezon klasörü içe aktarma, S01E01 ayrıştırma, TMDB'den bölüm isimleri ve görselleri
- [ ] **Disk seti planlayıcı** (bölüm sayısı + medya + kalite hedefi → dağılım)
- [ ] Hepsini oynat, bölüm seçim menüsü, set boyunca ortak tasarım ("Disk 2 / 4")
- [ ] Dizi kutusu menü şablonu

**Bitti kriteri:** Bir sezonu tutarlı menülü disk setine çevirebiliyoruz.

---

## Faz 6 — Gelişmiş menüler ve disk mantığı

- [ ] Hareketli menüler (video arka plan, giriş + döngü), hareketli thumbnail'lar, geçiş videoları
- [ ] Kaldığın yerden devam, rastgele bölüm, zaman aşımıyla otomatik oynat
- [ ] Ses/altyazı menüsünde seçili olanı gösterme
- [ ] Gizli içerik butonları, kumanda kısıtlamaları
- [ ] **Disk haritası düzenleyicisi** (düğüm grafiği)
- [ ] Şablon editörü, şablon dışa/içe aktarma

---

## Faz 7 — Kendi authoring motorumuz (dibine kadar)

- [ ] IFO/BUP okuyucu → referans analizörü uygulamaya entegre (menü ağacı, VM komutları okunur halde)
- [ ] IFO yazıcı: VMG, VTS, PGC, program/cell tabloları, VM komutları
- [ ] VOB multiplexer: NAV pack (PCI/DSI), VOBU sınırları, zaman damgaları
- [ ] Seamless branching, çoklu açı
- [ ] DVD-9 katman geçişi yerleşimi
- [ ] VM komut derleyicisi (okunabilir mini dil → DVD VM)
- [ ] Tam uyumluluk doğrulayıcı

**Bitti kriteri:** dvdauthor olmadan üretilen diskler tüm cihaz matrisinde çalışıyor.

---

## Faz 8 — Çıktı ve cila

- [ ] Doğrudan yakma (IMAPI2 / ImgBurn), yakma sonrası doğrulama
- [ ] Kapak ve disk etiketi tasarımı, yazdırılabilir PDF
- [ ] İş kuyruğu, bitince bildirim/kapatma, duraklat-devam
- [ ] Proje arşivi, Türkçe/İngilizce arayüz, tema, otomatik güncelleme

---

## Fikir havuzu

- Referans DVD'den otomatik profil çıkarma ("bu diskin ayarlarını kopyala")
- Otomatik sorunlu sahne tespiti → segment yeniden encode
- Çevrimiçi meta veri (dizi bölüm isimleri, afişler)
- Harici dublaj sesini otomatik senkronlama
