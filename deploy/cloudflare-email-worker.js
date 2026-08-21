const DEFAULT_TIMEOUT_MS = 10000;

function resolveWebhookUrl(value) {
  const url = new URL(String(value || "").trim());
  if (url.pathname === "/" || url.pathname === "") {
    url.pathname = "/api/webhook/email";
  }
  return url.toString();
}

function timeoutMs(value) {
  const parsed = Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_TIMEOUT_MS;
}

export default {
  async email(message, env) {
    const webhookUrl = resolveWebhookUrl(env.EMAIL_WEBHOOK_URL);
    const rawContent = await new Response(message.raw).text();
    const messageId = message.headers.get("message-id") || crypto.randomUUID();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs(env.EMAIL_WEBHOOK_TIMEOUT_MS));

    let response;
    try {
      response = await fetch(webhookUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Webhook-Secret": String(env.EMAIL_WEBHOOK_SECRET || ""),
        },
        body: JSON.stringify({
          message_id: messageId,
          to_addr: message.to,
          from_addr: message.from,
          raw_content: rawContent,
        }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
    }

    if (!response.ok) {
      const responseText = (await response.text()).slice(0, 500);
      throw new Error(`Email webhook returned ${response.status}: ${responseText}`);
    }

    console.log(`Email webhook delivered: ${messageId}`);
  },
};
