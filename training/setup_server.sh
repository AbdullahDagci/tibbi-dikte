#!/usr/bin/env bash
# GPU eğitim sunucusu kurulumu (Ubuntu 22.04/24.04, NVIDIA sürücüsü + CUDA 12.x kurulu varsayılır).
# Kullanım:  bash setup_server.sh   (training/ klasöründe)
set -euo pipefail
cd "$(dirname "$0")"

python3.11 -m venv .venv-gpu
source .venv-gpu/bin/activate
pip install -U pip
# Kurtarma/dışa aktarma torch 2.4.1 ile doğrulandı; eğitim için de aynı sürüm (k2 tekerlekleri bu sürüme göre seçilir)
pip install torch==2.4.1 torchaudio==2.4.1 --index-url https://download.pytorch.org/whl/cu121
# k2: torch 2.4.1 + CUDA 12.1 + Python 3.11 ile eşleşen tekerleği seçin:
#   https://k2-fsa.github.io/k2/cuda.html  (dosya adında "cuda12.1.torch2.4.1" ve "cp311" geçmeli)
: "${K2_WHEEL:?K2_WHEEL ortam değişkenine k2 tekerlek URL'sini verin (yukarıdaki sayfadan)}"
pip install "$K2_WHEEL"
pip install "numpy<2" "pyarrow<17" lhotse kaldialign pypinyin tensorboard sentencepiece onnx==1.16.2 \
    onnxruntime==1.19.2 kaldi-native-fbank soundfile huggingface_hub sherpa-onnx

[ -d icefall ] || git clone --depth 1 https://github.com/k2-fsa/icefall icefall
python -c "import k2, torch; print('k2', k2.__version__, 'cuda', torch.cuda.is_available())"
echo "Kurulum tamam. Sonraki adımlar: docs/EGITIM.md"
