# Model başarı raporu

Her satır bir ölçüm çalıştırması. **Uygulama** = hotword + tıbbi sonişleme (kullanıcının gördüğü metin). Doğruluk = 1 − WER. Karşılaştırmada sayı ve birimler okunuşuna çevrilir.

## FLEURS-TR test (gerçek ses, genel Türkçe)

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-04 12:12 | mihu v1 (eski temel) | 715 | %9.9 | **%10.1** | %89.9 | %2.8 | %87.3 | 5× gerçek zaman |
| 2026-11-04 13:22 | v2 — mevcut uygulama modeli 🏆 | 715 | %6.8 | **%7.0** | %93.0 | %1.9 | %94.5 | 9× gerçek zaman |
| 2026-11-04 13:58 | ufakzeka-kulak (Apache-2.0, akışsız) | 715 | %9.8 | **%9.7** | %90.3 | %2.8 | %89.1 | 43× gerçek zaman |

<details><summary>Son çalıştırmada en çok hata yapılan örnekler (ufakzeka-kulak (Apache-2.0, akışsız))</summary>

- **fleurs-11446785038892875951-413** (WER %80)
  - doğru: Lakkha Singh, şarkıcı Raju Khandelwal'ın eşliğinde chhappan bhog bhajan'ı söyledi.
  - çıktı: Loca Cing, şarkıcı Reshu Cander Wall'ın eşliğinde Chap Bangwoog Buin'ı söyledi.
- **fleurs-3821382969495596105-414** (WER %70)
  - doğru: Lakkha Singh, şarkıcı Raju Khandelwal'ın eşliğinde chhappan bhog bhajan'ı söyledi.
  - çıktı: Loca Sing, şarkıcı Raju, Kandel Val'ın eşliğinde Çaphan Boğuk Bajan'ı söyledi.
- **fleurs-8635712831779220795-379** (WER %67)
  - doğru: Daha sonra Cambridge'deki Addenbrooke Hastanesi'ne nakledildi.
  - çıktı: Daha sonra Cambridge'teki Ad Tham Broke Hastanesi'ne nakledildi.
- **fleurs-1769159075613236297-364** (WER %62)
  - doğru: Araç aynı gün takriben on iki virgül sıfır sıfır GMT'de kaza yerinden kaldırıldı.
  - çıktı: Aynı gün takipçili ben. 12 0. CTM'de kaza yerine kaldırıldı.
- **fleurs-3760582813802136359-104** (WER %56)
  - doğru: Falklands resmi para birimi değeri bir İngiliz sterlinine (GBP) denk şekilde ayarlanmış olan Falkland sterlinidir (FKP).
  - çıktı: Falcland resmi para birimi değeri bir İngiliz sterlinine parantez içinde GBP denk gelecek şekilde ayarlanmış olan Falk Land sterlinidir. F key pi.

</details>

## Radyoloji — sentetik

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-04 12:12 | mihu v1 (eski temel) | 100 | %26.1 | **%18.8** | %81.2 | %4.1 | %84.1 | 9× gerçek zaman |
| 2026-11-04 13:22 | v2 — mevcut uygulama modeli 🏆 | 100 | %19.5 | **%13.9** | %86.1 | %3.0 | %85.8 | 8× gerçek zaman |
| 2026-11-04 13:58 | ufakzeka-kulak (Apache-2.0, akışsız) | 100 | %18.8 | **%16.7** | %83.3 | %3.7 | %79.4 | 45× gerçek zaman |

<details><summary>Son çalıştırmada en çok hata yapılan örnekler (ufakzeka-kulak (Apache-2.0, akışsız))</summary>

- **47_Emel** (WER %67)
  - doğru: Pnömotoraks bulgusu saptanmadı.
  - çıktı: Yine Motoraks bulgusu saptanmadı.
