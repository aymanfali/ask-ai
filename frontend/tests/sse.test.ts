import assert from "node:assert/strict";
import test from "node:test";
import { consumeSseStream } from "../src/lib/sse.ts";

function streamFromChunks(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

function bytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

test("parses named events across chunk boundaries and preserves Unicode", async () => {
  const source = [
    ": keep-alive\r\nevent: generation.started\r\ndata: {\"generation_id\":\"g-1\"}\r\n\r\n",
    "event: message.delta\ndata: {\"text\":\"Hello ",
    "🌍\"}\n\n",
    "event: generation.completed\ndata: {\"message_id\":\"m-1\"}\n\n",
  ];
  const chunks = source.map(bytes);
  const received: Array<{ name: string; data: Record<string, unknown> }> = [];

  await consumeSseStream(streamFromChunks(chunks), (name, data) => {
    received.push({ name, data });
  });

  assert.deepEqual(received, [
    { name: "generation.started", data: { generation_id: "g-1" } },
    { name: "message.delta", data: { text: "Hello 🌍" } },
    { name: "generation.completed", data: { message_id: "m-1" } },
  ]);
});

test("supports multi-line data fields", async () => {
  const received: Array<{ name: string; data: Record<string, unknown> }> = [];
  await consumeSseStream(
    streamFromChunks([bytes('event: generation.completed\ndata: {\n' + 'data: "ok": true}\n\n')]),
    (name, data) => received.push({ name, data }),
  );
  assert.deepEqual(received[0], {
    name: "generation.completed",
    data: { ok: true },
  });
});

test("rejects malformed JSON event payloads", async () => {
  await assert.rejects(
    consumeSseStream(
      streamFromChunks([bytes("event: generation.completed\ndata: {not-json}\n\n")]),
      () => undefined,
    ),
    /invalid generation.completed event/,
  );
});

test("rejects a stream that closes without a terminal generation event", async () => {
  await assert.rejects(
    consumeSseStream(
      streamFromChunks([bytes('event: message.delta\ndata: {"text":"partial"}\n\n')]),
      () => undefined,
    ),
    /ended before a terminal generation event/,
  );
});

test("dispatches an error terminal event without treating it as a transport failure", async () => {
  const received: string[] = [];
  await consumeSseStream(
    streamFromChunks([bytes('event: generation.error\ndata: {"code":"provider_timeout"}\n\n')]),
    (name) => received.push(name),
  );
  assert.deepEqual(received, ["generation.error"]);
});

test("preserves a UTF-8 code point split between network chunks", async () => {
  const received: Array<{ name: string; data: Record<string, unknown> }> = [];
  const emoji = bytes("🌍");
  const chunks = [
    bytes('event: message.delta\ndata: {"text":"'),
    emoji.slice(0, 2),
    emoji.slice(2),
    bytes('"}\n\nevent: generation.completed\ndata: {}\n\n'),
  ];
  await consumeSseStream(streamFromChunks(chunks), (name, data) => received.push({ name, data }));
  assert.equal(received[0]?.data.text, "🌍");
  assert.equal(received[1]?.name, "generation.completed");
});

test("does not split SSE fields when CRLF is divided across network chunks", async () => {
  const received: string[] = [];
  const chunks = [
    bytes('event: generation.started\r'),
    bytes('\ndata: {"generation_id":"g-2"}\r'),
    bytes('\n\r'),
    bytes('\nevent: generation.completed\r\ndata: {}\r\n\r\n'),
  ];
  await consumeSseStream(streamFromChunks(chunks), (name) => received.push(name));
  assert.deepEqual(received, ["generation.started", "generation.completed"]);
});
