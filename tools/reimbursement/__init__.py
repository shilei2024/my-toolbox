"""
报销助手 — 发票上传、OCR 识别、封面生成、批量打印。

流程：上传发票 → 识别/录入明细 → 填写报销信息 → 生成封面 → 打印
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, session

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import csrf, limiter

tool_bp = Blueprint("reimbursement", __name__)

# ---------------------------------------------------------------------------
# 参考数据 — 来自公司 ERP 系统的产品线/办事处/部门
# ---------------------------------------------------------------------------
PRODUCT_LINES = [
    {"name": "DIODES", "code": "01", "office": "深圳办"},
    {"name": "MSTAR", "code": "02", "office": "厦门办"},
    {"name": "MSTAR-OTHERS", "code": "0201", "office": "杭州办"},
    {"name": "MSTAR-GPS", "code": "0202", "office": "上海办"},
    {"name": "MSTAR-OTT", "code": "0203", "office": "北京办"},
    {"name": "MSTAR-SIGMA", "code": "0204", "office": "合肥办"},
    {"name": "星宸", "code": "0205", "office": "西安办"},
    {"name": "MSTAR-MTK", "code": "0206", "office": ""},
    {"name": "MSTAR-RAFAEL", "code": "0222", "office": ""},
    {"name": "3PEAK", "code": "03", "office": ""},
    {"name": "KEMET", "code": "04", "office": ""},
    {"name": "REALTEK", "code": "05", "office": ""},
    {"name": "PANASONIC", "code": "06", "office": ""},
    {"name": "SILERGY", "code": "07", "office": ""},
    {"name": "SILERGY AC-DC", "code": "0701", "office": ""},
    {"name": "SILERGY DC-DC", "code": "0702", "office": ""},
    {"name": "SILERGY OTHERS", "code": "0703", "office": ""},
    {"name": "VIC", "code": "08", "office": ""},
    {"name": "艾为", "code": "09", "office": ""},
    {"name": "VANCHIP", "code": "10", "office": ""},
    {"name": "LITEON", "code": "11", "office": ""},
    {"name": "长虹WIFI模块", "code": "12", "office": ""},
    {"name": "创达特", "code": "13", "office": ""},
    {"name": "MEGACHIPS", "code": "14", "office": ""},
    {"name": "兴芯微", "code": "15", "office": ""},
    {"name": "ZTE", "code": "16", "office": ""},
    {"name": "西安紫光国芯", "code": "17", "office": ""},
    {"name": "CHIP-LEAD", "code": "18", "office": ""},
    {"name": "VIVA", "code": "19", "office": ""},
    {"name": "SINOPOWER", "code": "20", "office": ""},
    {"name": "比亚迪", "code": "21", "office": ""},
    {"name": "芯天下", "code": "22", "office": ""},
    {"name": "东软载波", "code": "23", "office": ""},
    {"name": "FEELING-TECH", "code": "24", "office": ""},
    {"name": "明月微", "code": "25", "office": ""},
    {"name": "海矽美", "code": "26", "office": ""},
    {"name": "DREAMTECH", "code": "27", "office": ""},
    {"name": "新大陆", "code": "28", "office": ""},
    {"name": "SENSORTEK", "code": "29", "office": ""},
    {"name": "FITIPOWER", "code": "30", "office": ""},
    {"name": "信炜", "code": "31", "office": ""},
    {"name": "AMPHENOL", "code": "32", "office": ""},
    {"name": "P2I", "code": "33", "office": ""},
    {"name": "CHIPOWN", "code": "34", "office": ""},
    {"name": "ANYKA", "code": "35", "office": ""},
    {"name": "思泰迪", "code": "36", "office": ""},
    {"name": "I-PEX", "code": "37", "office": ""},
    {"name": "费用", "code": "38", "office": ""},
    {"name": "太盟", "code": "39", "office": ""},
    {"name": "CAPELLA", "code": "40", "office": ""},
    {"name": "IMAGIS", "code": "41", "office": ""},
    {"name": "希荻微", "code": "42", "office": ""},
    {"name": "EVEREST", "code": "43", "office": ""},
    {"name": "YMIN", "code": "44", "office": ""},
    {"name": "JOULWATT", "code": "45", "office": ""},
    {"name": "DSPG", "code": "46", "office": ""},
    {"name": "CME", "code": "47", "office": ""},
    {"name": "SIGMA-EZVIZ", "code": "48", "office": ""},
    {"name": "临泰微", "code": "49", "office": ""},
    {"name": "老威欣", "code": "50", "office": ""},
    {"name": "新威欣", "code": "51", "office": ""},
    {"name": "厦门威欣", "code": "52", "office": ""},
    {"name": "澎湃微", "code": "53", "office": ""},
    {"name": "TI", "code": "54", "office": ""},
    {"name": "UnitedSiC", "code": "55", "office": ""},
    {"name": "易冲", "code": "56", "office": ""},
    {"name": "海思", "code": "57", "office": ""},
    {"name": "停用存货", "code": "94", "office": ""},
    {"name": "外箱", "code": "98", "office": ""},
    {"name": "其他", "code": "99", "office": ""},
    {"name": "其他-SSFI", "code": "9901", "office": ""},
    {"name": "其他-新大陆", "code": "9902", "office": ""},
    {"name": "其他-KINETIC", "code": "9903", "office": ""},
    {"name": "其他-村田", "code": "9904", "office": ""},
    {"name": "其他-BELLING", "code": "9905", "office": ""},
    {"name": "其他-DAVICOM", "code": "9906", "office": ""},
    {"name": "其他-乐沪", "code": "9907", "office": ""},
    {"name": "其他-威富锐", "code": "9908", "office": ""},
    {"name": "其他-UTC", "code": "9909", "office": ""},
    {"name": "其他-美思先端", "code": "9910", "office": ""},
    {"name": "其他-珊口", "code": "9911", "office": ""},
    {"name": "其他-RUNIC", "code": "9912", "office": ""},
    {"name": "其他-欢创", "code": "9913", "office": ""},
    {"name": "其他-移柯", "code": "9914", "office": ""},
    {"name": "其他-博流", "code": "9915", "office": ""},
    {"name": "其他-SSM", "code": "9916", "office": ""},
    {"name": "其他-RichWave", "code": "9917", "office": ""},
    {"name": "其他-捷捷微", "code": "9918", "office": ""},
    {"name": "其他-炬佑", "code": "9920", "office": ""},
    {"name": "其他-启英泰伦", "code": "9921", "office": ""},
    {"name": "其他-众智", "code": "9922", "office": ""},
    {"name": "其他-金贝", "code": "9923", "office": ""},
    {"name": "其他-爱信诺", "code": "9924", "office": ""},
    {"name": "其他-齐展", "code": "9925", "office": ""},
    {"name": "其他-瀚昕微", "code": "9926", "office": ""},
    {"name": "其他-维晟", "code": "9927", "office": ""},
    {"name": "其他-致象尔微", "code": "9928", "office": ""},
    {"name": "其他-爱普特", "code": "9929", "office": ""},
    {"name": "其他-启达微", "code": "9930", "office": ""},
    {"name": "其他-芯朋微", "code": "9931", "office": ""},
    {"name": "其他-凌思微", "code": "9932", "office": ""},
    {"name": "其他-MOSFET", "code": "9933", "office": ""},
    {"name": "其他-国民技术", "code": "9934", "office": ""},
    {"name": "其他-零星", "code": "9999", "office": ""},
]

OFFICES = [
    "深圳办", "厦门办", "杭州办", "上海办", "北京办",
    "合肥办", "西安办", "贸易组", "",
]

DEPARTMENTS = [
    "业务部", "市场部", "行政部",
]

EXPENSE_CATEGORIES = [
    {"key": "entertainment", "label": "招待费", "default": 0},
    {"key": "travel_transport", "label": "出差交通费", "default": 0},
    {"key": "travel_hotel", "label": "出差住宿费", "default": 0},
    {"key": "local_transport", "label": "市内交通费", "default": 0},
    {"key": "vehicle", "label": "车辆费用", "default": 0},
    {"key": "communication", "label": "通讯费", "default": 0},
    {"key": "office_supplies", "label": "办公费", "default": 0},
    {"key": "delivery", "label": "快递费", "default": 0},
    {"key": "welfare", "label": "福利", "default": 0},
]

CUSTOMER_LEVELS = [
    {"name": "0-1", "label": "0-1"},
    {"name": "level 1", "label": "level 1"},
    {"name": "level 2", "label": "level 2"},
    {"name": "level 3", "label": "level 3"},
]

ENTERTAINMENT_CATEGORIES = ["餐费", "送礼", "其他"]


# ---------------------------------------------------------------------------
# 金额大写转换
# ---------------------------------------------------------------------------
def _number_to_chinese(amount: float) -> str:
    """将金额转换为中文大写（如 5616.10 → 伍仟陆佰壹拾陆元壹角整）"""
    if amount == 0:
        return "零元整"
    digit_cn = ["零", "壹", "贰", "叁", "肆", "伍", "陆", "柒", "捌", "玖"]
    radices_cn = ["", "拾", "佰", "仟", "万", "拾", "佰", "仟", "亿"]
    fraction_cn = ["角", "分"]

    yuan = int(amount)
    jiao = int(round((amount - yuan) * 10))
    fen = int(round((amount - yuan - jiao / 10) * 100))

    # 整数部分
    result = ""
    if yuan == 0:
        result = "零"
    else:
        s = str(yuan)
        n = len(s)
        need_zero = False
        for i, ch in enumerate(s):
            d = int(ch)
            pos = n - i - 1
            if d == 0:
                need_zero = True
                if pos % 4 == 0 and pos > 0:
                    result += radices_cn[pos]
                    need_zero = False
            else:
                if need_zero:
                    result += "零"
                    need_zero = False
                result += digit_cn[d] + radices_cn[pos]
        if result.endswith("零"):
            result = result[:-1]
    result += "元"

    # 小数部分
    if jiao == 0 and fen == 0:
        result += "整"
    else:
        if jiao > 0:
            result += digit_cn[jiao] + fraction_cn[0]
        if fen > 0:
            result += digit_cn[fen] + fraction_cn[1]
        else:
            result += "整"
    return result


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "reimbursement",
            "name": "报销助手",
            "icon": "bi-receipt",
            "color": "#198754",
        },
        remaining=remaining_for("reimbursement"),
        body_template="tools/reimbursement/_body.html",
    )


@tool_bp.post("/upload")
@csrf.exempt
@limiter.limit(lambda: "20/minute")
@require_usage("reimbursement")
def upload():
    """上传发票图片/PDF，返回缩略图 URL。"""
    f = request.files.get("file")
    if not f or f.filename == "":
        return jsonify(error="请选择文件"), 400

    ext = Path(f.filename).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png", ".pdf", ".bmp", ".gif", ".webp"}
    if ext not in allowed:
        return jsonify(error=f"不支持的文件格式：{ext}"), 400

    # 保存到 uploads 目录
    upload_dir = Path(current_app.config["UPLOAD_DIR"]) / "reimbursement"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4().hex[:12]
    safe_name = f"{file_id}{ext}"
    filepath = upload_dir / safe_name
    f.save(str(filepath))

    commit_usage("reimbursement")

    return jsonify(
        success=True,
        file_id=file_id,
        filename=safe_name,
        original_name=f.filename,
        preview_url=f"/tools/reimbursement/preview/{safe_name}",
        size=filepath.stat().st_size,
    )


@tool_bp.get("/preview/<filename>")
def preview(filename):
    """返回上传文件的缩略图/预览。"""
    from flask import send_file

    filepath = Path(current_app.config["UPLOAD_DIR"]) / "reimbursement" / filename
    if not filepath.exists():
        return jsonify(error="文件不存在"), 404

    ext = filepath.suffix.lower()
    mimetypes = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".pdf": "application/pdf",
    }
    return send_file(
        str(filepath),
        mimetype=mimetypes.get(ext, "application/octet-stream"),
        max_age=3600,
    )


@tool_bp.post("/ocr/<file_id>")
@csrf.exempt
@limiter.limit(lambda: "10/minute")
@require_usage("reimbursement")
def ocr(file_id):
    """
    OCR 识别发票信息。

    优先级：
    1. 百度智能云增值税发票识别 (BAIDU_OCR_API_KEY + BAIDU_OCR_SECRET_KEY)
    2. 本地 PaddleOCR (PADDLEOCR_ENABLED=true)
    3. 模拟模式（返回空模板供手动填写）
    """
    # 查找文件
    f = request.files.get("file")
    upload_dir = Path(current_app.config["UPLOAD_DIR"]) / "reimbursement"
    filepath = None

    if f and f.filename != "":
        ext = Path(f.filename).suffix.lower()
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{file_id}{ext}"
        filepath = upload_dir / safe_name
        f.save(str(filepath))
    else:
        # 从已上传文件中按 file_id 查找
        for p in upload_dir.glob(f"{file_id}.*"):
            filepath = p
            break

    if not filepath or not filepath.exists():
        return jsonify(error="文件未找到，请重新上传"), 404

    # 尝试百度云 OCR
    baidu_key = os.environ.get("BAIDU_OCR_API_KEY", "").strip()
    baidu_secret = os.environ.get("BAIDU_OCR_SECRET_KEY", "").strip()

    if baidu_key and baidu_secret:
        result = _baidu_ocr_invoice(filepath, baidu_key, baidu_secret)
        if result:
            return jsonify(success=True, file_id=file_id, data=result, provider="baidu")

    # 尝试 PaddleOCR
    if os.environ.get("PADDLEOCR_ENABLED", "").strip() == "true":
        result = _paddle_ocr_invoice(filepath)
        if result:
            return jsonify(success=True, file_id=file_id, data=result, provider="paddleocr")

    # 模拟模式
    return jsonify(
        success=True,
        file_id=file_id,
        data={
            "invoice_number": "",
            "invoice_date": "",
            "seller_name": "",
            "amount_excluding_tax": "",
            "tax_amount": "",
            "total_amount": "",
            "description": "",
        },
        provider="mock",
        note="未配置 OCR 服务，请手动填写。支持百度云 OCR/PaddleOCR。",
    )


def _baidu_ocr_invoice(filepath: Path, api_key: str, secret_key: str) -> dict | None:
    """调用百度智能云增值税发票识别 API。"""
    import base64
    from urllib.parse import quote

    try:
        # Step 1: 获取 access_token
        token_url = (
            "https://aip.baidubce.com/oauth/2.0/token"
            f"?grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}"
        )
        token_resp = __import__("requests").get(token_url, timeout=10)
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            current_app.logger.warning("Baidu token failed: %s", token_data)
            return None

        # Step 2: 读取图片，PDF 需转换
        ext = filepath.suffix.lower()
        img_bytes = None

        if ext == ".pdf":
            # PDF 转图片（取第一页）
            try:
                from pdf2image import convert_from_path
                images = convert_from_path(str(filepath), first_page=1, last_page=1, dpi=200)
                if images:
                    import io as _io
                    buf = _io.BytesIO()
                    images[0].save(buf, format="PNG")
                    img_bytes = buf.getvalue()
            except Exception as e:
                current_app.logger.warning("PDF to image failed: %s", e)
                return None
        else:
            with open(filepath, "rb") as f:
                img_bytes = f.read()

        if not img_bytes:
            return None

        # Step 3: Base64 编码并显式 URL 编码
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
        img_encoded = quote(img_b64, safe="")  # 对 + / = 等字符做百分号编码

        # Step 4: 调用增值税发票识别
        ocr_url = (
            "https://aip.baidubce.com/rest/2.0/ocr/v1/vat_invoice"
            f"?access_token={access_token}"
        )
        # 必须手动拼接 form body，确保 image 值被正确 urlencode
        body = f"image={img_encoded}"
        ocr_resp = __import__("requests").post(
            ocr_url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        ocr_data = ocr_resp.json()

        # 检查错误
        err_code = ocr_data.get("error_code")
        if err_code:
            err_msg = ocr_data.get("error_msg", "")
            current_app.logger.warning(
                "Baidu VAT OCR error [%s]: %s", err_code, err_msg
            )

            # 如果不是增值税发票，尝试通用 OCR
            if err_code in (216100, 216101, 216102, 282103, 282104):
                return _baidu_general_ocr(img_bytes, access_token)

            return None

        words = ocr_data.get("words_result", {})

        def _get(field: str) -> str:
            val = words.get(field, "")
            if isinstance(val, list):
                return val[0] if val else ""
            return str(val) if val else ""

        amount = _get("AmountInFiguers") or _get("TotalAmount") or ""
        tax = _get("TaxAmount") or ""
        amount_no_tax = ""
        try:
            if amount and tax:
                amount_no_tax = str(round(float(amount) - float(tax), 2))
        except (ValueError, TypeError):
            pass

        return {
            "invoice_number": _get("InvoiceNum") or _get("InvoiceCodeConfirm"),
            "invoice_date": _get("InvoiceDate"),
            "seller_name": _get("SellerName"),
            "seller_tax_id": _get("SellerRegisterNum"),
            "buyer_name": _get("PurchaserName"),
            "buyer_tax_id": _get("PurchaserRegisterNum"),
            "amount_excluding_tax": amount_no_tax,
            "tax_amount": tax,
            "total_amount": amount,
            "description": _get("CommodityName") or "",
        }

    except Exception as exc:
        current_app.logger.warning("Baidu OCR exception: %s", exc)
        return None


def _baidu_general_ocr(img_bytes: bytes, access_token: str) -> dict | None:
    """通用 OCR 作为增值税发票识别的降级方案。"""
    import base64
    from urllib.parse import quote

    try:
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
        img_encoded = quote(img_b64, safe="")

        url = (
            "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
            f"?access_token={access_token}"
        )
        body = f"image={img_encoded}"
        resp = __import__("requests").post(
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        data = resp.json()

        if data.get("error_code"):
            current_app.logger.warning(
                "Baidu general OCR error [%s]: %s",
                data.get("error_code"), data.get("error_msg", ""),
            )
            return None

        # 提取文本
        words = data.get("words_result", [])
        lines = [w.get("words", "") for w in words]
        full_text = " ".join(lines)

        # 尝试用正则提取关键字段
        import re
        inv_num = ""
        inv_date = ""
        total = ""

        m = re.search(r"发票号码[：:]\s*(\S+)", full_text)
        if m: inv_num = m.group(1)
        m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", full_text)
        if m: inv_date = m.group(1)
        m = re.search(r"[价税合计小写]+\s*[¥￥]\s*(\d+\.?\d*)", full_text)
        if m: total = m.group(1)

        return {
            "invoice_number": inv_num,
            "invoice_date": inv_date,
            "seller_name": "",
            "amount_excluding_tax": "",
            "tax_amount": "",
            "total_amount": total,
            "description": "",
        }

    except Exception as exc:
        current_app.logger.warning("Baidu general OCR exception: %s", exc)
        return None


def _paddle_ocr_invoice(filepath: Path) -> dict | None:
    """本地 PaddleOCR 识别（需提前安装 paddleocr）。"""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        current_app.logger.warning("PaddleOCR not installed")
        return None

    try:
        ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr_engine.ocr(str(filepath), cls=True)

        # 提取所有文本行
        lines = []
        if result and result[0]:
            for line_info in result[0]:
                text = line_info[1][0] if len(line_info) > 1 else ""
                conf = line_info[1][1] if len(line_info) > 1 else 0
                lines.append((text, conf))

        full_text = "\n".join([t[0] for t in lines])

        # 简单规则提取（PaddleOCR 不返回结构化发票数据，仅能做参考）
        import re

        invoice_number = ""
        invoice_date = ""
        total_amount = ""
        seller_name = ""

        # 发票号码：通常10位数字
        m = re.search(r"发票号码[:：]?\s*(\d{8,20})", full_text)
        if m:
            invoice_number = m.group(1)

        # 开票日期
        m = re.search(r"(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)", full_text)
        if m:
            invoice_date = m.group(1)

        # 价税合计
        m = re.search(r"[价税合计小写].*?[¥￥]\s*(\d+\.?\d*)", full_text)
        if m:
            total_amount = m.group(1)

        return {
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "seller_name": seller_name,
            "amount_excluding_tax": "",
            "tax_amount": "",
            "total_amount": total_amount,
            "description": "",
        }

    except Exception as exc:
        current_app.logger.warning("PaddleOCR exception: %s", exc)
        return None


@tool_bp.get("/reference")
def reference_data():
    """返回参考数据：产品线、办事处、部门、费用类别等。"""
    return jsonify(
        product_lines=PRODUCT_LINES,
        offices=OFFICES,
        departments=DEPARTMENTS,
        expense_categories=EXPENSE_CATEGORIES,
        customer_levels=CUSTOMER_LEVELS,
        entertainment_categories=ENTERTAINMENT_CATEGORIES,
    )


@tool_bp.post("/cover-data")
@csrf.exempt
def cover_data():
    """
    接收前端传来的完整报销数据，返回封面所需的汇总计算结果。

    前端发送：
    {
        "header": {"employee_name":"","department":"","date":"","reason":"","period":""},
        "invoices": [{...发票字段..., "product_line":"","expense_type":"","office":"",
                       "customer_level":"","entertainment":{...}, "vehicle":{...}, "travel":{...} }]
    }
    后端返回汇总 + 中文大写金额。
    """
    data = request.get_json(silent=True) or {}
    header = data.get("header", {})
    invoices = data.get("invoices", [])

    # 按产品线+代码分组汇总
    groups: dict[str, dict] = {}
    for inv in invoices:
        pl_name = inv.get("product_line", "") or "未分类"
        pl_code = inv.get("product_line_code", "") or "-"
        office = inv.get("office", "") or ""
        key = f"{pl_code}|{pl_name}"

        total = float(inv.get("total_amount", 0) or 0)
        exp_type = inv.get("expense_type", "")

        if key not in groups:
            groups[key] = {
                "product_line": pl_name,
                "code": pl_code,
                "office": office,
                "totals": {c["key"]: 0.0 for c in EXPENSE_CATEGORIES},
                "remarks": [],
            }
        for cat in EXPENSE_CATEGORIES:
            if exp_type == cat["key"]:
                groups[key]["totals"][cat["key"]] += total
        rem = inv.get("remarks", "") or ""
        if rem and rem not in groups[key]["remarks"]:
            groups[key]["remarks"].append(rem)

    # 排序
    sorted_groups = sorted(groups.values(), key=lambda g: g["code"])

    # 合计
    grand_totals = {c["key"]: 0.0 for c in EXPENSE_CATEGORIES}
    for g in sorted_groups:
        for k in grand_totals:
            grand_totals[k] += g["totals"][k]

    total_all = sum(grand_totals.values())

    # 按费用类别汇总（封面左下角）
    expense_summary = [
        {
            "key": cat["key"],
            "label": cat["label"],
            "amount": round(grand_totals[cat["key"]], 2),
        }
        for cat in EXPENSE_CATEGORIES
    ]

    # 按客户等级汇总（费用分类表）
    level_groups: dict[str, dict] = {}
    for inv in invoices:
        level = inv.get("customer_level", "") or "未分类"
        total = float(inv.get("total_amount", 0) or 0)
        exp_type = inv.get("expense_type", "")
        if level not in level_groups:
            level_groups[level] = {
                "level": level,
                "entertainment": 0.0,
                "travel": 0.0,
                "other": 0.0,
                "total": 0.0,
            }

        if exp_type in ("entertainment",):
            level_groups[level]["entertainment"] += total
        elif exp_type in ("travel_transport", "travel_hotel"):
            level_groups[level]["travel"] += total
        else:
            level_groups[level]["other"] += total
        level_groups[level]["total"] += total

    # 应酬费明细
    entertainment_details = []
    for inv in invoices:
        ent = inv.get("entertainment", {})
        if ent and ent.get("amount", ""):
            entertainment_details.append({
                "date": ent.get("date", ""),
                "category": ent.get("category", ""),
                "place": ent.get("place", ""),
                "customer": ent.get("customer", ""),
                "participants": ent.get("participants", ""),
                "amount": float(ent.get("amount", 0) or 0),
                "purpose": ent.get("purpose", ""),
            })

    # 派车单明细
    vehicle_details = []
    for inv in invoices:
        veh = inv.get("vehicle", {})
        km = float(veh.get("km_total", 0) or 0)
        toll = float(veh.get("toll_fee", 0) or 0)
        parking = float(veh.get("parking_fee", 0) or 0)
        if km > 0 or toll > 0 or parking > 0:
            vehicle_details.append({
                "date": veh.get("date", ""),
                "from_location": veh.get("from_location", ""),
                "to_location": veh.get("to_location", ""),
                "contact": veh.get("contact", ""),
                "km_start": veh.get("km_start", ""),
                "km_end": veh.get("km_end", ""),
                "km_total": km,
                "toll_fee": toll,
                "parking_fee": parking,
                "remarks": veh.get("remarks", ""),
            })

    # 出差明细
    travel_details = []
    for inv in invoices:
        tr = inv.get("travel", {})
        amt = float(tr.get("amount", 0) or 0)
        if tr and amt > 0:
            travel_details.append({
                "date": tr.get("date", ""),
                "location": tr.get("location", ""),
                "customer": tr.get("customer", ""),
                "expense_type": tr.get("expense_type", ""),
                "amount": amt,
                "purpose": tr.get("purpose", ""),
            })

    return jsonify(
        success=True,
        header=header,
        groups=sorted_groups,
        grand_totals={
            cat["key"]: round(grand_totals[cat["key"]], 2)
            for cat in EXPENSE_CATEGORIES
        },
        expense_summary=expense_summary,
        total_all=round(total_all, 2),
        total_cn=_number_to_chinese(round(total_all, 2)),
        invoice_count=len(invoices),
        level_groups=list(level_groups.values()),
        entertainment_details=entertainment_details,
        vehicle_details=vehicle_details,
        travel_details=travel_details,
        expense_categories=EXPENSE_CATEGORIES,
        customer_levels=CUSTOMER_LEVELS,
    )


# ---------------------------------------------------------------------------
# 模板下载
# ---------------------------------------------------------------------------
TEMPLATES = {
    "entertainment": "应酬费_出差明细_派车单_模板.xls",
    "cover": "报销封面及费用分类表_模板.xls",
}

@tool_bp.get("/templates")
def list_templates():
    """列出可下载的空白模板。"""
    return jsonify(
        templates=[
            {
                "id": "entertainment",
                "name": "应酬费、出差明细、派车单模板",
                "download": "/tools/reimbursement/download-template/entertainment",
            },
            {
                "id": "cover",
                "name": "报销封面及费用分类表模板",
                "download": "/tools/reimbursement/download-template/cover",
            },
        ]
    )


@tool_bp.get("/download-template/<template_id>")
def download_template(template_id):
    """下载空白模板文件。"""
    from flask import send_file

    filename = TEMPLATES.get(template_id)
    if not filename:
        return jsonify(error="模板不存在"), 404

    filepath = Path(current_app.config["UPLOAD_DIR"]) / "reimbursement_templates" / filename
    if not filepath.exists():
        return jsonify(error="模板文件不存在"), 404

    return send_file(
        str(filepath),
        mimetype="application/vnd.ms-excel",
        as_attachment=True,
        download_name=filename,
    )


# ---------------------------------------------------------------------------
# 导出 Excel（保持原格式）
# ---------------------------------------------------------------------------
def _excel_styles():
    """共享样式对象，避免重复创建。"""
    import openpyxl
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    thin = Border(left=Side("thin"), right=Side("thin"), top=Side("thin"), bottom=Side("thin"))
    return {
        "thin": thin,
        "title": Font(name="微软雅黑", size=14, bold=True),
        "subtitle": Font(name="微软雅黑", size=12, bold=True),
        "header": Font(name="微软雅黑", size=10, bold=True),
        "normal": Font(name="微软雅黑", size=10),
        "bold": Font(name="微软雅黑", size=10, bold=True),
        "header_fill": PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "left": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "right": Alignment(horizontal="right", vertical="center"),
    }


def _build_cover_file(cover_data):
    """
    生成文件1：报销封面及费用分类表.xlsx
    两张表：「费用报销单」封面 +「费用分类表」
    格式严格参照原始模板。
    """
    import io, openpyxl
    from openpyxl.utils import get_column_letter
    s = _excel_styles()

    wb = openpyxl.Workbook()
    header = cover_data.get("header", {})
    groups = cover_data.get("groups", [])
    expense_cats = EXPENSE_CATEGORIES
    total_all = cover_data.get("total_all", 0)
    total_cn = cover_data.get("total_cn", "")

    # ===== Sheet 1: 费用报销单 =====
    ws = wb.active
    ws.title = "封面"
    # 页面设置 A4 纵向
    ws.sheet_properties.pageSetUpPr = openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = 9  # A4

    # 标题
    ws.merge_cells("A1:O1")
    c = ws["A1"]; c.value = "费 用 报 销 单"; c.font = s["title"]; c.alignment = s["center"]
    ws.row_dimensions[1].height = 36

    # 空行
    ws.row_dimensions[2].height = 6
    ws.row_dimensions[3].height = 6

    # 信息行
    EMP = header.get("employee_name", "")
    DEPT = header.get("department", "")
    DATE = header.get("date", "")
    ws.merge_cells("A4:C4"); ws["A4"].value = f"员工姓名：{EMP}"; ws["A4"].font = s["normal"]
    ws.merge_cells("G4:I4"); ws["G4"].value = f"部门：{DEPT}"; ws["G4"].font = s["normal"]
    ws.merge_cells("L4:M4"); ws["L4"].value = f"报销日期：{DATE}"; ws["L4"].font = s["normal"]

    ws.row_dimensions[4].height = 6

    # 表头行
    row = 6
    col_headers = ["序号", "产品线", "代码", "办事处", "费用期间"]
    for cat in expense_cats:
        col_headers.append(cat["label"])
    col_headers.append("备注栏")

    for ci, h in enumerate(col_headers, 1):
        cell = ws.cell(row=row, column=ci, value=h)
        cell.font = s["header"]; cell.fill = s["header_fill"]; cell.alignment = s["center"]; cell.border = s["thin"]
    ws.row_dimensions[row].height = 22

    # 数据行
    for gi, g in enumerate(groups):
        row += 1
        vals = [gi + 1, g["product_line"], g["code"], g.get("office", ""), header.get("period", "")]
        for cat in expense_cats:
            v = g["totals"].get(cat["key"], 0)
            vals.append(v if v != 0 else "")
        vals.append("；".join(g.get("remarks", [])))

        for ci, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=ci, value=v)
            cell.font = s["normal"]; cell.border = s["thin"]
            cell.alignment = s["right"] if isinstance(v, (int, float)) and v != "" else s["center"]

    # 合计行
    row += 1
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=5)
    for ci2 in range(1, len(col_headers) + 1):
        ws.cell(row=row, column=ci2).border = s["thin"]
    ws.cell(row=row, column=2).value = "合 计"
    ws.cell(row=row, column=2).font = s["bold"]; ws.cell(row=row, column=2).alignment = s["center"]

    for ci, cat in enumerate(expense_cats, 6):
        v = cover_data["grand_totals"].get(cat["key"], 0)
        cell = ws.cell(row=row, column=ci, value=v if v != 0 else "")
        cell.font = s["bold"]; cell.alignment = s["right"]

    # 总金额区
    row += 2
    INV_COUNT = cover_data.get("invoice_count", 0)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.cell(row=row, column=1).value = f"费用总额（小写）：¥ {total_all:,.2f}"; ws.cell(row=row, column=1).font = s["normal"]
    ws.cell(row=row, column=6).value = f"单据张数：{INV_COUNT} 张"; ws.cell(row=row, column=6).font = s["normal"]
    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    ws.cell(row=row, column=1).value = f"费用总额（大写）：{total_cn}"; ws.cell(row=row, column=1).font = s["normal"]

    # 签字区
    row += 2
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws.cell(row=row, column=2).value = f"申请人：{EMP}"; ws.cell(row=row, column=2).font = s["normal"]
    ws.merge_cells(start_row=row, start_column=7, end_row=row, end_column=8)
    ws.cell(row=row, column=7).value = "财务审核："; ws.cell(row=row, column=7).font = s["normal"]
    ws.merge_cells(start_row=row, start_column=10, end_row=row, end_column=11)
    ws.cell(row=row, column=10).value = "部门主管："; ws.cell(row=row, column=10).font = s["normal"]
    ws.merge_cells(start_row=row, start_column=13, end_row=row, end_column=14)
    ws.cell(row=row, column=13).value = "总经理："; ws.cell(row=row, column=13).font = s["normal"]

    row += 1
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws.cell(row=row, column=2).value = f"日期：{DATE}"; ws.cell(row=row, column=2).font = s["normal"]
    ws.merge_cells(start_row=row, start_column=7, end_row=row, end_column=8)
    ws.cell(row=row, column=7).value = "日期："; ws.cell(row=row, column=7).font = s["normal"]
    ws.merge_cells(start_row=row, start_column=10, end_row=row, end_column=11)
    ws.cell(row=row, column=10).value = "日期："; ws.cell(row=row, column=10).font = s["normal"]
    ws.merge_cells(start_row=row, start_column=13, end_row=row, end_column=14)
    ws.cell(row=row, column=13).value = "日期："; ws.cell(row=row, column=13).font = s["normal"]

    # 列宽
    col_widths = [6, 18, 6, 8, 10] + [9] * len(expense_cats) + [16]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ===== Sheet 2: 按客户等级费用分类明细表 =====
    ws2 = wb.create_sheet("费用分类表")
    ws2.merge_cells("A1:H1")
    ws2["A1"].value = "按客户等级费用分类明细表"; ws2["A1"].font = s["title"]; ws2["A1"].alignment = s["center"]
    ws2.row_dimensions[1].height = 36
    ws2.row_dimensions[2].height = 6

    row = 4
    cls_h = ["序号", "客户等级", "招待费", "差旅费", "", "其他费用", "费用合计", "备注"]
    for ci, h in enumerate(cls_h, 1):
        cell = ws2.cell(row=row, column=ci, value=h)
        cell.font = s["header"]; cell.fill = s["header_fill"]; cell.alignment = s["center"]; cell.border = s["thin"]

    level_groups = cover_data.get("level_groups", [])
    lvl_order = {"0-1": 0, "level 1": 1, "level 2": 2, "level 3": 3}
    level_groups.sort(key=lambda lg: lvl_order.get(lg.get("level", ""), 99))

    for li, lg in enumerate(level_groups):
        row += 1
        vs = [li + 1, lg.get("level", ""),
              lg.get("entertainment", 0) or "", lg.get("travel", 0) or "", "",
              lg.get("other", 0) or "", lg.get("total", 0) or "", ""]
        for ci, v in enumerate(vs, 1):
            cell = ws2.cell(row=row, column=ci, value=v)
            cell.font = s["normal"]; cell.border = s["thin"]
            cell.alignment = s["right"] if isinstance(v, (int, float)) else s["center"]

    # 合计
    row += 1
    for ci2 in range(1, 9):
        ws2.cell(row=row, column=ci2).border = s["thin"]
    ws2.cell(row=row, column=2).value = "合 计"; ws2.cell(row=row, column=2).font = s["bold"]; ws2.cell(row=row, column=2).alignment = s["center"]
    lvl_tot = [
        sum(lg.get("entertainment", 0) for lg in level_groups),
        sum(lg.get("travel", 0) for lg in level_groups), "",
        sum(lg.get("other", 0) for lg in level_groups),
        total_all, "",
    ]
    for ci, v in enumerate(lvl_tot, 3):
        cell = ws2.cell(row=row, column=ci, value=v if v not in (0, "") else "")
        cell.font = s["bold"]; cell.alignment = s["right"]

    row += 2
    ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws2.cell(row=row, column=2).value = f"费用总额（小写）：¥ {total_all:,.2f}"; ws2.cell(row=row, column=2).font = s["normal"]
    row += 1
    ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws2.cell(row=row, column=2).value = f"费用总额（大写）：{total_cn}"; ws2.cell(row=row, column=2).font = s["normal"]

    row += 2
    ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws2.cell(row=row, column=2).value = f"申请人：{EMP}"; ws2.cell(row=row, column=2).font = s["normal"]
    ws2.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
    ws2.cell(row=row, column=6).value = "部门主管："; ws2.cell(row=row, column=6).font = s["normal"]
    row += 1
    ws2.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
    ws2.cell(row=row, column=2).value = f"日期：{DATE}"; ws2.cell(row=row, column=2).font = s["normal"]
    ws2.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
    ws2.cell(row=row, column=6).value = "日期："; ws2.cell(row=row, column=6).font = s["normal"]

    for i, w in enumerate([6, 12, 12, 12, 4, 12, 12, 12], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return buf


def _build_detail_file(cover_data, entertainment, vehicles, travels):
    """
    生成文件2：应酬费_出差明细_派车单.xlsx
    三张表：应酬费明细表 + 派车单 + 出差明细表
    格式严格参照原始模板。
    """
    import io, openpyxl
    from openpyxl.styles import Alignment
    from openpyxl.utils import get_column_letter
    s = _excel_styles()
    header = cover_data.get("header", {})

    wb = openpyxl.Workbook()

    # ===== Sheet 1: 应酬费明细表 =====
    ws = wb.active
    ws.title = "应酬费明细"
    ws.merge_cells("A1:H1")
    ws["A1"].value = "应酬费报销明细"; ws["A1"].font = s["title"]; ws["A1"].alignment = s["center"]
    ws.row_dimensions[1].height = 36

    ws.merge_cells("A2:C2")
    ws["A2"].value = f"员工姓名：{header.get('employee_name', '')}"; ws["A2"].font = s["normal"]

    row = 4
    eh = ["时间", "费用类别", "用餐地点、名称", "客户名称", "主要参与人全称", "金额", "事由（请注明是 主要推广哪条产品线）", "主管审批（超金额）"]
    for ci, h in enumerate(eh, 1):
        cell = ws.cell(row=row, column=ci, value=h)
        cell.font = s["header"]; cell.fill = s["header_fill"]; cell.alignment = s["center"]; cell.border = s["thin"]

    ent_total = 0
    for e in entertainment:
        row += 1
        amt = float(e.get("amount", 0) or 0)
        vals = [e.get("date", ""), e.get("category", ""), e.get("place", ""),
                e.get("customer", ""), e.get("participants", ""), amt or "",
                e.get("purpose", ""), ""]
        for ci, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=ci, value=v)
            cell.font = s["normal"]; cell.border = s["thin"]
            cell.alignment = s["right"] if ci == 6 else s["left"]
        ent_total += amt

    # 合计行
    row += 1
    for ci2 in range(1, 9):
        ws.cell(row=row, column=ci2).border = s["thin"]
    ws.cell(row=row, column=1).value = "合计"; ws.cell(row=row, column=1).font = s["bold"]; ws.cell(row=row, column=1).alignment = s["center"]
    ws.cell(row=row, column=6).value = ent_total or ""; ws.cell(row=row, column=6).font = s["bold"]; ws.cell(row=row, column=6).alignment = s["right"]

    for i, w in enumerate([12, 10, 18, 14, 18, 10, 18, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # ===== Sheet 2: 派车单 =====
    ws2 = wb.create_sheet("派车单")
    ws2.merge_cells("A1:J1")
    ws2["A1"].value = "威欣电子有限公司"; ws2["A1"].font = s["title"]; ws2["A1"].alignment = s["center"]
    ws2.row_dimensions[1].height = 36

    period_text = f" {header.get('period', '')}派车单" if header.get("period") else "派车单"
    ws2.merge_cells("A2:C2")
    ws2["A2"].value = f"员工姓名：{header.get('employee_name', '')}"; ws2["A2"].font = s["normal"]
    ws2.cell(row=2, column=8).value = period_text; ws2.cell(row=2, column=8).font = s["normal"]
    ws2.cell(row=2, column=8).alignment = Alignment(horizontal="right")

    row = 4
    vh1 = ["日期", "出发地", "目的地", "客户联系人", "行车路程", "", "公里数", "过桥费", "停车费", "备注"]
    ws2.merge_cells(start_row=row, start_column=5, end_row=row, end_column=6)
    for ci, h in enumerate(vh1, 1):
        if h == "" and ci == 6:
            continue  # 跳过合并单元格的非左上角
        cell = ws2.cell(row=row, column=ci, value=h)
        cell.font = s["header"]; cell.fill = s["header_fill"]; cell.alignment = s["center"]; cell.border = s["thin"]

    row += 1
    vh2 = ["", "", "", "", "起", "止", "", "", "", ""]
    for ci, h in enumerate(vh2, 1):
        cell = ws2.cell(row=row, column=ci, value=h)
        cell.font = s["header"]; cell.fill = s["header_fill"]; cell.alignment = s["center"]; cell.border = s["thin"]

    km_t, toll_t, park_t = 0, 0, 0
    for v in vehicles:
        row += 1
        km = float(v.get("km_total", 0) or 0); toll = float(v.get("toll_fee", 0) or 0); park = float(v.get("parking_fee", 0) or 0)
        vals = [v.get("date", ""), v.get("from_location", ""), v.get("to_location", ""),
                v.get("contact", ""), v.get("km_start", ""), v.get("km_end", ""),
                km or "", toll or "", park or "", v.get("remarks", "")]
        for ci, val in enumerate(vals, 1):
            cell = ws2.cell(row=row, column=ci, value=val)
            cell.font = s["normal"]; cell.border = s["thin"]
            cell.alignment = s["right"] if ci >= 7 else s["left"]
        km_t += km; toll_t += toll; park_t += park

    row += 1
    for ci2 in range(1, 11):
        ws2.cell(row=row, column=ci2).border = s["thin"]
    ws2.cell(row=row, column=1).value = "合计"; ws2.cell(row=row, column=1).font = s["bold"]; ws2.cell(row=row, column=1).alignment = s["center"]
    ws2.cell(row=row, column=7).value = km_t or ""; ws2.cell(row=row, column=7).font = s["bold"]; ws2.cell(row=row, column=7).alignment = s["right"]
    ws2.cell(row=row, column=8).value = toll_t or ""; ws2.cell(row=row, column=8).font = s["bold"]; ws2.cell(row=row, column=8).alignment = s["right"]
    ws2.cell(row=row, column=9).value = park_t or ""; ws2.cell(row=row, column=9).font = s["bold"]; ws2.cell(row=row, column=9).alignment = s["right"]

    for i, w in enumerate([12, 8, 18, 12, 8, 8, 8, 8, 8, 14], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    # ===== Sheet 3: 出差明细表 =====
    ws3 = wb.create_sheet("出差明细")
    ws3.merge_cells("A1:F1")
    ws3["A1"].value = "出差明细表"; ws3["A1"].font = s["title"]; ws3["A1"].alignment = s["center"]
    ws3.row_dimensions[1].height = 36

    ws3.merge_cells("A2:C2")
    ws3["A2"].value = f"员工姓名：{header.get('employee_name', '')}"; ws3["A2"].font = s["normal"]

    row = 4
    th = ["日期", "出差地", "客户名称", "费用类型", "金额", "事由（请注明是 主要推广哪条产品线）"]
    for ci, h in enumerate(th, 1):
        cell = ws3.cell(row=row, column=ci, value=h)
        cell.font = s["header"]; cell.fill = s["header_fill"]; cell.alignment = s["center"]; cell.border = s["thin"]

    tr_total = 0
    for t in travels:
        row += 1
        amt = float(t.get("amount", 0) or 0)
        vals = [t.get("date", ""), t.get("location", ""), t.get("customer", ""),
                t.get("expense_type", ""), amt or "", t.get("purpose", "")]
        for ci, v in enumerate(vals, 1):
            cell = ws3.cell(row=row, column=ci, value=v)
            cell.font = s["normal"]; cell.border = s["thin"]
            cell.alignment = s["right"] if ci == 5 else s["left"]
        tr_total += amt

    row += 1
    for ci2 in range(1, 7):
        ws3.cell(row=row, column=ci2).border = s["thin"]
    ws3.cell(row=row, column=1).value = "合计"; ws3.cell(row=row, column=1).font = s["bold"]; ws3.cell(row=row, column=1).alignment = s["center"]
    ws3.cell(row=row, column=5).value = tr_total or ""; ws3.cell(row=row, column=5).font = s["bold"]; ws3.cell(row=row, column=5).alignment = s["right"]

    for i, w in enumerate([12, 14, 14, 10, 10, 20], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf); buf.seek(0)
    return buf


@tool_bp.post("/export-cover")
@csrf.exempt
def export_cover():
    """导出文件1：报销封面及费用分类表.xlsx（2张表：封面 + 费用分类表）"""
    from flask import send_file
    data = request.get_json(silent=True) or {}
    cover_data = data.get("cover_data", {})
    if not cover_data:
        return jsonify(error="无封面数据"), 400
    try:
        buf = _build_cover_file(cover_data)
        emp = cover_data.get("header", {}).get("employee_name", "报销")
        period = cover_data.get("header", {}).get("period", "").replace(" ", "_")
        filename = f"报销封面及费用分类表_{emp}_{period}.xlsx"
        return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        current_app.logger.exception("export-cover failed")
        return jsonify(error=f"导出失败：{str(e)}"), 500


@tool_bp.post("/export-details")
@csrf.exempt
def export_details():
    """导出文件2：应酬费_出差明细_派车单.xlsx（3张表：应酬费明细 + 派车单 + 出差明细）"""
    from flask import send_file
    data = request.get_json(silent=True) or {}
    cover_data = data.get("cover_data", {})
    entertainment = data.get("entertainment", [])
    vehicles = data.get("vehicles", [])
    travels = data.get("travels", [])
    if not cover_data:
        return jsonify(error="无数据"), 400
    try:
        buf = _build_detail_file(cover_data, entertainment, vehicles, travels)
        emp = cover_data.get("header", {}).get("employee_name", "报销")
        period = cover_data.get("header", {}).get("period", "").replace(" ", "_")
        filename = f"应酬费_出差明细_派车单_{emp}_{period}.xlsx"
        return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=filename)
    except Exception as e:
        current_app.logger.exception("export-details failed")
        return jsonify(error=f"导出失败：{str(e)}"), 500
