from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from database import db
from jose import jwt, JWTError
from fastapi import HTTPException
import google.generativeai as genai
from datetime import datetime
import os

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login", auto_error=False)
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

async def get_optional_user(token: str = Depends(oauth2_scheme)):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        user = await db["users"].find_one({"email": email})
        if not user:
            return None
        return {"email": email, "id": str(user["_id"]), "name": user["name"]}
    except JWTError:
        return None

@router.post("/recommend")
async def get_recommendations(data: dict):
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-flash-latest")

    skills = data.get("skills", [])
    prompt = f"""
    Based on these skills: {', '.join(skills)}
    Suggest 5 career paths with:
    1. Job title
    2. Why it suits these skills
    3. Skill gaps to fill
    Return as JSON.
    """
    response = model.generate_content(prompt)
    return {"recommendations": response.text}

@router.get("/generate-questions")
async def generate_questions():
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-flash-latest")

    prompt = """
    Generate 9 aptitude test questions (3 LRDI, 3 QA, 3 VARC).
    Return ONLY a JSON array in this exact format:
    [
      {
        "id": 1,
        "section": "LRDI",
        "question": "question text",
        "options": ["A", "B", "C", "D"],
        "answer": "correct option"
      }
    ]
    Make questions unique and different each time. No markdown, just pure JSON.
    """

    response = model.generate_content(prompt)
    cleaned = response.text.replace("```json", "").replace("```", "").strip()
    import json
    questions = json.loads(cleaned)
    return {"questions": questions}

@router.post("/save-aptitude")
async def save_aptitude(data: dict, user=Depends(get_optional_user)):
    if not user:
        return {"message": "Not logged in, score not saved"}

    score = data.get("score")
    total = data.get("total")
    sections = data.get("sections", {})

    await db["student_profiles"].update_one(
        {"user_id": user["id"]},
        {"$set": {
            "user_id": user["id"],
            "email": user["email"],
            "aptitude_score": {
                "score": score,
                "total": total,
                "percentage": round((score / total) * 100) if total else 0,
                "sections": sections
            },
            "updated_at": datetime.utcnow().isoformat()
        }},
        upsert=True
    )
    return {"message": "Aptitude score saved successfully"}
