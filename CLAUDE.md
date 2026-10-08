# CLAUDE.md

Windows masaüstü uygulaması: Blu-ray/WEB kaynaklarını ticari DVD kalitesinde DVD-Video'ya dönüştüren, özelleştirilebilir menülü authoring aracı.
Kullanıcıyla Türkçe konuşulur; belgeler Türkçe.

## Durum

Tasarım/planlama aşaması — henüz kod yok. Kod Windows'ta yazılacak.
Sıradaki adım: `docs/kararlar.md`'deki açık kararları (özellikle K8 arayüz teknolojisi) kapat, sonra ROADMAP.md **Faz 0**.

## Belgeler

- `ROADMAP.md` — fazlar ve bitti kriterleri (ilerledikçe kutucukları işaretle)
- `docs/ozellikler.md` — öncelik etiketli özellik listesi
- `docs/profiller.md` — katmanlı profil/preset sistemi
- `docs/arayuz.md` — ekran taslakları
- `docs/kalite.md` — kalite pipeline'ı ve bitrate bütçesi
- `docs/dvd-spec.md` — DVD-Video teknik notları
- `docs/mimari.md` — teknoloji yığını, modüller, proje dosyası modeli
- `docs/kararlar.md` — açık / verilmiş kararlar (yeni kararları buraya tarihle ekle)

## Kurallar

- Medya dosyaları (MKV, VOB, ISO, test klipleri) repoya girmez; `.gitignore`'a bak.
- Kaliteyle ilgili her seçim ölçülerek (korpus + metrik + A/B görsel) yapılır.
