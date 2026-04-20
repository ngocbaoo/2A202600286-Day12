import requests
import logging
from langchain.tools import tool
from typing import List, Dict, Any
import itertools

logger = logging.getLogger(__name__)

@tool
def check_interaction_openfda(drug_list: List[str]) -> Dict[str, Any]:
    """
    Kiểm tra tương tác giữa nhiều thuốc bằng cách truy vấn dữ liệu nhãn thuốc từ OpenFDA API.

    Tool này nhận vào danh sách các tên thuốc (có thể là brand name hoặc generic name)
    và kiểm tra tương tác từng cặp thuốc bằng cách tìm kiếm trong trường
    "drug_interactions" của nhãn thuốc trong OpenFDA.

    Cách hoạt động:
    - Tự động tạo tất cả các cặp thuốc có thể từ danh sách đầu vào
    - Với mỗi cặp (A, B), tool sẽ:
      + Kiểm tra xem nhãn của thuốc A có đề cập đến tương tác với thuốc B không
      + Nếu không có, sẽ kiểm tra ngược lại (B với A)
    - Nếu tìm thấy, trả về đoạn cảnh báo tương tác từ FDA label

    Lưu ý quan trọng:
    - OpenFDA chỉ chứa thông tin từ nhãn thuốc, KHÔNG phải là cơ sở dữ liệu tương tác đầy đủ
    - Nếu không tìm thấy dữ liệu (404), điều đó KHÔNG đảm bảo rằng hai thuốc an toàn khi dùng chung
    - Kết quả chỉ mang tính tham khảo

    Khi nào nên dùng tool này:
    - Khi cần kiểm tra tương tác giữa nhiều thuốc trong một toa
    - Sau khi đã chuẩn hóa tên thuốc (nếu có thể) để tăng độ chính xác

    Args:
        drug_list (List[str]): Danh sách tên thuốc (ít nhất 2 thuốc)

    Returns:
        Dict[str, Any]:
            - success (bool): Trạng thái thực thi
            - message (str): Tóm tắt kết quả cho từng cặp thuốc
            - interactions (List[Dict]): Danh sách các cặp có tương tác, gồm:
                + pair (str): Tên 2 thuốc
                + warning_text (str): Nội dung cảnh báo từ FDA
    """
    if not drug_list or len(drug_list) < 2:
        return {"success": False, "message": "Cần ít nhất 2 thuốc để kiểm tra tương tác", "interactions": []}

    fda_drugs = [drug for drug in drug_list]

    # Loại bỏ trùng lặp (phòng trường hợp user nhập 2 thuốc giống nhau)
    fda_drugs = list(set(fda_drugs))
    if len(fda_drugs) < 2:
        return {"success": False, "message": "Cần ít nhất 2 thuốc khác biệt nhau để kiểm tra.", "interactions": []}

    # 2. Tạo các cặp thuốc (Combinations) để kiểm tra chéo
    # VD: [A, B, C] -> sẽ tạo ra 3 cặp (A,B), (A,C), (B,C)
    drug_pairs = list(itertools.combinations(fda_drugs, 2))

    all_interactions = []
    summary_messages = []

    # 3. Chạy vòng lặp kiểm tra từng cặp qua OpenFDA
    url = 'https://api.fda.gov/drug/label.json'
    for drug_a, drug_b in drug_pairs:
        # Thử chiều 1: Xem nhãn thuốc A có nhắc đến cảnh báo với thuốc B không
        params_1 = {
            'search': f'(openfda.generic_name:"{drug_a}" OR openfda.brand_name:"{drug_a}") AND drug_interactions:"{drug_b}"',
            'limit': 1
        }

        try:
            res = requests.get(url, params=params_1)

            # Nếu không tìm thấy ở nhãn A (404), ta thử chiều 2: Xem nhãn thuốc B có nhắc đến A không
            if res.status_code == 404:
                params_2 = {
                    'search': f'(openfda.generic_name:"{drug_b}" OR openfda.brand_name:"{drug_b}") AND drug_interactions:"{drug_a}"',
                    'limit': 1
                }
                res = requests.get(url, params=params_2)

            # Phân tích kết quả
            if res.status_code == 200:
                data = res.json()
                interaction_text = data['results'][0].get('drug_interactions', [''])[0]

                all_interactions.append({
                    "pair": f"{drug_a} + {drug_b}",
                    "warning_text": interaction_text
                })
                summary_messages.append(f"⚠️ CÓ TƯƠNG TÁC: {drug_a} và {drug_b}")

            elif res.status_code == 404:
                summary_messages.append(f"✅ AN TOÀN (Không thấy dữ liệu): {drug_a} và {drug_b}")
            else:
                summary_messages.append(f"❓ LỖI TRA CỨU: {drug_a} và {drug_b} (Mã lỗi {res.status_code})")

        except Exception as e:
            summary_messages.append(f"❌ LỖI HỆ THỐNG: {drug_a} và {drug_b} - {str(e)}")

    # 4. Trả về kết quả tổng hợp cho Langchain Agent
    return {
        "success": True,
        "message": "\n".join(summary_messages),
        "interactions": all_interactions
    }