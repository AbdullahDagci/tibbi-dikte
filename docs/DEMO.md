# Müşteri demosu

## Lisans Yöneticisi
Verilen anahtarlar, kalan günler, yenileme ve yeni anahtar üretimi için `tools\LisansYoneticisi.cmd` dosyasını çalıştırın.
Yalnızca bu bilgisayarda çalışır (`tools/private_key.pem` gerekir) ve müşteri paketine girmez. Kayıtlar
`tools/issued_keys.csv` dosyasındadır; bu iki dosya git'e girmez, şifreli olarak yedekleyin.

## Müşteriye deneme lisansı
Müşteriye **o bilgisayara bağlı**, kısa süreli anahtar verilir ve her müşteri için ayrı üretilir:

1. Müşteri uygulamayı kurar, Lisans sayfasındaki **makine kodunu** size gönderir.
2. Lisans Yöneticisi'nde **Yeni lisans** ile anahtarı üretirsiniz. Komut satırından da üretilebilir:
   ```powershell
   .\.venv\Scripts\python tools\keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "X Hastanesi (deneme)" --days 14
   ```
3. Müşteri anahtarı Lisans sayfasına yapıştırıp Etkinleştir'e basar.

Anahtar başka bilgisayarda çalışmaz; kime verildiği `tools/issued_keys.csv` dosyasında kalır. Uygulama kalan süreyi
tepside ve Lisans sayfasında gösterir, son 3 günde uyarır. Satın alırsa aynı makine kodu için yeni anahtar üretilir
(`--days 365`). Yeni biçim anahtarlar bu sürümden eski kurulumlarda çalışmaz.

### Herkese açık demo anahtarı
`keygen.py issue --demo` her bilgisayarda çalışır, en fazla 31 gün geçerlidir ve **iptal edilemez**. Yalnızca kendi
sunumlarınızda kullanın, müşteriye vermeyin.

### Saat koruması
Süreli anahtarlarda saati geri almak süreyi uzatmaz: geri alınan süre Windows'un saat kayıtlarından okunup kalan
süreden düşülür, süre dolduysa lisans kapanır. Uygulama açık kalsa bile lisans saatte bir yeniden denetlenir.
Süresiz lisans saatten etkilenmez. İnternet bağlantısı kullanılmadığı için şu durumlar engellenemez: Windows
günlüğünü ve uygulamanın kayıtlarını birlikte silmek, sanal makine anlık görüntüsüne dönmek, saati BIOS'tan her gün
geri almak.

## Canlı demo senaryosu (~10 dk)
Hazırlık: USB/dikte mikrofonu, sessiz oda, müşterinin branşından 3–4 rapor; bir kez prova edip kaçan terimleri
Ayarlar › Sözlük'e ekleyin.

1. **Canlı dikte** (Word veya müşterinin HBYS'sine benzer alan): alt gösterge, konuşurken yazma, cümle sonu
   düzeltmeleri ("beş yüz miligram" → 500 mg, "L dört L beş" → L4-L5).
2. **Bas-konuş**: Boşluk basılı tut → konuş → bırak.
3. **Biçim komutları**: "yeni satır", "yeni paragraf", "yeni madde".
4. **Test ve doğruluk**: önceden kaydedilmiş rapor + doğru metni → doğruluk %, renkli fark (tests\cases örnekleri).
5. **Mahremiyet**: interneti kapatıp dikteye devam edin — "ses bilgisayardan çıkmıyor" (KVKK).
