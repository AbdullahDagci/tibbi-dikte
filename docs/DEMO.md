# Müşteri demosu

## Deneme (demo) anahtarı
Her bilgisayarda çalışır, makine kodu gerekmez, **en fazla 31 gün** geçerlidir (uygulama daha uzununu reddeder).

```powershell
.\.venv\Scripts\python tools\keygen.py issue --demo --customer "X Hastanesi (demo)"            # 14 gün
.\.venv\Scripts\python tools\keygen.py issue --demo --customer "Y Kliniği (demo)" --days 30
```
Müşteriye kurulum dosyasıyla birlikte gönderin. Müşteri: Kur → Ayarlar › Lisans › anahtarı yapıştır → Etkinleştir.
Uygulama kalan süreyi tepside ve Lisans sekmesinde gösterir; son 3 günde uyarır. Süre bitince normal anahtar ister.
Satın alırsa: müşteri Lisans sekmesindeki **makine kodunu** gönderir, normal anahtar üretilir
(`keygen.py issue <makine-kodu> --customer ... --days 365`).

> ⚠️ Kurulum dosyası mihu modelini içerir. mihu'nun yazılı izni gelene kadar kurulumu müşteriye vermek dağıtım
> sayılır (lisans md. 5e). İzin gelene kadar demoyu kendi bilgisayarınızdan (yüz yüze / ekran paylaşımı) yapın;
> kendi modelimiz (B yolu) hazır olduğunda bu kısıt kalkar.

## Canlı demo senaryosu (~10 dk)
Hazırlık: USB/dikte mikrofonu, sessiz oda, müşterinin branşından 3–4 rapor; bir kez prova edip kaçan terimleri
Ayarlar › Sözlük'e ekleyin.

1. **Canlı dikte** (Word veya müşterinin HBYS'sine benzer alan): alt gösterge, konuşurken yazma, cümle sonu
   düzeltmeleri ("beş yüz miligram" → 500 mg, "L dört L beş" → L4-L5).
2. **Bas-konuş**: Boşluk basılı tut → konuş → bırak.
3. **Biçim komutları**: "yeni satır", "yeni paragraf", "yeni madde".
4. **Test ve doğruluk**: önceden kaydedilmiş rapor + doğru metni → doğruluk %, renkli fark (tests\cases örnekleri).
5. **Mahremiyet**: interneti kapatıp dikteye devam edin — "ses bilgisayardan çıkmıyor" (KVKK).
