export type SsePayload = Record<string, unknown>;
export type SseHandler = (eventName: string, data: SsePayload) => void;

const TERMINAL_EVENTS = new Set([
  "generation.completed",
  "generation.error",
  "generation.cancelled",
]);

/** Consume an SSE stream with UTF-8 boundary, CRLF, comments, and multiline-data support. */
export async function consumeSseStream(
  stream: ReadableStream<Uint8Array>,
  onEvent: SseHandler,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let lineBuffer = "";
  let eventName = "message";
  let dataLines: string[] = [];
  let sawTerminalEvent = false;
  let pendingCarriageReturn = false;

  const dispatch = () => {
    if (dataLines.length === 0) {
      eventName = "message";
      return;
    }
    const rawData = dataLines.join("\n");
    const dispatchedName = eventName;
    let data: SsePayload;
    try {
      data = JSON.parse(rawData) as SsePayload;
    } catch {
      eventName = "message";
      dataLines = [];
      throw new Error(`The server sent an invalid ${dispatchedName} event payload.`);
    }
    eventName = "message";
    dataLines = [];
    onEvent(dispatchedName, data);
    if (TERMINAL_EVENTS.has(dispatchedName)) sawTerminalEvent = true;
  };

  const processLine = (line: string) => {
    if (line === "") {
      dispatch();
      return;
    }
    if (line.startsWith(":")) return;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") eventName = value || "message";
    if (field === "data") dataLines.push(value);
  };

  const processText = (text: string) => {
    let index = 0;
    if (pendingCarriageReturn) {
      processLine(lineBuffer);
      lineBuffer = "";
      pendingCarriageReturn = false;
      if (text.startsWith("\n")) index = 1;
    }

    for (; index < text.length; index += 1) {
      const character = text[index];
      if (character === "\r") {
        if (index === text.length - 1) {
          pendingCarriageReturn = true;
          break;
        }
        if (text[index + 1] === "\n") index += 1;
        processLine(lineBuffer);
        lineBuffer = "";
      } else if (character === "\n") {
        processLine(lineBuffer);
        lineBuffer = "";
      } else {
        lineBuffer += character;
      }
    }
  };

  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("The request was aborted.", "AbortError");
      const { value, done } = await reader.read();
      if (done) break;
      processText(decoder.decode(value, { stream: true }));
    }
    processText(decoder.decode());
    if (pendingCarriageReturn) {
      processLine(lineBuffer);
      lineBuffer = "";
      pendingCarriageReturn = false;
    }
    if (lineBuffer.length > 0) processLine(lineBuffer);
    dispatch();
    if (!sawTerminalEvent && !signal?.aborted) {
      throw new Error("The response stream ended before a terminal generation event.");
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // The stream may already have been cancelled or closed by the browser.
    }
    reader.releaseLock();
  }
}
