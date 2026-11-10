# Müşteri demosu

## Lisans Yöneticisi
Verilen anahtarlar, kalan günler, yenileme ve yeni anahtar üretimi için `tools\LisansYoneticisi.cmd` dosyasını çalıştırın.
Yalnızca bu bilgisayarda çalışır (`tools/private_key.pem` gerekir) ve müşteri paketine girmez. Kayıtlar
`tools/issued_keys.csv` dosyasındadır; bu iki dosya git'e girmez, şifreli olarak yedekleyin. Listeden kaldırılan
kayıtlar `tools/issued_keys_removed.csv` dosyasına taşınır. Kaldırmak anahtarı iptal etmez: uygulama internete
bağlanmadığı için anahtar süresi bitene kadar kurulu olduğu bilgisayarda çalışır.

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

## Canlı demo senaryosu (~12 dk)
Hazırlık:
- USB/dikte mikrofonu, sessiz oda, müşterinin branşından 3–4 rapor.
- **Mikrofon**: Ayarlar › Mikrofon'da kullanacağınız mikrofonu seçip kaydedin, **Mikrofonu test et** ile bir cümle
  okuyun. Sonuç "Mikrofon iyi çalışıyor" olmalı; değilse yazan öneriyi uygulayın, **Kaydı dinle** ile duyulanı
  kontrol edin.
- **Sözlük**: boş görünmesin diye Sözlük › İçe aktar › `testData\demo_sozluk.csv` (20 radyoloji terimi; modelin
  test kayıtlarında gerçekten yanlış yazdığı söylenişler, ör. `SUVmax ← sumax`, `STIR ← steer`, `BI-RADS ← brads`).
- Bir kez prova edip kaçan terimleri de Sözlük'e ekleyin.

1. **Canlı dikte** (Word veya müşterinin HBYS'sine benzer alan): alt gösterge, konuşurken yazma, cümle sonu
   düzeltmeleri ("beş yüz miligram" → 500 mg, "L dört L beş" → L4-L5).
2. **Bas-konuş**: Boşluk basılı tut → konuş → bırak.
3. **Biçim komutları**: "yeni satır" / "alt satır" / "satır başı" (alt satıra geçer), "yeni paragraf", "yeni madde".
4. **Sözlük**: Sözlük ekranında bir terimi ve söylenişlerini gösterin; **Dene** kutusuna
   `sagittal steer sekanslarda diffüz bolging` yazın → `sagittal STIR sekanslarda diffüz bulging`. Dikte ekranında
   yanlış çıkan kelimeyi seçip sağ tık › *Sözlüğe varyant olarak ekle* ile anında düzeltmeyi gösterin.
   Canlı diktede aynı hata çıkmayabilir (model o an ne duyduysa); sözlüğü Dene kutusuyla göstermek garantilidir.
   Varsayılan modelde terim ekleyince tanıma güçlenmez; sözlük söylenişi doğru yazıma çevirir.
5. **Mikrofon denetimi**: Ayarlar › Mikrofonu test et → sonuç ve Kaydı dinle. İsterseniz mikrofonu Windows'tan
   sessize alıp dikte başlatın: birkaç saniye içinde göstergede "Mikrofondan ses gelmiyor" uyarısı çıkar.
6. **Test ve doğruluk**: önceden kaydedilmiş rapor + doğru metni → doğruluk %, renkli fark (tests\cases örnekleri).
7. **Mahremiyet**: interneti kapatıp dikteye devam edin — "ses bilgisayardan çıkmıyor" (KVKK).

Not: **Veri toplama** ekranı bu sürümde menülerde gizlidir, demoda gösterilmez (geri açmak için
`app/main_window.py` › `HIDDEN_PAGES`).

## Mikrofon sorunları
- Önce Ayarlar › **Mikrofonu test et**: sonuç sorunu düz cümleyle söyler (ses gelmiyor / kısık / patlıyor /
  gürültülü). **Kaydı dinle** ile programın duyduğu sese bakın: ses kötüyse sorun mikrofonda, ses iyi ama metin
  yanlışsa modelde ya da sözlükte.
- "Ses gelmiyor": Windows › Ayarlar › Gizlilik › Mikrofon › *masaüstü uygulamalarının erişimi* açık mı, mikrofon
  sessizde mi, Teams/Zoom mikrofonu tutuyor mu? Bluetooth kulaklık mikrofonu tanımayı belirgin bozar.
- Her dikte sonunda `%APPDATA%\TibbiDikte\app.log`'a "mikrofon özeti" satırı yazılır (konuşma/gürültü düzeyi,
  patlama, ses kaybı; metin yazılmaz). Kelime atlanıyorsa `ses kaybı` ve `işleme gecikmesi` satırlarına bakın;
  gecikme varsa Ayarlar › İşlemci iş parçacığı'nı 4'e çıkarın.
- Uygulama açıkken takılan USB mikrofon, uygulama yeniden başlatılınca listede görünür. "Varsayılan mikrofon"
  seçiliyse Windows'un o anki mikrofonu kullanılır.
