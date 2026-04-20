import os
import csv
import json
import logging
import re
from pathlib import Path
from langchain.tools import tool    
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai import GenerativeModel

load_dotenv()

SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
INVENTORY_FILE    = Path("./inventory.csv")
GEMINI_MODEL      = "gemini-2.0-flash"

SYSTEM_PROMPT = """Bạn là chuyên gia OCR hóa đơn thuốc.
Hãy đọc hình ảnh này và trích xuất TẤT CẢ các thuốc xuất hiện trong hóa đơn.
Với mỗi thuốc, hãy tách riêng: tên thuốc và liều lượng (mg, ml, mcg, g, IU, %).
KHÔNG trả về số lượng mua, đơn giá, hoạt chất, hay thông tin nào khác.
Kết quả BẮT BUỘC chỉ là một JSON array thuần túy (không có markdown, không có ```json), theo format:
[
  {"ten_thuoc": "<Tên thuốc>", "lieu_luong": "<liều lượng hoặc null>", "full_name": "<Tên đầy đủ>"}
]
Nếu không tìm thấy thuốc nào, trả về: []"""

# SETUP LOGGING
def setup_logging() -> logging.Logger:
    """Console + File logging (logs/pipeline_<timestamp>.log)."""
    log_dir = Path("./logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logger = logging.getLogger("ocr_pill_pipeline")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  [%(levelname)-8s]  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.info(f"Log file: {log_file.resolve()}")
    return logger

# BƯỚC 1 — KHỞI TẠO GEMINI CLIENT
def _setup_gemini(logger: logging.Logger) -> GenerativeModel:
    logger.info("BƯỚC 1 — Khởi tạo Gemini client ...")
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.error("Không tìm thấy GEMINI_API_KEY trong file .env")
        raise EnvironmentError("GEMINI_API_KEY not set. Add it to .env: GEMINI_API_KEY=...")
    genai.configure(api_key=api_key)
    logger.info(f"Gemini client khởi tạo thành công | model: {GEMINI_MODEL}")
    return GenerativeModel(GEMINI_MODEL)

# BƯỚC 2 — TẢI DỮ LIỆU TỒN KHO
def _load_inventory(inventory_path: Path, logger: logging.Logger) -> dict[str, str]:
    logger.info(f"BƯỚC 2 — Tải dữ liệu tồn kho từ: {inventory_path.resolve()}")
    if not inventory_path.exists():
        logger.error(f"Không tìm thấy file inventory: {inventory_path}")
        raise FileNotFoundError(f"Không tìm thấy file inventory: {inventory_path}")
    stock: dict[str, str] = {}
    with open(inventory_path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = row.get("Ten_Thuoc", "").strip()
            if name:
                stock[name] = row.get("Ton_Kho", "").strip()
    logger.info(f"Tải thành công {len(stock)} mặt hàng từ inventory.")
    return stock

# BƯỚC 3 — OCR ẢNH (Gemini Vision)
def _extract_drugs(model: GenerativeModel, image_path: Path, logger: logging.Logger) -> list[dict]:
    logger.info(f"BƯỚC 3 — Gửi ảnh lên Gemini Vision: {image_path.name}")

    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png", ".webp": "image/webp", ".bmp": "image/bmp"}
    mime_type = mime_map.get(image_path.suffix.lower(), "image/jpeg")
    logger.debug(f"  → mime_type: {mime_type}")

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    try:
        response = model.generate_content(
            [{"mime_type": mime_type, "data": image_bytes}, SYSTEM_PROMPT],
            generation_config={"temperature": 0, "max_output_tokens": 1024},
        )
    except Exception as e:
        logger.error(f"  → Lỗi khi gọi Gemini API: {e}")
        raise

    raw_text = response.text.strip()
    logger.debug(f"  → Raw response (300 ký tự đầu): {raw_text[:300]}")

    # Làm sạch nếu Gemini bọc markdown ```json ... ```
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.MULTILINE).strip()
    try:
        drugs = json.loads(cleaned)
        if not isinstance(drugs, list):
            raise ValueError("Kết quả không phải JSON array")
        result = [{"ten_thuoc": str(d.get("ten_thuoc", "")).strip() or None,
                   "lieu_luong": d.get("lieu_luong") or None,
                   "full_name":  str(d.get("full_name", "")).strip() or None}
                  for d in drugs]
        logger.info(f"  → OCR thành công: tìm được {len(result)} thuốc.")
        for d in result:
            tag = f"[{d['lieu_luong']}]" if d.get("lieu_luong") else "[không có liều lượng]"
            logger.info(f"     • {d['ten_thuoc']} {tag}")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"  → Không parse được JSON từ Gemini: {e}")
        logger.error(f"  → Raw response: {raw_text[:300]}")
        return []

