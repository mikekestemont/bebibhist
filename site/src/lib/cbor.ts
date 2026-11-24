/** The parts of CBOR that Pagefind's files use: texts, lists and whole numbers. */
export class Reader {
  at: number;
  private bytes: Uint8Array;

  constructor(bytes: Uint8Array, at = 0) {
    this.bytes = bytes;
    this.at = at;
  }

  private value(byte: number): number {
    const info = byte & 31;
    if (info < 24) return info;
    if (info > 26) throw new Error(`search index: unexpected byte ${byte} at ${this.at - 1}`);
    let value = 0;
    for (let size = 1 << (info - 24); size > 0; size -= 1) value = value * 256 + this.bytes[this.at++];
    return value;
  }

  private head(major: number): number {
    const byte = this.bytes[this.at++];
    if (byte >> 5 !== major) throw new Error(`search index: unexpected byte ${byte} at ${this.at - 1}`);
    return this.value(byte);
  }

  /** The length of a list that begins here. */
  list(): number {
    return this.head(4);
  }

  number(): number {
    return this.head(0);
  }

  /** A whole number, also below zero. */
  integer(): number {
    const byte = this.bytes[this.at++];
    if (byte >> 5 > 1) throw new Error(`search index: unexpected byte ${byte} at ${this.at - 1}`);
    return byte >> 5 ? -1 - this.value(byte) : this.value(byte);
  }

  numbers(): Uint32Array {
    return Uint32Array.from({ length: this.list() }, () => this.number());
  }

  text(): string {
    const length = this.head(3);
    const end = this.at + length;
    let plain = "";
    // Ids and filter values are short and plain: a decoder call for each of 240,000 ids is slower than this.
    for (let at = this.at; at < end; at += 1) {
      if (this.bytes[at] > 127) {
        plain = new TextDecoder().decode(this.bytes.subarray(this.at, end));
        break;
      }
      plain += String.fromCharCode(this.bytes[at]);
    }
    this.at = end;
    return plain;
  }

  skipText(): void {
    const length = this.head(3);
    this.at += length;
  }
}
