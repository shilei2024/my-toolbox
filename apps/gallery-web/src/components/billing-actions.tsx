"use client";

import { useState } from "react";

export function CheckoutButton({ planSlug, disabled = false }: { planSlug: string; disabled?: boolean }) {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  async function checkout() {
    setState("loading");
    try {
      const response = await fetch("/api/billing/checkout", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planSlug, idempotencyKey: crypto.randomUUID() }),
      });
      const body = await response.json() as { url?: string; error?: { message?: string } };
      if (!response.ok || !body.url) throw new Error(body.error?.message ?? "暂时无法创建结账会话");
      window.location.assign(body.url);
    } catch { setState("error"); }
  }
  return <div className="billing-action"><button className="button primary billing-button" type="button" onClick={checkout} disabled={disabled || state === "loading"}>{state === "loading" ? "正在前往安全结账…" : "选择此方案"}</button>{state === "error" ? <p role="alert">结账暂不可用，请稍后再试。</p> : null}</div>;
}

export function PortalButton() {
  const [state, setState] = useState<"idle" | "loading" | "error">("idle");
  async function openPortal() {
    setState("loading");
    try {
      const response = await fetch("/api/billing/portal", { method: "POST", credentials: "same-origin" });
      const body = await response.json() as { url?: string };
      if (!response.ok || !body.url) throw new Error("portal unavailable");
      window.location.assign(body.url);
    } catch { setState("error"); }
  }
  return <div className="billing-action"><button className="button" type="button" onClick={openPortal} disabled={state === "loading"}>{state === "loading" ? "正在打开…" : "管理订阅与发票"}</button>{state === "error" ? <p role="alert">订阅管理暂不可用。</p> : null}</div>;
}

