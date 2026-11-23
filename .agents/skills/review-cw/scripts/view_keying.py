"""Plot an unlabeled spectrum and two independently filtered envelopes on a shared time axis."""

import argparse

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import gaussian_filter1d


def plot(wav, output, start, end, tone):
    data, rate = sf.read(wav)
    if data.ndim != 1:
        raise ValueError("Extract a mono carrier channel before plotting")
    first = round(rate * start)
    last = len(data) if end is None else round(rate * end)
    if not 0 <= first < last <= len(data) or last - first < 8:
        raise ValueError("Choose a time range within the recording")
    segment = data[first:last]
    t = (np.arange(len(segment)) + first) / rate
    length = min(len(segment), max(8, round(0.048 * rate)))
    f, times, power = signal.spectrogram(segment, rate, window="hann", nperseg=length,
                                         noverlap=length * 7 // 8, detrend=False)
    if tone is None:
        band = (f >= 200) & (f <= 1600)
        if not band.any():
            raise ValueError("Specify a tone for this sample rate or duration")
        tone = f[band][np.argmax(np.mean(power[band], axis=1))]
    display = np.abs(f - tone) <= 320
    if not display.any() or not 0 < tone < rate / 2:
        raise ValueError("Choose a tone inside the sampled frequency band")
    fig, (spectrum, envelope) = plt.subplots(2, sharex=True, figsize=(13, 5), layout="constrained")
    db = 10 * np.log10(np.maximum(power[display], 1e-18))
    peak = np.percentile(db, 99.6)
    spectrum.pcolormesh(times + start, f[display], db, shading="auto", cmap="magma",
                        vmin=peak - 42, vmax=peak)
    spectrum.set_ylabel("Frequency (Hz)")
    spectrum.axhline(tone, color="white", ls=":", lw=0.6)
    baseband = segment * np.exp(-2j * np.pi * tone * t)
    step = max(1, round(rate / 400))
    for sigma in (0.006, 0.014):
        carrier = gaussian_filter1d(baseband, sigma * rate, mode="constant")
        envelope.plot(t[::step], np.abs(carrier[::step]), label=f"{1000 * sigma:g} ms smoothing")
    envelope.legend()
    envelope.set(xlabel="Source time (s)", ylabel="Carrier amplitude", xlim=(t[0], t[-1]))
    envelope.grid(alpha=0.25)
    fig.savefig(output, dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav")
    parser.add_argument("output")
    parser.add_argument("--start", type=float, default=0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--tone", type=float)
    args = parser.parse_args()
    plot(args.wav, args.output, args.start, args.end, args.tone)
