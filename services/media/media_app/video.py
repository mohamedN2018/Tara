"""ffmpeg and ffprobe, hardened, for the video transcoder (roadmap 5.2).

Every run:

* reads only local files: the source is downloaded to a scratch dir first,
  ``-protocol_whitelist file`` stops ffmpeg opening anything else, and the
  demuxer is forced from the verified type, so a file cannot pose as an HLS
  playlist or an image sequence;
* gets an empty environment (no storage keys or other secrets), a lower CPU
  priority, an address-space limit and a wall-clock timeout;
* strips every metadata block (``-map_metadata -1``), so a phone's location,
  device and creation time never reach a viewer.

``VideoError`` carries the short failure code stored on the asset and sent in
``media.failed``.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import resource
import subprocess
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from . import validation

logger = logging.getLogger("tara.media.video")

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
PROBE_TIMEOUT = 60

# The ladder (short side of the picture, px) with its video and audio bitrates
# in kbit/s and the H.264 level announced in the master playlist.
LADDER = (
    (240, 400, 64, "4d401e"),
    (360, 800, 96, "4d401e"),
    (480, 1400, 128, "4d401e"),
    (720, 2800, 128, "4d401f"),
)
SEGMENT_SECONDS = 4
MP4_FALLBACK_HEIGHT = 480
POSTER_MAX = 720
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
# zscale linearises, tonemap maps the highlights, zscale goes back to BT.709.
TONEMAP = (
    "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
    "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"
)
SEGMENT_NAME = re.compile(r"^seg_\d{5}\.ts$")


class VideoError(Exception):
    """A file the pipeline refuses or cannot process; ``code`` is stored and sent."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


@dataclass(frozen=True)
class Probe:
    duration: float
    width: int  # as displayed (rotation applied)
    height: int
    fps: float
    has_audio: bool
    hdr: bool
    rotation: int

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)

    def as_meta(self) -> dict:
        return {
            "duration": round(self.duration, 3),
            "width": self.width,
            "height": self.height,
            "fps": round(self.fps, 3),
            "has_audio": self.has_audio,
            "hdr": self.hdr,
            "rotation": self.rotation,
        }

    @classmethod
    def from_meta(cls, meta: dict) -> Probe:
        return cls(
            duration=float(meta["duration"]),
            width=int(meta["width"]),
            height=int(meta["height"]),
            fps=float(meta.get("fps") or 30),
            has_audio=bool(meta.get("has_audio")),
            hdr=bool(meta.get("hdr")),
            rotation=int(meta.get("rotation") or 0),
        )


