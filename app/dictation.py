"""Dikte denetleyicisi: mikrofon -> STT oturumu -> tıbbi sonişleme -> imlece yazma.

Ayrı bir iş parçacığında çalışır. toggle() ile açılıp kapanır. Durum değişiklikleri
on_state(state) geri çağrısıyla bildirilir: "loading" | "idle" | "listening" | "error".
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from .audio import MIC_OPEN_ERROR, LevelMonitor, Microphone, configured_device, level_fraction
from .config import Config
from .engines.base import ModelInfo, SttEngine
from .engines.registry import discover_models, load_engine, resolve_model
from .medical.postprocess import MedicalPostProcessor, WordScore, read_lexicon, tr_capitalize
from .paths import resource_dir, user_dir
from .live import LiveWriter
from .typer import backspace, type_text

log = logging.getLogger(__name__)

NO_DATA_S = 2.0  # dikte sürerken bu kadar süre mikrofondan hiç parça gelmezse bağlantı kopmuş sayılır
DICTATION_ERROR = "Dikte sırasında hata oluştu (günlük dosyasına bakın)."

BUILTIN_LEXICON = resource_dir() / "medical" / "lexicon_tr.txt"
RADIOLOGY_LEXICON = resource_dir() / "medical" / "radiology_terms_tr.txt"
RADIOLOGY_KNOWN = resource_dir() / "medical" / "radiology_known_tr.txt"
GENERAL_WORDS = resource_dir() / "medical" / "general_tr_words.txt"
BUILTIN_CORRECTIONS = resource_dir() / "medical" / "corrections_tr.tsv"
USER_LEXICON = user_dir() / "kullanici_terimler.txt"
USER_CORRECTIONS = user_dir() / "kullanici_duzeltmeler.tsv"


def ensure_user_files() -> None:
    if not USER_LEXICON.exists():
        USER_LEXICON.write_text("# Kendi tıbbi terimleriniz — her satıra bir terim\n", encoding="utf-8")
    if not USER_CORRECTIONS.exists():
        USER_CORRECTIONS.write_text("# yanlış duyulan<TAB>doğru yazım\n", encoding="utf-8")


def write_hotwords(lexicon_files: list[Path], out: Path) -> Path:
    """Sözlük dosyalarından sherpa-onnx hotword dosyası üretir (tekrarsız).

    Model büyük/küçük harf duyarlı; cümle başında da tercih edilsin diye büyük harfli
    biçim de eklenir (aksi hâlde "levotiroksin" cümle başında küçük harfle çıkıyor).
    """
    seen: dict[str, None] = {}
    for p in lexicon_files:
        for t in read_lexicon(p):
            seen.setdefault(t, None)
            if t[:1].islower():
                seen.setdefault(tr_capitalize(t), None)
    out.write_text("\n".join(seen), encoding="utf-8")
    return out


class Dictation:
    def __init__(self, cfg: Config, on_state: Callable[[str], None] | None = None,
                 on_text: Callable[[str], None] | None = None,
                 typer: Callable[[str], None] = type_text,
                 on_level: Callable[[float], None] | None = None,
                 on_partial: Callable[[str], None] | None = None,
                 eraser: Callable[[int], None] = backspace,
                 on_segment: Callable[[list[tuple[str, str]]], None] | None = None,
                 on_scores: Callable[[list[WordScore]], None] | None = None,
                 on_warning: Callable[[str], None] | None = None):
        """on_warning(anahtar): mikrofon uyarısı (audio.MIC_WARNINGS anahtarı; "" = uyarı kalktı)."""
        self.cfg = cfg
        self.on_warning = on_warning or (lambda k: None)
        self.last_error = ""  # son hatanın kullanıcıya gösterilecek açıklaması
        self.on_state = on_state or (lambda s: None)
        self.on_text = on_text or (lambda t: None)
        self.typer = typer
        self.eraser = eraser
        self._writer: LiveWriter | None = None
        self.on_level = on_level or (lambda v: None)
        self.on_partial = on_partial or (lambda t: None)
        self.on_segment = on_segment
        self.on_scores = on_scores
        self._last_spans: list[tuple[str, str]] = []
        self.engine: SttEngine | None = None
        self.post: MedicalPostProcessor | None = None
        self.model: ModelInfo | None = None
        self._active = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._toggle_lock = threading.Lock()
        self._load_lock = threading.RLock()  # yükleme ve sözlük yenileme aynı anda çalışmaz
        self._thread: threading.Thread | None = None

    # ------------------------------------------------ yükleme
    def pick_model(self) -> ModelInfo:
        models = discover_models()
        if not models:
            raise FileNotFoundError("Hiç model bulunamadı (models klasöründe model.json yok).")
        return resolve_model(models, self.cfg.model_dir)

    def load(self) -> None:
        """Modeli ve sonişleyiciyi (yeniden) yükler. Dikte açıksa önce durdurur."""
        with self._load_lock:
            self._load()

    def needs_engine_reload_for_dictionary(self) -> bool:
        """Terimler modele hotword olarak veriliyorsa sözlük değişince motor da yeniden kurulmalı."""
        return bool(self.cfg.use_hotwords and self.model is not None and self.model.hotwords)

    def reload_dictionary(self) -> None:
        """Sözlük değişti: yalnız sonişleyici yeniden kurulur. Model yüklenmez, dikte kesilmez."""
        with self._load_lock:
            if self.engine is None:
                return  # model henüz yüklenmedi; yüklenirken güncel sözlüğü zaten okur
            try:
                post = self._build_post()
            except Exception:  # noqa: BLE001 (eski sözlükle devam edilir)
                log.exception("Sözlük yeniden yüklenemedi")
                return
            with self._lock:
                self.post = post
            log.info("Sözlük yenilendi")

    def _build_post(self) -> MedicalPostProcessor:
        lex_files = [BUILTIN_LEXICON, RADIOLOGY_LEXICON, USER_LEXICON]
        return MedicalPostProcessor.from_files(
            lex_files, [BUILTIN_CORRECTIONS, USER_CORRECTIONS],
            protected_files=[RADIOLOGY_KNOWN], general_files=[GENERAL_WORDS],
            use_itn=self.cfg.use_itn)

    def _load(self) -> None:
        self.stop_listening()
        self.on_state("loading")
        try:
            ensure_user_files()
            model = self.pick_model()
            lex_files = [BUILTIN_LEXICON, RADIOLOGY_LEXICON, USER_LEXICON]
            hw = None
            if self.cfg.use_hotwords and model.hotwords:
                hw = str(write_hotwords(lex_files, user_dir() / "hotwords.txt"))
            elif self.cfg.use_hotwords:
                log.info("Hotword bu modelde kapalı (model.json: hotwords=false)")
            engine = load_engine(model, num_threads=self.cfg.num_threads,
                                 hotwords_file=hw, hotwords_score=self.cfg.hotwords_score)
            post = self._build_post()
            with self._lock:
                self.model, self.engine, self.post = model, engine, post
            log.info("Model yüklendi: %s", model.name)
            self.on_state("idle")
        except Exception:
            log.exception("Model yüklenemedi")
            self.on_state("error")
            raise

    # ------------------------------------------------ dikte
    @property
    def listening(self) -> bool:
        return self._active.is_set()

    def toggle(self) -> None:
        if not self._toggle_lock.acquire(blocking=False):
            return  # önceki aç/kapa hâlâ sürüyor (ör. son ses çözülüyor)
        try:
            if self.listening:
                self.stop_listening()
            else:
                self.start_listening()
        finally:
            self._toggle_lock.release()

    def start_listening(self) -> None:
        if self.engine is None or self.listening:
            return
        self._stop.clear()
        self.last_error = ""
        self._active.set()
        self._thread = threading.Thread(target=self._run, name="dictation", daemon=True)
        self._thread.start()
        self.on_state("listening")

    def stop_listening(self) -> None:
        if not self.listening:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._active.clear()
        self.on_state("idle")

    def _finish_text(self, raw: str, confidences: list[tuple[str, float]] | None = None) -> str:
        if self.post:
            annotate = getattr(self.post, "annotate", None)
            spans = annotate(raw, confidences) if annotate else [(self.post(raw), "normal")]
        else:
            spans = [(raw, "normal")] if raw else []
        text = "".join(t for t, _ in spans)
        if text and self.cfg.add_trailing_space and not text.endswith(("\n", "• ")):
            text += " "
            spans = spans + [(" ", "normal")]
        self._last_spans = spans
        return text

    def _emit(self, parts: list[str], confidences: list[tuple[str, float]] | None = None) -> None:
        for raw in parts:
            text = self._finish_text(raw, confidences)
            log.debug("ham=%r -> %r", raw, text)
            try:
                if self._writer is not None:
                    self._writer.finalize(text)  # anlık yazılanı düzeltilmiş hâline getir
                elif text:
                    self.typer(text)
            except OSError:
                log.exception("Metin yazılamadı")
            if text:
                self.on_text(text)
                if self.on_segment:
                    try:
                        self.on_segment(self._last_spans)
                    except Exception:
                        log.exception("Vurgulama gösterilemedi")
                if self.on_scores:
                    try:
                        self.on_scores(self._word_scores(raw, confidences))
                    except Exception:
                        log.exception("Güven skorları gösterilemedi")

    def _word_scores(self, raw: str, confidences: list[tuple[str, float]] | None) -> list[WordScore]:
        if self.post:
            return self.post.word_scores(raw, confidences)
        if confidences:
            return [WordScore(w, w, c, "normal") for w, c in confidences]
        return [WordScore(w, w, None, "normal") for w in raw.split()]

    def _make_writer(self) -> LiveWriter | None:
        if not self.cfg.live_typing:
            return None
        return LiveWriter(self.typer, self.eraser, transform=self._live_transform)

    def _live_transform(self, text: str) -> str:
        """Anlık yazılan kelimeler de cümle sonundaki gibi sonişlenir."""
        return self.post(text) if self.post else text

    def _live(self, partial: str) -> None:
        if self._writer is not None:
            try:
                self._writer.update_partial(partial)
            except OSError:
                log.exception("Metin yazılamadı")

    def _run(self) -> None:
        with self._lock:
            engine = self.engine
        mic = Microphone(sample_rate=engine.sample_rate, device=configured_device(self.cfg))
        monitor = LevelMonitor(engine.sample_rate)
        warning = ""
        session = engine.new_session()
        self._writer = self._make_writer()
        try:
            try:
                mic.start()
            except Exception:
                self.last_error = MIC_OPEN_ERROR
                raise
            last_partial = ""
            warned = 0.0
            last_chunk_at = time.monotonic()
            while not self._stop.is_set():
                chunk = mic.read(timeout=0.2)
                backlog = mic.q.qsize()
                if backlog >= 5 and time.monotonic() - warned > 1.0:  # 100 ms'lik parçalar: ≥0,5 sn geride
                    warned = time.monotonic()
                    log.warning("işleme gecikmesi: %d ses parçası (%.1f sn) bekliyor", backlog, backlog / 10)
                if chunk is None:
                    new = "lost" if time.monotonic() - last_chunk_at > NO_DATA_S else monitor.warning
                else:
                    last_chunk_at = time.monotonic()
                    new = monitor.feed(chunk)
                if new != warning:
                    warning = new
                    if warning:
                        log.warning("mikrofon uyarısı: %s", warning)
                    else:
                        log.info("mikrofon uyarısı kalktı")
                    self._warn(warning)
                if chunk is not None:
                    self.on_level(level_fraction(chunk))  # ekrandaki nabız animasyonu
                    parts = session.accept(chunk)
                    self._emit(parts, session.word_confidences() if parts else None)
                    part = session.partial()
                    self._live(part)  # zamanla kararlılaşan kelimeler için her parçada çağrılır
                    if part != last_partial:
                        log.debug("kısmi: %r", part)
                        last_partial = part
                        self.on_partial(part)
            mic.stop()
            # durdurulmadan önce kuyruğa düşmüş sesi de işle
            while (chunk := mic.read(timeout=0)) is not None:
                parts = session.accept(chunk)
                self._emit(parts, session.word_confidences() if parts else None)
            flushed = session.flush()
            self._emit(flushed, session.word_confidences() if flushed else None)
            self.on_partial("")
        except Exception:
            log.exception("Dikte hatası")
            self.last_error = self.last_error or DICTATION_ERROR
            self.on_state("error")
        finally:
            mic.stop()
            if monitor.seconds:
                log.info(monitor.summary(getattr(mic, "overflows", 0)))
            if warning:
                self._warn("")
            self._active.clear()

    def _warn(self, key: str) -> None:
        try:
            self.on_warning(key)
        except Exception:  # noqa: BLE001 (uyarı gösterilemese de dikte sürer)
            log.exception("Mikrofon uyarısı gösterilemedi")
