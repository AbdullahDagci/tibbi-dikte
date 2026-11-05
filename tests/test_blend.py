"""Ağırlık karıştırma (training/blend_model.py): ince ayarlı model + temel model. torch gerektirir (WSL eğitim ortamı)."""
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "training"))
from blend_model import blend  # noqa: E402


def _state(w: float):
    return {"w": torch.full((2, 2), w), "b": torch.full((2,), w, dtype=torch.bfloat16),
            "steps": torch.tensor(7, dtype=torch.int64)}


def test_blend_interpolates_float_tensors():
    out = blend(_state(1.0), _state(0.0), 0.7)
    assert torch.allclose(out["w"], torch.full((2, 2), 0.7))
    assert out["b"].dtype == torch.bfloat16 and abs(float(out["b"][0]) - 0.7) < 0.01


def test_blend_endpoints_and_integer_buffers():
    ft, base = _state(3.0), _state(1.0)
    assert torch.equal(blend(ft, base, 1.0)["w"], ft["w"])
    assert torch.equal(blend(ft, base, 0.0)["w"], base["w"])
    assert int(blend(ft, base, 0.5)["steps"]) == 7  # tamsayı tamponlar karıştırılmaz


def test_blend_rejects_mismatched_models():
    with pytest.raises(ValueError):
        blend({"a": torch.zeros(1)}, {"b": torch.zeros(1)}, 0.5)
