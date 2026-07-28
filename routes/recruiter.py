from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from database import db
from models import RecruiterJobPost, ApplicationStatus
from jose import jwt, JWTError
from bson import ObjectId
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

router = APIRouter()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/users/login")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

# ── helper: get current user from token ──────────────────────
async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        role = payload.get("role")
        user = await db["users"].find_one({"email": email})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {"email": email, "role": role, "id": str(user["_id"])}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# ── helper: recruiter only ───────────────────────────────────
async def recruiter_only(user=Depends(get_current_user)):
    if user["role"] != "recruiter":
        raise HTTPException(status_code=403, detail="Recruiters only")
    return user

# ════════════════════════════════════════════════════════════
#  JOB ROUTES
# ════════════════════════════════════════════════════════════

# Post a new job
@router.post("/jobs")
async def post_job(job: RecruiterJobPost, user=Depends(recruiter_only)):
    job_data = job.dict()
    job_data["recruiter_id"] = user["id"]
    job_data["recruiter_email"] = user["email"]
    job_data["status"] = "active"
    job_data["created_at"] = datetime.utcnow().isoformat()
    result = await db["jobs"].insert_one(job_data)
    return {"message": "Job posted successfully", "job_id": str(result.inserted_id)}

# Get all jobs posted by THIS recruiter
@router.get("/jobs")
async def get_my_jobs(user=Depends(recruiter_only)):
    jobs = []
    async for job in db["jobs"].find({"recruiter_id": user["id"]}):
        job["_id"] = str(job["_id"])
        jobs.append(job)
    return jobs

# Get dashboard stats
@router.get("/dashboard")
async def get_dashboard(user=Depends(recruiter_only)):
    total_jobs = await db["jobs"].count_documents({"recruiter_id": user["id"]})
    
    job_ids = []
    async for job in db["jobs"].find({"recruiter_id": user["id"]}, {"_id": 1}):
        job_ids.append(str(job["_id"]))
    
    total_applicants = await db["applications"].count_documents(
        {"job_id": {"$in": job_ids}}
    )
    shortlisted = await db["applications"].count_documents(
        {"job_id": {"$in": job_ids}, "status": "shortlisted"}
    )
    pending = await db["applications"].count_documents(
        {"job_id": {"$in": job_ids}, "status": "pending"}
    )
    
    return {
        "total_jobs": total_jobs,
        "total_applicants": total_applicants,
        "shortlisted": shortlisted,
        "pending": pending
    }

# Toggle job status active/closed
@router.patch("/jobs/{job_id}/status")
async def toggle_job_status(job_id: str, status: str, user=Depends(recruiter_only)):
    job = await db["jobs"].find_one({"_id": ObjectId(job_id), "recruiter_id": user["id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db["jobs"].update_one(
        {"_id": ObjectId(job_id)},
        {"$set": {"status": status}}
    )
    return {"message": f"Job marked as {status}"}

# Delete a job
@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, user=Depends(recruiter_only)):
    job = await db["jobs"].find_one({"_id": ObjectId(job_id), "recruiter_id": user["id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    await db["jobs"].delete_one({"_id": ObjectId(job_id)})
    return {"message": "Job deleted"}

# ════════════════════════════════════════════════════════════
#  APPLICANT ROUTES
# ════════════════════════════════════════════════════════════

 
 # Get all applicants for a specific job
@router.get("/jobs/{job_id}/applicants")
async def get_applicants(job_id: str, user=Depends(recruiter_only)):
    # verify this job belongs to recruiter
    job = await db["jobs"].find_one({"_id": ObjectId(job_id), "recruiter_id": user["id"]})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    applicants = []
    async for app in db["applications"].find({"job_id": job_id}):
        app["_id"] = str(app["_id"])

        # Look up resume_url from the student's profile
        profile = await db["student_profiles"].find_one({"user_id": app["student_id"]})
        app["resume_url"] = profile.get("resume_url") if profile else None

        applicants.append(app)
    return applicants

# Update applicant status (shortlist / reject / pending)
@router.patch("/applicants/{app_id}/status")
async def update_applicant_status(
    app_id: str,
    body: ApplicationStatus,
    user=Depends(recruiter_only)
):
    if body.status not in ["pending", "shortlisted", "rejected"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    result = await db["applications"].update_one(
        {"_id": ObjectId(app_id)},
        {"$set": {"status": body.status}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"message": f"Status updated to {body.status}"}
