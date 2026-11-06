"""Ses çalar ve test sayfasındaki düğmeleri: çal, duraklat, kaldığı yerden devam et, durdur."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import sounddevice as sd  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtGui import QHideEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app import testbench  # noqa: E402
from app.audio import AudioPlayer  # noqa: E402


class FakeStream:
    """Ses aygıtı olmadan sounddevice.OutputStream: pull() aygıtın örnek istemesini taklit eder."""
    instances = []
    latency = 0.0

    def __init__(self, samplerate, channels, dtype, callback, finished_callback):
        self.samplerate, self.channels, self.dtype = samplerate, channels, dtype
        self.callback, self.finished_callback = callback, finished_callback
        self.started = self.aborted = self.closed = False
        FakeStream.instances.append(self)

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True
        self.finished_callback()  # gerçek akış da durdurulunca bunu çağırır

    def close(self):
        self.closed = True

    def pull(self, frames):
        out = np.full((frames, 1), 9.0, dtype=np.float32)
        self.callback(out, frames, None, None)
        return out[:, 0].tolist()


@pytest.fixture(autouse=True)
def fake_stream(monkeypatch):
    FakeStream.instances = []
    monkeypatch.setattr(FakeStream, "latency", 0.0)
    monkeypatch.setattr(sd, "OutputStream", FakeStream)


def _ramp(n=10):
    return np.arange(1, n + 1, dtype=np.float32) / 100


def _player(n=10, sr=16000, on_finished=None):
    p = AudioPlayer(on_finished=on_finished)
    p.load(_ramp(n), sr)
    return p


def _reach_end(stream, frames=5):
    with pytest.raises(sd.CallbackStop):
        stream.pull(frames)
    stream.finished_callback()


def test_play_opens_mono_float_stream_at_audio_rate():
    p = _player(sr=8000)
    p.play()
    s = FakeStream.instances[0]
    assert (s.samplerate, s.channels, s.dtype, s.started) == (8000, 1, "float32", True)
    assert p.is_playing and not p.is_paused


def test_playback_delivers_samples_in_order():
    p = _player()
    p.play()
    s = FakeStream.instances[0]
    assert s.pull(3) == pytest.approx([0.01, 0.02, 0.03])
    assert s.pull(2) == pytest.approx([0.04, 0.05])


def test_pause_closes_stream_and_reports_paused():
    p = _player()
    p.play()
    s = FakeStream.instances[0]
    s.pull(4)
    p.pause()
    assert s.aborted and s.closed
    assert p.is_paused and not p.is_playing


def test_resume_continues_where_it_stopped():
    p = _player()
    p.play()
    FakeStream.instances[0].pull(4)
    p.pause()
    p.play()
    assert len(FakeStream.instances) == 2
    assert FakeStream.instances[1].pull(2) == pytest.approx([0.05, 0.06])


def test_pause_rewinds_samples_the_device_had_not_played_yet():
    """Aygıt tamponundaki ses duraklatınca kaybolur; devam edince o bölüm atlanmamalı."""
    FakeStream.latency = 0.002
    p = _player(sr=1000)
    p.play()
    FakeStream.instances[0].pull(5)
    p.pause()
    p.play()
    assert FakeStream.instances[1].pull(1) == pytest.approx([0.04])


def test_rewind_never_goes_before_the_start():
    FakeStream.latency = 1.0
    p = _player(sr=1000)
    p.play()
    FakeStream.instances[0].pull(2)
    p.pause()
    p.play()
    assert FakeStream.instances[1].pull(1) == pytest.approx([0.01])


def test_end_of_audio_fills_silence_stops_and_notifies():
    ended = []
    p = _player(3, on_finished=lambda: ended.append(True))
    p.play()
    s = FakeStream.instances[0]
    out = np.full((5, 1), 9.0, dtype=np.float32)
    with pytest.raises(sd.CallbackStop):
        s.callback(out, 5, None, None)
    assert out[:, 0].tolist() == pytest.approx([0.01, 0.02, 0.03, 0, 0])
    s.finished_callback()
    assert ended == [True]


def test_pausing_does_not_report_end_of_audio():
    ended = []
    p = _player(on_finished=lambda: ended.append(True))
    p.play()
    FakeStream.instances[0].pull(2)
    p.pause()
    assert ended == []


def test_finish_closes_stream_and_rewinds_after_end():
    p = _player(3)
    p.play()
    s = FakeStream.instances[0]
    _reach_end(s)
    p.finish()
    assert s.closed and not p.is_playing and not p.is_paused
    p.play()
    assert FakeStream.instances[1].pull(1) == pytest.approx([0.01])


def test_late_end_notice_does_not_disturb_a_paused_player():
    """Ses bittiği an duraklat'a basılırsa kuyruktaki bitiş bildirimi duraklatmayı bozmamalı."""
    FakeStream.latency = 0.001
    p = _player(3, sr=1000)
    p.play()
    with pytest.raises(sd.CallbackStop):
        FakeStream.instances[0].pull(5)
    p.pause()
    p.finish()
    assert p.is_paused


def test_stop_rewinds_and_next_play_starts_from_beginning():
    p = _player()
    p.play()
    FakeStream.instances[0].pull(5)
    p.stop()
    assert not p.is_playing and not p.is_paused
    p.play()
    assert FakeStream.instances[1].pull(1) == pytest.approx([0.01])


