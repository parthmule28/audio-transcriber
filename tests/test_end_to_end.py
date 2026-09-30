import base64
import hashlib
import json
import os
import socket
import subprocess
from pathlib import Path

import httpx
import pytest

from audio_transcriber import constants, pipeline as pipeline_module
from audio_transcriber.audio import (
    detect_quiet_midpoints,
    extract_chunk,
    probe,
    resolve_binary,
)
from audio_transcriber.chunking import plan_chunks
from audio_transcriber.openrouter_client import OpenRouterClient
from audio_transcriber.pipeline import TranscriptionPipeline
from audio_transcriber.workdir import AudioWorkspace


@pytest.mark.skipif(
    not os.environ.get("AUDIO_TRANSCRIBER_SAMPLE"),
    reason="set AUDIO_TRANSCRIBER_SAMPLE to a local media path",
)
def test_real_sample_runs_first_three_chunks_through_mocked_pipeline(
    tmp_path, monkeypatch,
):
    source = Path(os.environ["AUDIO_TRANSCRIBER_SAMPLE"]).expanduser()
    assert source.is_file(), f"AUDIO_TRANSCRIBER_SAMPLE is not a file: {source}"

    ffmpeg = resolve_binary("ffmpeg")
    ffprobe = resolve_binary("ffprobe")
    media = probe(source, ffprobe=ffprobe)
    assert media.has_audio
    assert media.duration > 0
    quiet_midpoints = detect_quiet_midpoints(
        source,
        noise_db=constants.SILENCE_NOISE_DB,
        min_duration=constants.SILENCE_MIN_DURATION,
        ffmpeg=ffmpeg,
    )
    spans = plan_chunks(media.duration, quiet_midpoints)
    assert len(spans) >= 3

    # Keep the real plan and pipeline path, but bound this opt-in smoke run to
    # three chunks rather than transcoding and submitting an entire recording.
    real_pipeline_plan_chunks = pipeline_module.plan_chunks

    def first_three_chunks(duration, quiet_points=()):
        planned = real_pipeline_plan_chunks(duration, quiet_points)
        assert duration == pytest.approx(media.duration)
        assert planned == spans
        return planned[:3]

    monkeypatch.setattr(pipeline_module, "plan_chunks", first_three_chunks)

    chunk_streams = {}
    chunk_hashes = {}
    real_extract_chunk = pipeline_module.extract_chunk

    def extract_and_probe_chunk(media_path, start, duration, out_path, *, ffmpeg=None):
        index = int(Path(out_path).stem.removeprefix("chunk_"))
        assert 0 <= index < 3
        assert start == pytest.approx(spans[index].start)
        assert duration == pytest.approx(spans[index].duration)

        extracted = real_extract_chunk(
            media_path, start, duration, out_path, ffmpeg=ffmpeg,
        )
        result = subprocess.run(
            [
                str(ffprobe), "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name,sample_rate,channels",
                "-of", "json", str(extracted),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        stream = json.loads(result.stdout)["streams"][0]
        chunk_streams[index] = stream
        chunk_hashes[hashlib.sha256(extracted.read_bytes()).hexdigest()] = index
        return extracted

    monkeypatch.setattr(pipeline_module, "extract_chunk", extract_and_probe_chunk)

    transcript_by_index = {
        0: "first mocked segment",
        1: "second mocked segment",
        2: "third mocked segment",
    }
    cost_by_index = {0: 0.001, 1: 0.002, 2: 0.003}
    requested_indices = []

    def mock_openrouter(request):
        assert request.url.scheme == "https"
        assert request.url.host == "openrouter.ai"
        assert request.url.path == "/api/v1/audio/transcriptions"
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test"

        payload = json.loads(request.content)
        assert payload["model"] == constants.DEFAULT_MODEL
        assert payload["input_audio"]["format"] == "wav"
        chunk_bytes = base64.b64decode(payload["input_audio"]["data"])
        digest = hashlib.sha256(chunk_bytes).hexdigest()
        assert digest in chunk_hashes, "request did not contain a locally extracted chunk"
        index = chunk_hashes[digest]
        requested_indices.append(index)
        return httpx.Response(
            200,
            json={
                "text": transcript_by_index[index],
                "usage": {"seconds": 1, "cost": cost_by_index[index]},
            },
        )

    def reject_network(*_args, **_kwargs):
        pytest.fail("the opt-in test attempted a non-mocked network connection")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)

    transport = httpx.MockTransport(mock_openrouter)
    with OpenRouterClient("sk-or-v1-test", transport=transport) as client:
        pipeline = TranscriptionPipeline(
            client,
            model=constants.DEFAULT_MODEL,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            workspace=AudioWorkspace(root=tmp_path),
            sleep_fn=lambda _delay: None,
        )
        report = pipeline.run(source)

    assert set(chunk_streams) == {0, 1, 2}
    for stream in chunk_streams.values():
        assert stream["codec_name"] == "pcm_s16le"
        assert stream["sample_rate"] == "16000"
        assert stream["channels"] == constants.CANONICAL_CHANNELS

    assert sorted(requested_indices) == [0, 1, 2]
    assert report.is_complete
    assert report.total_chunks == 3
    assert report.transcript() == (
        "first mocked segment second mocked segment third mocked segment"
    )
    assert report.total_cost() == pytest.approx(sum(cost_by_index.values()))
