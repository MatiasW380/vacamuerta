// Alta al newsletter. Usa Buttondown (https://buttondown.com) si la variable
// BUTTONDOWN_API_KEY está configurada en Vercel. Sin ella, responde 503 y la
// web muestra que el alta todavía no está habilitada.

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "method" });
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  const email = String(body?.email || "").trim().toLowerCase();
  const lang = ["es", "en", "pt", "el"].includes(body?.lang) ? body.lang : "en";
  if (!EMAIL.test(email) || email.length > 254) {
    return res.status(400).json({ ok: false, error: "email" });
  }

  const key = process.env.BUTTONDOWN_API_KEY;
  if (!key) {
    return res.status(503).json({ ok: false, error: "not_configured" });
  }

  try {
    const r = await fetch("https://api.buttondown.com/v1/subscribers", {
      method: "POST",
      headers: { Authorization: `Token ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ email_address: email, tags: [`lang-${lang}`, "vacamuerta-web"] }),
    });
    if (r.ok || r.status === 409) {
      return res.status(200).json({ ok: true });
    }
    const detail = await r.text();
    if (/already/i.test(detail)) return res.status(200).json({ ok: true });
    console.error("Buttondown", r.status, detail);
    return res.status(502).json({ ok: false, error: "provider" });
  } catch (e) {
    console.error("Buttondown", e);
    return res.status(502).json({ ok: false, error: "provider" });
  }
}
