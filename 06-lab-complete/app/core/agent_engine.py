import sys
import logging
from pathlib import Path

# Hỗ trợ chạy trực tiếp
if __package__ is None or __package__ == "":
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from langchain_google_genai import ChatGoogleGenerativeAI
from app.tools.fda import get_full_fda_info
from app.tools.interaction_checker import check_interaction_openfda
from langchain.agents import create_agent
from app.core.agent_config import CLINICAL_SYSTEM_PROMPT, get_core_config
from app.tools.check_name_drug import get_us_standard_name

# Cấu hình logging
logger = logging.getLogger(__name__)
CORE_CONFIG = get_core_config()

# LLM hỗ trợ gọi tool (function calling)
llm = ChatGoogleGenerativeAI(
    model=CORE_CONFIG.gemini_model,
    api_key=CORE_CONFIG.gemini_api_key
)

# Tạo Agent
agent_executor = create_agent(
    model=llm,
    system_prompt=CLINICAL_SYSTEM_PROMPT,
    tools=[get_full_fda_info, check_interaction_openfda, get_us_standard_name]
)

def run_clinical_agent(query: str, chat_history: list = None):
    """
    Chạy Agent lâm sàng với lịch sử hội thoại hỗ trợ Stateless (Redis).
    """
    try:
        # LangChain agent executor expects history in 'chat_history' key
        inputs = {
            "input": query,
            "chat_history": chat_history or []
        }
        
        response = agent_executor.invoke(inputs)
        
        # Xử lý format output (đề phòng Gemini trả về list/dict)
        content = response.get("output", "")
        if isinstance(content, list):
            final_text = ""
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    final_text += item["text"] + " "
                elif isinstance(item, str):
                    final_text += item + " "
            return final_text.strip()
        
        return str(content)

    except Exception as e:
        logger.error(f"Agent Engine Error: {str(e)}")
        return f"Lỗi xử lý Agent: {str(e)}"

if __name__ == "__main__":
    # Test nhanh
    print(run_clinical_agent("Chào bạn, bạn là ai?"))
