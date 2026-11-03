# Radyoloji ince ayarı (fine-tuning) — çalışma kılavuzu

Tümü `training/` klasöründedir. Windows makinede adım 1-3 ve küçük ölçekli denemeler yapıldı; asıl eğitim
GPU'lu Linux sunucusunda yapılır (k2 yalnızca Linux+CUDA'da var).

## Durum
| Adım | Durum |
|---|---|
| 1. mihu'dan izin + `.pt` | Taslak: `docs/mihu_izin_talebi.md` — **gönderilmedi** |
| 2. Gerçek test seti | Araç + 50 cümle hazır (`tools/record_testset.py`); kayıt bekleniyor. Sentetik başlangıç: `data/radiology_test/baseline_synthetic.txt` |
| 3. Checkpoint kurtarma | v1 birebir, v2 int8 gürültüsü düzeyinde doğrulandı (`exp/mihu-v1`, `exp/mihu-v2`) |
| 4. Veri | medv3 5,7 sa · MediaSpeech 10 sa · FLEURS 7,7+1,1+2,4 sa hazır; ISSAI (218 sa) ve Common Voice sunucuda |
| 5. Eğitim | Betik hazır, CPU'da 40 adım duman testi geçti; GPU çalıştırması bekleniyor |
| 6. Dışa aktarma | `export_model.py` -> `models/<ad>/` doğrulandı; uygulama otomatik bulur |


## Karar (3.11.2026): önce A, paralelde B — eğitim kendi GPU makinemizde
| | A) mihu üzerine ince ayar | B) Kendi modelimiz (bağımsız) |
|---|---|---|
| Başlangıç | `exp/mihu-v2/epoch-0.pt` (kurtarılmış) | Rastgele (varsayılan) · lisansı yazılı teyit edilirse İngilizce Zipformer kodlayıcısı (`--init-mode encoder`) |
| Sözlük | mihu bpe.model | `train_bpe.py` ile kendi BPE'miz |
| Dışa aktarma | `export_model.py` (atıf eklenir) | `export_model.py --independent --lang-dir lang_tr_bpe500` (atıf yok) |

### Veri toplama (radyologlar)
Uygulama tepsi menüsü › **Veri toplama…** — konuşmacı kodu + KVKK onayı, "Cümle oku" veya "Serbest dikte".
Kayıtlar: `%APPDATA%\TibbiDikteeri_toplama\` → sunucuya kopyalayın:
`python prepare_data.py dir --src /yol/veri_toplama --name radreal`
Hedef: 20–50 sa, ≥10 konuşmacı. Bir konuşmacının kayıtlarını tamamen test setine ayırın (konuşmacıdan bağımsız ölçüm).

### B yolu komutları
```bash
python train_bpe.py --vocab-size 500 --out lang_tr_bpe500 --extra-text ../data/reports/metinler.txt
python finetune.py --exp-dir exp/own-v1 --bpe-model lang_tr_bpe500/bpe.model --base-lr 0.045   --train issai_train:4,commonvoice_train:2,mediaspeech_train:1,fleurs_train:1,medv3_train:2,radsynth_train:2,radreal_train:4   --valid fleurs_dev,radiology_real_test --max-duration 1000 --num-steps 150000
python export_model.py --ckpt exp/own-v1/averaged.pt --name tibbi-tr-own-v1 --title "Türkçe Tıbbi Dikte (kendi model) v1"   --independent --lang-dir lang_tr_bpe500
```
B'yi ürüne koyma ölçütü: gerçek radyoloji test setinde A ile eşit/daha iyi WER. O gün `models/tibbi-tr-v2` paketten
çıkarılır; NOTICE ve Hakkında'daki mihu satırı otomatik kaybolur (`tools/make_notice.py`).

## Sunucuda çalıştırma
```bash
# 0) kurulum (bir kez)
K2_WHEEL=<k2 tekerlek URL> bash setup_server.sh && source .venv-gpu/bin/activate
# Windows'ta üretilen exp/mihu-v2/epoch-0.pt dosyasını sunucuya kopyalayın (ya da recover_checkpoint.py'yi
# orada çalıştırın: python recover_checkpoint.py --onnx-dir ../models/tibbi-tr-v2 --out exp/mihu-v2/epoch-0.pt)

