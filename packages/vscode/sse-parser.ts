export const SSE_MAX_BUFFER_CHARS = 1024 * 1024;

export interface SseEvent {
  id: string | null;
  type: string | null;
  data: string;
}

export class SseBufferOverflowError extends Error {
  readonly limit: number;

  constructor(limit: number) {
    super(`SSE buffer exceeded ${limit} characters`);
    this.name = "SseBufferOverflowError";
    this.limit = limit;
  }
}

export class SseParser {
  private tail = "";
  private pendingId: string | null = null;
  private pendingType: string | null = null;
  private pendingData: string[] = [];
  private pendingChars = 0;

  constructor(
    private readonly onEvent: (event: SseEvent) => void,
    private readonly maxChars: number = SSE_MAX_BUFFER_CHARS,
  ) {}

  push(chunk: string): void {
    let start = 0;
    for (;;) {
      const newline = chunk.indexOf("\n", start);
      if (newline === -1) break;
      const piece = chunk.slice(start, newline);
      const line = this.tail.length > 0 ? this.tail + piece : piece;
      this.tail = "";
      this.consumeLine(line);
      start = newline + 1;
    }
    if (start < chunk.length) {
      const rest = start === 0 ? chunk : chunk.slice(start);
      if (this.tail.length + rest.length > this.maxChars) {
        throw new SseBufferOverflowError(this.maxChars);
      }
      this.tail += rest;
    }
  }

  private consumeLine(line: string): void {
    if (line.length > this.maxChars) {
      throw new SseBufferOverflowError(this.maxChars);
    }
    if (line === "") {
      this.flush();
      return;
    }
    if (line.startsWith(":")) {
      return;
    }
    if (line.startsWith("id:")) {
      this.pendingId = line.slice(3).replace(/^\s+/, "");
      return;
    }
    if (line.startsWith("event:")) {
      this.pendingType = line.slice(6).replace(/^\s+/, "");
      return;
    }
    if (line.startsWith("data:")) {
      const value = line.slice(5).replace(/^\s/, "");
      this.pendingChars += value.length;
      if (this.pendingChars > this.maxChars) {
        throw new SseBufferOverflowError(this.maxChars);
      }
      this.pendingData.push(value);
    }
  }

  private flush(): void {
    if (
      this.pendingData.length === 0 &&
      this.pendingType === null &&
      this.pendingId === null
    ) {
      return;
    }
    const event: SseEvent = {
      id: this.pendingId,
      type: this.pendingType,
      data: this.pendingData.join("\n"),
    };
    this.pendingId = null;
    this.pendingType = null;
    this.pendingData = [];
    this.pendingChars = 0;
    this.onEvent(event);
  }
}
