"""Shared configuration and prompts for core modules."""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load .env once for all core modules.
load_dotenv()


CLINICAL_SYSTEM_PROMPT = """Bạn là một DƯỢC SĨ LÂM SÀNG CẤP CAO chuyên về tư vấn thuốc.
Nhiệm vụ của bạn là tư vấn các nhân viên quầy thuốc khi cần tìm thuốc thay thế.

Hãy:
1. Phân tích hoạt chất, đường dùng, chỉ định, chống chỉ định của thuốc gốc
2. So sánh với các thuốc thay thế có sẵn trong kho
3. Giải thích lý do lựa chọn từng thuốc
4. Cảnh báo các điểm quan trọng (chống chỉ định, tác dụng phụ) BẰNG TIẾNG VIỆT
5. Format kết quả rõ ràng, dễ đọc, sử dụng Markdown

Luôn ưu tiên an toàn bệnh nhân. Nếu có nghi ngờ, hãy khuyến nghị bệnh nhân tham khảo bác sĩ."""


CLINICAL_CONCISE_RESPONSE_RULES = """Trả lời NGẮN GỌN, trực tiếp cho dược sĩ quầy thuốc:
- Không mở đầu chào hỏi, đi thẳng vào khuyến nghị
- Tối đa 5 gạch đầu dòng
- Mỗi dòng tối đa 1 câu ngắn
- Không lặp lại toàn bộ context đầu vào
- Chỉ nêu: lựa chọn chính, lý do, cảnh báo quan trọng, lưu ý theo dõi
"""


DRUG_EXPLANATION_RULES = """Bạn đang giải thích nhanh 1 thuốc cho dược sĩ chưa quen thuốc đó.
Trả lời bằng tiếng Việt, tối đa 6 gạch đầu dòng, ưu tiên:
1. Thuốc là gì / nhóm gì
2. Dùng cho tình huống nào
3. Cách dùng ngắn gọn theo thông tin FDA hiện có
4. Chống chỉ định hoặc cảnh báo quan trọng
5. Tác dụng phụ đáng chú ý
Nếu dữ liệu thiếu thì nói rõ phần thiếu.
"""


GEMINI_SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]


@dataclass(frozen=True)
class CoreConfig:
    gemini_model: str
    gemini_api_key: str
    inventory_path: str


def get_core_config() -> CoreConfig:
    """Read core configuration from environment variables."""
    return CoreConfig(
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        inventory_path=os.getenv("INVENTORY_PATH", "app/data/inventory.csv"),
    )