- **29_Ahme** (WER %54)
  - doğru: Sağ diz manyetik rezonans incelemesinde medial menisküs arka boynuzda grade üç yırtık izlendi.
  - çıktı: Sadiz manyetik rezonans incelemesinde Medya Meniskü arka boynuzda Great 3 yıl tık izlendi.
- **06_Ahme** (WER %46)
  - doğru: Pulmoner arter dallarında dolum defekti saptanmadı, pulmoner emboli lehine bulgu yoktur.
  - çıktı: Bulmer artar dallarında dolum defekti saptanmadı, pulmoner embolu ile yine bulgu yoktur.
- **28_Emel** (WER %44)
  - doğru: Torakal vertebra korpuslarında hemanjiom ile uyumlu sinyal değişiklikleri izlendi.
  - çıktı: Torakal ve Ertebra Korpuslarında hem Anjeom ile uyumlu sinyal değişiklikleri izlendi.
- **37_Ahme** (WER %43)
  - doğru: Boyunda bilateral reaktif görünümlü lenf nodları izlendi.
  - çıktı: Boyunda bile teral reaktif görünümlü lenf notları izlendi.

</details>

## Genel tıbbi — sentetik

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-04 12:12 | mihu v1 (eski temel) | 24 | %27.4 | **%19.3** | %80.7 | %5.1 | %75.7 | 8× gerçek zaman |
| 2026-11-04 13:22 | v2 — mevcut uygulama modeli 🏆 | 24 | %18.9 | **%9.4** | %90.6 | %2.4 | %86.5 | 8× gerçek zaman |
| 2026-11-04 13:58 | ufakzeka-kulak (Apache-2.0, akışsız) | 24 | %17.5 | **%12.7** | %87.3 | %3.7 | %78.4 | 46× gerçek zaman |

<details><summary>Son çalıştırmada en çok hata yapılan örnekler (ufakzeka-kulak (Apache-2.0, akışsız))</summary>

- **10_Ahme** (WER %50)
  - doğru: Batın ultrasonografisinde kolelitiazis ve hepatomegali izlendi.
  - çıktı: Batı ultrasonografisinde koleli tiyazis ve hepatomegali izlendi.
- **07_Emel** (WER %50)
  - doğru: Hastada dispne, ortopne ve bilateral pretibial ödem mevcut.
  - çıktı: Hastada dispne, ortokne ve bilateral pileti bir haleden mevcut.
- **10_Emel** (WER %33)
  - doğru: Batın ultrasonografisinde kolelitiazis ve hepatomegali izlendi.
  - çıktı: Batın ultrasonografisinde koleli tazis ve hepatomegali izlendi.
- **04_Emel** (WER %22)
  - doğru: Fizik muayenede epigastrik hassasiyet mevcut, defans ve rebound yok.
  - çıktı: Fizik muayenede epigastrik hassasiyet mevcut, defans ve rebondio.
- **04_Ahme** (WER %22)
  - doğru: Fizik muayenede epigastrik hassasiyet mevcut, defans ve rebound yok.
  - çıktı: Fizik muayenede epigastrik hassasiyet mevcut, defans ve rebondio.

</details>

## Gerçek vakalar (yalnızca sonişleme)

| Tarih | Model | Örnek | Ham WER | **Uygulama WER** | Doğruluk | CER | Terim isabeti | Hız |
|---|---|---|---|---|---|---|---|---|
| 2026-11-04 12:12 | mihu v1 (eski temel) 🏆 | 1 | %18.7 | **%1.2** | %98.8 | %0.3 | %100.0 | — |
| 2026-11-04 13:22 | v2 — mevcut uygulama modeli 🏆 | 1 | %18.7 | **%1.2** | %98.8 | %0.3 | %100.0 | — |
| 2026-11-04 13:58 | ufakzeka-kulak (Apache-2.0, akışsız) 🏆 | 1 | %18.7 | **%1.2** | %98.8 | %0.3 | %100.0 | — |
