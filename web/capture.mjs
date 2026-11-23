class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(2048);
    this.offset = 0;
    this.finished = false;
    this.port.onmessage = ({data}) => {
      if (data !== 'flush' || this.finished) return;
      this.finished = true;
      if (this.offset) this.send(this.block.slice(0, this.offset));
      this.port.postMessage(null);
    };
  }

  send(block) {
    this.port.postMessage(block, [block.buffer]);
  }

  process(inputs) {
    if (this.finished) return false;
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    let start = 0;
    while (start < channel.length) {
      const count = Math.min(channel.length - start, this.block.length - this.offset);
      this.block.set(channel.subarray(start, start + count), this.offset);
      this.offset += count;
      start += count;
      if (this.offset === this.block.length) {
        this.send(this.block);
        this.block = new Float32Array(2048);
        this.offset = 0;
      }
    }
    return true;
  }
}

registerProcessor('morse-capture', Capture);
