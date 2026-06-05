import httpx
from config import GEMINI_API_KEY

DEFAULT_SYSTEM_INSTRUCTION = (
    "Bạn là Trợ lý số hóa \"Cây Hài Văn Phòng\" của một nhóm văn phòng trẻ trung, vui nhộn. "
    "Nhiệm vụ của bạn là trò chuyện và trả lời các câu hỏi bằng tiếng Việt với phong cách cực kỳ hài hước, lầy lội, "
    "sử dụng nhiều từ ngữ văn phòng thịnh hành (slang), có chút \"cà khịa\" nhẹ nhàng nhưng văn minh, mang lại niềm vui cho cả team. "
    "Luôn sử dụng các emoji một cách dí dỏm (🤡, 🍱, 💻, ☕, 🤪, 🧐, 🚀, 🤦‍♂️, 💀). "
    "Nếu câu hỏi yêu cầu giải quyết công việc hoặc cung cấp thông tin, hãy lồng ghép câu trả lời chính xác vào trong câu đùa của bạn. "
    "Hãy trả lời ngắn gọn (không quá 2-4 câu ngắn đối với các câu chat thông thường) để tránh làm loãng group chat."
)

async def generate_ai_response(prompt: str, system_instruction: str = None) -> str:
    """Calls Gemini API asynchronously using httpx."""
    if not GEMINI_API_KEY:
        return (
            "🔌 Sếp ơi, Trợ lý AI chưa được 'cắm điện'! "
            "Vui lòng cấu hình `GEMINI_API_KEY` trong file `.env` để kích hoạt nhé 🤪."
        )
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
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
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                # Extract text response from Gemini API structure
                candidates = data.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                return "🤪 Ối, Gemini trả về kết quả rỗng tuếch sếp ạ!"
            else:
                print(f"Gemini API Error Status: {response.status_code}, Body: {response.text}")
                return f"💀 Huhu sếp ơi, Gemini API báo lỗi rồi: {response.status_code}. Em đi ngủ đây! 🛌"
    except Exception as e:
        print(f"Exception during Gemini API call: {e}")
        return "🧠 Đầu óc em đang bị chập mạch rồi sếp ạ! (Network/Timeout Error) 🤪"
