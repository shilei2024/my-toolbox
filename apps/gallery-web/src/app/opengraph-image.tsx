/* eslint-disable @next/next/no-img-element */
import { ImageResponse } from "next/og";

export const alt = "Mavis Gallery — A quiet home for remarkable AI images";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  const logo = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%230d6efd'/%3E%3Cpath d='M9 8h7l5 5v11a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V10a2 2 0 0 1 2-2z' fill='%23ffffff' opacity='.95'/%3E%3Cpath d='M16 8v5h5' fill='none' stroke='%230d6efd' stroke-width='1.5'/%3E%3Ccircle cx='16' cy='19' r='2.5' fill='%23ffc107'/%3E%3C/svg%3E";
  return new ImageResponse(
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", padding: "72px 78px", color: "#152438", background: "#f6f9fc" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 28, fontWeight: 700 }}><img src={logo} alt="" width={54} height={54} />Mavis Gallery</div>
      <div style={{ display: "flex", flexDirection: "column" }}><div style={{ display: "flex", fontSize: 72, fontWeight: 650, letterSpacing: "-4px", lineHeight: 1.08 }}>A quiet home for</div><div style={{ display: "flex", color: "#0d6efd", fontSize: 72, fontWeight: 650, letterSpacing: "-4px", lineHeight: 1.08 }}>remarkable AI images.</div><div style={{ display: "flex", marginTop: 28, color: "#65758b", fontSize: 26 }}>Public, moderated, and made to be discovered.</div></div>
      <div style={{ width: 92, height: 7, borderRadius: 8, background: "#ffc107" }} />
    </div>,
    size,
  );
}
