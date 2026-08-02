import type { Metadata } from "next";
import Link from "next/link";
import { PortalButton } from "@/components/billing-actions";
import type { BillingSummary } from "@/lib/billing-types";
import { getBillingSummary } from "@/server/billing-client";
import { GalleryClientError } from "@/server/gallery-client";
import { resolveViewerFromRequest } from "@/server/viewer";

export const metadata: Metadata = { title: "积分与账单", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";

export default async function BillingPage() {
  const viewer = await resolveViewerFromRequest();
  if (viewer.role === "guest") return <main className="page-shell"><section className="billing-auth"><p className="eyebrow"><span className="eyebrow-dot" />Account billing</p><h1>登录后查看积分与账单</h1><p>余额、会员状态与每一条积分变化都只对账户本人可见。</p><Link className="button primary" href="/login?next=/billing">登录账户</Link></section></main>;
  let summary: BillingSummary;
  try { summary = await getBillingSummary(viewer); } catch (error) { return <main className="page-shell"><section className="billing-auth"><h1>账单服务暂不可用</h1><p>{error instanceof GalleryClientError ? error.message : "请稍后再试。"}</p></section></main>; }
  const account = summary.account!;
  return <main className="page-shell billing-page">
    <section className="billing-heading"><div><p className="eyebrow"><span className="eyebrow-dot" />Account billing</p><h1>积分与账单</h1><p>余额来自内部账本；支付渠道只负责完成交易。</p></div><Link className="button" href="/pricing">查看方案</Link></section>
    <section className="balance-grid">
      <article className="balance-primary"><span>可用积分</span><strong>{trimDecimal(account.availableAmount)}</strong><small>新生成任务可使用</small></article>
      <article><span>预占中</span><strong>{trimDecimal(account.reservedAmount)}</strong><small>任务结束后结算或释放</small></article>
      <article><span>累计获得</span><strong>{trimDecimal(account.lifetimeGranted)}</strong><small>会员、积分包与调整</small></article>
      <article><span>累计使用</span><strong>{trimDecimal(account.lifetimeSpent)}</strong><small>仅成功生成计入</small></article>
    </section>
    <section className="billing-columns">
      <article className="membership-panel"><p className="panel-label">当前会员</p>{summary.subscription ? <><div className="membership-title"><h2>{summary.subscription.planName}</h2><span className={`status-pill status-${summary.subscription.status}`}>{statusLabel(summary.subscription.status)}</span></div><dl><div><dt>续订状态</dt><dd>{summary.subscription.cancelAtPeriodEnd ? "本周期结束后取消" : "自动续订"}</dd></div><div><dt>当前周期</dt><dd>{summary.subscription.currentPeriodEnd ? `至 ${formatDate(summary.subscription.currentPeriodEnd)}` : "等待支付渠道同步"}</dd></div></dl><PortalButton /></> : <><h2>Free</h2><p>当前没有付费订阅。你仍可使用免费方案包含的功能。</p><Link className="button primary" href="/pricing">比较会员方案</Link></>}</article>
      <article className="ledger-panel"><div className="ledger-heading"><div><p className="panel-label">Credit ledger</p><h2>积分流水</h2></div><span>最近 30 条</span></div>{summary.ledger.length ? <ol className="ledger-list">{summary.ledger.map((entry) => <li key={entry.id}><div><strong>{entryLabel(entry.entryType)}</strong><time>{formatDateTime(entry.createdAt)}</time></div><span className={Number(entry.deltaAvailable) >= 0 ? "credit-positive" : "credit-negative"}>{signed(entry.deltaAvailable)}</span></li>)}</ol> : <div className="ledger-empty"><strong>还没有积分变动</strong><p>购买方案、系统赠送或完成生成后，流水会出现在这里。</p></div>}</article>
    </section>
  </main>;
}
function trimDecimal(value: string): string { return value.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1"); }
function signed(value: string): string { const number = Number(value); return `${number > 0 ? "+" : ""}${trimDecimal(value)}`; }
function statusLabel(value: string): string { return ({ active: "生效中", trialing: "试用中", past_due: "待付款", paused: "已暂停", cancelled: "已取消", unpaid: "未付款", incomplete: "待完成" } as Record<string, string>)[value] ?? value; }
function entryLabel(value: string): string { return ({ signup_grant: "注册赠送", subscription_grant: "会员积分到账", pack_purchase: "积分包到账", admin_adjustment: "人工调整", generation_reserve: "生成预占", generation_settle: "生成结算", generation_release: "预占释放", payment_refund: "退款冲正", credit_expiry: "积分到期" } as Record<string, string>)[value] ?? value; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(new Date(value)); }
function formatDateTime(value: string): string { return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)); }
