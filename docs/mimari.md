# Mimari (taslak)

**Hedef platform: Windows masaüstü uygulaması.** Tüm dış araçlar uygulamayla birlikte paketlenir; kullanıcı ayrıca bir şey kurmaz.

## Teknoloji yığını

| Katman | Seçim | Gerekçe |
|---|---|---|
| Dil | **Python 3.12+** | VapourSynth Python ile sürülüyor; tek dil hem motor hem arayüz |
| Arayüz | **PySide6 (Qt 6)** | Native Windows görünümü; `QGraphicsView` menü editörü için ideal (katmanlar, sürükle-bırak, yakınlaştırma); LGPL |
| Ön işleme | **VapourSynth** (+ resize, neo_f3kdb, QTGMC, placebo vb.) | Kaliteli küçültme/deband/dither/deinterlace için en iyi ekosistem; Windows'ta tam destekli |
| Decode / ses | **FFmpeg** (`ffmpeg.exe`, `ffprobe.exe`) | Her formatı okur; AC-3 encoder'ı iyi |
| MPEG-2 encode | **HCEnc** (Windows native) + FFmpeg `mpeg2video` + (deneysel) x262 | HCEnc'in Windows'ta doğrudan çalışması büyük avantaj; Faz 2'de ölçülüp varsayılan seçilecek |
| Mux / authoring (başlangıç) | `dvdauthor` + `spumux` Windows derlemeleri | Hızlı MVP; Faz 7'de kendi motorumuzla değişecek |
| ISO | Kendi UDF/ISO yazıcımız veya `xorriso`/`mkisofs` Windows derlemesi | Doğrulanacak |
| Yakma | Windows **IMAPI2** (yerleşik) — katman geçişi kontrolü yetersizse ImgBurn entegrasyonu | Doğrulanacak |
| Menü/altyazı render | Qt `QPainter` + gerekirse Pillow | Türkçe metin, anti-alias, font kontrolü; editörde gördüğün = render edilen |
| Proje modeli | pydantic + JSON/YAML | Doğrulanabilir, elle okunabilir |
| CLI | `typer` | Otomasyon, test, toplu iş |
| Paketleme | Nuitka veya PyInstaller + Inno Setup | Tek kurulum dosyası |
| Paket yönetimi | `uv` | Kilit dosyalı, birebir tekrarlanabilir geliştirme ortamı |

## Katmanlar

```
┌─────────────────────────────────────────────┐
│  Arayüz (PySide6)                            │  ekranlar, menü editörü, karşılaştırma, kuyruk
├─────────────────────────────────────────────┤
│  CLI (typer)                                 │  aynı motoru komut satırından sürer
├─────────────────────────────────────────────┤
│  Motor (saf Python kütüphanesi, GUI'siz)     │  proje modeli, profiller, bütçe, pipeline,
│                                              │  menü modeli, VM, authoring
├─────────────────────────────────────────────┤
│  Araç sürücüleri                             │  ffmpeg, vspipe/VapourSynth, HCEnc,
│                                              │  dvdauthor, ISO, yakma — değiştirilebilir
└─────────────────────────────────────────────┘
```

Motor arayüzden bağımsız: her özellik önce motorda (CLI ile test edilebilir), sonra arayüzde.

## Modüller (önerilen dizin yapısı)

```
src/dvd/
  project/      proje modeli, kaydet/yükle, doğrulama
  profiles/     katmanlı profil sistemi (standart, medya, içerik, izleme ortamı, ses)
  probe/        kaynak analizi, referans DVD analizörü
  video/        VapourSynth zinciri, encoder sürücüleri, pulldown enjektörü, uyumluluk denetimi
  audio/        AC-3/LPCM encode, downmix, PAL speedup
  subs/         SRT/ASS/PGS → subpicture render ve kuantizasyon
  chapters/
  menu/         menü modeli, şablonlar, render, navigasyon grafiği
  budget/       bitrate planlayıcı, disk seti planlayıcı
  author/       dvdauthor sürücüsü → (Faz 7) kendi IFO/VOB yazıcımız
  vm/           DVD VM komut modeli, derleyici, simülatör
  output/       ISO, yakma, kapak
  qa/           metrikler, karşılaştırma görselleri, raporlar
  jobs/         iş kuyruğu, önbellek, ilerleme
  cli.py
  gui/          PySide6 arayüzü
tests/
corpus/         (git dışı) test klipleri — repoda yalnızca liste
tools/          (git dışı) paketlenecek .exe'ler — repoda yalnızca indirme/sürüm listesi
```

## Windows'a özgü notlar

- **Yollar**: Türkçe karakterli ve uzun yollar (`\\?\` öneki / long path desteği), boşluklu klasör adları.
- **Geçici alan**: bir film için onlarca GB ara dosya → kullanıcının seçtiği hızlı bir sürücüde çalışma klasörü.
- **Süreç yönetimi**: dış araçlar alt süreç olarak, iptal edilebilir; uyku modunu engelleme (encode sırasında).
- **GPU**: NVDEC/QSV/AMF ile decode, VapourSynth placebo (Vulkan) ile tonemapping — opsiyonel.
- **Kaynak DVD'ler**: analizör, kullanıcının kendi ripleme aracıyla çıkardığı VIDEO_TS/ISO üzerinde çalışır.

## Proje dosyası

Uzantı `*.dvd.yaml`; model `src/dvd/project/model.py`. Bilinmeyen anahtarlar reddedilir (yazım hatası sessizce
yok sayılmasın), DVD sınırları yüklerken denetlenir: en çok 99 başlık, başlık başına 8 ses, 32 altyazı ve 99 bölüm;
AC-3 bitrate'i 192k–448k; dil kodları iki harfli (`tur` gibi üç harfli kodlar `tr`'ye çevrilir). Kayıt atomik yapılır.
`menus` ve `first_play` Faz 4'e kadar olduğu gibi saklanır.

- `dvd new kaynak.mkv`: kaynağı analiz edip varsayılanlarla proje oluşturur.
- `dvd check film.dvd.yaml`: dosyayı ve kaynakları denetler (dosyalar var mı, gösterilen izler kaynakta var mı).

Örnek:

```yaml
disc:
  name: "Interstellar"
  standard: pal              # pal | ntsc
  media: dvd9                # dvd5 | dvd9
  profiles:
    content: grenli-film
    viewing: modern-tv
    audio: "5.1"

titles:
  - source: "D:/Rips/Interstellar.mkv"
    video:
      crop: auto
      overrides: { deband: 3 }
    audio:
      - { track: 1, lang: en, codec: ac3, channels: "5.1", bitrate: 448k }
      - { track: 3, lang: tr, codec: ac3, channels: "5.1", bitrate: 448k }
    subtitles:
      - { file: "Interstellar.tr.srt", lang: tr, style: varsayilan, default: true }
    chapters: from-source

menus:
  template: sinematik
  pages: [main, chapters, settings]
  background: { frame: "01:12:03" }

first_play: [ { intro: "logo.mkv", skippable: true }, main_menu ]
```

## İlkeler

1. **Önce ölç, sonra karar ver** — kaliteyle ilgili her seçim korpus + metrik + göz ile doğrulanır.
2. **Bildirimsel proje** — disk tek bir proje dosyasından yeniden üretilebilir.
3. **Ara çıktılar önbelleğe alınır** — sadece menü değişince film yeniden encode edilmez.
4. **Dış araçlar değiştirilebilir sürücü** — HCEnc/dvdauthor gibi bağımlılıklar arayüz arkasında.
5. **Editörde gördüğün diske yazılan** — menü ve altyazı önizlemesi aynı render kodunu kullanır.
