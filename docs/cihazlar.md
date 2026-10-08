# Cihaz matrisi

Üretilen diskler hangi oynatıcılarda denenecek ve her birinin neyi desteklediği.

Donanım oynatıcılar yazılım oynatıcılardan çok daha katıdır. VLC ya da mpv bozuk bir diski de çoğu zaman oynatır,
bu yüzden uyumluluk testi için yeterli değiller. Asıl ölçüt gerçek bir oynatıcıda sorunsuz çalışmasıdır. Farklı
oynatıcılar şu konularda ayrışır: yazılabilir medya (DVD±R, DL) okuma, tepe bitrate'e dayanıklılık, katman
geçişinde takılma, menü ve VM komutlarının yorumu, altyazı renkleri.

| Cihaz | Tür | Medya | PAL / NTSC | Bağlantı | Not |
|---|---|---|---|---|---|
| Sony DVP-NS38 | Masaüstü DVD oynatıcı (~2005) | DVD±R, DVD±RW, DVD±R DL (perakende veri sayfasına göre, doğrulanacak) | Doğrulanacak | SCART | Ana test cihazı |
| PC: VLC / mpv | Yazılım | ISO / VIDEO_TS | İkisi de | — | Yalnızca hızlı kontrol, uyumluluk testi değil |

## Doğrulanacaklar (Sony DVP-NS38)

İlk test diskleriyle denenecek:

- [ ] DVD-R (tek katman) okuyor mu?
- [ ] DVD+R DL okuyor mu, katman geçişinde takılma var mı?
- [ ] PAL ve NTSC disklerin ikisini de oynatıyor mu? Bağlı TV'ye hangi sinyali veriyor?
- [ ] 16:9 anamorfik görüntü TV'de doğru oranda mı?
- [ ] Altyazı renkleri ve konumu doğru mu?
- [ ] SCART çıkışı RGB'ye ayarlanabiliyor mu? (Kompozitten belirgin şekilde daha net.) TV, SCART üzerinden gelen
      16:9 sinyaliyle görüntüyü kendiliğinden genişletiyor mu?
- [ ] NTSC disk SCART üzerinden PAL60 / NTSC olarak mı çıkıyor, TV bunu gösterebiliyor mu?

SCART bağlantısı neredeyse her zaman 50 Hz PAL için kurulmuş TV'lerde olur. NTSC disklerin bu zincirde
çalışıp çalışmadığı, 23.976 fps filmler için PAL mi NTSC mi önereceğimizi etkiler (bkz. K1).
