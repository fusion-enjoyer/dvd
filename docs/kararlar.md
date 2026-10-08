# Kararlar

## Verilen kararlar

| Tarih | # | Karar | Gerekçe / not |
|---|---|---|---|
| 2026-10-08 | K1 | **PAL ve NTSC ikisi de** desteklenecek, proje bazında seçilir | Kaynağın kare hızına göre uygulama öneri yapar |
| 2026-10-08 | K2 | İzleme ortamı sabit değil → **izleme ortamı profilleri** (Modern TV, Projeksiyon, CRT, Bilgisayar, Konsol, Taşınabilir, Evrensel) | Bkz. [profiller.md](profiller.md) |
| 2026-10-08 | K3 | Hedef platform **Windows masaüstü uygulaması**; geliştirme de Windows'ta | Docker gereksiz: araçlar uygulamayla paketlenir |
| 2026-10-08 | K4 | Motor GUI'den bağımsız kütüphane + CLI; arayüz her fazda motorun üstüne eklenir | Test edilebilirlik, otomasyon |
| 2026-10-08 | K5 | HCEnc kullanılacak (Windows'ta native çalışıyor); FFmpeg alternatif backend | Kalite farkı Faz 2'de ölçülecek |
| 2026-10-08 | K6 | DVD-5 ve DVD-9 ikisi de; uzun filmlerde DVD-9 önerilir | Kullanıcının yazıcısı DL destekliyor |
| 2026-10-08 | K8 | Arayüz teknolojisi: **Python + PySide6 (Qt 6)** | Kullanıcı öneriyle ilerlemeyi seçti; tek dil, VapourSynth uyumu, menü editörü için QGraphicsView |
| 2026-10-08 | — | Orijinal DVD'ler yalnızca geliştirmede kalibrasyon için; uygulama kullanıcıdan referans rip istemez | Kişisel videolar dahil her kaynakta profillerle çalışır |
| 2026-10-08 | K12 | **TMDB entegrasyonu** (başlık, Türkçe meta veri, menü görselleri, dizi bölüm bilgileri) | Kullanıcı isteği; API anahtarını kullanıcı girer, TMDB atfı gösterilir |
| 2026-10-08 | K13 | Altyazıda **serbest font seçimi** + anamorfik düzeltme | Subpicture resim olduğu için font kısıtı yok |
| 2026-10-08 | K14 | Arayüz **koyu tema** öncelikli (açık tema sonra) | Video önizlemede renk algısını bozmaz; video araçlarında yaygın |
| 2026-10-08 | K15 | **İki kullanım modu**: Basit mod (preset'lerle, az karar) ve Profesyonel mod (tüm ayarlar) | Kurcalamak istemeyen de isteyen de aynı uygulamayı kullanır; ayrıntılar [arayuz.md](arayuz.md) |
| 2026-10-08 | — | Ön işleme VapourSynth ile | Kalite ekosistemi |
| 2026-10-08 | — | Önce menüsüz uçtan uca MVP, sonra kalite motoru | Erken gerçek cihaz testi |
| 2026-10-09 | K7 | Repo **public**, lisans **GPL-3.0-or-later** | dvdauthor ve FFmpeg GPL derlemesiyle birlikte dağıtılıyor |
| 2026-10-09 | — | Film kaynaklarında (23.976/24 fps) önerilen standart **PAL** | Test zinciri SCART'lı bir PAL TV; PAL 576 satır verir. Bedeli %4 hızlanma. NTSC her zaman seçilebilir; cihaz testinden sonra yeniden bakılacak |
| 2026-10-09 | — | Proje dosyası YAML, uzantı `*.dvd.yaml`, `version` alanıyla | Elle okunup düzenlenebilir; sürüm alanı ileride geçiş için |
| 2026-10-09 | — | HCEnc'e kareler kendi köprümüzle (named pipe + `DvdSource.dll`) verilir | Ara dosya yok, iki geçiş çalışıyor; bkz. riskler |
| 2026-10-09 | K10 | ISO için **kendi UDF 1.02 + ISO 9660 yazıcımız** (`src/dvd/output/iso.py`) | xorriso DVD-Video UDF'si üretmiyor, mkisofs yalnızca Cygwin'de. Dosyalar IFO'ların gösterdiği sektörlere yerleşiyor; pycdlib, 7-Zip ve libdvdread ile doğrulandı. Faz 7'deki katman geçişi için de temel |
| 2026-10-09 | K9 | Faz 1–7'de **yalnızca ISO** üretilir; kullanıcı Windows'un yerleşik yakıcısıyla ya da ImgBurn ile yakar. Doğrudan yakma Faz 8'de (IMAPI2; DVD-9 katman geçişi kontrolü yetmezse ImgBurn) | Yakma, disk üretiminden bağımsız ve en son eklenebilecek parça |
| 2026-10-09 | K11 | Arayüz **Türkçe**; tüm metinler baştan `src/dvd/gui/i18n.py` tablosundan geliyor, İngilizce v1'de bu tabloya eklenir | Çeviri altyapısı sonradan eklemek pahalı |
| 2026-10-09 | — | Paketleme: PyInstaller/Nuitka yerine **taşınabilir CPython + kilitli bağımlılıklar + küçük C başlatıcı**, Inno Setup ile kullanıcı başına kurulum | VapourSynth eklenti yolu ve PySide6 dondurulmuş uygulamada kırılgan; bu düzen geliştirme ortamıyla birebir aynı çalışır. Yönetici izni gerekmez |
| 2026-10-09 | — | FFmpeg paketlenirken gyan.dev **shared** derlemesi kullanılır | Aynı özellikler, iki statik exe'nin yarısı boyut (245 MB yerine 424 MB) |
| 2026-10-09 | — | 32-bit VC++ çalışma zamanı (msvcp140, vcruntime140) HCEnc'in yanında uygulamayla gelir | x86 AviSynth.dll ister; Microsoft uygulama içi kopyaya izin veriyor |
| 2026-10-09 | — | Her build'de encode edilen video DVD sınırlarına göre denetlenir; hata varsa disk üretilmez | Gerçek oynatıcıda takılacak bir diski yakmadan yakalamak. Not: FFmpeg `mpeg2video` varsayılanı `progressive_sequence=1` yazıyor (DVD'de 0 olmalı); FFmpeg encoder sürücüsü yazılırken düzeltilmeli |
| 2026-10-09 | — | Kod, CLI çıktısı ve commit'ler İngilizce; arayüz ve belgeler Türkçe | Kod ve araç çıktısı uluslararası, kullanıcıya görünen her şey Türkçe |
| 2026-10-09 | — | Arayüz fontları uygulamayla gelir: Bricolage Grotesque, Source Sans 3, JetBrains Mono (OFL, `src/dvd/assets/fonts`) | Tasarım sistemi; Windows'ta kurulu font aranmaz |
| 2026-10-09 | — | Altyazılar Qt ile çizilir, varsayılan font **Source Sans 3 SemiBold** (uygulamayla gelir); 4 renk: saydam, dolgu, kontur, yarı saydam kontur kenarı. Anamorfik düzeltme (K13) baştan var | Editörde görülenle diske yazılan aynı kod; 16:9'da harfler şişmez |
| 2026-10-09 | — | SRT kodlaması: BOM'a, sonra UTF-8 geçerliliğine bakılır; değilse Windows-1254 | 1254, ISO-8859-9 Türkçe harflerini de doğru okur |
| 2026-10-09 | — | `dvd new`: ana ses Türkçe değilse ve kaynakta Türkçe altyazı varsa altyazı açık başlar | Türk izleyicinin beklentisi |

## Açık kararlar

Şu an açık karar yok. Yeni bir soru çıktığında buraya `| # | Soru | Seçenekler | Öneri |` tablosuyla eklenir.

## Doğrulanacak riskler

| Risk | Neden önemli | Ne zaman |
|---|---|---|
| HCEnc girdisi | **Çözüldü (2026-10-09):** HCEnc 0.28 32-bit ve yalnızca `.avs`/`.d2v` okuyor. Kendi köprümüzü yazdık: motor VapourSynth karelerini named pipe ile sunuyor, 32-bit `DvdSource.dll` AviSynth eklentisi kareleri numarayla istiyor. İki geçişli encode ve rastgele erişim çalışıyor, ara dosya yok. Test: 120 kare, 241 istek (2 geçiş + yoklama), PSNR-Y 50.7 dB. Gerçek film üzerinde hız ölçümü Faz 1'de | Faz 0 |
| HCEnc'in geleceği | 2015'ten beri geliştirilmiyor (son sürüm 0.28). Kalite avantajı Faz 2'de FFmpeg/x262 ile karşılaştırılarak ölçülmeli | Faz 2 |
| HCEnc'in uygulamayla dağıtılması | Freeware ama yeniden dağıtım izni doğrulanmadı. Kurulum paketi şimdilik kişisel kullanım için; herkese açık sürümden önce izin alınmalı ya da HCEnc ilk açılışta kullanıcıdan istenmeli | İlk açık sürüm |
| dvdauthor/spumux Windows derlemeleri | **Çözüldü (2026-10-09):** resmî derleme yok; ldo/dvdauthor'ı MSYS2 UCRT64 ile küçük bir uyum katmanıyla derliyoruz (`native/dvdauthor/build.sh`). Türkçe karakterli çıktı klasörüne VIDEO_TS yazdı. spumux ile altyazı/menü testi Faz 1'de | Faz 1 |
| PS mux | FFmpeg `-f dvd` kullanılıyor. **Bulunan hata (2026-10-09):** ham m2v'de zaman damgası olmadığından FFmpeg tüm filmi tek VOBU yapıyordu (bölümler başa düşüyor, ileri sarma bozuk). `-fflags +genpts` ile düzeldi, testle korunuyor. Kalan: FFmpeg yeni VOBU'yu I-kareden en az 0.4 sn sonra açtığı için bölüm, bölüm karesinden önceki VOBU başına düşebiliyor (sapma < 0.4 sn). Kare doğruluğu için GOP yerleşimi ya da kendi muxer'ımız (Faz 7). Tampon uyumu gerçek oynatıcıda doğrulanmalı | Faz 1 / 7 |
| IMAPI2 ile DVD-9 katman geçişi | Katman geçiş noktasını kontrol edemezsek ImgBurn gerekir | Faz 8 |
