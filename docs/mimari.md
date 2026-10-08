# Mimari (taslak)

## Teknoloji yığını

| Katman | Seçim | Gerekçe |
|---|---|---|
| Çekirdek dil | **Python 3.12+** | VapourSynth Python ile sürülüyor; orkestrasyon, bitstream düzenleme, IFO yazımı için yeterli |
| Paket yönetimi | `uv` | Hızlı, kilit dosyalı, PC değiştirince birebir aynı ortam |
| Ön işleme | **VapourSynth** (+ resize, neo_f3kdb, dither, havsfunc vb.) | Kaliteli küçültme/deband/dither için en iyi açık ekosistem |
| Decode / ses / yardımcı encode | **FFmpeg** | Her şeyi okur; AC-3 encoder'ı iyi |
| MPEG-2 encode | FFmpeg → HCEnc (Wine) → x262 | Değiştirilebilir backend; Faz 2'de ölçüp karar |
| Mux / authoring (başlangıç) | `mplex`, `dvdauthor`, `spumux` | Hızlı MVP; Faz 7'de kendi yazıcımızla değiştirilecek |
| ISO | `xorriso` | UDF + ISO 9660 köprü, DVD-Video sıralaması |
| Menü/altyazı render | Pillow + **Cairo/Pango** | Türkçe metin şekillendirme, anti-alias kontrolü |
| Proje modeli | **pydantic** + YAML | Doğrulanabilir, elle de düzenlenebilir proje dosyası |
| CLI | `typer` | |
| GUI (Faz 8) | FastAPI + tarayıcı arayüzü (Svelte/React + canvas) | Menü editörü için canvas en rahat ortam; platformdan bağımsız |
| Ortam | **Docker** (+ devcontainer) | Tüm araç zinciri tek imajda; başka PC'de dakikalar içinde hazır |

## Modüller (önerilen dizin yapısı)

```
src/dvd/
  project/      proje modeli (pydantic), YAML okuma/yazma, doğrulama
  probe/        kaynak analizi (ffprobe), referans DVD analizi
  video/        VapourSynth zinciri, encoder backend'leri, pulldown enjektörü, uyumluluk denetimi
  audio/        AC-3/LPCM encode, downmix, PAL speedup
  subs/         SRT/ASS/PGS → subpicture render ve kuantizasyon
  menu/         menü modeli, şablonlar, render, navigasyon grafiği
  budget/       bitrate planlayıcı, disk seti planlayıcı
  author/       dvdauthor sürücüsü → (Faz 7) kendi IFO/VOB yazıcımız
  vm/           DVD VM komut modeli, derleyici, simülatör
  iso/          ISO üretimi, yakma
  qa/           metrikler (VMAF/SSIM), A/B görseller, HTML rapor
  cli.py
tests/
corpus/         (git dışı) test klipleri — yalnızca tarif/manifest dosyası repoda
docker/
```

## Proje dosyası (taslak örnek)

```yaml
disc:
  name: "Interstellar"
  standard: pal            # pal | ntsc
  media: dvd9              # dvd5 | dvd9
  profile: film-dvd9-max

titles:
  - source: "/media/rips/Interstellar.mkv"
    video:
      crop: auto
      filters: { deband: true, denoise: off }
    audio:
      - { track: 1, lang: en, codec: ac3, channels: 5.1, bitrate: 448k }
      - { track: 3, lang: tr, codec: ac3, channels: 5.1, bitrate: 448k }
    subtitles:
      - { file: "Interstellar.tr.srt", lang: tr, style: default, default: true }
    chapters: from-source

menus:
  template: "templates/minimal-dark"
  pages: [main, chapters, audio, subtitles]
  background: { image: "art/interstellar-bg.png" }
```

## İlkeler

1. **Önce ölç, sonra karar ver** — kalite ile ilgili her seçim korpus + metrik + göz ile doğrulanır.
2. **Bildirimsel proje** — disk, tek bir proje dosyasından yeniden üretilebilir olmalı.
3. **Ara çıktılar önbelleğe alınır** — sadece menüyü değiştirince film yeniden encode edilmez.
4. **Dış araçlar değiştirilebilir backend** — dvdauthor/HCEnc gibi bağımlılıklar arayüz arkasında.