def _limits() -> None:  # pragma: no cover - runs in the child process
    os.nice(10)
    mb = settings.MEDIA_FFMPEG_MAX_MEMORY_MB
    if mb > 0:
        limit = mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(args: list[str], *, timeout: int, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run ffmpeg/ffprobe with no environment, limits and a timeout."""
    try:
        return subprocess.run(  # noqa: S603 - fixed binaries, no shell, list args
            args,
            cwd=cwd,
            # No secrets reach ffmpeg. Two malloc arenas keep its address space
            # (one 64 MB arena per thread otherwise) under the RLIMIT_AS cap.
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "MALLOC_ARENA_MAX": "2"},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            preexec_fn=_limits,  # noqa: PLW1509 - Celery prefork: no threads here
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoError("timeout", f"{Path(args[0]).name} took longer than {timeout}s") from exc


def _input_args(mime: str, *, decoder_threads: bool = True) -> list[str]:
    demuxer = validation.VIDEO_DEMUXERS.get(validation.normalize_mime(mime))
    if demuxer is None:
        raise VideoError("unsupported_type")
    # Decoder threads too, so one job stays within the container's 2 CPUs.
    threads = ["-threads", str(settings.MEDIA_FFMPEG_THREADS)] if decoder_threads else []
    return [*threads, "-protocol_whitelist", "file", "-f", demuxer]


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return int(round(float(side["rotation"]))) % 360
            except (TypeError, ValueError):
                return 0
    try:
        return int(stream.get("tags", {}).get("rotate", 0)) % 360
    except (TypeError, ValueError):
        return 0


def _fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(stream.get(key) or "0/0").partition("/")
        try:
            value = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if 0 < value < 1000:
            return value
    return 30.0


def _measured_duration(src: Path, mime: str) -> float:
    """Duration by reading every packet (WebM from a browser recorder has none
    in its header). A stream copy to nowhere, so it is fast."""
    result = run(
        [
            FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *_input_args(mime),
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "null",
            "-progress",
            "pipe:1",
            "-",
        ],
        timeout=PROBE_TIMEOUT * 5,
    )
    times = re.findall(rb"out_time_us=(\d+)", result.stdout)
    if result.returncode != 0 or not times:
        raise VideoError("unreadable", "the video could not be read")
    return int(times[-1]) / 1_000_000


def probe(src: Path, mime: str) -> Probe:
    result = run(
        [
            FFPROBE,
            "-v",
            "error",
            *_input_args(mime, decoder_threads=False),
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(src),
        ],
        timeout=PROBE_TIMEOUT,
    )
    if result.returncode != 0:
        raise VideoError("unreadable", "the file is not a video ffmpeg can read")
    try:
        info = json.loads(result.stdout or b"{}")
    except ValueError as exc:
        raise VideoError("unreadable") from exc
    streams = info.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video"
            and not (s.get("disposition") or {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise VideoError("no_video_stream", "the file has no video track")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise VideoError("unreadable", "the video has no picture size")
    if width * height > settings.MEDIA_VIDEO_MAX_PIXELS:
        raise VideoError("dimensions_too_large", f"{width}x{height} is too large")
    rotation = _rotation(video)
    if rotation in (90, 270):
        width, height = height, width
    duration = 0.0
    for raw in ((info.get("format") or {}).get("duration"), video.get("duration")):
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            break
    if duration <= 0:
        duration = _measured_duration(src, mime)
    return Probe(
        duration=duration,
        width=width,
        height=height,
        fps=_fps(video),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        hdr=str(video.get("color_transfer") or "") in HDR_TRANSFERS,
        rotation=rotation,
    )


@functools.lru_cache(maxsize=1)
def has_zscale() -> bool:
    try:
        result = run([FFMPEG, "-hide_banner", "-filters"], timeout=PROBE_TIMEOUT)
    except VideoError:
        return False
    return b" zscale " in result.stdout


def check_source(p: Probe, max_seconds: int) -> None:
    """Refuse what the pipeline will not process, with its failure code."""
    if p.duration > max_seconds + 0.5:
        raise VideoError("too_long", f"{p.duration:.1f}s is over the {max_seconds}s limit")
    if p.hdr and (settings.MEDIA_VIDEO_HDR_MODE != "tonemap" or not has_zscale()):
        raise VideoError("hdr_unsupported", "HDR video cannot be converted here")


def ladder(p: Probe) -> list[int]:
    """Rungs no taller than the source (never upscaled) nor the configured cap.

    A source smaller than the lowest rung gets one rendition at its own size.
    """
    cap = min(p.short_side, settings.MEDIA_VIDEO_MAX_HEIGHT)
    rungs = [r[0] for r in LADDER if r[0] <= cap]
    return rungs or [_even(p.short_side)]


def _even(n: int) -> int:
    return max(2, n - n % 2)


def rung_spec(rung: int) -> tuple[int, int, str]:
    """(video kbit/s, audio kbit/s, H.264 level) for a rung (or the nearest below)."""
    best = LADDER[0]
    for spec in LADDER:
        if spec[0] <= rung:
            best = spec
    return best[1], best[2], best[3]


def output_size(p: Probe, rung: int) -> tuple[int, int]:
    """The picture size of a rung: the short side is ``rung``, the other keeps the ratio."""
    if p.width >= p.height:
        return _even(round(p.width * rung / p.height)), rung
    return rung, _even(round(p.height * rung / p.width))


def _filters(p: Probe, rung: int) -> str:
    chain = [TONEMAP] if p.hdr else []
    if p.fps > settings.MEDIA_VIDEO_MAX_FPS:
        chain.append(f"fps={settings.MEDIA_VIDEO_MAX_FPS}")
    width, height = output_size(p, rung)
    chain += [f"scale={width}:{height}:flags=bicubic", "setsar=1", "format=yuv420p"]
    return ",".join(chain)


def _encode_args(p: Probe, rung: int, max_seconds: int) -> list[str]:
    video_kbps, audio_kbps, _ = rung_spec(rung)
    args = [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-sn",
        "-dn",
        "-vf",
        _filters(p, rung),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-profile:v",
        "main",
        "-crf",
        "23",
        "-maxrate",
        f"{video_kbps}k",
        "-bufsize",
        f"{video_kbps * 2}k",
        "-force_key_frames",
        f"expr:gte(t,n_forced*{SEGMENT_SECONDS / 2})",
        "-threads",
        str(settings.MEDIA_FFMPEG_THREADS),
        "-t",
        str(max_seconds + 1),
    ]
    if p.has_audio:
        args += ["-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2", "-ar", "48000"]
    return args


def _ffmpeg(src: Path, mime: str, out_args: list[str], *, cwd: Path, step: str) -> None:
    result = run(
        [
            FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *_input_args(mime),
            "-i",
            str(src),
            *out_args,
        ],
        timeout=settings.MEDIA_TRANSCODE_STEP_TIMEOUT,
        cwd=cwd,
    )
    if result.returncode != 0:
        logger.warning(
            "ffmpeg failed",
            extra={"step": step, "stderr": result.stderr[-2000:].decode("utf-8", "replace")},
        )
        raise VideoError("transcode_failed", f"ffmpeg could not make the {step}")


def hls_rendition(src: Path, mime: str, p: Probe, rung: int, out: Path, max_seconds: int) -> str:
    """Encode one HLS rendition into ``out``; returns its playlist text."""
    out.mkdir(parents=True, exist_ok=True)
    _ffmpeg(
        src,
        mime,
        [
            *_encode_args(p, rung, max_seconds),
            "-f",
            "hls",
            "-hls_time",
            str(SEGMENT_SECONDS),
            "-hls_playlist_type",
            "vod",
            "-hls_flags",
            "independent_segments",
            "-hls_segment_type",
            "mpegts",
            "-hls_segment_filename",
            "seg_%05d.ts",
            "index.m3u8",
        ],
        cwd=out,
        step=f"{rung}p rendition",
    )
    manifest = (out / "index.m3u8").read_text(encoding="utf-8")
    segments = [ln for ln in manifest.splitlines() if ln and not ln.startswith("#")]
    if not segments or not all(SEGMENT_NAME.match(s) for s in segments):
        raise VideoError("transcode_failed", "the rendition has no usable segments")
    return manifest


def mp4_fallback(src: Path, mime: str, p: Probe, out: Path, max_seconds: int) -> tuple[Path, int]:
    """A faststart MP4 at 480p (or the source's size when smaller)."""
    rung = min(MP4_FALLBACK_HEIGHT, ladder(p)[-1])
    out.mkdir(parents=True, exist_ok=True)
    target = out / "video.mp4"
    _ffmpeg(
        src,
        mime,
        [*_encode_args(p, rung, max_seconds), "-movflags", "+faststart", "-f", "mp4", target.name],
        cwd=out,
        step="MP4 fallback",
    )
    return target, rung


def poster(src: Path, mime: str, p: Probe, out: Path) -> Path:
    """One JPEG frame (a second in, or a third of a short clip), at most 720 px tall."""
    out.mkdir(parents=True, exist_ok=True)
    target = out / "poster.jpg"
    at = min(1.0, p.duration / 3)
    rung = min(POSTER_MAX, p.short_side)
    width, height = output_size(p, _even(rung))
    chain = ([TONEMAP] if p.hdr else []) + [
        f"scale={width}:{height}",
        "setsar=1",
        "format=yuvj420p",
    ]
    result = run(
        [
            FFMPEG,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{at:.3f}",
            *_input_args(mime),
            "-i",
            str(src),
            "-map",
            "0:v:0",
            "-map_metadata",
            "-1",
            "-frames:v",
            "1",
            "-vf",
            ",".join(chain),
            "-q:v",
            "3",
            target.name,
        ],
        timeout=settings.MEDIA_TRANSCODE_STEP_TIMEOUT,
        cwd=out,
    )
    if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        raise VideoError("transcode_failed", "ffmpeg could not make the poster")
    return target


def segment_names(manifest: str) -> list[str]:
    return [ln for ln in manifest.splitlines() if SEGMENT_NAME.match(ln)]


def codecs(rung: int, has_audio: bool) -> str:
    level = rung_spec(rung)[2]
    return f"avc1.{level},mp4a.40.2" if has_audio else f"avc1.{level}"
