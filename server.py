"""
FastAPI Backend Server for Multi-Source Candidate Data Transformer.

Exposes endpoints for file uploading, executing the pipeline dynamically,
resetting the sandbox to sample inputs, and serving the frontend dashboard UI.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel

from src.pipeline import run_pipeline
from src.projection.projector import ProjectionConfig

app = FastAPI(title="Candidate Data Transformer Dashboard")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directories
WORKSPACE_DIR = Path(__file__).parent.resolve()
UPLOAD_DIR = WORKSPACE_DIR / "uploads"
NOTES_DIR = UPLOAD_DIR / "notes"
RESUMES_DIR = UPLOAD_DIR / "resumes"
FRONTEND_DIR = WORKSPACE_DIR / "frontend"

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)
RESUMES_DIR.mkdir(parents=True, exist_ok=True)
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


class PipelineState:
    last_result: Optional[dict] = None
    last_run_success: bool = False
    error: Optional[str] = None


state = PipelineState()


@app.on_event("startup")
def startup_event():
    # Copy sample inputs to uploads directory if uploads is empty
    sample_inputs_dir = WORKSPACE_DIR / "sample_inputs"
    if sample_inputs_dir.exists() and not any(UPLOAD_DIR.iterdir()):
        print("Pre-populating uploads with sample inputs...")
        for item in sample_inputs_dir.iterdir():
            if item.is_file() and item.name in ("recruiter.csv", "ats.json"):
                shutil.copy(item, UPLOAD_DIR / item.name)
            elif item.is_dir() and item.name == "notes":
                for note_file in item.iterdir():
                    shutil.copy(note_file, NOTES_DIR / note_file.name)
                    
        # Create a mock resume PDF so there is a resume to process by default
        try:
            from tests.test_resume_extractor import create_mock_resume
            create_mock_resume(RESUMES_DIR / "Priya_Sharma_Resume.pdf")
            print("Sample inputs copied and default mock resume generated.")
        except Exception as exc:
            print(f"Could not generate mock resume during startup: {exc}")


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="Empty filename")
        
    try:
        # Determine target folder based on extension
        if filename.endswith(".pdf"):
            target_path = RESUMES_DIR / filename
        elif filename.endswith(".txt"):
            target_path = NOTES_DIR / filename
        elif filename.endswith((".csv", ".json")):
            target_path = UPLOAD_DIR / filename
        else:
            target_path = UPLOAD_DIR / filename

        with target_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        return {"status": "success", "filename": filename, "type": target_path.parent.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/run")
def execute_pipeline(config: Optional[dict] = None):
    try:
        projection_config = None
        if config:
            try:
                projection_config = ProjectionConfig.model_validate(config)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid projection config: {e}")
                
        # Run pipeline
        result = run_pipeline(
            input_dir=UPLOAD_DIR,
            projection_config=projection_config,
            notes_dir=NOTES_DIR
        )
        
        # Serialize candidate profiles for display
        candidates_data = []
        for c in result.candidates:
            candidates_data.append(c.model_dump())
            
        state.last_result = {
            "sources_processed": result.sources_processed,
            "sources_skipped": result.sources_skipped,
            "errors": result.errors,
            "candidates": candidates_data,
            "projected_output": result.projected_output
        }
        state.last_run_success = True
        return state.last_result
    except Exception as e:
        state.last_run_success = False
        state.error = str(e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/status")
def get_status():
    files = {
        "csv": [f.name for f in UPLOAD_DIR.glob("*.csv")],
        "json": [f.name for f in UPLOAD_DIR.glob("*.json")],
        "notes": [f.name for f in NOTES_DIR.glob("*.txt")],
        "resumes": [f.name for f in RESUMES_DIR.glob("*.pdf")]
    }
    return {
        "files": files,
        "last_run_success": state.last_run_success,
        "has_result": state.last_result is not None,
        "error": state.error
    }


@app.post("/api/reset")
def reset_uploads():
    try:
        # Clear files in uploads
        for f in UPLOAD_DIR.iterdir():
            if f.is_file():
                f.unlink()
        for f in NOTES_DIR.glob("*.txt"):
            f.unlink()
        for f in RESUMES_DIR.glob("*.pdf"):
            f.unlink()
            
        state.last_result = None
        state.last_run_success = False
        state.error = None
        
        # Repopulate
        startup_event()
        return {"status": "success", "message": "Uploads reset to sample inputs."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Serving the frontend static files
@app.get("/")
def get_index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>Frontend files not found</h1>")


@app.get("/style.css")
def get_css():
    return FileResponse(FRONTEND_DIR / "style.css")


@app.get("/app.js")
def get_js():
    return FileResponse(FRONTEND_DIR / "app.js")
