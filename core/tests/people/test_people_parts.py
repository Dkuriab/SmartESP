"""Части модуля людей: признаки, сопоставление с порогом и отрывом, скачивание модели."""

import hashlib
from pathlib import Path

import httpx
import numpy as np
import pytest

from smartesp.contracts import Person, VoiceSample
from smartesp.people import ModelDownloadError, download_model, model_path
from smartesp.people import model as model_module
from smartesp.people.features import BINS, fbank, frame_count, normalized_fbank
from smartesp.people.matching import best_match, centroid


def _person(name: str, *vectors: list[float], model: str = "m") -> Person:
    samples = tuple(VoiceSample(f"s{i}", 0.0, "A", 2.0, -6.0, model, tuple(v)) for i, v in enumerate(vectors))
    return Person(name, name, 0.0, samples)


def test_fbank_shape_and_short_input() -> None:
    assert frame_count(399) == 0 and frame_count(400) == 1 and frame_count(16000) == 98
    tone = np.sin(2 * np.pi * 1000 * np.arange(16000) / 16000)
    feats = fbank(tone)
    assert feats.shape == (98, BINS) and feats.dtype == np.float32
    assert int(np.argmax(feats.mean(axis=0))) in (26, 27, 28)  # 1 кГц: мел 1000 из 31…2840, шаг ~35
    assert normalized_fbank(b"\x00\x00" * 100).shape == (0, BINS)
    pcm = (tone * 8000).astype("<i2").tobytes()
    assert np.allclose(normalized_fbank(pcm).mean(axis=0), 0.0, atol=1e-4)


def test_centroid_ignores_other_models() -> None:
    person = _person("a", [1.0, 0.0], [0.0, 1.0])
    center = centroid(person, "m")
    assert center is not None and np.allclose(center, [2**-0.5, 2**-0.5])
    assert centroid(person, "other") is None


def test_best_match_threshold_and_margin() -> None:
    anya, danya = _person("Аня", [1.0, 0.0, 0.0]), _person("Даня", [0.0, 1.0, 0.0])
    assert best_match([0.9, 0.1, 0.0], [anya, danya], "m").person == anya
    weak = best_match([0.5, 0.0, 0.866], [anya, danya], "m")
    assert weak.person is None and weak.score == pytest.approx(0.5)  # ниже порога 0,55
    close = best_match([0.7, 0.68, 0.2], [anya, danya], "m", margin=0.05)
    assert close.person is None  # двое почти одинаково похожи — не угадываем
    assert best_match([1.0, 0.0, 0.0], [], "m").person is None


def _client(body: bytes, status: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, content=body)))


def test_download_checks_sha256(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    body = b"model-bytes"
    monkeypatch.setattr(model_module, "MODEL_SHA256", hashlib.sha256(body).hexdigest())
    seen: list[int] = []
    path = download_model(tmp_path, client=_client(body), progress=lambda done, total: seen.append(done))
    assert path == model_path(tmp_path) and path.read_bytes() == body and seen[-1] == len(body)


def test_download_rejects_wrong_file_and_http_error(tmp_path: Path) -> None:
    with pytest.raises(ModelDownloadError, match="не тот файл"):
        download_model(tmp_path, client=_client(b"evil"))
    with pytest.raises(ModelDownloadError):
        download_model(tmp_path, client=_client(b"", status=404))
    folder = model_path(tmp_path).parent
    assert list(folder.iterdir()) == []  # ни файла, ни .part
