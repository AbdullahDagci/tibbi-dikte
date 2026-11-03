# Tıbbi Dikte

Windows sistem tepsisinde çalışan, **imlecin bulunduğu herhangi bir alana** Türkçe konuşmayı yazan
dikte uygulaması. Tıbbi terimler için ayarlanmıştır, tamamen çevrimdışı çalışır (ses cihazdan çıkmaz),
ürün anahtarıyla lisanslanır.

## Kullanım
1. Kur → ilk açılışta **Ayarlar › Lisans**'taki *makine kodunu* satıcıya ilet, gelen ürün anahtarını gir.
2. Yazmak istediğin alana tıkla, **Ctrl+Alt+Space** → konuş → tekrar **Ctrl+Alt+Space**.
   Metin her duraklamadan (~0,8 sn) sonra yazılır. Tepsi ikonu: mavi = hazır, kırmızı = dinliyor.
3. **Ayarlar › Sözlük**: kendi terimlerin ve "yanlış duyulan → doğru" düzeltmelerin.

## Tıbbi terim doğruluğu
| Katman | Ne yapar |
|---|---|
| Hotword (`app/medical/lexicon_tr.txt`) | ~700 terim modele öncelikli olarak verilir |
| Kesin düzeltme (`corrections_tr.tsv`) | `e ka ge → EKG`, `kılavulan at → klavulanat` |
| ITN (damga) | `beş yüz miligram → 500 mg`, `yüzde doksan dört → %94` |
| Birim/tansiyon | `1.000 mg → 1000 mg`, `tansiyon 140 90 → 140/90` |
| Bulanık düzeltme | `Tropolin → Troponin`, `intrabenoz → intravenöz` (ekler korunur) |

Sentetik test setinde (12 cümle × 2 ses, `tests/eval_wer.py`):
WER %19,9 → **%12,9**, tıbbi terim isabeti %61 → **%86**. Gerçek doktor kayıtlarıyla tekrar ölçülmeli:
kendi `.wav` kayıtlarını `tests/audio/NN_ad.wav` olarak, metnini `tests/sentences_tr.txt`'nin NN. satırına koy.

## Model değiştirme
Her model `models/<klasör>/model.json` ile tanımlanır; uygulama `models/` ve `%APPDATA%\TibbiDikte\models`
klasörlerini tarar, **Ayarlar › Genel › STT modeli**'nden seçilir. sherpa-onnx'in desteklediği her model
kodsuz eklenebilir:

```json
{ "name": "Whisper small", "engine": "sherpa-onnx", "mode": "offline", "type": "whisper",
  "encoder": "small-encoder.int8.onnx", "decoder": "small-decoder.int8.onnx",
  "tokens": "small-tokens.txt", "language": "tr" }
```
`mode`: `online` (akış) | `offline` (Silero VAD ile bölünür). `type`: online için `transducer`,
`paraformer`, `zipformer2_ctc`; offline için `transducer`, `whisper`, `nemo_ctc`, `paraformer`, `sense_voice`.
Başka bir çalışma zamanı için `app/engines/base.py`'deki `SttEngine`'i uygulayıp `registry.py`'ye ekle.

## Lisans anahtarı üretme (yalnızca satıcı)
```powershell
python tools\keygen.py init                       # bir kez: imza anahtar çifti
python tools\keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Dr. X" --days 365
python tools\keygen.py issue ABCD-EFGH-IJKL-MNOP --customer "Y Hastanesi" --perpetual
```
`tools/private_key.pem` **gizlidir**: yedekle, paylaşma, git'e koyma (`.gitignore`'da). Kaybolursa
mevcut anahtarlar çalışmaya devam eder ama yenisi üretilemez; değişirse eski anahtarların hepsi geçersiz olur.
Verilen anahtarlar `tools/issued_keys.csv`'ye kaydedilir.

## Geliştirme
```powershell
py -3.11 -m venv .venv; .\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python tools\setup_model.py      # modeli indir + bpe.vocab + model.json
.\.venv\Scripts\python -m app.main               # çalıştır
.\.venv\Scripts\python -m pytest                 # testler
.\build.ps1                                      # dist\installer\TibbiDikte-Kurulum-*.exe
```

## ⚠️ Model lisansı
Varsayılan model **mihu Community License** altındadır: yalnızca yıllık ciro < 500.000 USD iken
ticari kullanım; ücretli üründe dağıtımı açıkça izinli değil (md. 5e); "Powered by mihu" ibaresi
zorunlu (Hakkında sekmesinde ve tepsi ipucunda var). **Satıştan önce support@mihu.ai'den yazılı izin alın.**
