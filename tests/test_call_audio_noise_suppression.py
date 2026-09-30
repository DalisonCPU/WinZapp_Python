"""Noise suppression and echo bookkeeping in the call's microphone path."""

import base64
import threading

import numpy as np

from core.call_audio import (
    CALL_FRAME_SAMPLES, CALL_SAMPLE_RATE, CallAudioConfig, CallAudioSession, _pcm16_bytes,
)
from tests.test_call_audio_session import _Socket, _wait_for


def test_noise_suppression_is_off_unless_configured():
    assert CallAudioSession(_Socket(), CallAudioConfig(session="s"))._noise_suppressor is None
    enabled = CallAudioSession(_Socket(), CallAudioConfig(session="s", noise_suppression=True))
    assert enabled._noise_suppressor is not None


def _send(noise_suppression):
    sio = _Socket()
    session = CallAudioSession(
        sio, CallAudioConfig(session="s", noise_suppression=noise_suppression))
    rng = np.random.default_rng(3)
    noise = (rng.standard_normal(CALL_SAMPLE_RATE * 4) * 0.02).astype(np.float32)
    thread = threading.Thread(target=session._send_microphone_loop, daemon=True)
    thread.start()
    for i in range(0, len(noise), CALL_FRAME_SAMPLES):
        session._mic_queue.put(_pcm16_bytes(noise[i:i + CALL_FRAME_SAMPLES]))
        _wait_for(lambda: session._mic_queue.qsize() == 0)
    session._stop_event.set()
    thread.join(timeout=2)
    sent = b"".join(base64.b64decode(event[1]["pcm"]) for event in sio.events)
    return np.frombuffer(sent, dtype="<i2").astype(np.float32) / 32768.0, noise


def test_send_loop_lowers_steady_noise_when_enabled():
    plain, noise = _send(False)
    suppressed, _ = _send(True)
    tail = slice(-CALL_SAMPLE_RATE, None)
    assert np.sqrt(np.mean(plain[tail] ** 2)) > 0.9 * np.sqrt(np.mean(noise[tail] ** 2))
    assert np.sqrt(np.mean(suppressed[tail] ** 2)) < 0.6 * np.sqrt(np.mean(plain[tail] ** 2))


def test_frames_dropped_for_latency_are_reported_to_the_echo_canceller():
    session = CallAudioSession(_Socket(), CallAudioConfig(session="s", echo_cancellation=True))
    skipped = []
    session._echo_canceller.skip_microphone = skipped.append
    # A backlog deeper than the target makes the sender drop the stale frames.
    for _ in range(6):
        session._mic_queue.put(_pcm16_bytes(np.zeros(CALL_FRAME_SAMPLES, dtype=np.float32)))
    thread = threading.Thread(target=session._send_microphone_loop, daemon=True)
    thread.start()
    _wait_for(lambda: session._mic_queue.qsize() == 0)
    session._stop_event.set()
    thread.join(timeout=2)
    assert skipped and skipped[0] % CALL_FRAME_SAMPLES == 0
