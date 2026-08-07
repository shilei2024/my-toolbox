"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

export function RedeemCodeForm() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>();

  async function redeem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setMessage(undefined);
    try {
      const response = await fetch("/api/billing/redeem", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code.trim() }),
      });
      const body = await response.json().catch(() => undefined) as { error?: { message?: string }; amount?: string } | undefined;
      if (!response.ok || !body) throw new Error(body?.error?.message || "兑换失败，请稍后重试。");
      setMessage(`兑换成功，会员积分 +${body.amount}。`);
      setCode("");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "兑换失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return <form className="redeem-form" onSubmit={(event) => void redeem(event)}>
    <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="输入兑换码（如 MP-XXXX-XXXX）" maxLength={40} aria-label="兑换码" />
    <button className="button primary" type="submit" disabled={busy || !code.trim()}>{busy ? "兑换中…" : "兑换会员积分"}</button>
    {message && <p className="redeem-message" role="status">{message}</p>}
  </form>;
}
