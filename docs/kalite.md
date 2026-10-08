# Görüntü Kalitesi

DVD-Video'nun sınırları sabit: MPEG-2, 720×480 (NTSC) / 720×576 (PAL), 4:2:0, 8-bit, en fazla ~9.8 Mbps video.
Ticari DVD'lerle hazır araçlar arasındaki fark bu sınırlardan değil, **sınırlara gelene kadar yapılanlardan** geliyor.

## 1. Hazır araçlar neyi yanlış yapıyor?

| Sorun | Belirti | Bizim çözümümüz |
|---|---|---|
| Kötü küçültme (bilinear, anti-alias yok) | Merdivenlenme, titreyen ince çizgiler (moiré), ya da tersine aşırı bulanıklık | Kontrollü kernel seçimi (Spline36 / SSIM downsampler / Lanczos), korpusta ölçülerek |
| Anamorfik yerine 4:3 içine letterbox ya da yanlış SAR | Gereksiz çözünürlük kaybı, basık/uzamış görüntü | 16:9 anamorfik 720 piksel genişliğin tamamını kullan, bayrakları doğru yaz |
| BT.709 → BT.601 dönüşümü yok | Renk kayması (özellikle kırmızı/yeşil tonları, ten rengi) | Matris dönüşümü + doğru `colour_description` bayrakları |
| 10-bit / yüksek bit kaynaktan kaba 8-bit'e indirme | Gökyüzünde, karanlık sahnelerde **banding** | Yüksek bit derinliğinde işlem, deband, sonda dithering |
| Tek geçiş, CBR ya da düşük sabit bitrate | Karmaşık sahnelerde blok blok görüntü, kolay sahnelerde bit israfı | Çok geçişli VBR, diskin tamamına göre bütçe |
| 23.976 film → hard telecine ya da fps dönüşümü | Interlace artefaktları, takılma (judder), boşa harcanan bit | Progresif encode + soft pulldown bayrakları (NTSC) / 25 fps speedup (PAL) |
| Letterbox bantları macroblock sınırına denk gelmiyor | Bant kenarında boşa harcanan bit, kenarda "kaynama" | Bantları 16 piksellik sınırlara hizala |
| Varsayılan, ayarsız encoder | Genel olarak düşük verim | Ayarlı FFmpeg profili ya da HCEnc, quant matrisi denemeleri |
| Disk bütçesi planlanmıyor | Film DVD-5'e sıkıştırılıyor, ses gereğinden fazla yer kaplıyor | Bitrate planlayıcı, DVD-9 önerisi, ses/altyazı/menü hesabı |

## 2. Ticari DVD'ler ne yapıyor?

- **Film materyali progresif encode edilir.** NTSC'de 23.976p olarak encode edilir; oynatıcının 29.97i çıkış için alanları
  tekrarlaması `repeat_first_field` / `top_field_first` bayraklarıyla söylenir (soft pulldown). Böylece hiç bit interlace'e harcanmaz.
  PAL'de film %4 hızlandırılıp 25p olarak encode edilir.
