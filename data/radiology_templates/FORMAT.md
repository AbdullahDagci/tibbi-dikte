# Radyoloji cümle şablonları (sentetik eğitim sesi için)

`training/make_radiology_text.py` bu klasördeki `*.txt` dosyalarını okur, şablonları rastgele doldurur,
`textnorm.normalize` ile sayıları yazıya çevirir ("12 mm" -> "on iki milimetre") ve Chatterbox ile seslendirilecek
cümle listesini üretir. Model bu cümlelerden radyoloji terimlerini ve rapor dilini öğrenir; bu yüzden cümleler
gerçek bir radyoloğun dikte ettiği gibi doğal, dilbilgisi açısından doğru ve klinik olarak tutarlı olmalıdır.

## Biçim

- UTF-8, her satır bir şablon. Boş satırlar ve `#` ile başlayan satırlar yok sayılır (bölüm başlığı için kullanın).
- Her satır tek, tam bir rapor cümlesidir ve `.` ile biter. 4–30 kelime; kısa ve uzun cümleleri karıştırın.
- **Seçenek:** `{a|b|c}` — biri rastgele seçilir. Her seçeneği ekiyle birlikte tam yazın:
  `{sağ|sol} memede`, `{sağda|solda}`, `{izlenmedi|izlenmemiştir|saptanmadı|saptanmamıştır}`.
  İç içe süslü parantez yok. Boş seçenek serbest: `{|belirgin }kalınlaşma`.
- **Sayı yuvaları:** `{mm}` 2–60 arası tam sayı, `{cm}` tek ondalıklı santimetre (ör. 3,5), `{n}` 1–12 arası tam sayı.
  Birimi arkasına yazın: `{mm} mm`, `{cm} cm'lik`, `{mm}x{mm} mm`, `{mm} mm'den`. Klinik aralığı dar olan ölçülerde
  yuva yerine seçenek kullanın: `{3|4|5} mm`, `{8|9|10|11} cm`.
- Yazılabilir hazır biçimler: rakam + birim (mm, cm, ml), `%30`, `BI-RADS 4a`, `TI-RADS 3`, `T2`, `L4-L5`, `C5-C6`,
  `12x8 mm`, `HU`. Kısaltmaları raporda yazıldığı gibi yazın (BT, MR, USG, FLAIR, BI-RADS…).
- **Sıra sayıları yazıyla:** `beşinci kosta`, `ikinci` — `5. kosta` yazmayın.
- Tarih, isim, hastane, hasta bilgisi yok.

## Örnek

```
# Kitle ve nodüller
{Sağ|Sol} meme {üst dış|üst iç|alt dış|alt iç} kadranda {mm}x{mm} mm boyutlu, {düzgün|mikrolobüle|spiküler} konturlu {hipoekoik|izoekoik} solid lezyon izlendi.
Lezyon BI-RADS {3|4a|4b|4c} olarak değerlendirilmiştir.
Her iki aksillada {patolojik boyut ve görünümde lenf nodu saptanmadı|yağlı hilusu korunmuş reaktif görünümde lenf nodları izlendi}.
```
