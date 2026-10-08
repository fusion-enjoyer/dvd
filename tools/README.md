# Dış araçlar

Bu klasöre konan `.exe` dosyaları ve alt klasörler repoya girmez (`.gitignore`). Burada yalnızca hangi aracın
hangi sürümünün kullanıldığı ve nereden alındığı tutulur. Araçlar kontrolü: `uv run dvd doctor`.

Arama sırası: `DVD_TOOLS_DIR` ortam değişkeni (yoksa bu klasör) ve onun bir alt klasör seviyesi, sonra `PATH`.
Örneğin `tools/hcenc/HCenc_028.exe` bulunur.

| Araç | Sürüm | Görev | Kaynak | Lisans | Uygulamayla dağıtım | Durum |
|---|---|---|---|---|---|---|
| FFmpeg / ffprobe | 9.0.1 (gyan.dev full build) | Decode, AC-3 encode, analiz | `winget install Gyan.FFmpeg` | GPL (full build) | GPL build dağıtılırsa uygulama lisansı etkilenir; bkz. K7 | Kurulu |
| VapourSynth | R81 | Ön işleme | PyPI `vapoursynth` (uv ile `.venv`'e kurulur) | LGPL 2.1 | Evet | Kurulu |
| HCEnc | 0.28 (21.12.2015) | MPEG-2 encode | http://hank315.nl | Freeware | **Belirsiz**, izin kontrol edilecek | Yok |
| AviSynth+ | 3.7.5 | HCEnc'e girdi sağlamak | https://github.com/AviSynth/AviSynthPlus/releases | GPL 2+ | Evet | Yok |
| dvdauthor + spumux | 0.7.2 (2016) | VIDEO_TS authoring, subpicture | Resmî Windows derlemesi yok; MSYS2 ile kaynaktan derlenecek | GPL 2+ | Evet (GPL) | Yok |
| mkisofs (cdrtools) | — | DVD-Video ISO (`-dvd-video -udf`) | Cygwin derlemeleri | CDDL / GPL | Evet | Yok, K10'a bağlı |

## Notlar

- **HCEnc** 2015'ten beri geliştirilmiyor ve yalnızca AviSynth betiği (`.avs`) ya da DGIndex (`.d2v`) okuyor.
  VapourSynth çıktısını ona vermek için köprü gerekir; seçenekler `docs/kararlar.md` → Doğrulanacak riskler.
- **xorriso** DVD-Video için gereken UDF dosya sistemini üretmiyor; ISO için aday değil.
- VapourSynth eklentileri (deband, resize, QTGMC vb.) Faz 2'de bu tabloya eklenecek.
