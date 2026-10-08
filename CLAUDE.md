# CLAUDE.md

Blu-ray/WEB kaynaklarını ticari DVD kalitesinde DVD-Video'ya dönüştüren, özelleştirilebilir menülü authoring aracı.
Kullanıcıyla Türkçe konuşulur; belgeler Türkçe.

## Durum

Planlama aşaması — henüz kod yok. Sıradaki adım: ROADMAP.md'deki **Faz 0**.
Başlamadan önce `docs/kararlar.md`'deki açık kararları kullanıcıyla netleştir.

## Belgeler

- `ROADMAP.md` — fazlar ve bitti kriterleri (ilerledikçe kutucukları işaretle)
- `docs/kalite.md` — kalite pipeline'ı ve bitrate bütçesi
- `docs/dvd-spec.md` — DVD-Video teknik notları
- `docs/mimari.md` — teknoloji yığını, modüller, proje dosyası modeli
- `docs/kararlar.md` — açık / verilmiş kararlar (yeni kararları buraya tarihle ekle)

## Kurallar

- Medya dosyaları (MKV, VOB, ISO, test klipleri) repoya girmez; `.gitignore`'a bak.
- Kaliteyle ilgili her seçim ölçülerek (korpus + metrik + A/B görsel) yapılır.
