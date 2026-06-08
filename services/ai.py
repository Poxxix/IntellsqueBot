import httpx
from config import GEMINI_API_KEY

DEFAULT_SYSTEM_INSTRUCTION = (
    "Bạn là Trợ lý Số hóa Văn phòng chuyên nghiệp và nghiêm túc. "
    "Nhiệm vụ của bạn là hỗ trợ và trả lời các câu hỏi bằng tiếng Việt một cách lịch sự, chính xác và trực diện. "
    "Tuyệt đối không pha trò, không đùa cợt, không sử dụng phong cách hài hước hay cà khịa. "
    "Khi xưng hô, luôn tự xưng là 'mình' và gọi người dùng là 'bạn'. "
    "Hãy giữ giọng điệu nghiêm túc, chuyên nghiệp và có cấu trúc rõ ràng. "
    "Hạn chế tối đa việc sử dụng emoji (chỉ sử dụng các emoji trang trọng như 💼, 📊, 📝 khi thật sự cần thiết). "
    "Hãy trả lời ngắn gọn, đi thẳng vào nội dung câu hỏi."
)

# In-memory cache for the working API endpoint URL
WORKING_URL = None

async def generate_ai_response(prompt: str, system_instruction: str = None) -> str:
    """Calls Gemini API asynchronously using httpx with automatic model/endpoint fallback and caching."""
    global WORKING_URL
    if not GEMINI_API_KEY:
        return (
            "🔌 Sếp ơi, Trợ lý AI chưa được 'cắm điện'! "
            "Vui lòng cấu hình `GEMINI_API_KEY` trong file `.env` để kích hoạt nhé 🤪."
        )
        
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "systemInstruction": {
            "parts": [
                {"text": system_instruction or DEFAULT_SYSTEM_INSTRUCTION}
            ]
        }
    }
    
    # 1. Use the cached working URL if available
    if WORKING_URL:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(WORKING_URL, json=payload, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {})
                        parts = content.get("parts", [])
                        if parts:
                            return parts[0].get("text", "").strip()
        except Exception as e:
            print(f"Cached URL failed, re-running fallback search. Error: {e}")
            WORKING_URL = None  # Reset cache if it fails
            
    # 2. Fallback search: try combinations of stable/beta and different model names
    models_to_try = [
        "gemini-3.1-flash-lite",
        "gemini-1.5-flash-latest",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash-exp"
    ]
    
    api_versions = ["v1", "v1beta"]
    
    last_status = None
    last_body = ""
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        for version in api_versions:
            for model in models_to_try:
                url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={GEMINI_API_KEY}"
                try:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            if parts:
                                WORKING_URL = url  # Cache the working endpoint
                                print(f"Successfully connected and cached Gemini endpoint: {version}/models/{model}")
                                return parts[0].get("text", "").strip()
                    else:
                        last_status = response.status_code
                        last_body = response.text
                except Exception as e:
                    last_status = "ConnectionError"
                    last_body = str(e)
                    
    return f"💀 Huhu sếp ơi, Gemini API báo lỗi rồi: {last_status}.\nChi tiết: `{last_body[:300]}`\nEm đi ngủ đây! 🛌"
