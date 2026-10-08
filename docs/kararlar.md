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
| 2026-10-09 | — | HCEnc'e kareler kendi köprümüzle (named pipe + `DvdSource.dll`) verilir | Ara dosya yok, iki geçiş çalışıyor; bkz. riskler |

## Açık kararlar

| # | Soru | Seçenekler | Öneri |
|---|---|---|---|
| K9 | Yakma yöntemi | Windows IMAPI2 / ImgBurn entegrasyonu / sadece ISO üret, kullanıcı yaksın | MVP'de sadece ISO; sonra IMAPI2, DL katman geçişi kontrolü yetersizse ImgBurn |
| K10 | ISO üretimi | Kendi UDF/ISO yazıcımız / mkisofs Windows derlemesi / IMAPI2 dosya sistemi oluşturucu (IMAPI2FS) | Kendi UDF 1.02 + ISO 9660 köprü yazıcımız. xorriso DVD-Video UDF'si üretmiyor; mkisofs yalnızca Cygwin derlemesi olarak var; IMAPI2FS'te dosya sırası ve hizalama kontrolü belirsiz. Kendi yazıcımız Faz 7'deki katman geçişi için de gerekli. mkisofs çıktısı doğrulamada referans olarak kullanılır (2026-10-09 araştırması) |
| K11 | Arayüz dili | Türkçe / İngilizce / ikisi | İkisi (çeviri altyapısı baştan) |

## Doğrulanacak riskler

| Risk | Neden önemli | Ne zaman |
|---|---|---|
| HCEnc girdisi | **Çözüldü (2026-10-09):** HCEnc 0.28 32-bit ve yalnızca `.avs`/`.d2v` okuyor. Kendi köprümüzü yazdık: motor VapourSynth karelerini named pipe ile sunuyor, 32-bit `DvdSource.dll` AviSynth eklentisi kareleri numarayla istiyor. İki geçişli encode ve rastgele erişim çalışıyor, ara dosya yok. Test: 120 kare, 241 istek (2 geçiş + yoklama), PSNR-Y 50.7 dB. Gerçek film üzerinde hız ölçümü Faz 1'de | Faz 0 |
| HCEnc'in geleceği | 2015'ten beri geliştirilmiyor (son sürüm 0.28). Kalite avantajı Faz 2'de FFmpeg/x262 ile karşılaştırılarak ölçülmeli | Faz 2 |
| HCEnc'in uygulamayla dağıtılması | Freeware ama yeniden dağıtım izni kontrol edilmeli; değilse ilk açılışta kullanıcıdan yolu istenir | Faz 0 |
| dvdauthor/spumux Windows derlemeleri | **Çözüldü (2026-10-09):** resmî derleme yok; ldo/dvdauthor'ı MSYS2 UCRT64 ile küçük bir uyum katmanıyla derliyoruz (`native/dvdauthor/build.sh`). Türkçe karakterli çıktı klasörüne VIDEO_TS yazdı. spumux ile altyazı/menü testi Faz 1'de | Faz 1 |
| PS mux | Deneme zincirinde m2v + AC-3, FFmpeg'in `-f dvd` muxer'ıyla birleştirildi ve dvdauthor kabul etti. FFmpeg muxer'ının DVD uyumu (tampon, zaman damgaları) gerçek oynatıcıda doğrulanmalı | Faz 1 |
| IMAPI2 ile DVD-9 katman geçişi | Katman geçiş noktasını kontrol edemezsek ImgBurn gerekir | Faz 8 |
