// Push-to-talk: hold a button (or the space bar) to record, release to send — like the voice button on a
// steering wheel. Audio goes to the server, which transcribes it with Whisper (Groq).

export class PushToTalk {
  constructor({ button, onAudio, onState }) {
    this.button = button;
    this.onAudio = onAudio;
    this.onState = onState || (() => {});
    this.recorder = null;
    this.chunks = [];
    this.stream = null;
    this.startedAt = 0;
    this.active = false;
    const down = (e) => { e.preventDefault(); this.start(); };
    const up = (e) => { e.preventDefault(); this.stop(); };
    button.addEventListener("pointerdown", down);
    button.addEventListener("pointerup", up);
    button.addEventListener("pointerleave", () => this.active && this.stop());
    button.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  get supported() { return Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder); }

  async start() {
    if (this.active || !this.supported) {
      if (!this.supported) this.onState("unsupported");
      return;
    }
    this.active = true;
    try {
      this.stream ||= await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (err) {
      this.active = false;
      this.onState("denied", err);
      return;
    }
    if (!this.active) return; // released before permission was granted
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]
      .find((m) => MediaRecorder.isTypeSupported(m)) || "";
    this.chunks = [];
    this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.recorder.onstop = () => {
      const duration = performance.now() - this.startedAt;
      const blob = new Blob(this.chunks, { type: this.recorder.mimeType || "audio/webm" });
      if (duration < 350 || blob.size < 1500) {
        this.onState("too-short");
        return;
      }
      this.onState("sending");
      this.onAudio(blob);
    };
    this.startedAt = performance.now();
    this.recorder.start();
    this.onState("recording");
  }

  stop() {
    if (!this.active) return;
    this.active = false;
    if (this.recorder && this.recorder.state === "recording") this.recorder.stop();
    else this.onState("idle");
  }
}
