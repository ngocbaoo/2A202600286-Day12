"""
Module FDA API Integration - Lấy thông tin chi tiết từ OpenFDA
Tra cứu: Hoạt chất, Đường dùng, Chỉ định, Chống chỉ định, Tác dụng phụ
"""
import os
import requests
import logging
import re
import time
from pathlib import Path
from typing import Dict, Optional, List, Any
from langchain.tools import tool
import pandas as pd

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Hằng số
FDA_API_BASE_URL = "https://api.fda.gov/drug/label.json"
API_TIMEOUT = 10  # seconds

# Cấu hình từ env
INVENTORY_PATH = os.getenv("INVENTORY_PATH", "inventory.csv")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def resolve_inventory_path() -> Path:
    """Tìm đường dẫn inventory ổn định dù chạy từ cwd nào."""
    configured = INVENTORY_PATH.strip() if INVENTORY_PATH else ""

    # Ưu tiên path được cấu hình (absolute hoặc relative theo cwd hiện tại)
    candidates: List[Path] = []
    if configured:
        cfg_path = Path(configured)
        candidates.append(cfg_path)
        if not cfg_path.is_absolute():
            candidates.append(Path.cwd() / cfg_path)

    # Fallback theo cấu trúc project hiện tại
    module_dir = Path(__file__).resolve().parent  # app/tools
    project_root = module_dir.parents[1]          # repo root
    candidates.extend([
        project_root / "app" / "data" / "inventory.csv",
        project_root / "inventory.csv",
        module_dir.parent / "data" / "inventory.csv",  # app/data/inventory.csv
    ])

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    # Trả candidate đầu tiên để log dễ hiểu nếu không file nào tồn tại
    return candidates[0] if candidates else Path("inventory.csv")

