# dvd

Blu-ray / WEB kaynaklı filmleri ve dizileri, **ticari (fabrika basımı) DVD'lerin görüntü kalitesinde**
DVD-Video'ya dönüştüren ve tam kontrollü menüler tasarlamaya izin veren bir authoring aracı.

> Durum: **Planlama aşaması.** Henüz kod yok.

## Neden?

İnternetteki "MKV → DVD" araçlarının çoğu kaynağı kalitesiz küçültür, renk uzayını yanlış dönüştürür,
düşük bitrate'li tek geçişli CBR ile encode eder ve menüleri sabit şablonlarla sınırlar.
Ticari DVD'ler ise aynı 720×480/576 MPEG-2 sınırları içinde çok daha iyi görünür; çünkü:

- kaynak dikkatli bir mastering zincirinden geçer (doğru küçültme, renk matrisi, dithering, gürültü kontrolü),
- encode çok geçişli VBR ile, sahne sahne bitrate dağıtılarak yapılır,
- film materyali progresif encode edilip pulldown bayraklarıyla işaretlenir,
- diskin her baytı (menüler, ses, altyazı, katman geçişi) bütçeye göre planlanır.

Bu proje o zinciri açık kaynak araçlarla — gerektiğinde kendi yazdığımız bileşenlerle — yeniden kurmayı hedefliyor.

## Belgeler

| Belge | İçerik |
|---|---|
| [ROADMAP.md](ROADMAP.md) | Fazlar, kilometre taşları, "bitti" kriterleri |
| [docs/kalite.md](docs/kalite.md) | Görüntü kalitesi neden bozuluyor, ticari DVD'ler ne yapıyor, bizim pipeline'ımız |
| [docs/dvd-spec.md](docs/dvd-spec.md) | DVD-Video teknik notları: sınırlar, disk yapısı, VM, menüler, altyazılar |
| [docs/mimari.md](docs/mimari.md) | Teknoloji yığını, modüller, proje dosyası modeli |
| [docs/kararlar.md](docs/kararlar.md) | Açık kararlar ve verilen kararların kaydı |
