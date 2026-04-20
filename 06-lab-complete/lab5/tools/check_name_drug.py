import requests
import logging
from langchain.tools import tool

logger = logging.getLogger(__name__)

@tool
def get_us_standard_name(drug_name: str) -> str:
    """
    Chuẩn hóa tên thuốc về tên tiêu chuẩn tại Mỹ (US standard name) sử dụng RxNorm API.

    Tool này nhận vào một tên thuốc bất kỳ (có thể là tên thương mại, tên generic,
    tên viết sai chính tả hoặc tên theo quốc gia khác) và trả về tên chuẩn hóa theo
    hệ thống RxNorm của Mỹ (thường là generic name viết thường).

    Ví dụ:
    - "Advil" → "ibuprofen"
    - "Panadol" → "acetaminophen"

    Luôn sử dụng tool này trước khi:
    - tra cứu thông tin thuốc (FDA, DrugBank, v.v.)
    - kiểm tra tương tác thuốc
    - so sánh hoặc mapping thuốc

    Args:
        drug_name (str): Tên thuốc đầu vào (có thể không chuẩn hóa)

    Returns:
        str: Tên thuốc đã được chuẩn hóa theo RxNorm (lowercase).
             Nếu không tìm thấy, trả về tên gốc dạng lowercase.
"""
    try:
        search_url = "https://rxnav.nlm.nih.gov/REST/approximateTerm.json"
        search_res = requests.get(search_url, params={"term": drug_name, "maxEntries": 1}).json()

        candidates = search_res.get("approximateGroup", {}).get("candidate", [])
        if not candidates:
            return drug_name.lower()

        rxcui = candidates[0].get("rxcui")
        prop_url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/properties.json"
        prop_res = requests.get(prop_url).json()

        properties = prop_res.get("properties")
        if properties and "name" in properties:
            standard_name = properties["name"].lower()
            logger.info(f"🔄 Đổi tên: {drug_name} -> {standard_name}")
            return standard_name
    except Exception as e:
        logger.warning(f"Lỗi đổi tên cho {drug_name}: {str(e)}")

    return drug_name.lower()