import json
import boto3
import asyncio
from config import (
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    AWS_REGION,
    AWS_BEDROCK_MODEL_ID
)

DEFAULT_SYSTEM_INSTRUCTION = (
    "Bạn là Trợ lý số hóa \"Cây Hài Văn Phòng\" của một nhóm văn phòng trẻ trung, vui nhộn. "
    "Nhiệm vụ của bạn là trò chuyện và trả lời các câu hỏi bằng tiếng Việt với phong cách cực kỳ hài hước, lầy lội, "
    "sử dụng nhiều từ ngữ văn phòng thịnh hành (slang), có chút \"cà khịa\" nhẹ nhàng nhưng văn minh, mang lại niềm vui cho cả team. "
    "Luôn sử dụng các emoji một cách dí dỏm (🤡, 🍱, 💻, ☕, 🤪, 🧐, 🚀, 🤦‍♂️, 💀). "
    "Nếu câu hỏi yêu cầu giải quyết công việc hoặc cung cấp thông tin, hãy lồng ghép câu trả lời chính xác vào trong câu đùa của bạn. "
    "Hãy trả lời ngắn gọn (không quá 2-4 câu ngắn đối với các câu chat thông thường) để tránh làm loãng group chat."
)

def _call_bedrock_sync(prompt: str, system_instruction: str = None) -> str:
    """Synchronous function to invoke AWS Bedrock (Claude 3.5 Sonnet)."""
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        return (
            "🔌 Sếp ơi, Trợ lý AI chưa được 'cắm điện'! "
            "Vui lòng cấu hình các biến môi trường AWS (`AWS_ACCESS_KEY_ID` & `AWS_SECRET_ACCESS_KEY`) trên Railway nhé 🤪."
        )
        
    try:
        # Initialize boto3 client
        client = boto3.client(
            service_name="bedrock-runtime",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY
        )
        
        # Payload structure for Claude 3 Messages API on AWS Bedrock
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": system_instruction or DEFAULT_SYSTEM_INSTRUCTION,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        })
        
        # Invoke model
        response = client.invoke_model(
            modelId=AWS_BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=body
        )
        
        # Parse response
        response_body = json.loads(response.get("body").read())
        content = response_body.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0].get("text", "").strip()
            
        return "🤪 Ối, Claude 3.5 Sonnet trả về kết quả rỗng tuếch sếp ạ!"
        
    except Exception as e:
        print(f"Exception during AWS Bedrock API call: {e}")
        return f"💀 Huhu sếp ơi, AWS Bedrock báo lỗi rồi: {str(e)[:150]}. Em đi ngủ đây! 🛌"

async def generate_ai_response(prompt: str, system_instruction: str = None) -> str:
    """Asynchronously calls AWS Bedrock using asyncio.to_thread to prevent blocking the event loop."""
    return await asyncio.to_thread(_call_bedrock_sync, prompt, system_instruction)
