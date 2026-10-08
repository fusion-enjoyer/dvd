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
| 2026-10-08 | — | Referans analiz için kullanıcının elindeki orijinal DVD'ler kullanılacak | Faz 0 |
| 2026-10-08 | — | Ön işleme VapourSynth ile | Kalite ekosistemi |
| 2026-10-08 | — | Önce menüsüz uçtan uca MVP, sonra kalite motoru | Erken gerçek cihaz testi |

## Açık kararlar

| # | Soru | Seçenekler | Öneri |
|---|---|---|---|
| K7 | Repo görünürlüğü ve lisans | Private / Public; MIT / GPL | dvdauthor kodundan yararlanırsak veya onu paketlersek GPL uyumu gerekir |
| K8 | Arayüz teknolojisi | **Python + PySide6** / C# (WPF/WinUI) + Python motor / Tauri veya Electron (web arayüz) + Python motor | PySide6: tek dil, VapourSynth ile doğal uyum, `QGraphicsView` menü editörüne çok uygun. C# daha "Windows'lu" ama iki dil + süreçler arası iletişim demek. |
| K9 | Yakma yöntemi | Windows IMAPI2 / ImgBurn entegrasyonu / sadece ISO üret, kullanıcı yaksın | MVP'de sadece ISO; sonra IMAPI2, DL katman geçişi kontrolü yetersizse ImgBurn |
| K10 | ISO üretimi | Kendi UDF/ISO yazıcımız / mkisofs-xorriso Windows derlemesi / IMAPI2 dosya sistemi oluşturucu (IMAPI2FS) | Araştırılacak |
| K11 | Arayüz dili | Türkçe / İngilizce / ikisi | İkisi (çeviri altyapısı baştan) |

## Doğrulanacak riskler

| Risk | Neden önemli | Ne zaman |
|---|---|---|
| HCEnc girdisi | HCEnc AviSynth betiği bekliyor olabilir; VapourSynth çıktısını nasıl besleyeceğimiz (köprü, sanal dosya, ara dosya) netleşmeli | Faz 0 |
| HCEnc'in uygulamayla dağıtılması | Freeware ama yeniden dağıtım izni kontrol edilmeli; değilse ilk açılışta kullanıcıdan yolu istenir | Faz 0 |
| dvdauthor/spumux Windows derlemeleri | Eski ve az bakımlı; Türkçe yollarla sorun çıkarabilir | Faz 0–1 |
| IMAPI2 ile DVD-9 katman geçişi | Katman geçiş noktasını kontrol edemezsek ImgBurn gerekir | Faz 8 |
