"""Single-video editing orchestrator with explicit arguments.

1. synthesize the voice-over (one injected TTS call) to learn the duration;
2. assemble a random B-roll track of ``voice + margin_final`` seconds;
3. overlay subtitle clips built by an injected factory;
4. mix the voice over the (optionally kept) original audio;
5. append the end card, write ``<name>.mp4`` (+ optional ``.srt``).

There are no module globals: every setting travels in
:class:`PipelineConfig` or as an explicit argument, and ``moviepy`` is
imported lazily inside :func:`edit_video`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from .broll import BrollConfig, BrollSelector
from .endcard import EndcardConfig, build_endcard
from .subtitles import write_srt

logger = logging.getLogger(__name__)

#: A word stamp: (text, start_seconds, end_seconds).
WordStamp = tuple[str, float, float]

#: An SRT row: (start_seconds, end_seconds, text).
SrtEntry = tuple[float, float, str]

#: Synthesize ``text`` into ``audio_path``; return (word stamps, duration).
TtsCallable = Callable[[str, Path], tuple[list[WordStamp], float]]

#: Build overlay clips for one script block:
#: ``(words, video_width, video_height, font_path) -> clips``.
SubtitleFactory = Callable[[list[WordStamp], int, int, Path], list[Any]]


@dataclass(frozen=True)
class PipelineConfig:
    """Settings for :func:`edit_video`."""

    output_dir: Path
    bricks_dir: Path
    margin_final: float = 1.0
    speed_min: float = 0.95
    speed_max: float = 1.05
    min_fragment: float = 1.0
    generate_srt: bool = True
    original_volume: float = 0.0
    fps: int = 24
    threads: int = 4
    bricks_already_cropped: bool = True
    seed: int | None = None
    endcard: EndcardConfig = field(default_factory=EndcardConfig)

    def broll_config(self) -> BrollConfig:
        """Derive the :class:`BrollConfig` for this pipeline run."""
        return BrollConfig(
            bricks_dir=self.bricks_dir,
            speed_min=self.speed_min,
            speed_max=self.speed_max,
            min_fragment=self.min_fragment,
        )


def _close_quietly(clip: Any | None) -> None:
    if clip is None:
        return
    try:
        clip.close()
    except Exception:
        pass


class _MoviepyProgress:
    """Minimal proglog-compatible logger forwarding encode progress.

    Maps encode fraction ``f`` (0..1) to overall ``50 + 45*f`` so the
    UI bar moves 50->95 during ``write_videofile``.
    """

    def __init__(
        self, on_progress: Callable[[str, float], None] | None = None
    ) -> None:
        self._on_progress = on_progress

    @staticmethod
    def encode_pct(fraction: float) -> float:
        try:
            f = float(fraction)
        except Exception:
            return 50.0
        if f != f:  # NaN
            return 50.0
        if f < 0:
            f = 0.0
        if f > 1:
            f = 1.0
        return 50.0 + 45.0 * f

    def _report(self, fraction: float) -> None:
        if self._on_progress is None:
            return
        try:
            self._on_progress("encode", self.encode_pct(fraction))
        except Exception:
            pass

    def iter_bar(self, *args, **kwargs):
        iterable = None
        total = None
        for key in ("total", "n_total", "length", "n", "size"):
            if key in kwargs:
                try:
                    total = float(kwargs[key])
                    break
                except Exception:
                    continue
        if args:
            candidate = args[0]
            if candidate is not None and not isinstance(candidate, (str, bytes)):
                try:
                    iter(candidate)
                    iterable = candidate
                except Exception:
                    iterable = None
        if iterable is None:
            for value in kwargs.values():
                if value is None or isinstance(
                    value, (str, bytes, int, float, bool)
                ):
                    continue
                try:
                    iter(value)
                    iterable = value
                    break
                except Exception:
                    continue
        if iterable is None:
            return
            yield  # pragma: no cover - makes this a generator
        if total is None:
            try:
                total = float(len(iterable))  # type: ignore[arg-type]
            except Exception:
                total = None
        try:
            total_f = float(total) if total else 0.0
        except Exception:
            total_f = 0.0
        done = 0
        for item in iterable:
            yield item
            done += 1
            if total_f > 0:
                self._report(done / total_f)

    def __call__(self, *args, **kwargs):
        return None

    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)

        def _noop(*args, **kwargs):
            return None

        return _noop


def edit_video(
    name: str,
    lines: Sequence[str],
    font_path: str | Path,
    tmp_dir: str | Path,
    *,
    config: PipelineConfig,
    synthesize_speech: TtsCallable | None = None,
    subtitle_overlays: SubtitleFactory | None = None,
    crop_fn: Callable[[Any], Any] | None = None,
    instructions: str = "",
    fallback_path: str | Path | None = None,
    on_progress: Callable[[str, float], None] | None = None,
) -> bool:
    """Edit a single reel; return ``True`` on success.

    Args:
        name: Output basename (``<name>.mp4`` under ``config.output_dir``).
        lines: Script blocks; ``[bracketed]`` direction lines are skipped by
            the default flow (callers may pre-filter instead).
        font_path: Subtitle font file used by ``subtitle_overlays``.
        tmp_dir: Scratch directory for the synthesized voice file.
        config: All pipeline settings (no globals are read).
        synthesize_speech: TTS provider hook; required.
        subtitle_overlays: Factory for burned-in subtitle clips; when
            ``None`` the video is rendered without subtitle overlays
            (the ``.srt`` sidecar is still written when enabled).
        crop_fn: Applied to the B-roll when the bricks are *not* already
            cropped (``bricks_already_cropped=False``).
        instructions: Voice-direction hint forwarded to providers that
            support it (ignored otherwise).
        fallback_path: Fallback background video used only when B-roll
            assembly fails and the path exists.
        on_progress: Optional ``(stage, pct)`` callback where ``pct`` is
            0-100. Never raises (calls are guarded).
    """
    def _emit(stage: str, pct: float) -> None:
        if on_progress is None:
            return
        try:
            on_progress(stage, float(pct))
        except Exception:
            pass

    _ = instructions  # documented for providers; consumed by the TTS hook
    script = [line.strip() for line in lines if line.strip()]
    if not script:
        logger.warning("%s: empty script, skipped.", name)
        return False
    # Voice-direction lines are never narrated: drop them before TTS so
    # the synthesized words line up 1:1 with the subtitled blocks.
    narratable = [
        block
        for block in script
        if not (block.startswith("[") and block.endswith("]"))
    ]
    if not narratable:
        logger.warning("%s: empty script, skipped.", name)
        return False
    if synthesize_speech is None:
        logger.error("%s: no TTS provider was injected.", name)
        return False

    from moviepy.editor import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        VideoFileClip,
    )

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{name}.mp4"
    scratch = Path(tmp_dir)
    scratch.mkdir(parents=True, exist_ok=True)

    video_original: Any | None = None
    broll_raw: Any | None = None
    broll_opened: list[Any] = []
    video: Any | None = None
    final: Any | None = None
    voice_track: Any | None = None
    endcard: Any | None = None

    try:
        # --- 1) Voice-over first: its duration sets the video target. ---
        full_text = " ".join(narratable)
        # WAV: OpenRouter returns raw PCM wrapped as WAV, so request the
        # real container upfront (an .mp3 request never materializes).
        audio_path = scratch / f"{name}_full.wav"
        logger.info("TTS (openrouter, 1 call, %d blocks).", len(narratable))
        words, voice_dur = synthesize_speech(full_text, audio_path)
        if voice_dur <= 0 or not audio_path.exists():
            logger.error("%s: TTS failed, cannot size the B-roll.", name)
            return False
        target_dur = voice_dur + config.margin_final
        usable_dur = voice_dur
        logger.info(
            "Voice: %.2fs -> video target: %.2fs (+%.1fs margin).",
            voice_dur,
            target_dur,
            config.margin_final,
        )
        _emit("voice", 5)

        # --- 2) Random B-roll (optionally cropped when bricks are raw). ---
        try:
            selector = BrollSelector(config.broll_config())
            broll_raw, broll_opened, _sel = selector.build_broll(
                target_dur, seed=config.seed
            )
            if config.bricks_already_cropped or crop_fn is None:
                video = broll_raw
            else:
                video = crop_fn(broll_raw)
        except Exception as exc:
            logger.warning("B-roll failed (%s), trying fallback.", str(exc)[:200])
            broll_raw = None
            if fallback_path is not None and Path(fallback_path).exists():
                video_original = VideoFileClip(str(fallback_path))
                video = crop_fn(video_original) if crop_fn is not None else video_original
                usable_dur = min(voice_dur, float(video.duration))
                target_dur = float(video.duration)
            else:
                logger.error("%s: no bricks and no fallback video.", name)
                return False
        _emit("b-roll", 30)

        # --- 3) Subtitles, distributing word stamps across script blocks. ---
        subtitle_layers: list[Any] = []
        srt_entries: list[SrtEntry] = []
        if subtitle_overlays is not None:
            cursor = 0
            font = Path(font_path)
            for block in narratable:
                count = len(block.split())
                block_words = words[cursor : cursor + count]
                cursor += count
                kept = [
                    (text, start, min(end, usable_dur))
                    for text, start, end in block_words
                    if start < usable_dur and min(end, usable_dur) > start
                ]
                if not kept:
                    continue
                srt_entries.append((kept[0][1], kept[-1][2], block))
                built = subtitle_overlays(kept, int(video.w), int(video.h), font)
                if built:
                    subtitle_layers.extend(built)
            logger.info("Subtitles: %d overlay clips.", len(subtitle_layers))
        else:
            # Still produce the sidecar from whole-block timing when the
            # word stamps allow a trivial even split.
            if config.generate_srt and words:
                span = usable_dur / max(len(narratable), 1)
                srt_entries = [
                    (i * span, min((i + 1) * span, usable_dur), block)
                    for i, block in enumerate(narratable)
                ]
        _emit("subtitles", 50)

        # --- 4) Audio: optional original bed + trimmed voice with fade-out. ---
        audio_tracks: list[Any] = []
        try:
            original_audio = video.audio
        except Exception:
            original_audio = None
        if original_audio is not None and config.original_volume > 0:
            audio_tracks.append(original_audio.volumex(config.original_volume))
        if audio_path.exists():
            voice = AudioFileClip(str(audio_path))
            if voice.duration > usable_dur:
                voice = voice.subclip(0, usable_dur)
            try:
                if words:
                    last_end = max(e for _, _, e in words if e <= usable_dur + 0.01)
                    cut = min(voice.duration, last_end + 0.20)
                    if cut < voice.duration - 0.05 and cut > 0.5:
                        voice = voice.subclip(0, cut)
            except Exception:
                pass
            try:
                from moviepy.audio.fx.audio_fadeout import audio_fadeout

                voice = voice.fx(audio_fadeout, min(0.3, voice.duration / 2))
            except Exception:
                pass
            voice = voice.set_start(0)
            voice_track = voice
            audio_tracks.append(voice)

        final = CompositeVideoClip(
            [video] + subtitle_layers, size=(video.w, video.h)
        )

        # --- 5) End card over the closing seconds (does not extend video). ---
        try:
            video_dur = float(video.duration)
            end_cfg = config.endcard
            if end_cfg.active and video_dur > end_cfg.duration + 0.5:
                endcard = build_endcard(int(video.w), int(video.h), None, end_cfg)
                if endcard is not None:
                    final = CompositeVideoClip(
                        [final, endcard.set_start(video_dur - end_cfg.duration)],
                        size=(video.w, video.h),
                    ).set_duration(video_dur)
                    logger.info(
                        "End card: fade to black + logo, last %.1fs.",
                        end_cfg.duration,
                    )
        except Exception as exc:
            logger.warning("End card failed (%s), continuing.", str(exc)[:150])

        try:
            if config.endcard.fade_out > 0:
                final = final.fadeout(config.endcard.fade_out)
        except Exception:
            pass

        if audio_tracks:
            final = final.set_audio(CompositeAudioClip(audio_tracks))
        else:
            final = final.without_audio()

        final.write_videofile(
            str(out_path),
            codec="libx264",
            audio_codec="aac",
            fps=config.fps,
            preset="ultrafast",
            threads=config.threads,
            logger=_MoviepyProgress(on_progress) if on_progress is not None else None,
        )

        if config.generate_srt:
            write_srt(srt_entries, output_dir / f"{name}.srt")

        logger.info(
            "B-roll %.2fs / voice %.2fs / margin %.2fs.",
            float(video.duration),
            usable_dur,
            float(video.duration) - usable_dur,
        )
        _emit("finalize", 100)
        return True

    except Exception as exc:
        logger.error("Edit failed: %s", exc)
        logger.debug("Traceback:", exc_info=True)
        return False
    finally:
        _close_quietly(final)
        _close_quietly(voice_track)
        _close_quietly(broll_raw)
        for clip in broll_opened:
            _close_quietly(clip)
        _close_quietly(video_original)
        _close_quietly(endcard)
