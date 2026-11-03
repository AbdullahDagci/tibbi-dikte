"""Windows/CPU için k2 yerine geçen minimal modül — YALNIZCA checkpoint kurtarma ve ONNX dışa aktarma içindir.
Eğitim (pruned RNN-T kaybı) gerçek k2 ister: Linux + CUDA ortamında `pip install k2` kullanın."""
import torch

__version__ = "0.0-shim"


def swoosh_l_forward(x):
    return torch.logaddexp(torch.zeros_like(x), x - 4.0) - 0.08 * x - 0.035


def swoosh_r_forward(x):
    return torch.logaddexp(torch.zeros_like(x), x - 1.0) - 0.08 * x - 0.313261687


swoosh_l = swoosh_l_forward
swoosh_r = swoosh_r_forward


def swoosh_l_forward_and_deriv(x):
    # d/dx [softplus(x-4) - 0.08x - 0.035] = sigmoid(x-4) - 0.08
    return swoosh_l_forward(x), torch.sigmoid(x - 4.0) - 0.08


def swoosh_r_forward_and_deriv(x):
    return swoosh_r_forward(x), torch.sigmoid(x - 1.0) - 0.08


class _Missing:
    def __init__(self, *a, **k):
        raise RuntimeError("k2 shim: bu özellik gerçek k2 gerektirir (Linux + CUDA)")


def __getattr__(name):  # k2.Fsa, k2.RaggedTensor vb. tip ipuçları içe aktarmada çözülebilsin
    return type(name, (_Missing,), {})
