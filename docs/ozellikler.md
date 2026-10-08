# Özellik Listesi

Öncelik etiketleri: **[MVP]** ilk çalışan sürüm · **[v1]** ilk "gerçek" sürüm · **[v2]** sonraki büyük sürüm · **[İleri]** fikir havuzu

## A. Proje ve iş akışı

- [MVP] Proje dosyası (tek dosya, elle de okunabilir), otomatik kaydetme
- [MVP] Sürükle-bırak kaynak ekleme: MKV, M2TS, MP4, TS, MOV — Blu-ray ripleri kadar **kendi videoların** (telefon, kamera, montaj çıktısı) da
- [MVP] Kaynak bilgi paneli: çözünürlük, fps, renk uzayı, HDR, ses/altyazı/bölüm izleri
- [MVP] **Canlı disk bütçe çubuğu**: her değişiklikte doluluk ve tahmini video bitrate'i güncellenir
- [v1] Yeni proje sihirbazı: Film / Dizi / Karışık → standart → medya → profiller
- [v1] Önbellek: sadece menü değişince film yeniden encode edilmez; neyin yeniden üretileceği gösterilir
- [v1] İş kuyruğu: birden fazla proje sırayla; bitince bildirim / bilgisayarı uyut-kapat
- [v1] Build öncesi gereken geçici disk alanı tahmini ve kontrolü
- [v2] Blu-ray klasörü / ISO (şifresiz) girişi, playlist (MPLS) seçimi
- [v2] Proje şablonları ("Benim film diskim" düzeni)
- [İleri] Duraklat / devam ettir (uzun encode'lar için kaldığı yerden)

## B. Video

- [MVP] PAL / NTSC seçimi, kaynağa göre öneri
- [MVP] 16:9 anamorfik ve 4:3 başlıklar
- [MVP] Otomatik siyah bant tespiti + önizlemeli elle düzeltme
- [v1] NTSC soft pulldown (23.976p progresif encode + bayrak enjektörü)
- [v1] PAL speedup (25p)
- [v1] Ön işleme zinciri: küçültme kernel'ı, renk matrisi dönüşümü, deband, dither, denoise, gren yönetimi
- [v1] Letterbox bantlarını macroblock sınırına hizalama
- [v1] Encoder seçimi: FFmpeg / HCEnc / (deneysel) x262
- [v1] Hedef mod: "diski doldur" (boyut hedefli) veya "kalite hedefli"
- [v1] **Test encode**: seçili 10–30 sn'lik aralığı tam ayarlarla encode edip hemen karşılaştır
- [v1] Interlaced kaynaklar: deinterlace (QTGMC) veya interlaced encode
- [v1] HDR/UHD kaynak → SDR tonemapping
- [v1] **Kişisel videolar**: değişken kare hızı (telefon) düzeltme, 50/60 fps kaynaklardan akıcı hareketi koruyan interlaced encode, eski kamera (DV, 4:3, interlaced) kayıtları, telefon HDR'ı (HLG/Dolby Vision) → SDR
- [v1] **Dikey video**: bulanık arka planlı ya da siyah kenarlı yerleşim
- [v2] **Sahne bazlı bitrate müdahalesi** (zone): zor sahneye ekstra bit, jeneriğe daha az
- [v2] GPU hızlandırma: decode (NVDEC/QSV/AMF) ve tonemapping
- [İleri] Otomatik sorunlu sahne tespiti → sadece o segmenti yeniden encode etme

## C. Ses

- [MVP] İz seçimi, dil etiketi, sıralama, varsayılan iz
- [MVP] AC-3 encode (2.0 / 5.1, bitrate seçimi), 48 kHz'e dönüştürme
- [v1] Uygun AC-3 kaynaklarda yeniden encode etmeden kopyalama (passthrough)
- [v1] TrueHD / DTS-HD / Atmos / E-AC-3 → 5.1 AC-3, doğru downmix
- [v1] Stereo downmix (Pro Logic II uyumlu seçeneği), dialnorm, gece modu (DRC)
- [v1] PAL speedup: pitch düzeltmeli / düzeltmesiz
- [v1] Gecikme (delay) düzeltme
- [v2] LPCM, MP2, DTS (passthrough) desteği
- [v2] Yorum (commentary) izi ve menüde ayrı gösterimi
- [İleri] Harici ses dosyası ekleme (başka kaynaktan Türkçe dublaj vb.), otomatik senkron hizalama

## D. Altyazı

- [MVP] SRT girişi, **Türkçe karakter kodlaması otomatik tespiti** (Windows-1254 / ISO-8859-9 / UTF-8)
- [MVP] Kendi render motorumuz: 4 renkli subpicture, anti-alias'lı kontur
- [v1] ASS/SSA girişi (italik, kalın, konumlandırma; desteklenmeyen efektler için uyarı)
- [v1] PGS (Blu-ray SUP) → yeniden ölçekleme + 4 renge kuantizasyon
- [v1] VobSub (IDX/SUB) olduğu gibi kullanma
- [v1] **İstediğin fontu kullanma**: bilgisayardaki herhangi bir TTF/OTF font (altyazılar diske resim olarak yazıldığı için font kısıtı yok)
- [v1] **Anamorfik düzeltme**: 16:9 disklerde oynatıcı altyazıyı yatayda gerer; render sırasında bunu telafi et, harfler şişman/geniş görünmesin
- [v1] Akıllı kenar yumuşatma: 4 renk sınırındaki 2 ara rengi kontur ve geçiş için en iyi şekilde kullan
- [v1] Stil editörü: font, boyut, dolgu/kontur/gölge rengi, kalınlık, konum, güvenli alan — **gerçek DVD renk sınırıyla önizleme**
- [v1] Forced altyazı, varsayılan altyazı, zamanlama kaydırma
- [v1] Satır kırma / satır uzunluğu kontrolü
- [v1] Altyazı stil şablonları ("Sinema", "Netflix tarzı", "Klasik DVD", "Büyük — uzaktan izleme")
- [v2] Aynı dilde iki farklı stil izi (örn. "Türkçe" ve "Türkçe — büyük")
- [v2] Letterbox'lı filmlerde altyazıyı alttaki siyah banda yerleştirme seçeneği
- [v2] PGS → OCR → metin → bizim stilimizle yeniden render
- [İleri] Altyazı zamanlama düzeltme aracı (ses dalgasına göre)

## E. Bölümler

- [MVP] Kaynaktan içe aktarma, bölüm noktalarında I-frame zorlama
- [v1] Elle ekle/sil/taşı (zaman çizelgesi üzerinde), isimlendirme
- [v1] Otomatik: her X dakikada bir / sahne değişimine göre öneri
- [v1] Menü thumbnail karesi seçimi (bölüm başı değil, bölümü en iyi temsil eden kare)

## F. Menüler

- [v1] Menü türleri: Ana, Bölüm seçimi (sayfalı), Ses, Altyazı, Ses+Altyazı (Ayarlar), Ekstralar
- [v1] Arka plan: görsel, filmden kare, bulanıklaştırılmış kare
- [v1] Öğeler: metin, görsel, buton, bölüm thumbnail'ı, şekil
- [v1] Buton highlight stilleri: alt çizgi, çerçeve, ok/ikon, renk değişimi (4 renk sınırı içinde)
- [v1] Normal / seçili / aktif durum renkleri
- [v1] Otomatik navigasyon (konuma göre) + elle düzenleme, kenarda başa sarma
- [v1] Hazır şablon kütüphanesi: Minimal, Sinematik, 2000'ler DVD'si, Dizi kutusu
- [v1] Menü müziği (still menüde döngü sesi)
- [v1] Güvenli alan kılavuzları (izleme profiline göre)
- [v1] Ses/altyazı menüsünde **şu an seçili olanı işaretleme**
- [v2] Hareketli menüler: video arka plan, döngü noktası, giriş animasyonu + döngü kısmı
- [v2] Hareketli bölüm thumbnail'ları
- [v2] Menüler arası geçiş videoları
- [v2] Zaman aşımı: menüde X sn işlem olmazsa otomatik oynat
- [v2] Şablon dışa/içe aktarma, şablon editörü
- [İleri] Gizli içerik (easter egg) butonları

## G. Disk mantığı / oynatma davranışı

- [MVP] Disk takılınca: doğrudan film veya menü
- [v1] **First Play zinciri**: logo/intro → (opsiyonel uyarı ekranı) → ana menü; atlanabilir/atlanamaz seçimi
- [v1] Başlık bitince: menüye dön / sonrakine geç / dur
- [v1] Bölge kodu: bölgesiz (varsayılan)
- [v1] Oynatıcının dil tercihine göre otomatik ses/altyazı seçimi
- [v2] Hepsini oynat, oynatma sırası
- [v2] Kaldığın yerden devam (oturum içi), "Devam Et" butonu
- [v2] Rastgele bölüm oynat (DVD VM'in rastgele sayı komutuyla)
- [v2] Kumanda kısıtlamaları (UOP): örn. intro sırasında menü tuşu, varsayılan hepsi serbest
- [İleri] **Disk haritası düzenleyicisi**: diskin tüm mantığını düğüm grafiği olarak görsel düzenleme

## L. TMDB entegrasyonu

Film/dizi adını ya da dosya adını verince bilgileri ve görselleri [TMDB](https://www.themoviedb.org/)'den otomatik çeker.

- [v1] Dosya adından otomatik eşleştirme (`Interstellar.2014.1080p...` → Interstellar, 2014), elle arama ve doğru sonucu seçme
- [v1] **Türkçe meta veri**: Türkçe başlık ve özet (yoksa İngilizce'ye düşer)
- [v1] Disk adı / proje adı / disk etiketi (volume label) otomatik doldurma
- [v1] **Menü görselleri**: arka plan (backdrop), afiş, **saydam logo** (filmin kendi yazı logosu — menüde başlık olarak çok iyi durur)
- [v1] Görsel seçici: TMDB'deki tüm afiş/arka plan/logolar arasından seçme, dile göre filtreleme (Türkçe afiş)
- [v1] Diziler: sezon ve **bölüm isimleri**, bölüm özetleri, bölüm görselleri (bölüm seçim menüsünde thumbnail olarak), sezon afişi
- [v2] Menü şablonlarında TMDB alanları: `{başlık}`, `{yıl}`, `{tür}`, `{süre}`, `{özet}`, `{oyuncular}` gibi yer tutucular
- [v2] Kapak tasarımında afiş, özet, oyuncular, yönetmen, süre otomatik
- [v2] Önbellek: çekilen bilgiler ve görseller projeye kaydedilir, internet olmadan da yeniden üretilebilir
- [İleri] fanart.tv gibi ek kaynaklar (disk baskı görselleri, clearart)

Not: TMDB API anahtarı ücretsiz; kullanıcı kendi anahtarını ayarlara girer. TMDB kullanım şartları gereği uygulamada
TMDB'ye atıf (logo + "bu ürün TMDB API'sini kullanır ancak TMDB tarafından onaylanmamıştır") gösterilir.

## H. Diziler

- [v1] Sezon klasörü içe aktarma, dosya adından sezon/bölüm no (S01E01) çıkarma
- [v1] Bölüm isimleri (elle, dosya adından veya TMDB'den)
- [v1] **Disk seti planlayıcı**: bölüm sayısı + medya + kalite hedefi → disk sayısı ve dağılım, elle değiştirilebilir
- [v1] Set boyunca ortak menü tasarımı, "Disk 2 / 4" bilgisi
- [v2] Hepsini oynat + bölüm seçimi + bölüm içi bölümler
- [v2] Intro / jenerik için bölüm işareti
- [İleri] Çevrimiçi meta veri (bölüm isimleri, görseller) — opsiyonel

## I. Analiz ve kalite

- [v1] **Referans DVD analizörü** (ripteki VIDEO_TS / ISO): bitrate grafiği, GOP yapısı, quant matrisleri, pulldown bayrakları, ses/altyazı formatları
- [v1] Uyumluluk denetleyici: tepe bitrate, VBV, GOP, sınırlar
- [v1] Kalite metrikleri (VMAF/SSIM/PSNR), en kötü sahneler listesi
- [v1] **Karşılaştırma görüntüleyici**: kaynak / sonuç / referans DVD, kaydırmalı ve yan yana
- [v2] Analizörde menü yapısı ağacı ve VM komutlarının okunur gösterimi (ticari DVD'lerin menülerini "nasıl yapmışlar" diye incelemek için)
- [v2] Encoder benchmark aracı

## J. Çıktı

- [MVP] VIDEO_TS klasörü ve ISO
- [v1] DVD-9 katman geçişi: otomatik (sahne geçişi/sessiz an) + elle seçim
- [v1] Doğrudan yakma: sürücü seçimi, hız, yakma sonrası doğrulama
- [v2] Kapak tasarımı: standart DVD kutusu, slim kutu, disk etiketi; yazdırılabilir PDF
- [v2] Proje arşivi: diski yeniden üretmek için gereken her şey

## K. Uygulama

- [MVP] Windows kurulum paketi, tüm araçlar paketli, ek kurulum gerektirmez
- [v1] Koyu / açık tema, Türkçe / İngilizce arayüz
- [v1] Ayarlar: geçici klasör (yüksek boş alan gerekir), iş parçacığı sayısı, araç yolları
- [v1] Log görüntüleyici, hata durumunda anlaşılır mesaj
- [v1] Kullanıcı profilleri ve şablonların tek dosyada yedeklenmesi
- [İleri] Otomatik güncelleme
