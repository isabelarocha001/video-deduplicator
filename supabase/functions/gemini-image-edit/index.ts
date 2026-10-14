const MODEL = "gemini-3.1-flash-image";
const MAX_IMAGE_BASE64 = 8_000_000;
const encoder = new TextEncoder();

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

async function digest(value: string) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

async function constantTimeEqual(left: string, right: string) {
  const [a, b] = await Promise.all([digest(left), digest(right)]);
  let difference = 0;
  for (let index = 0; index < a.length; index += 1) difference |= a[index] ^ b[index];
  return difference === 0;
}

Deno.serve(async (request) => {
  if (request.method !== "POST") return json({ ok: false, error: "Method not allowed." }, 405);

  const expectedToken = Deno.env.get("GEMINI_IMAGE_EDIT_ONESHOT_TOKEN")?.trim();
  const providedToken = request.headers.get("x-image-edit-token")?.trim() || "";
  if (!expectedToken || !providedToken || !(await constantTimeEqual(providedToken, expectedToken))) {
    return json({ ok: false, error: "Unauthorized." }, 401);
  }

  const apiKey = Deno.env.get("GEMINI_API_KEY")?.trim();
  if (!apiKey) return json({ ok: false, error: "Gemini is not configured." }, 503);

  let body: { image_base64?: unknown; mime_type?: unknown };
  try {
    body = await request.json();
  } catch {
    return json({ ok: false, error: "Invalid JSON." }, 400);
  }

  const imageBase64 = typeof body.image_base64 === "string"
    ? body.image_base64.replace(/^data:[^;]+;base64,/, "")
    : "";
  const mimeType = typeof body.mime_type === "string" ? body.mime_type.toLowerCase() : "";
  if (!imageBase64 || imageBase64.length > MAX_IMAGE_BASE64) {
    return json({ ok: false, error: "Image is missing or too large." }, 413);
  }
  if (!["image/jpeg", "image/png", "image/webp"].includes(mimeType)) {
    return json({ ok: false, error: "Unsupported image format." }, 415);
  }

  const prompt = [
    "Edit this exact source photograph. Replace only the teal Mexico crop-top with a realistic yellow Brazil national football jersey: bright Brazil yellow fabric, green collar and sleeve trim, natural knit texture and authentic folds following the existing pose and lighting.",
    "Remove the word MEXICO and the Mexican flag/heart graphic from the shirt. Add a small tasteful Brazil football crest in green, blue, and yellow on the chest; do not add readable words, sponsors, numbers, or extra logos.",
    "Preserve the same person and identity, face, expression, hair, glasses, body, skin, tattoos, jewelry, hands, pose, proportions, background, camera angle, crop, and image composition exactly. Keep all pixels outside the shirt unchanged as much as possible.",
    "This is a precise clothing edit, not a new photo or a restaging. Do not mirror, crop, retouch skin, change body shape, or alter anything other than the shirt and its chest graphic.",
  ].join(" ");

  let providerResponse: Response;
  try {
    providerResponse = await fetch(
      `https://generativelanguage.googleapis.com/v1/models/${MODEL}:generateContent`,
      {
      method: "POST",
      headers: { "x-goog-api-key": apiKey, "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{
          role: "user",
          parts: [
            { text: prompt },
            { inline_data: { mime_type: mimeType, data: imageBase64 } },
          ],
        }],
        generationConfig: {
          responseModalities: ["TEXT", "IMAGE"],
        },
      }),
      signal: AbortSignal.timeout(120_000),
      },
    );
  } catch {
    return json({ ok: false, error: "Gemini request failed." }, 502);
  }

  const responseText = await providerResponse.text();
  if (!providerResponse.ok) {
    let providerMessage = "";
    let providerStatus = "";
    try {
      const providerError = JSON.parse(responseText)?.error;
      providerMessage = typeof providerError?.message === "string" ? providerError.message.slice(0, 300) : "";
      providerStatus = typeof providerError?.status === "string" ? providerError.status.slice(0, 80) : "";
    } catch {
      // Keep a generic message if the provider response is not JSON.
    }
    console.error(JSON.stringify({
      event: "gemini_image_edit_provider_error",
      status: providerResponse.status,
      provider_status: providerStatus,
      provider_message: providerMessage,
    }));
    return json({ ok: false, error: `Gemini returned HTTP ${providerResponse.status}.`, provider_message: providerMessage }, 502);
  }

  try {
    const payload = JSON.parse(responseText);
    const parts = payload?.candidates?.[0]?.content?.parts || [];
    const imagePart = parts.find((part: any) => part?.inlineData?.data || part?.inline_data?.data);
    const imageData = imagePart?.inlineData?.data || imagePart?.inline_data?.data;
    if (typeof imageData !== "string" || !imageData) {
      return json({ ok: false, error: "Gemini returned no edited image." }, 502);
    }
    return json({
      ok: true,
      mime_type: imagePart.inlineData?.mimeType || imagePart.inline_data?.mime_type || "image/jpeg",
      image_base64: imageData,
    });
  } catch {
    return json({ ok: false, error: "Gemini returned an unreadable response." }, 502);
  }
});
