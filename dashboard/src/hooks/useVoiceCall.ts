import { useCallback, useRef, useState } from 'react';
import { calls } from '../services/api';

export type CallStatus = 'idle' | 'requesting' | 'waiting' | 'connecting' | 'active' | 'error';

const RATE = 16000;

const WORKLET_SRC = `
class Capture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = []; this.ratio = sampleRate / ${RATE}; this.pos = 0; }
  process(inputs) {
    const ch = inputs[0][0]; if (!ch) return true;
    for (; this.pos < ch.length; this.pos += this.ratio) {
      const i = Math.floor(this.pos), j = Math.min(ch.length, Math.floor(this.pos + this.ratio));
      let s = 0; for (let k = i; k < j; k++) s += ch[k];
      this.buf.push(s / Math.max(1, j - i));
    }
    this.pos -= ch.length;
    if (this.buf.length >= 320) {
      const out = new Int16Array(this.buf.length);
      for (let k = 0; k < out.length; k++) out[k] = Math.max(-1, Math.min(1, this.buf[k])) * 32767;
      this.port.postMessage(out.buffer, [out.buffer]); this.buf = [];
    }
    return true;
  }
}
registerProcessor('capture', Capture);`;

export interface VoiceCallHook {
  status: CallStatus;
  sessionId: string | null;
  error: string | null;
  micLevel: number;
  start: (agentId: string) => Promise<void>;
  stop: () => void;
}

export function useVoiceCall(): VoiceCallHook {
  const [status, setStatus] = useState<CallStatus>('idle');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [micLevel, setMicLevel] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const playTimeRef = useRef(0);
  const playingRef = useRef<Set<AudioBufferSourceNode>>(new Set());

  const cleanup = useCallback(() => {
    streamRef.current?.getTracks().forEach(t => t.stop());
    ctxRef.current?.close();
    wsRef.current?.close();
    wsRef.current = null;
    ctxRef.current = null;
    nodeRef.current = null;
    streamRef.current = null;
    playTimeRef.current = 0;
    playingRef.current.clear();
    setMicLevel(0);
  }, []);

  const stop = useCallback(() => {
    if (sessionId) {
      calls.end(sessionId).catch(() => {});
    }
    cleanup();
    setStatus('idle');
    setSessionId(null);
  }, [sessionId, cleanup]);

  const start = useCallback(async (agentId: string) => {
    try {
      setError(null);
      setStatus('requesting');

      const callData = await calls.startWeb(agentId);
      setSessionId(callData.session_id);
      setStatus('waiting');

      // Poll for worker URL
      let workerUrl = callData.worker_ws_url;
      if (!workerUrl) {
        const deadline = Date.now() + 15000;
        while (Date.now() < deadline) {
          const state = await calls.get(callData.session_id);
          if (state.worker_ws_url) { workerUrl = state.worker_ws_url; break; }
          if (state.status === 'failed' || state.status === 'ended') throw new Error('Call failed');
          await new Promise(r => setTimeout(r, 500));
        }
      }
      if (!workerUrl) throw new Error('Worker did not start in time');

      setStatus('connecting');

      // Mic access
      const micStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = micStream;

      const ctx = new AudioContext();
      ctxRef.current = ctx;
      const blob = new Blob([WORKLET_SRC], { type: 'text/javascript' });
      await ctx.audioWorklet.addModule(URL.createObjectURL(blob));
      const node = new AudioWorkletNode(ctx, 'capture');
      nodeRef.current = node;
      ctx.createMediaStreamSource(micStream).connect(node);

      // WS with retry
      let ws: WebSocket | null = null;
      for (let attempt = 1; attempt <= 5; attempt++) {
        const connected = await new Promise<boolean>(resolve => {
          const s = new WebSocket(workerUrl!);
          s.binaryType = 'arraybuffer';
          s.onopen = () => { ws = s; resolve(true); };
          s.onclose = () => resolve(false);
          s.onerror = () => {};
        });
        if (connected) break;
        if (attempt < 5) await new Promise(r => setTimeout(r, 1000));
      }
      if (!ws) throw new Error('Could not connect to worker');

      wsRef.current = ws;

      (ws as WebSocket).onmessage = (e: MessageEvent) => {
        if (typeof e.data === 'string') {
          const msg = JSON.parse(e.data);
          if (msg.type === 'clear') {
            playingRef.current.forEach(s => { try { s.stop(); } catch {} });
            playingRef.current.clear();
            playTimeRef.current = 0;
          }
        } else {
          // Play PCM audio
          const i16 = new Int16Array(e.data, 0, (e.data as ArrayBuffer).byteLength >> 1);
          const f32 = Float32Array.from(i16, v => v / 32768);
          const ab = ctx.createBuffer(1, f32.length, RATE);
          ab.copyToChannel(f32, 0);
          const src = ctx.createBufferSource();
          src.buffer = ab;
          src.connect(ctx.destination);
          const t = Math.max(ctx.currentTime + 0.05, playTimeRef.current);
          src.start(t);
          playTimeRef.current = t + ab.duration;
          playingRef.current.add(src);
          src.onended = () => playingRef.current.delete(src);
        }
      };

      (ws as WebSocket).onclose = () => {
        cleanup();
        setStatus('idle');
      };

      node.port.onmessage = (e: MessageEvent) => {
        if (wsRef.current?.readyState === 1) wsRef.current.send(e.data);
        const a = new Int16Array(e.data);
        let pk = 0;
        for (let i = 0; i < a.length; i += 8) pk = Math.max(pk, Math.abs(a[i]));
        setMicLevel(Math.min(100, pk / 200));
      };

      setStatus('active');
    } catch (err) {
      cleanup();
      setError(err instanceof Error ? err.message : 'Unknown error');
      setStatus('error');
    }
  }, [cleanup]);

  return { status, sessionId, error, micLevel, start, stop };
}
