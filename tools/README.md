# Dış araçlar

Bu klasöre konan `.exe` dosyaları ve alt klasörler repoya girmez (`.gitignore`). Burada yalnızca hangi aracın
hangi sürümünün kullanıldığı ve nereden alındığı tutulur. Araçlar kontrolü: `uv run dvd doctor`.

Arama sırası: `DVD_TOOLS_DIR` ortam değişkeni (yoksa bu klasör) ve onun bir alt klasör seviyesi, sonra `PATH`.

| Araç | Sürüm | Görev | Kaynak | Lisans | Uygulamayla dağıtım | Yer |
|---|---|---|---|---|---|---|
| FFmpeg / ffprobe | 9.0.1 (gyan.dev full build) | Decode, AC-3 encode, analiz | `winget install Gyan.FFmpeg` | GPL (full build) | Evet (GPL) | `PATH` |
| VapourSynth | R81 | Ön işleme | PyPI `vapoursynth` (uv ile `.venv`'e kurulur) | LGPL 2.1 | Evet | `.venv` |
| BestSource | R22 | VapourSynth kaynak okuyucu (MKV, M2TS, MP4...) | PyPI `vapoursynth-bestsource` | MIT | Evet | `.venv` |
| HCEnc | 0.28 (21.12.2015), 32-bit | MPEG-2 encode | http://hank315.nl/files/HC_028/HC028_21-12-2015.zip | Freeware | **Belirsiz**, izin kontrol edilecek | `tools/hcenc/` |
| AviSynth+ | 3.7.5, yalnızca x86 `AviSynth.dll` | HCEnc'in betik okuması | [GitHub v3.7.5](https://github.com/AviSynth/AviSynthPlus/releases/tag/v3.7.5) `-filesonly.7z` | GPL 2+ | Evet | `tools/hcenc/AviSynth.dll` (tam paket `tools/avisynthplus/`) |
| DvdSource | bizim | VapourSynth karelerini HCEnc'e taşır | `native/dvdsource/build.sh` | Projeyle aynı | Evet | `tools/hcenc/DvdSource.dll` |
| dvdauthor + spumux | 0.7.2+ (ldo/dvdauthor `fe8fe35`) | VIDEO_TS authoring, subpicture | `native/dvdauthor/build.sh` | GPL 2+ | Evet (GPL) | `tools/dvdauthor/` |
| mkisofs | — | — | Kullanılmayacak; ISO için kendi UDF yazıcımız (K10) | — | — | — |

## Kurulum (yeni makine)

1. `winget install Gyan.FFmpeg MSYS2.MSYS2 7zip.7zip` ve `uv sync`
2. HCEnc zip'ini `tools/hcenc/` içine aç; AviSynth+ arşivindeki `x86/AviSynth.dll`'i yanına koy.
3. MSYS2'de derleme paketleri: `pacman -S base-devel autotools gettext-devel mingw-w64-i686-gcc mingw-w64-ucrt-x86_64-{gcc,pkgconf,libxml2,libpng,freetype,fribidi,fontconfig,libdvdread}`
4. `bash native/dvdsource/build.sh` ve `bash native/dvdauthor/build.sh`
5. `uv run dvd doctor`

## Notlar

- **HCEnc** 32-bit ve yalnızca AviSynth betiği okuyor. Motor kareleri 64-bit VapourSynth'ten bir named pipe ile sunar
  (`src/dvd/video/frameserver.py`), HCEnc'in yüklediği `DvdSource.dll` bunları kare numarasıyla ister. İki geçişli
  encode ve rastgele erişim çalışır; ara dosya gerekmez.
- AviSynth+ sisteme kurulmaz; HCEnc yanındaki DLL'i kullanır.
- **dvdauthor** Windows'a taşınmamış; derleme betiği küçük bir uyum katmanı (`native/dvdauthor/shim/`) kullanır.
  Türkçe karakterli çıktı klasörüyle denendi.
- **xorriso** DVD-Video için gereken UDF dosya sistemini üretmiyor.
- VapourSynth eklentileri (deband, resize, QTGMC vb.) Faz 2'de bu tabloya eklenecek.
