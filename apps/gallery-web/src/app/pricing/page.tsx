import type { Metadata } from "next";
import Link from "next/link";
import { CheckoutButton } from "@/components/billing-actions";
import type { BillingPlan, BillingSummary } from "@/lib/billing-types";
import { getBillingSummary } from "@/server/billing-client";
import { GalleryClientError } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

export const metadata: Metadata = { title: "会员与积分", description: "选择适合你的 Mavis 创作额度与会员方案。" };
export const dynamic = "force-dynamic";

export default async function PricingPage() {
  const viewer = await resolveViewerFromRequest();
  let summary: BillingSummary = { plans: [freeFallback], ledger: [] };
  let unavailable = false;
  try { summary = await getBillingSummary(viewer); } catch (error) { unavailable = error instanceof GalleryClientError; }
  const paidPlans = summary.plans.filter((plan) => plan.kind !== "free");
  return <main className="page-shell pricing-page">
    <section className="pricing-hero">
      <div><p className="eyebrow"><span className="eyebrow-dot" />Membership & credits</p><h1>把灵感留给创作，<br />把用量交给清晰的积分。</h1><p>每次生成先预占积分，成功后结算，失败自动释放。支付由托管结账页处理，Mavis 不接触你的银行卡信息。</p></div>
      <aside className="pricing-principle"><span>01</span><strong>一笔生成，一条可追溯流水</strong><p>积分与会员归属 Mavis 自己的账本，不依赖任何单一支付渠道。</p></aside>
    </section>
    {unavailable ? <section className="billing-notice"><strong>方案暂时无法读取</strong><p>现有作品与画廊不受影响，请稍后再查看。</p></section> : null}
    <section className="plan-grid" aria-label="会员方案">
      {summary.plans.map((plan, index) => <PlanCard key={plan.id} plan={plan} authenticated={viewer.role !== "guest"} featured={index === 1 && plan.kind !== "free"} />)}
      {paidPlans.length === 0 ? <article className="plan-card plan-coming"><p className="plan-kicker">Production safety</p><h2>付费方案正在配置</h2><p>我们不会在真实 Price ID、币种、税务与退款策略确认前展示虚构价格。免费方案可继续使用。</p><dl><div><dt>支付渠道</dt><dd>可替换</dd></div><div><dt>积分账本</dt><dd>已就绪</dd></div></dl></article> : null}
    </section>
    <section className="pricing-fineprint"><h2>你的余额不属于支付渠道</h2><div><p>支付 Provider 只返回已验证的订单与订阅事件。积分发放、预占、结算和退款冲正都发生在内部账本中。</p><p>因此未来接入微信支付、支付宝或其他渠道时，前端页面和生成服务无需改写业务规则。</p></div></section>
  </main>;
}

function PlanCard({ plan, authenticated, featured }: { plan: BillingPlan; authenticated: boolean; featured: boolean }) {
  const price = plan.kind === "free" ? "免费" : formatMoney(plan.amountMinor, plan.currency);
  const features = entitlementLines(plan);
  return <article className={`plan-card${featured ? " featured" : ""}`}>
    <p className="plan-kicker">{plan.kind === "free" ? "Start here" : plan.kind === "subscription" ? "For regular creation" : "Top up anytime"}</p>
    <h2>{plan.displayName}</h2><p className="plan-description">{plan.description}</p>
    <p className="plan-price"><strong>{price}</strong>{plan.billingInterval ? <span>/{plan.billingInterval === "month" ? "月" : "年"}</span> : null}</p>
    <ul>{features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
    {plan.kind === "free" ? <Link className="button billing-button" href="/gallery">浏览画廊</Link> : authenticated ? <CheckoutButton planSlug={plan.slug} /> : <Link className="button primary billing-button" href="/login?next=/pricing">登录后选择</Link>}
  </article>;
}
function entitlementLines(plan: BillingPlan): string[] {
  const result = plan.creditAmount !== "0.0000" && plan.creditAmount !== "0" ? [`${trimDecimal(plan.creditAmount)} 积分`] : ["公开画廊与基础功能"];
  if (plan.entitlements.private_generation === true) result.push("私密生成");
  if (plan.entitlements.priority_queue === true) result.push("优先队列");
  return result;
}
function formatMoney(amountMinor: string, currency: string): string { return new Intl.NumberFormat("zh-CN", { style: "currency", currency }).format(Number(amountMinor) / 100); }
function trimDecimal(value: string): string { return value.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1"); }
const freeFallback: BillingPlan = { id: "free", slug: "free", displayName: "Free", description: "适合体验公开画廊与基础创作流程。", kind: "free", currency: "USD", amountMinor: "0", creditAmount: "0", entitlements: {} };