def load_inventory() -> pd.DataFrame:
    """
    Load file inventory.csv vào DataFrame

    Returns:
        pd.DataFrame: DataFrame với các cột Ten_Thuoc, Hoat_Chat, Ton_Kho
    """
    try:
        inventory_path = resolve_inventory_path()
        df = pd.read_csv(inventory_path)
        logger.info(f"✅ Load inventory thành công: {len(df)} dòng | file={inventory_path}")
        return df
    except FileNotFoundError:
        logger.error(f"❌ Không tìm thấy file inventory. INVENTORY_PATH={INVENTORY_PATH} | cwd={Path.cwd()}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"❌ Lỗi load inventory: {str(e)}")
        return pd.DataFrame()


def find_alternative_drugs(active_ingredient: str) -> List[Dict]:
    """
    Tìm các thuốc thay thế có cùng hoạt chất và còn tồn kho > 0

    Args:
        active_ingredient (str): Hoạt chất chính (vd: "ibuprofen")

    Returns:
        List[Dict]: Danh sách thuốc thay thế
    """
    try:
        df = load_inventory()

        if df.empty:
            logger.warning("⚠️ Inventory trống!")
            return []

        active_ingredient_text = str(active_ingredient).lower().strip()

        # Tìm thuốc có cùng hoạt chất và còn tồn kho > 0.
        # Ưu tiên match chính xác, sau đó fallback match theo "chuỗi chứa hoạt chất"
        exact_match_df = df[
            (df["Hoat_Chat"].str.lower() == active_ingredient_text) &
            (df["Ton_Kho"] > 0)
            ]

        if not exact_match_df.empty:
            alternative_drugs = exact_match_df.to_dict("records")
        else:
            contains_match_df = df[
                (df["Ton_Kho"] > 0) &
                (df["Hoat_Chat"].str.lower().apply(lambda ing: str(ing) in active_ingredient_text))
                ]
            alternative_drugs = contains_match_df.to_dict("records")

        logger.info(f"🔎 Tìm thấy {len(alternative_drugs)} thuốc thay thế")

        return alternative_drugs

    except Exception as e:
        logger.error(f"❌ Lỗi tìm kiếm thuốc thay thế: {str(e)}")
        return []


def _normalize_drug_name_text(drug_name: str) -> str:
    """Chuẩn hóa tên thuốc để tăng tỉ lệ match OpenFDA (bỏ liều, chuẩn hóa khoảng trắng)."""
    cleaned = re.sub(r"\b\d+(?:\.\d+)?\s*(mg|g|mcg|ml)\b", "", drug_name, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or drug_name


def _short_text(value: Any, max_len: int = 90) -> str:
    text = str(value) if value is not None else ""
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def _build_fda_search_terms(user_input: str) -> List[str]:
    """Sinh danh sách term fallback để xử lý typo kiểu 'Pannadol'."""
    terms: List[str] = []

    def _add_term(term: Optional[str]):
        if not term:
            return
        t = term.strip()
        if not t:
            return
        if t.lower() not in {x.lower() for x in terms}:
            terms.append(t)

    _add_term(user_input)
    _add_term(_normalize_drug_name_text(user_input))

    # Tận dụng bộ chuẩn hóa đang có trong interaction checker (RxNorm approximate term)
    try:
        from app.tools.interaction_checker import get_us_standard_name
        standardized = get_us_standard_name(user_input)
        _add_term(standardized)
        _add_term(_normalize_drug_name_text(standardized))
    except Exception as e:
        logger.warning("[FDA][NORMALIZE_WARN] input='%s' | detail=%s", user_input, str(e))

    return terms


def _query_openfda_first_result(search_query: str) -> Optional[Dict[str, Any]]:
    """Trả về record đầu tiên nếu query có kết quả; None nếu không có dữ liệu."""
    params = {
        "search": search_query,
        "limit": 1,
    }

    start_time = time.perf_counter()
    response = requests.get(FDA_API_BASE_URL, params=params, timeout=API_TIMEOUT)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    logger.info(
        "[FDA][HTTP] status=%s | elapsed=%.1fms | url=%s",
        response.status_code,
        elapsed_ms,
        response.url,
    )

    # OpenFDA thường trả 404 khi không có kết quả
    if response.status_code == 404:
        logger.info("[FDA][MISS] query=%s", search_query)
        return None

    response.raise_for_status()
    data = response.json()
    results = data.get("results", []) if isinstance(data, dict) else []
    logger.info("[FDA][PARSE] total_results=%s | query=%s", len(results), search_query)

    if not results:
        return None

    return results[0]

@tool
def get_full_fda_info(brand_name: str):
    """
    Tra cứu thông tin CHI TIẾT của thuốc từ OpenFDA API.
    
    Args:
        brand_name (str): Tên thương mại của thuốc (vd: "Advil")
    
    Returns:
        Dict với keys: Hoat_Chat, Duong_Dung, Chi_Dinh, Chong_Chi_Dinh, Tac_Dung_Phu
        Ví dụ:
        {
            "Hoat_Chat": "ibuprofen",
            "Duong_Dung": "Oral",
            "Chi_Dinh": "For temporary relief of...",
            "Chong_Chi_Dinh": "Do not use if...",
            "Tac_Dung_Phu": "May cause...",
            "success": True
        }
    """
    result: Dict[str, Any] = {
        "Hoat_Chat": None,
        "Duong_Dung": None,
        "Chi_Dinh": None,
        "Chong_Chi_Dinh": None,
        "Tac_Dung_Phu": None,
        "success": False
    }
    
    try:
        search_terms = _build_fda_search_terms(brand_name)
        search_fields = [
            "openfda.brand_name",
            "openfda.generic_name",
            "openfda.substance_name",
        ]

        logger.info(
            "[FDA][START] input='%s' | terms=%s | fields=%s | timeout=%ss",
            brand_name,
            search_terms,
            search_fields,
            API_TIMEOUT,
        )

        drug = None
        matched_query = None
        for term in search_terms:
            for field in search_fields:
                search_query = f'{field}:"{term}"'
                logger.info("[FDA][TRY] field=%s | term='%s'", field, term)
                candidate = _query_openfda_first_result(search_query)
                if candidate is not None:
                    drug = candidate
                    matched_query = search_query
                    break
            if drug is not None:
                break

        if drug is None:
            logger.warning("[FDA][NOT_FOUND] input='%s' | attempted_terms=%s", brand_name, search_terms)
            return result

        logger.info("[FDA][MATCH] input='%s' | query=%s", brand_name, matched_query)
        
        # 1. Hoạt chất (Active Ingredient)
        # OpenFDA có thể trả về list[str], str, hoặc list[dict] tùy record.
        active_ingredient = drug.get("active_ingredient")
        if active_ingredient:
            if isinstance(active_ingredient, list) and len(active_ingredient) > 0:
                first_item = active_ingredient[0]
                if isinstance(first_item, dict):
                    result["Hoat_Chat"] = first_item.get("name") or first_item.get("value") or "Unknown"
                else:
                    result["Hoat_Chat"] = str(first_item)
            elif isinstance(active_ingredient, str):
                result["Hoat_Chat"] = active_ingredient

        # Fallback từ openfda.substance_name nếu active_ingredient thiếu
        if not result["Hoat_Chat"]:
            openfda = drug.get("openfda", {}) if isinstance(drug.get("openfda", {}), dict) else {}
            substance_name = openfda.get("substance_name")
            if isinstance(substance_name, list) and substance_name:
                result["Hoat_Chat"] = str(substance_name[0])
            elif isinstance(substance_name, str):
                result["Hoat_Chat"] = substance_name
        
        # 2. Đường dùng (Route of Administration)
        route = drug.get("route")
        if isinstance(route, list) and route:
            result["Duong_Dung"] = ", ".join(str(x) for x in route[:3])
        elif isinstance(route, str) and route:
            result["Duong_Dung"] = route

        # Fallback từ openfda.route nếu route thiếu
        if not result["Duong_Dung"]:
            openfda = drug.get("openfda", {}) if isinstance(drug.get("openfda", {}), dict) else {}
            openfda_route = openfda.get("route")
            if isinstance(openfda_route, list) and openfda_route:
                result["Duong_Dung"] = ", ".join(str(x) for x in openfda_route[:3])
            elif isinstance(openfda_route, str) and openfda_route:
                result["Duong_Dung"] = openfda_route
        
        # 3. Chỉ định (Indications and Usage)
        if "indications_and_usage" in drug and drug["indications_and_usage"]:
            usage_text = drug["indications_and_usage"]
            result["Chi_Dinh"] = usage_text[0][:500] if isinstance(usage_text, list) else usage_text[:500]
        
        # 4. Chống chỉ định (Contraindications)
        if "contraindications" in drug and drug["contraindications"]:
            contra_text = drug["contraindications"]
            result["Chong_Chi_Dinh"] = contra_text[0][:500] if isinstance(contra_text, list) else contra_text[:500]
        
        # 5. Tác dụng phụ (Adverse Reactions)
        if "adverse_reactions" in drug and drug["adverse_reactions"]:
            adverse_text = drug["adverse_reactions"]
            result["Tac_Dung_Phu"] = adverse_text[0][:500] if isinstance(adverse_text, list) else adverse_text[:500]
        
        # Thay thế None bằng "Not available"
        for key in result:
            if key != "success" and result[key] is None:
                result[key] = "Not available in FDA database"
        
        result["success"] = True
        logger.info(
            "[FDA][SUCCESS] input='%s' | hoat_chat='%s' | duong_dung='%s' | chi_dinh='%s' | chong_chi_dinh='%s' | tac_dung_phu='%s'",
            brand_name,
            _short_text(result.get("Hoat_Chat")),
            _short_text(result.get("Duong_Dung")),
            _short_text(result.get("Chi_Dinh")),
            _short_text(result.get("Chong_Chi_Dinh")),
            _short_text(result.get("Tac_Dung_Phu")),
        )
        
        return result
    
    except requests.exceptions.Timeout:
        logger.error("[FDA][TIMEOUT] input='%s' | timeout=%ss", brand_name, API_TIMEOUT)
        return result
    except requests.exceptions.ConnectionError:
        logger.error("[FDA][CONNECTION_ERROR] input='%s'", brand_name)
        return result
    except requests.exceptions.HTTPError as e:
        response = getattr(e, "response", None)
        logger.error(
            "[FDA][HTTP_ERROR] input='%s' | status=%s | url=%s | detail=%s",
            brand_name,
            getattr(response, "status_code", "unknown"),
            getattr(response, "url", "unknown"),
            str(e),
        )
        return result
    except ValueError:
        logger.error("[FDA][JSON_ERROR] input='%s'", brand_name)
        return result
    except Exception as e:
        logger.error("[FDA][UNEXPECTED_ERROR] input='%s' | detail=%s", brand_name, str(e))
        return result

if __name__ == "__main__":
    # Test
    result = get_full_fda_info.invoke({"brand_name": "Advil"})
    print("Success:", result["success"])
    print("Hoat_Chat:", result["Hoat_Chat"])
    print("Duong_Dung:", result["Duong_Dung"])
