"""
zip_extractor 单元测试 — 不走 create_app()，避免其他工具的依赖问题。
直接挂 zip_extractor blueprint 到一个最小 Flask app 上。
"""
import base64
import io
import os
import sys
import zipfile
from pathlib import Path

# 让 from tools.zip_extractor import ... 能找到
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask

from extensions import csrf, db, limiter, login_manager  # 复用项目里的扩展


def make_pdf_bytes(label: str, size_kb: int = 5) -> bytes:
    """构造看起来像 PDF 的字节流，size_kb 是目标大小（KB）。

    label 嵌入到 PDF header 注释，确保不同 filename 字节不同（否则会被去重）。
    """
    # 把 label 写进 header 注释（PDF 允许 header 后放 % 注释）
    label_bytes = label.encode("ascii", errors="replace")
    header = b"%PDF-1.4\n%label=" + label_bytes + b"\n%\xe2\xe3\xcf\xd3\n"
    footer = b"\n%%EOF\n"
    pad_chunk = b"X" * 1024
    body = pad_chunk * size_kb
    return header + body + footer


def make_zip(name: str, pdfs: list[tuple[str, int]], store: bool = False) -> bytes:
    buf = io.BytesIO()
    mode = zipfile.ZIP_STORED if store else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(buf, "w", mode) as zf:
        for fname, kb in pdfs:
            zf.writestr(fname, make_pdf_bytes(fname, kb))
    return buf.getvalue()


def make_app() -> Flask:
    """最小 Flask app，只挂 zip_extractor blueprint。"""
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["ANON_FREE_LIMIT"] = 100
    app.config["DAILY_FREE_LIMIT"] = 100
    # 限速相关的存储
    app.config["RATELIMIT_ENABLED"] = False
    csrf.init_app(app)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.user_loader(lambda _user_id: None)
    limiter.init_app(app)

    from tools.zip_extractor import tool_bp
    app.register_blueprint(tool_bp, url_prefix="/tools/zip-extractor")
    with app.app_context():
        db.create_all()
    return app


