# Model başarı raporu

Her satır bir ölçüm çalıştırması. **Uygulama** = hotword + tıbbi sonişleme (kullanıcının gördüğü metin). Doğruluk = 1 − WER. Karşılaştırmada sayı ve birimler okunuşuna çevrilir.

## FLEURS-TR test (gerçek ses, genel Türkçe)

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-03 16:29 | mihu v1 (eski temel) | 715 | %11.1 | **%11.2** | %88.8 | %2.9 | %87.3 | 10× gerçek zaman |
| 2026-11-04 10:27 | v2 — mevcut uygulama modeli 🏆 | 715 | %7.3 | **%7.8** | %92.2 | %2.1 | %94.5 | 4× gerçek zaman |

<details><summary>Son çalıştırmada en çok hata yapılan örnekler (v2 — mevcut uygulama modeli)</summary>

- **fleurs-3760582813802136359-104** (WER %69)
  - doğru: Falklands resmi para birimi değeri bir İngiliz sterlinine (GBP) denk şekilde ayarlanmış olan Falkland sterlinidir (FKP).
  - çıktı: Fot lans resmi para birimi değeri bir İngiliz sterlinine parantez içinde JBP" denk gelecek şekilde ayarlanmış olan Fotland Sterlin'idir. F Pi
- **fleurs-7737199873163370997-12** (WER %67)
  - doğru: Erkekler ayakta Super-G.'yi Avustralyalı Mitchell Gourley on birinci sırada bitirdi, Çek yarışmacı Oldrich Jelinek erkekler oturarak Super-G.'de on altıncı bitirdi.
  - çıktı: Arkekler ayakta Süper ciyi, Avustralyalı Michael Gorle'yı 11. sırada bitirdi. Çek yarışmacı All Strich, Jeinek, erkekler oturarak Süper J'de 16. yıl bitirildi.
- **fleurs-11446785038892875951-413** (WER %67)
  - doğru: Lakkha Singh, şarkıcı Raju Khandelwal'ın eşliğinde chhappan bhog bhajan'ı söyledi.
  - çıktı: Laka Sing, şarkıcı Reju Kandar'ın eşliğinde Cap Ban Woog Bugon'ı söyledi.
- **fleurs-14796200043332062398-385** (WER %60)
  - doğru: Futbol, ​​basketbol, ​​voleybol, sutopu, eskrim, ragbi, bisiklete binme, buz hokeyi, patenli hokey ve F bir motorlu araç yarışları popüler sporlardandır.
  - çıktı: Bu betbol, valeybol su topu ekstrim Rock bir bisiklete binme, buzoki, batenli okey ve F1 motorlu araç yarışları popüler sporlardandır.
- **fleurs-8845659249103320766-11** (WER %50)
  - doğru: Erkekler ayakta Super-G.'yi Avustralyalı Mitchell Gourley on birinci sırada bitirdi, Çek yarışmacı Oldrich Jelinek erkekler oturarak Super-G.'de on altıncı bitirdi.
  - çıktı: Erkekler ayakta süperceyi Avustralyalı Michel Goli 11. sırada bitirdi. Çek yarışmacı Audrich Jelinek, erkekler oturarak Süper J bitirdi.

</details>

## Radyoloji — sentetik

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-03 16:29 | mihu v1 (eski temel) | 100 | %27.3 | **%20.0** | %80.0 | %4.2 | %85.1 | 3× gerçek zaman |
| 2026-11-04 10:27 | v2 — mevcut uygulama modeli 🏆 | 100 | %19.8 | **%15.3** | %84.7 | %3.1 | %87.3 | 3× gerçek zaman |

<details><summary>Son çalıştırmada en çok hata yapılan örnekler (v2 — mevcut uygulama modeli)</summary>

- **47_Emel** (WER %67)
  - doğru: Pnömotoraks bulgusu saptanmadı.
  - çıktı: Yine Motorax bulgusu saptanmadı.
- **05_Emel** (WER %57)
  - doğru: Her iki akciğerde buzlu cam dansiteleri izlenmekte olup viral pnömoni açısından klinik korelasyon önerilir.
  - çıktı: Heriki akciğer de buzlu camdan siteleri izlenmekte olup bir al pinomoni açısından klinik korelasyon önerilir.
- **40_Ahme** (WER %56)
  - doğru: Uterus antevert pozisyonda, boyutları normal, endometrium kalınlığı sekiz milimetredir.
  - çıktı: Bu terus antevert pozisyonda boyutları normal, endometriumiği 8 milimetrikir.
- **35_Emel** (WER %56)
  - doğru: Mamografide sağ meme üst dış kadranda gruplaşmış mikrokalsifikasyonlar izlendi.
  - çıktı: Mamografide sağ memeüst dışkadranda gruplaşmış mikrokifikasyonlar izlendi.
- **34_Emel** (WER %56)
  - doğru: Meme ultrasonografisinde sol meme saat ikide on bir milimetrelik hipoekoik solid lezyon izlendi, BI-RADS dört olarak değerlendirildi.
  - çıktı: Meme ultrasonografiğinde solmeme saat 2'de 11 milimetrik hipo ekoik solid lezyon izlendi. Brads 4 olarak değerlendirildi.

</details>

## Genel tıbbi — sentetik

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-03 16:29 | mihu v1 (eski temel) | 24 | %27.6 | **%19.2** | %80.8 | %5.1 | %77.0 | 2× gerçek zaman |
| 2026-11-04 10:27 | v2 — mevcut uygulama modeli 🏆 | 24 | %18.7 | **%8.9** | %91.1 | %2.1 | %86.5 | 3× gerçek zaman |

<details><summary>Son çalıştırmada en çok hata yapılan örnekler (v2 — mevcut uygulama modeli)</summary>

- **10_Emel** (WER %50)
  - doğru: Batın ultrasonografisinde kolelitiazis ve hepatomegali izlendi.
  - çıktı: Batın ultrasonografiğinde koloneli tazis ve hepatomegali izlendi.
- **07_Emel** (WER %38)
  - doğru: Hastada dispne, ortopne ve bilateral pretibial ödem mevcut.
  - çıktı: Astada dispne, ortopne ve bilateral pretibi aleden mevcut.
- **07_Ahme** (WER %38)
  - doğru: Hastada dispne, ortopne ve bilateral pretibial ödem mevcut.
  - çıktı: Hastada disp ne ortopne ve bilateral piletibel ödem mevcut.
- **10_Ahme** (WER %33)
  - doğru: Batın ultrasonografisinde kolelitiazis ve hepatomegali izlendi.
  - çıktı: Batı ultrasonografisinde kolonitiyazis ve hepatomegali izlendi.
- **04_Emel** (WER %22)
  - doğru: Fizik muayenede epigastrik hassasiyet mevcut, defans ve rebound yok.
  - çıktı: Fizik muayenede epigastrik hassasiyet mevcut. Defans ve röbondiok

</details>

## Gerçek vakalar (yalnızca sonişleme)

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-03 16:29 | mihu v1 (eski temel) 🏆 | 1 | %18.7 | **%1.2** | %98.8 | %0.3 | %100.0 | — |
| 2026-11-04 10:27 | v2 — mevcut uygulama modeli 🏆 | 1 | %18.7 | **%1.2** | %98.8 | %0.3 | %100.0 | — |