# BƯỚC 4 — KIỂM TRA TỒN KHO
def _check_inventory(drugs: list[dict], stock: dict[str, str],
                     logger: logging.Logger) -> list[dict]:
    logger.info("BƯỚC 4 — Kiểm tra tồn kho ...")
    results = []
    for item in drugs:
        full_name = str(item.get("full_name", "")).strip()
        qty = stock.get(full_name)
        if qty is None:
            status = "KHÔNG TÌM THẤY trong kho"
            logger.warning(f"  ✗ {full_name!r} → {status}")
        elif qty.isdigit() and int(qty) > 0:
            status = f"CÒN HÀNG — tồn kho: {qty}"
            logger.info(f"  ✓ {full_name!r} → {status}")
        else:
            status = "HẾT HÀNG — tồn kho: 0"
            logger.warning(f"  ⚠ {full_name!r} → {status}")
        results.append({"full_name": full_name, "co_trong_db": qty is not None,
                        "ton_kho": qty if qty is not None else "KHONG_TIM_THAY",
                        "trang_thai": status})
    return results

# AGENT ENTRY POINT
@tool
def ocr_and_check_storage(image_path: str, inventory_path: str = str(INVENTORY_FILE)) -> dict:
    
    """
    Thực hiện OCR hóa đơn thuốc từ ảnh và kiểm tra tồn kho.

    Input:
        - image_path: đường dẫn tới ảnh hóa đơn thuốc (jpg, png, webp, bmp)
        - inventory_path: đường dẫn file CSV tồn kho (mặc định: inventory.csv)

    Xử lý:
    - Dùng Gemini Vision để trích xuất danh sách thuốc (tên + liều lượng)
    - So khớp tên đầy đủ (full_name) với dữ liệu tồn kho
    - Xác định trạng thái: còn hàng, hết hàng, hoặc không tìm thấy

    Output:
    {
        "drugs": [ {ten_thuoc, lieu_luong, full_name}, ... ],
        "results": [ {full_name, co_trong_db, ton_kho, trang_thai}, ... ],
        "error": lỗi nếu có, ngược lại None
    }
    """

    logger = setup_logging()
    logger.info("=" * 55)
    logger.info("  OCR + Kiểm Tra Tồn Kho Thuốc — Agent Tool")
    logger.info(f"  Image     : {image_path}")
    logger.info(f"  Inventory : {inventory_path}")
    logger.info("=" * 55)

    img = Path(image_path)
    if img.suffix.lower() not in SUPPORTED_FORMATS:
        logger.error(f"Định dạng ảnh không hỗ trợ: {img.suffix}")
        return {"drugs": [], "results": [], "error": f"Unsupported image format: {img.suffix}"}
    try:
        model = _setup_gemini(logger)
    except EnvironmentError as e:
        return {"drugs": [], "results": [], "error": str(e)}
    try:
        stock = _load_inventory(Path(inventory_path), logger)
    except FileNotFoundError as e:
        return {"drugs": [], "results": [], "error": str(e)}
    try:
        drugs = _extract_drugs(model, img, logger)
    except Exception as e:
        return {"drugs": [], "results": [], "error": f"OCR failed: {e}"}
    if not drugs:
        logger.warning("Không tìm được thuốc nào từ ảnh — bỏ qua bước kiểm kho.")
        return {"drugs": [], "results": [], "error": None}
    results = _check_inventory(drugs, stock, logger)

    logger.info("=" * 55)
    logger.info(f"HOÀN TẤT | {len(drugs)} thuốc OCR'd | {len(results)} thuốc kiểm kho")
    logger.info("=" * 55)
    return {"drugs": drugs, "results": results, "error": None}

if __name__ == "__main__":
    test_image = "C:/Users/ADMIN/Desktop/OIP.jpg"
    result = ocr_and_check_storage(test_image)

    print("\n=== KET QUA ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))