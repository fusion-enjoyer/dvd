# Kararlar

## Açık kararlar

| # | Soru | Seçenekler | Öneri |
|---|---|---|---|
| K1 | Varsayılan TV standardı | PAL (576 satır, %4 hızlanma) / NTSC (480 satır, orijinal hız, soft pulldown) | Proje bazında seçilebilir olsun. Türkiye'deki oynatıcılar genelde ikisini de oynatır; cihaz matrisinde test edip varsayılanı öyle seçelim. |
| K2 | İzleme ortamı | Modern TV + DVD oynatıcı / konsol / CRT / bilgisayar | Ön işleme ayarlarını (keskinlik, dikey filtre) etkiler — kullanıcıdan öğrenilecek. |
| K3 | Diğer PC'nin işletim sistemi | Linux / Windows / macOS | Docker her durumda; Windows'ta HCEnc native çalışır (artı). |
| K4 | Arayüz önceliği | CLI önce, GUI sonra / baştan GUI | CLI önce: kalite motoru ve menü modeli oturmadan GUI boşa emek. |
| K5 | Kapalı kaynak encoder (HCEnc) kullanımı | Evet (opsiyonel backend) / Hayır | Opsiyonel backend olarak evet; kalite farkını ölçüp karar verelim. |
| K6 | Hedef medya | DVD-5 / DVD-9 / ikisi | İkisi; uzun filmler için DVD-9 önerilsin. Yazıcının DL desteği kontrol edilmeli. |
| K7 | Repo görünürlüğü ve lisans | Private / Public + MIT/GPL | dvdauthor kodundan yararlanırsak GPL uyumu gerekir. |

## Verilen kararlar

| Tarih | Karar | Gerekçe |
|---|---|---|
| 2026-10-08 | Çekirdek dil Python, ön işleme VapourSynth | Kalite ekosistemi Python etrafında |
| 2026-10-08 | Proje önce menüsüz uçtan uca MVP, sonra kalite motoru | Erken gerçek cihaz testi |