- **Çok geçişli VBR**, çoğu zaman segment bazlı yeniden encode (CinemaCraft gibi profesyonel encoder'larla sorunlu sahneler tekrar ele alınır).
- **Mastering zinciri**: profesyonel ölçekleyiciler, gürültü azaltma, gerekiyorsa hafif yumuşatma. Ticari DVD'ler genellikle
  "keskin" değil "temiz" görünür — aşırı detay MPEG-2'de artefakta dönüşür.
- **DVD-9**: uzun filmler neredeyse her zaman çift katmanlıdır; ortalama video bitrate'i 6–8 Mbps civarında.
- **Ses bütçesi ölçülü**: 5.1 AC-3 genelde 384 veya 448 kbps, ek diller 192–448 kbps.

> Faz 0'da elimizdeki orijinal DVD'leri bu maddeler açısından **ölçeceğiz** (bitrate eğrisi, GOP, matris, bayraklar).
> Hedefimiz tahmin değil, referansa göre kalibrasyon.

## 3. Bizim video pipeline'ımız

```
Kaynak (MKV/M2TS)
  │  decode (yüksek bit derinliği korunur)
  ▼
[HDR ise] tonemap  BT.2020 PQ/HLG → BT.709 SDR
  ▼
Siyah bant tespiti → crop
  ▼
Küçültme → hedef aktif alan (anamorfik, yüksek bit derinliğinde)
  ▼
Renk matrisi  BT.709 → BT.601 (NTSC: SMPTE 170M, PAL: BT.470BG)
  ▼
Deband  →  (opsiyonel) denoise / gren yönetimi
  ▼
Dither → 8-bit, 4:2:0
  ▼
Pad: bantları 16 piksel hizalı ekle → 720×480 / 720×576
  ▼
MPEG-2 encode (çok geçişli VBR)  ──►  [NTSC] pulldown bayrak enjektörü
  ▼
Uyumluluk denetimi (VBV, tepe bitrate, GOP) + kalite metrikleri
```

### Aktif görüntü alanı örnekleri (16:9 anamorfik)

| Kaynak oranı | NTSC aktif yükseklik | PAL aktif yükseklik | Not |
|---|---|---|---|
| 1.78:1 (16:9) | 480 | 576 | Tam kare |
| 1.85:1 | ~462 | ~554 | İnce bantlar |
| 2.39:1 | ~357 | ~428 | Bantlar 16'nın katlarına yuvarlanır, görüntü ortalanır |

Bant yüksekliğinin macroblock'lara denk gelmesi için aktif alan ve pad değerleri hesaplanırken yuvarlama kuralı
Faz 2'de korpusla test edilecek (aktif alanı biraz kırpmak vs. bandın içine birkaç satır görüntü taşırmak).

### Küçültme

- Adaylar: Spline36, Lanczos3, Hermite (+ ayrı anti-alias), SSIM downsampler, linear-light vs. gamma-light ölçekleme.
- Ölçüt: hem metrik (referansa SSIM/VMAF) hem göz (A/B görselleri), ve **encode sonrası** sonuç — çok keskin bir kaynak
  MPEG-2'de daha çok bit ister; en iyi kernel encode edilmiş haliyle seçilir, ham haliyle değil.

### Encoder

| Encoder | Artı | Eksi |
|---|---|---|
| FFmpeg `mpeg2video` | Açık kaynak, her yerde var, kontrol edilebilir | Varsayılanları zayıf; ayarlanması gerekiyor; soft pulldown üretmiyor |
| HCEnc | Ücretsiz MPEG-2 encoder'lar arasında kalite açısından genelde en iyi kabul ediliyor, pulldown ve DVD uyumluluğu yerleşik | Windows, kapalı kaynak → Linux'ta Wine |
| x262 | x264 tabanlı psikovizüel optimizasyonlar | Deneysel/bakımsız, uyumluluğu doğrulanmalı |

FFmpeg için başlangıç noktası (Faz 2'de tek tek ölçülecek): 2-pass VBR, `-trellis`, `-mbd rd`, `-cmp/-subcmp` RD tabanlı,
`-bf 2`, PAL'de `-g 15` / NTSC'de `-g 18` ve altı, `-non_linear_quant 1`, `-intra_vlc 1`, `-dc 9/10`,
`-maxrate` ses dahil mux sınırına göre, `-bufsize 1835k` (DVD VBV tamponu), özel `-intra_matrix` / `-inter_matrix` denemeleri.

### Pulldown (NTSC)

FFmpeg'in `mpeg2video` encoder'ı soft pulldown bayrağı yazmıyor. Çözüm: 23.976p progresif encode, ardından
elementary stream'deki picture coding extension'larda `repeat_first_field` / `top_field_first` bayraklarını
3:2 desenine göre yazan ve sequence header'daki frame rate'i 29.97 yapan **küçük bir bitstream düzenleyicisi**
(DGPulldown'ın yaptığı iş). Bunu kendimiz yazacağız.

### PAL speedup

23.976 → 25 fps: video kare kare aynı, sadece süre %4.1 kısalır. Ses aynı oranda hızlandırılır;
pitch düzeltmesi opsiyonel (ticari PAL DVD'lerin çoğu düzeltmez, ses yarım ton tize kayar).

## 4. Bitrate bütçesi

```
kullanılabilir_bit = kapasite × 8 × (1 − overhead)          # overhead ≈ %2–4 (mux, IFO, menüler hariç)
toplam_bitrate     = (kullanılabilir_bit − menü_bitleri) / süre_sn
video_ortalama     = toplam_bitrate − Σ ses − Σ altyazı
video_tepe         ≤ min(9.8 Mbps, 10.08 Mbps − Σ ses − Σ altyazı)
```

| Kapasite | Byte |
|---|---|
| DVD-5 (tek katman) | 4.700.372.992 |
| DVD-9 (çift katman) | 8.543.666.176 |

**Örnek — 130 dk film, 2× AC-3 5.1 448 kbps, 2 altyazı:**
- DVD-9: ≈ 8.45 Mbps toplam → **≈ 7.5 Mbps video** (ticari DVD seviyesi). Tepe sınırı ≈ 9.1 Mbps.
- DVD-5: ≈ 4.7 Mbps toplam → **≈ 3.8 Mbps video** (tek ses iziyle ≈ 4.2). Fark gözle görülür; bu yüzden uzun filmler için DVD-9 önerilecek.

## 5. Ölçüm

- **Referans**: aynı kaynağın aynı zincirden geçmiş ama MPEG-2'ye encode edilmemiş hali → encode kaybı ölçülür.
- **Metrikler**: VMAF (genel), SSIM (yapı), PSNR (kaba kontrol), sahne bazlı en kötü değerler (ortalama yanıltır).
- **Görsel**: aynı kareden kırpılmış yan yana / kaydırmalı karşılaştırmalar, banding testleri için karanlık sahneler.
- **Gerçek cihaz**: son karar TV'de, gerçek oynatıcıyla izleyerek verilir.
