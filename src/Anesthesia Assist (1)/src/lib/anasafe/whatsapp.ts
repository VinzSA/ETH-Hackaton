import type { WhatsAppMessage, WhatsAppSource } from "./types";

// Parses a pasted WhatsApp chat. Tolerant of common export formats:
//   [10/05/26, 21:43] Mom: he took the blood thinner this morning
//   10/05/26, 21:43 - Mom: he took the blood thinner this morning
//   Mom (21:43): he took the blood thinner
//   Mom: he took the blood thinner
const LINE_RE =
  /^(?:\[)?(?:(\d{1,2}[\/.-]\d{1,2}(?:[\/.-]\d{2,4})?),?\s*)?(\d{1,2}:\d{2}(?::\d{2})?)?\]?\s*[-–—]?\s*([A-Za-zÀ-ÿ'’ .]+?):\s*(.*)$/;

export function parseWhatsApp(raw: string, chatId: string, title: string): WhatsAppSource {
  const lines = raw
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);

  const messages: WhatsAppMessage[] = [];
  let buffer: { sender: string; timestamp?: string; text: string } | null = null;

  for (const line of lines) {
    const m = line.match(LINE_RE);
    if (m && m[3] && m[4] !== undefined) {
      if (buffer) flush();
      buffer = {
        sender: m[3].trim(),
        timestamp: m[2] || m[1] || undefined,
        text: m[4].trim(),
      };
    } else if (buffer) {
      buffer.text += " " + line;
    } else {
      // Stray line with no sender — attribute to "Unknown"
      buffer = { sender: "Unknown", text: line };
    }
  }
  if (buffer) flush();

  function flush() {
    if (!buffer) return;
    messages.push({
      id: `${chatId}:M${messages.length + 1}`,
      sender: buffer.sender,
      timestamp: buffer.timestamp,
      text: buffer.text,
    });
    buffer = null;
  }

  return { kind: "whatsapp", id: chatId, title, messages };
}
