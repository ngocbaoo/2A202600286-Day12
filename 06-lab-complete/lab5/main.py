"""
Streamlit App - Pharmacist Assistant Chatbot
Giao diện cho hệ thống gợi ý thuốc thay thế dùng Google Gemini API
"""

import streamlit as st
import logging
import os
from app.core.rag_engine import (
    get_clinical_recommendation,
    get_clinical_recommendation_stream,
    get_drug_explanation_for_pharmacist,
    get_drug_explanation_for_pharmacist_stream,
)
from datetime import datetime
from dotenv import load_dotenv

# Load env từ file .env
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Cấu hình Streamlit
st.set_page_config(
    page_title="Trợ lý Dược sĩ - Gemini",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Custom CSS
st.markdown("""
<style>
    .main-container {
        padding: 2rem;
    }
    .recommendation-box {
        background-color: #f0f8ff;
        border-left: 5px solid #0066cc;
        padding: 1.5rem;
        border-radius: 5px;
        margin: 1rem 0;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .alternative-box {
        background-color: #e8f5e9;
        border-left: 5px solid #2e7d32;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    .fda-info-box {
        background-color: #fff8e1;
        border-left: 5px solid #f57f17;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    .warning-box {
        background-color: #fff3e0;
        border-left: 5px solid #f57c00;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    .error-box {
        background-color: #ffebee;
        border-left: 5px solid #c62828;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
    .success-box {
        background-color: #e8f5e9;
        border-left: 5px solid #2e7d32;
        padding: 1rem;
        border-radius: 5px;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Khởi tạo session state
if "recommendation_result" not in st.session_state:
    st.session_state.recommendation_result = None
if "feedback_submitted" not in st.session_state:
    st.session_state.feedback_submitted = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "drug_explanations" not in st.session_state:
    st.session_state.drug_explanations = {}


def stream_text(text: str, chunk_size: int = 80):
    """Stream text theo từng chunk để hiển thị dần trên UI."""
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]


def display_header():
    """Hiển thị header"""
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("💊 Trợ lý Dược sĩ - Powered by Google Gemini")
        st.markdown("*Hệ thống gợi ý thuốc thay thế thông minh khác biệt*")
    with col2:
        st.markdown(f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")


def ensure_env_ready() -> bool:
    """Kiểm tra cấu hình .env trước khi chạy"""
    if GEMINI_API_KEY:
        return True

    st.error("❌ Không tìm thấy GEMINI_API_KEY trong file .env")
    st.markdown("""
    Vui lòng kiểm tra file `.env`:

    ```env
    GEMINI_API_KEY=AIzaSy...
    GEMINI_MODEL=gemini-2.5-flash
    ```
    """)
    return False


def display_search_form():
    """Hiển thị form tìm kiếm"""
    st.subheader("🔍 Tìm kiếm Thuốc Thay Thế")
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        brand_name = st.text_input(
            "Tên thuốc bị hết hàng",
            placeholder="Ví dụ: Advil, Paracetamol, Tylenol, ...",
            key="brand_name_input"
        )
    
    with col2:
        search_button = st.button("🔎 Tìm kiếm", use_container_width=True)
    
    with col3:
        clear_button = st.button("🗑 Xóa", use_container_width=True)
    
    return brand_name, search_button, clear_button


def display_fda_info(fda_info):
    """Hiển thị thông tin từ FDA"""
    st.markdown("""
    ---
    ### 📊 Thông Tin từ FDA (English - Original)
    """)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Hoạt Chất (Active Ingredient):**")
        st.write(fda_info.get("Hoat_Chat", "N/A"))
        
        st.write("\n**Đường Dùng (Route of Administration):**")
        st.write(fda_info.get("Duong_Dung", "N/A"))
        
        st.write("\n**Chỉ Định (Indications):**")
        st.write(fda_info.get("Chi_Dinh", "N/A"))
    
    with col2:
        st.write("**⚠️ CHỐNG CHỈ ĐỊNH (Contraindications):**")
        st.markdown(
            f'<div class="warning-box">{fda_info.get("Chong_Chi_Dinh", "N/A")}</div>',
            unsafe_allow_html=True
        )
        
        st.write("\n**⚠️ TÁC DỤNG PHỤ (Side Effects):**")
        st.markdown(
            f'<div class="warning-box">{fda_info.get("Tac_Dung_Phu", "N/A")}</div>',
            unsafe_allow_html=True
        )


def display_recommendation(result):
    """Hiển thị kết quả tư vấn"""
    if not result["success"]:
        st.markdown(
            f'<div class="error-box">❌ {result["error_message"]}</div>',
            unsafe_allow_html=True
        )
        return
    
    # Thông tin cơ bản
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Thuốc Được Yêu Cầu",
            result["brand_name"],
            delta="Hết hàng"
        )
    
    with col2:
        st.metric(
            "Hoạt Chất",
            result["fda_info"].get("Hoat_Chat", "N/A")[:30]
        )
    
    with col3:
        st.metric(
            "Thuốc Thay Thế",
            len(result["alternative_drugs"])
        )
    
    # Thông tin FDA
    display_fda_info(result["fda_info"])

    st.markdown("""
    ---
    ### 💊 Thuốc Thay Thế Có Sẵn Trong Kho
    """)
    
    if result["alternative_drugs"]:
        for i, drug in enumerate(result["alternative_drugs"], 1):
            with st.expander(f"{i}. {drug['Ten_Thuoc']} - Tồn kho: {drug['Ton_Kho']} hộp"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.markdown(f"**Tên:** {drug['Ten_Thuoc']}")
                with col2:
                    st.markdown(f"**Hoạt Chất:** {drug['Hoat_Chat']}")
                with col3:
                    st.markdown(f"**Tồn Kho:** {drug['Ton_Kho']} hộp")

                explain_key = f"explain::{drug['Ten_Thuoc']}"
                if st.button("🧠 Không rõ thuốc này? Giải thích thêm", key=f"explain_btn_{i}_{drug['Ten_Thuoc']}"):
                    status_placeholder = st.empty()
                    explain_placeholder = st.empty()
                    live_explain = ""
                    explain_result = None

                    for event in get_drug_explanation_for_pharmacist_stream(drug["Ten_Thuoc"]):
                        event_type = event.get("type")

                        if event_type == "status":
                            status_placeholder.info(f"⏳ {event.get('message', '')}")
                        elif event_type == "fda_info":
                            status_placeholder.success("✅ Đã lấy thông tin FDA cho thuốc này")
                        elif event_type == "explanation_chunk":
                            live_explain += event.get("chunk", "")
                            explain_placeholder.markdown(live_explain)
                        elif event_type == "done":
                            explain_result = event.get("result")
                            break
                        elif event_type == "error":
                            explain_result = event.get("result")
                            status_placeholder.error(f"❌ {event.get('message', 'Lỗi không xác định')}")
                            break

                    if explain_result is None:
                        explain_result = get_drug_explanation_for_pharmacist(drug["Ten_Thuoc"])

                    st.session_state.drug_explanations[explain_key] = explain_result

                explained = st.session_state.drug_explanations.get(explain_key)
                if explained:
                    if explained.get("success"):
                        st.markdown("**Giải thích nhanh cho dược sĩ:**")
                        st.markdown(explained.get("explanation", ""))
                    else:
                        st.warning(explained.get("error_message", "Không thể giải thích thuốc lúc này."))
    else:
        st.info("ℹ️ Không tìm thấy thuốc thay thế nào có sẵn trong kho")
    
    st.markdown("""
    ---
    ### 📋 Tư Vấn Lâm Sàng Ngắn Gọn từ Google Gemini
    """)
    
    st.markdown(
        f'<div class="recommendation-box">{result["recommendation"]}</div>',
        unsafe_allow_html=True
    )


def display_feedback_buttons():
    """Hiển thị nút Duyệt bán / Từ chối"""
    st.markdown("""---""")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("✅ Duyệt Bán", use_container_width=True, key="approve_btn"):
            st.session_state.feedback_submitted = True
            st.success("✅ Tư vấn đã được duyệt bán. Cảm ơn!")
            # Lưu vào chat history
            st.session_state.chat_history.append({
                "status": "approved",
                "brand_name": st.session_state.recommendation_result["brand_name"],
                "timestamp": datetime.now()
            })
    
    with col2:
        if st.button("❌ Từ Chối", use_container_width=True, key="reject_btn"):
            st.session_state.feedback_submitted = True
            st.warning("❌ Tư vấn đã bị từ chối. Hệ thống sẽ tiếp tục cải thiện.")
            # Lưu vào chat history
            st.session_state.chat_history.append({
                "status": "rejected",
                "brand_name": st.session_state.recommendation_result["brand_name"],
                "timestamp": datetime.now()
            })
    
    with col3:
        if st.button("🔄 Tư Vấn Khác", use_container_width=True, key="retry_btn"):
            st.session_state.feedback_submitted = False
            st.session_state.recommendation_result = None
            st.rerun()


def display_chat_history():
    """Hiển thị lịch sử chat"""
    if st.session_state.chat_history:
        st.subheader("📜 Lịch Sử Tư Vấn")
        
        for i, item in enumerate(st.session_state.chat_history[-5:], 1):  # Hiển thị 5 lần gần nhất
            status_emoji = "✅" if item["status"] == "approved" else "❌"
            st.write(f"{status_emoji} **{item['brand_name']}** - {item['timestamp'].strftime('%H:%M:%S')}")


def main():
    """Hàm chính"""
    display_header()
    
    # Sidebar
    with st.sidebar:
        st.subheader("⚙️ Cài Đặt")
        enable_history = st.checkbox("Hiển thị lịch sử", value=True)
        
        st.divider()
        
        st.markdown("""
        ### 📌 Hướng Dẫn Sử Dụng
        1. ✅ Cấu hình GEMINI_API_KEY trong file `.env`
        2. 🔍 Nhập tên thuốc bị hết hàng
        3. ⏳ Hệ thống sẽ:
           - Tra cứu OpenFDA Database
           - Tìm thuốc thay thế trong kho
           - Gợi ý bằng Google Gemini AI
        4. 📋 Duyệt hoặc từ chối tư vấn
        
        ### 🔗 Nguồn Dữ Liệu
        - **FDA API**: OpenFDA Drug Labels
        - **Kho**: inventory.csv (Mock Data)
        - **LLM**: Google Gemini 2.5 Flash
        
        ### ⚙️ Công Nghệ
        - Python 3
        - Pandas (Xử lý CSV)
        - Requests (FDA API)
        - Google Generative AI (Gemini)
        - Streamlit (UI)
        """)
    
    if not ensure_env_ready():
        st.stop()
    
    # Form tìm kiếm
    brand_name, search_button, clear_button = display_search_form()
    
    # Xử lý nút Clear
    if clear_button:
        st.session_state.recommendation_result = None
        st.session_state.feedback_submitted = False
        st.rerun()
    
    # Xử lý tìm kiếm
    if search_button and brand_name.strip():
        st.session_state.drug_explanations = {}

        live_status = st.empty()
        live_context_placeholder = st.empty()
        live_recommendation_placeholder = st.empty()

        live_context = ""
        live_recommendation = ""
        stream_result = None

        try:
            for event in get_clinical_recommendation_stream(brand_name.strip()):
                event_type = event.get("type")

                if event_type == "status":
                    live_status.info(f"⏳ {event.get('message', '')}")

                elif event_type == "fda_info":
                    fda_data = event.get("data", {})
                    live_status.success(
                        f"✅ FDA: {fda_data.get('Hoat_Chat', 'N/A')} | {fda_data.get('Duong_Dung', 'N/A')}"
                    )

                elif event_type == "alternatives":
                    alternatives = event.get("data", [])
                    live_status.info(f"💊 Tìm thấy {len(alternatives)} thuốc thay thế trong kho")

                elif event_type == "context_chunk":
                    live_context += event.get("chunk", "")
                    live_context_placeholder.markdown(
                        "### 🧠 Context Phân Tích (Stream)\n\n" + live_context
                    )

                elif event_type == "recommendation_chunk":
                    live_recommendation += event.get("chunk", "")
                    live_recommendation_placeholder.markdown(
                        "### 📋 Tư Vấn Lâm Sàng (Streaming)\n\n" + live_recommendation
                    )

                elif event_type == "done":
                    stream_result = event.get("result")
                    live_status.success("✅ Hoàn tất tư vấn")
                    break

                elif event_type == "error":
                    stream_result = event.get("result")
                    live_status.error(f"❌ {event.get('message', 'Lỗi không xác định')}")
                    break

            if stream_result is None:
                stream_result = get_clinical_recommendation(brand_name.strip())

            st.session_state.recommendation_result = stream_result
            st.session_state.feedback_submitted = False

        except Exception as e:
            st.error(f"❌ Lỗi: {str(e)}")
    
    # Hiển thị kết quả
    if st.session_state.recommendation_result:
        display_recommendation(st.session_state.recommendation_result)
        
        # Chỉ hiển thị nút feedback nếu chưa submit
        if not st.session_state.feedback_submitted:
            display_feedback_buttons()
        else:
            st.markdown('<div class="success-box">💾 Phản hồi của bạn đã được lưu.</div>', unsafe_allow_html=True)
    
    # Chat history
    if enable_history:
        st.markdown("""---""")
        display_chat_history()
    
    # Footer
    st.divider()
    st.markdown("""
    <footer style='text-align: center; color: gray;'>
        <small>💊 Pharmacist Assistant v2.0 | Powered by OpenFDA API + Google Gemini 2.5 Flash</small>
    </footer>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
