import sys
from pathlib import Path

# Hỗ trợ chạy trực tiếp: python app/core/agent_engine.py
if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from langchain_google_genai import ChatGoogleGenerativeAI
from app.tools.fda import get_full_fda_info
from app.tools.interaction_checker import check_interaction_openfda
from langchain.agents import create_agent
from app.core.config import CLINICAL_SYSTEM_PROMPT, get_core_config
from app.tools.check_name_drug import get_us_standard_name


CORE_CONFIG = get_core_config()

system_prompt = CLINICAL_SYSTEM_PROMPT
# Danh sách tools cho Agent
tools = [get_full_fda_info, check_interaction_openfda, get_us_standard_name]

# LLM hỗ trợ gọi tool (function calling)
llm = ChatGoogleGenerativeAI(
    model=CORE_CONFIG.gemini_model,
    api_key=CORE_CONFIG.gemini_api_key
)

# Tạo Agent: Tự động quyết định gọi tool nào khi cần
agent_executor = create_agent(
    model = llm,
    system_prompt= system_prompt,
    tools = tools
)


def run_clinical_agent(query: str) -> str:
    """Hàm chạy agent để trả lời câu hỏi của người dùng"""
    try:
        inputs = {"messages": [("user", query)]}
        response = agent_executor.invoke(inputs)

        # Lấy nội dung tin nhắn cuối cùng từ agent
        content = response["messages"][-1].content

        # --- BẮT ĐẦU ĐOẠN SỬA LỖI FORMAT ---
        # Nếu content là một List (chứa cấu trúc JSON của Gemini)
        if isinstance(content, list):
            final_text = ""
            for item in content:
                # Trích xuất phần tử có chứa key 'text'
                if isinstance(item, dict) and "text" in item:
                    final_text += item["text"] + "\n"
                # Đề phòng trường hợp phần tử là chữ thuần
                elif isinstance(item, str):
                    final_text += item + "\n"
            return final_text.strip()

        # Nếu content đã là một chuỗi (string) bình thường thì trả về luôn
        elif isinstance(content, str):
            return content

        # Các trường hợp dị biệt khác (fallback)
        else:
            return str(content)
        # --- KẾT THÚC ĐOẠN SỬA LỖI FORMAT ---

    except Exception as e:
        return f"Lỗi khi chạy agent: {str(e)}"

if __name__ == "__main__":
    print("💊 Pharmacist Agent (type 'exit' to quit)\n")

    while True:
        query = input("🧑 Bạn: ")

        if query.lower() in ["exit", "quit"]:
            print("👋 Tạm biệt!")
            break

        answer = run_clinical_agent(query)
        print("🤖 Agent:", answer)
