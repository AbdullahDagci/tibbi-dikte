# Türkçe konuşma tanıma için veri setleri (araştırma: 3.11.2026)

Ölçüt: **ticari üründe kullanılabilir lisans**, indirilebilirlik, saat, konuşma türü. Lisanslar kaynak sayfalarından
alınmıştır; kullanmadan önce güncel lisans metnini yeniden doğrulayın.

## 1. Eğitimde kullanılabilir (ticari kullanıma uygun)
| Veri seti | Saat | Konuşma türü | Lisans | Erişim | Not |
|---|---|---|---|---|---|
| [ISSAI Turkish Speech Corpus](https://huggingface.co/datasets/issai/Turkish_Speech_Corpus) | 218 | okuma, çok konuşmacı | CC BY 4.0 (HF etiketi MIT) | açık, 21 GB | temel set; `prepare_data.py issai` |
| [Common Voice TR 26/27](https://mozilladatacollective.com/datasets/cmqinosfq00x4nr07gnk0rdf9) | ~136 (130 doğrulanmış) | okuma, 1.800+ konuşmacı | **CC0** | Mozilla Data Collective hesabı | konuşmacı çeşitliliği; `prepare_data.py commonvoice` |
| [alania-speech-captions-tr](https://huggingface.co/datasets/cloud0day3/alania-speech-captions-tr) | ~835 bin kayıt (tahmini ~1.800 sa) | YouTube, doğal/çeşitli | transkript CC BY 3.0 | açık | YODAS'tan bölünmüş hazır parçalar; `asr_disagrees_with_youtube` ile filtrelenebilir |
| [YODAS / YODAS2 / YODAS v3](https://huggingface.co/datasets/espnet/yodas2) | binlerce sa TR (kulak 4.696 sa kullandı) | YouTube, çok çeşitli | CC BY 3.0 | açık ama devasa (yodas2 60 TB) | transkript kalitesi değişken → filtreleme şart |
| [MediaSpeech TR (OpenSLR 108)](https://openslr.org/108/) | 10 | haber/medya | CC BY 4.0 | açık | `prepare_data.py mediaspeech` |
| [FLEURS tr_tr](https://huggingface.co/datasets/google/fleurs) train/dev | 7,7 + 1,1 | okuma (Wikipedia) | CC BY 4.0 | açık | test bölümü yalnızca değerlendirme |
| [turkmedstt medv3](https://huggingface.co/datasets/turkmedstt/medv3-turkish-medical-asr) | ~5,7 | **sentetik tıbbi** (Google TTS) | CC BY 4.0 | açık | tıbbi terim; tek başına yetmez (sentetik ses) |
| [antalia-voice-corpus](https://huggingface.co/datasets/cloud0day3/antalia-voice-corpus) | ~4 | tek konuşmacı, senaryolu | CC BY 4.0 | açık | düşük değer (tek ses); kart taklit/dolandırıcılık kullanımını yasaklar |
| **Kendi radyolog kayıtlarımız** | hedef 20–50 | **gerçek radyoloji diktesi** | bizim | Veri toplama ekranı | **en değerli veri** — başka kaynakta yok |

## 2. Yalnızca değerlendirme
| Veri seti | İçerik | Not |
|---|---|---|
| FLEURS-TR test | 715 kayıt, 2,4 sa | `tools/benchmark.py` kullanıyor; mihu/kulak da bunu raporluyor |
| [TurkASR-Bench](https://huggingface.co/datasets/yagmurtuncer/turkasr-bench) | 7 kaynak × 743, 14,7 sa (konuşma dili dahil) | girişli (gated); yalnızca değerlendirme/araştırma; Khan Academy NC, VoxForge GPL içerir |

## 3. Kullanılamaz / dikkat
| Veri seti | Sebep |
|---|---|
| Khan Academy TR | CC BY-NC-SA — ticari kullanım yok |
| MagicHub ASR-STurkDuSC (3,1 sa) | CC BY-NC-ND — ticari kullanım ve türev yok |
| LDC Turkish Broadcast News (~130 sa) | ücretli üyelik/lisans |
| [SpeechDataAI Turkish conversational](https://huggingface.co/datasets/SpeechDataAI/turkish-conversational-speech) (2.000 sa) | ticari satın alma — bütçe varsa doğal konuşma için seçenek |
| TBMM ses kayıtları | açık lisanslı ses yok (yalnızca metin; aşağıya bakın) |
| Gerçek Türkçe radyoloji/hekim dikte sesi | **açık kaynakta yok** — kendimiz toplamalıyız |

## 4. Metin (dil modeli, tokenizer, sentetik ses için)
| Kaynak | Lisans | Kullanım |
|---|---|---|
| Kendi anonim rapor metinlerimiz | bizim | veri toplama cümleleri, TTS |
| [TBMM tutanakları 1950–2023](https://zenodo.org/records/19713325) | CC BY 4.0 | genel resmî Türkçe metin |
| Türkçe Vikipedi | CC BY-SA | ürüne gömülecek modellerde paylaşım-benzer yükümlülüğü nedeniyle dikkat |

## 5. Hazır açık model: ufakzeka-kulak (B yolu için kritik)
[ufakai/ufakzeka-kulak](https://huggingface.co/ufakai/ufakzeka-kulak) — **Apache-2.0** (ticari serbest), 31,6M parametre,
~5.000 sa ile sıfırdan eğitilmiş (CV, ISSAI, YODAS). [Makale](https://arxiv.org/html/2611.03605): FLEURS-TR WER %9,2;
eğitim 52 GPU-saat (A100). **sherpa-onnx int8 sürümü var** → uygulamamızda çalışıyor (`model_type: nemo_transducer`,
`input_gain: 8`). Sınırlama: **akışlı değil** — metin her duraklamada gelir (kelime kelime değil).
Bizim ölçümlerimiz: `benchmarks/RAPOR.md`.

## Öneri
- **A yolu (mihu ince ayar):** ISSAI + Common Voice + MediaSpeech + FLEURS train + medv3 + kendi radyoloji kayıtlarımız
  (~370 sa + radyoloji). Yeterli.
- **B yolu (bağımsız):**
  1. Önce **kulak** ölçülür; radyolojide mihu'ya yakınsa en hızlı bağımsız temel odur → kendi radyoloji
     verimizle NeMo üzerinde ince ayar (Apache-2.0 izin verir).
  2. Akışlı (kelime kelime) bağımsız model istenirse: Zipformer sıfırdan + ISSAI + CV + alania/YODAS (filtrelenmiş,
     ~2.000+ sa). kulak'ın tarifi: YouTube altyazısı Whisper ile ≤%20 WER uyuşuyorsa kullan, değilse ikinci bir ASR
     ile CER ≤%10 doğrulanırsa kullan. Kendi GPU'muzda (RTX 4090 sınıfı) ~1 hafta.
- Her iki yolda **belirleyici veri kendi radyolog kayıtlarımızdır**; açık kaynakta Türkçe radyoloji sesi yoktur.
