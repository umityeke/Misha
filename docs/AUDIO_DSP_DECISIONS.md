# Audio DSP decisions

Misha normalizes microphone recordings with a bounded RMS gain stage and can
resample mono float audio deterministically when a provider/device rate differs.
The gain stage never boosts digital silence or already-clipped input.

Streaming PCM has a bounded sequence-aware jitter buffer. It reorders packets,
starts only after a small prefill, drops late frames, and inserts one exact silence
frame for a missing packet or playback underrun. This keeps latency bounded and
makes every concealment observable through counters.

Noise suppression was evaluated but is intentionally not enabled in the first
release: spectral gates damaged Turkish consonants and a bundled neural suppressor
would materially increase package size and CPU use. Energy calibration, VAD and
bounded AGC remain the safe local path. A future RNNoise/WebRTC adapter must pass
recorded intelligibility and CPU/battery acceptance before activation.

True acoustic echo cancellation cannot be honestly provided by the current
`sounddevice` input plus macOS `say` output pair because it has no synchronized
speaker reference stream. Misha therefore uses owner verification, an exact
interrupt phrase and a high score threshold. Native duplex WebRTC AEC remains a
measured follow-up; the product must not call the present guard “AEC”.