def main():
    app = make_app()
    client = app.test_client()

    # ===== A: 单批少量 zip =====
    print("\n=== A. 单批少量 zip（2 zip 各 1 小 PDF）===")
    z1 = make_zip("a.zip", [("inv1.pdf", 5)])
    z2 = make_zip("b.zip", [("inv2.pdf", 5)])
    resp = client.post(
        "/tools/zip-extractor/analyze",
        data={"files": [
            (io.BytesIO(z1), "a.zip"),
            (io.BytesIO(z2), "b.zip"),
        ]},
        content_type="multipart/form-data",
    )
    print(f"  status: {resp.status_code}")
    d = resp.get_json()
    print(f"  success={d.get('success')}, total={d.get('total')}, truncated={d.get('truncated')}, skipped={d.get('skipped_oversize')}")
    assert resp.status_code == 200
    assert d["success"] is True
    assert d["total"] == 2
    assert not d.get("truncated")
    assert d.get("skipped_oversize") == []
    print("  PASS")

    # ===== B: 前端按当前 20MB 上限规划批次 =====
    print("\n=== B. 当前 20MB 批量上限：6 个 ~1MB zip 可在同批处理 ===")
    big_zips = [make_zip(f"big{i}.zip", [(f"inv{i}.pdf", 1000)], store=True) for i in range(6)]
    total_size = sum(len(z) for z in big_zips)
    print(f"  6 个 zip 总大小: {total_size/1024/1024:.2f} MB")

    BATCH = 20 * 1024 * 1024
    batches = []
    cur, cur_bytes = [], 0
    for z in big_zips:
        if cur and cur_bytes + len(z) > BATCH:
            batches.append(cur)
            cur, cur_bytes = [], 0
        cur.append(z)
        cur_bytes += len(z)
    if cur:
        batches.append(cur)
    print(f"  切分为 {len(batches)} 批")
    for bi, b in enumerate(batches):
        print(f"    批 {bi+1}: {sum(len(z) for z in b)/1024/1024:.2f} MB ({len(b)} 个文件)")

    all_files = []
    trunc_count = 0
    for bi, batch in enumerate(batches):
        resp = client.post(
            "/tools/zip-extractor/analyze",
            data={"files": [(io.BytesIO(z), f"big{bi}_{i}.zip") for i, z in enumerate(batch)]},
            content_type="multipart/form-data",
        )
        d = resp.get_json()
        print(f"  批 {bi+1}: status={resp.status_code}, files={d.get('total')}, truncated={d.get('truncated')}")
        assert resp.status_code == 200
        all_files.extend(d.get("files", []))
        if d.get("truncated"):
            trunc_count += d.get("truncated_count", 0)
    print(f"  累计获得 {len(all_files)} 个 PDF（truncated={trunc_count}）")
    # 验证：所有批要么一起返回了全部 6 个（如果单批没超），要么总数加上 truncated = 6
    assert len(all_files) + trunc_count == 6, f"got {len(all_files)} + {trunc_count} truncated != 6"
    print("  PASS")

    # ===== C: 旧 4MB 门槛已取消 =====
    print("\n=== C. 5MB ZIP（应正常处理）===")
    huge_pdf = make_pdf_bytes("huge", size_kb=5 * 1024)  # ~5MB
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("huge.pdf", huge_pdf)
    huge_bytes = buf.getvalue()
    print(f"  huge.zip 大小: {len(huge_bytes)/1024/1024:.2f} MB")

    resp = client.post(
        "/tools/zip-extractor/analyze",
        data={"files": [(io.BytesIO(huge_bytes), "huge.zip")]},
        content_type="multipart/form-data",
    )
    d = resp.get_json()
    print(f"  status: {resp.status_code}, skipped: {d.get('skipped_oversize')}")
    assert resp.status_code == 200
    assert d.get("total") == 1
    assert d.get("skipped_oversize") == []
    print("  PASS")

    # ===== D: 可配置响应门限仍会安全截断 =====
    print("\n=== D. 将测试响应门限设为 3MB，验证安全截断 ===")
    app.config["INVOICE_ZIP_RESPONSE_MB"] = 3
    many_pdfs = [(f"inv{i:03d}.pdf", 400) for i in range(6)]
    many_zip = make_zip("many.zip", many_pdfs, store=True)
    print(f"  many.zip 大小: {len(many_zip)/1024/1024:.2f} MB")
    print(f"  PDF base64 预估: {6*400*1024*4//3/1024/1024}MB（> 3MB 上限）")
    resp = client.post(
        "/tools/zip-extractor/analyze",
        data={"files": [(io.BytesIO(many_zip), "many.zip")]},
        content_type="multipart/form-data",
    )
    d = resp.get_json()
    print(f"  status: {resp.status_code}, returned: {d.get('total')}, truncated: {d.get('truncated')}, truncated_count: {d.get('truncated_count')}")
    assert resp.status_code == 200
    assert d.get("truncated") is True
    assert d.get("total") > 0
    assert d.get("truncated_count") > 0
    assert d.get("total") + d.get("truncated_count") == 6
    print(f"  PASS（返回 {d['total']} 个，截断 {d['truncated_count']} 个）")
    app.config["INVOICE_ZIP_RESPONSE_MB"] = 48

    # ===== E: 单批内 PDF 数量刚好 =====
    print("\n=== E. 单批 zip 内 PDF 全部能装下（不截断）===")
    few_pdfs = [(f"inv{i}.pdf", 100) for i in range(3)]  # 3 × ~100KB PDF → base64 ~400KB
    few_zip = make_zip("few.zip", few_pdfs, store=True)
    resp = client.post(
        "/tools/zip-extractor/analyze",
        data={"files": [(io.BytesIO(few_zip), "few.zip")]},
        content_type="multipart/form-data",
    )
    d = resp.get_json()
    print(f"  status: {resp.status_code}, total: {d.get('total')}, truncated: {d.get('truncated')}")
    assert resp.status_code == 200
    assert d["total"] == 3
    assert not d.get("truncated")
    print("  PASS")

    # ===== F: 空提交 =====
    print("\n=== F. 无文件 → 400 ===")
    resp = client.post("/tools/zip-extractor/analyze", data={}, content_type="multipart/form-data")
    print(f"  status: {resp.status_code}, error: {resp.get_json().get('error')}")
    assert resp.status_code == 400
    print("  PASS")

    # ===== G: 非 zip 文件 =====
    print("\n=== G. 上传非 zip 文件 → 应忽略或提示 ===")
    resp = client.post(
        "/tools/zip-extractor/analyze",
        data={"files": [(io.BytesIO(b"plain text"), "readme.txt")]},
        content_type="multipart/form-data",
    )
    d = resp.get_json()
    print(f"  status: {resp.status_code}, error: {d.get('error')}")
    assert resp.status_code == 400
    print("  PASS")

    # ===== H: 多层嵌套 zip =====
    print("\n=== H. 嵌套 3 层 zip，验证递归 ===")
    inner_pdf = make_zip("inner.zip", [("deep.pdf", 3)], store=True)
    mid_zip = make_zip("mid.zip", [("inner.zip", 0)])  # placeholder, 会被覆盖
    # 重写 mid_zip 让 inner.zip 内容是真正的 inner_zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("inner.zip", inner_pdf)
    mid_zip = buf.getvalue()

    outer_buf = io.BytesIO()
    with zipfile.ZipFile(outer_buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("mid.zip", mid_zip)
    outer_zip = outer_buf.getvalue()
    print(f"  outer.zip: {len(outer_zip)} B，内含 3 层 → 应提取 1 个 deep.pdf")

    resp = client.post(
        "/tools/zip-extractor/analyze",
        data={"files": [(io.BytesIO(outer_zip), "outer.zip")]},
        content_type="multipart/form-data",
    )
    d = resp.get_json()
    print(f"  status: {resp.status_code}, total: {d.get('total')}")
    assert resp.status_code == 200
    assert d["total"] == 1
    print(f"  PASS（path_chain={d['files'][0].get('path_chain')}）")

    print("\n========== 全部测试通过 ==========")


if __name__ == "__main__":
    main()