def test_loading_new_audio_stops_current_playback():
    p = _player()
    p.play()
    p.load(_ramp(4), 8000)
    assert FakeStream.instances[0].closed and not p.is_playing and not p.is_paused
    p.play()
    assert FakeStream.instances[1].samplerate == 8000


def test_commands_without_audio_do_nothing():
    p = AudioPlayer()
    p.pause()
    p.stop()
    p.finish()
    p.play()
    assert FakeStream.instances == [] and not p.is_playing


def test_second_play_while_playing_does_not_open_another_stream():
    p = _player()
    p.play()
    p.play()
    assert len(FakeStream.instances) == 1


def test_failed_start_leaves_player_stopped_and_stream_closed(monkeypatch):
    def broken(self):
        raise sd.PortAudioError("aygıt yok")
    monkeypatch.setattr(FakeStream, "start", broken)
    p = _player()
    with pytest.raises(sd.PortAudioError):
        p.play()
    assert FakeStream.instances[0].closed and not p.is_playing


def test_closing_error_is_not_raised(monkeypatch):
    def broken(self):
        raise sd.PortAudioError("aygıt çıkarıldı")
    monkeypatch.setattr(FakeStream, "abort", broken)
    p = _player()
    p.play()
    p.stop()
    assert not p.is_playing


# ------------------------------------------------------------ test sayfasındaki düğmeler
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(qapp):
    p = testbench.TestPage(lambda: (None, None, False), [])
    yield p
    p.close()
    p.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _buttons(page):
    return page.btn_play.isEnabled(), page.btn_pause.isEnabled(), page.btn_stop.isEnabled(), page.btn_play.text()


def test_buttons_are_disabled_without_audio(page):
    assert _buttons(page) == (False, False, False, "Dinle")


def test_pause_and_stop_buttons_have_icons(page):
    assert not page.btn_pause.icon().isNull()
    assert not page.btn_stop.icon().isNull()


def test_buttons_follow_play_pause_resume(page):
    page._set_audio(_ramp(), 16000, "kayit.wav")
    assert _buttons(page) == (True, False, False, "Dinle")
    page.btn_play.click()
    assert _buttons(page) == (False, True, True, "Dinle")
    FakeStream.instances[0].pull(4)
    page.btn_pause.click()
    assert _buttons(page) == (True, False, True, "Devam et")
    page.btn_play.click()
    assert _buttons(page) == (False, True, True, "Dinle")
    assert FakeStream.instances[1].pull(1) == pytest.approx([0.05])


def test_stop_button_returns_to_the_beginning(page):
    page._set_audio(_ramp(), 16000, "kayit.wav")
    page.btn_play.click()
    FakeStream.instances[0].pull(4)
    page.btn_pause.click()
    page.btn_stop.click()
    assert _buttons(page) == (True, False, False, "Dinle")
    page.btn_play.click()
    assert FakeStream.instances[1].pull(1) == pytest.approx([0.01])


def test_buttons_reset_when_audio_ends(page):
    page._set_audio(_ramp(3), 16000, "kayit.wav")
    page.btn_play.click()
    s = FakeStream.instances[0]
    _reach_end(s)
    QCoreApplication.processEvents()
    assert _buttons(page) == (True, False, False, "Dinle")
    assert s.closed


def test_new_audio_resets_paused_state(page):
    page._set_audio(_ramp(), 16000, "bir.wav")
    page.btn_play.click()
    FakeStream.instances[0].pull(2)
    page.btn_pause.click()
    page._set_audio(_ramp(4), 16000, "iki.wav")
    assert _buttons(page) == (True, False, False, "Dinle")


def test_leaving_page_pauses_playback(page):
    page.show()
    page._set_audio(_ramp(), 16000, "kayit.wav")
    page.btn_play.click()
    FakeStream.instances[0].pull(2)
    page.hide()
    assert FakeStream.instances[0].closed
    assert _buttons(page) == (True, False, True, "Devam et")


def test_minimizing_keeps_playing(page):
    page._set_audio(_ramp(), 16000, "kayit.wav")
    page.btn_play.click()
    event = QHideEvent()
    event.spontaneous = lambda: True
    page.hideEvent(event)
    assert page.player.is_playing


def test_recording_stops_playback_and_blocks_listening(page, monkeypatch):
    class FakeInput:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(sd, "InputStream", FakeInput)
    page._set_audio(_ramp(), 16000, "kayit.wav")
    page.btn_play.click()
    page._toggle_record()
    assert not page.player.is_playing
    assert _buttons(page) == (False, False, False, "Dinle")
    page._toggle_record()
    assert _buttons(page) == (True, False, False, "Dinle")


def test_playback_failure_is_shown_and_keeps_results(page, monkeypatch):
    def broken(*a, **k):
        raise sd.PortAudioError("aygıt yok")
    monkeypatch.setattr(sd, "OutputStream", broken)
    page._set_audio(_ramp(), 16000, "kayit.wav")
    page.diff.setPlainText("önceki sonuç")
    page.btn_play.click()
    assert "Ses çalınamadı" in page.file_label.text()
    assert page.diff.toPlainText() == "önceki sonuç"
    assert _buttons(page) == (True, False, False, "Dinle")


def test_long_file_name_does_not_widen_the_page(page):
    page._set_audio(_ramp(), 16000, "a.wav")
    width = page.minimumSizeHint().width()
    name = "radyoloji_raporu_" * 12 + ".mp4"
    page._set_audio(_ramp(), 16000, name)
    assert page.minimumSizeHint().width() == width
    assert name in page.file_label.toolTip()
