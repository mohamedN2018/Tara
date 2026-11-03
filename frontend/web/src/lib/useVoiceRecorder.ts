import { onBeforeUnmount, ref } from "vue";

export interface VoiceNote {
  file: File;
  durationMs: number;
}

// Types the media service accepts for kind=voice, best first.
const CONTAINERS = [
  { mime: "audio/webm;codecs=opus", ext: "webm" },
  { mime: "audio/ogg;codecs=opus", ext: "ogg" },
  { mime: "audio/mp4", ext: "m4a" },
];
const MAX_SECONDS = 300;

export function pickContainer(supports: (mime: string) => boolean) {
  return CONTAINERS.find((c) => supports(c.mime)) ?? null;
}

/** Record from the microphone. `stop()` resolves with the note, `cancel()` drops it. */
export function useVoiceRecorder() {
  const recording = ref(false);
  const seconds = ref(0);
  const supported =
    typeof MediaRecorder !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

  let recorder: MediaRecorder | null = null;
  let stream: MediaStream | null = null;
  let ticker: number | undefined;
  let startedAt = 0;
  let resolveStop: ((note: VoiceNote | null) => void) | null = null;
  let chunks: Blob[] = [];

  function release() {
    window.clearInterval(ticker);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
    recorder = null;
    recording.value = false;
    seconds.value = 0;
  }

  async function start(): Promise<void> {
    const container = pickContainer((mime) => MediaRecorder.isTypeSupported(mime));
    if (!container) throw new Error("no supported audio format");
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    chunks = [];
    const active = new MediaRecorder(stream, { mimeType: container.mime });
    active.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    active.onstop = () => {
      const durationMs = Date.now() - startedAt;
      // The signed upload is for the bare type, without codec parameters.
      const type = container.mime.split(";")[0];
      const file = new File(chunks, `voice.${container.ext}`, { type });
      release();
      resolveStop?.(file.size ? { file, durationMs } : null);
      resolveStop = null;
    };
    recorder = active;
    active.start();
    startedAt = Date.now();
    recording.value = true;
    ticker = window.setInterval(() => {
      seconds.value = Math.floor((Date.now() - startedAt) / 1000);
      if (seconds.value >= MAX_SECONDS) active.stop();
    }, 250);
  }

  function stop(): Promise<VoiceNote | null> {
    if (!recorder || recorder.state === "inactive") return Promise.resolve(null);
    return new Promise((resolve) => {
      resolveStop = resolve;
      recorder?.stop();
    });
  }

  function cancel() {
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = release;
      recorder.stop();
    } else {
      release();
    }
  }

  onBeforeUnmount(cancel);

  return { supported, recording, seconds, start, stop, cancel };
}