# 1) veri
python prepare_data.py issai          # 21 GB indirme
python prepare_data.py mediaspeech; python prepare_data.py medv3; python prepare_data.py fleurs
python prepare_data.py commonvoice --src /yol/cv-corpus-XX/tr      # Mozilla Data Collective'den
python make_radiology_text.py --n 20000 [--reports anonim_raporlar.txt]
python tts_synthesize.py --sentences data/radsynth_sentences.txt --out data/raw/radsynth --backend google \
    --voices tr-TR-Chirp3-HD-Aoede,tr-TR-Chirp3-HD-Charon,tr-TR-Chirp3-HD-Kore,tr-TR-Chirp3-HD-Orus --per-sentence 2
python prepare_data.py dir --src data/raw/radsynth --name radsynth
python prepare_data.py dir --src /yol/radyolog_kayitlari --name radreal          # gerçek eğitim kayıtları
python prepare_data.py testset --src ../data/radiology_test/audio --sentences ../data/radiology_test/sentences.txt
python prepare_data.py fbank --jobs 16 --speed-perturb

# 2) eğitim (tek A100/4090: ~30k adım ≈ 1-2 gün)
python finetune.py --init-ckpt exp/mihu-v2/epoch-0.pt --exp-dir exp/rad-ft1 \
  --train issai_train:4,commonvoice_train:2,mediaspeech_train:1,fleurs_train:1,medv3_train:2,radsynth_train:3,radreal_train:4 \
  --valid fleurs_dev,radiology_real_test --max-duration 600 --num-steps 30000 --base-lr 0.002

# 3) dışa aktarma + değerlendirme
python export_model.py --ckpt exp/rad-ft1/averaged.pt --name mihu-tr-radyoloji-ft1 --title "mihu TR + radyoloji ft1"
cd .. && python tests/eval_wer.py --model models/mihu-tr-radyoloji-ft1 \
    --sentences data/radiology_test/sentences.txt --audio data/radiology_test/audio
python tests/eval_wer.py --model models/mihu-tr-radyoloji-ft1      # genel tıbbi set: gerilemediğini kontrol et
```
Karar ölçütü: gerçek radyoloji setinde WER belirgin düşmeli **ve** FLEURS-test / genel setlerde artmamalı.
Genel sette gerileme varsa: genel veri ağırlıklarını artırın veya `--base-lr` düşürün.

## Önemli ayrıntılar
- **Metin biçimi**: hedefler modelin çıktı biçiminde (büyük/küçük harf, noktalama, sayılar yazıyla, birimler
  okunuşuyla). `textnorm.py`. Küçük harfli kaynaklarda (ör. MediaSpeech) cümle başı/son nokta onarılır.
- **Sözlük aynı** (500 BPE) — decoder/joiner korunur, yalnızca ince ayar.
- **Akış korunur**: eğitimde rastgele parça boyu, dışa aktarımda 16/128 → uygulamadaki gecikme ve CPU hızı aynı.
- **v2 kaynağı int8**: kurtarılan ağırlıklar int8'den çevrildi; eğitimsiz yeniden dışa aktarım genel sette
  orijinalle aynı sonucu verdi (hotword+sonişleme %11,9).
- **Lisans**: mihu (md. 2 türev serbest, md. 5a "rakip model" belirsiz) — yazılı onay olmadan türev model dağıtmayın.
  TTS sağlayıcısının şartları eğitim kullanımına izin vermeli. Gerçek kayıtlar için KVKK açık rızası.
