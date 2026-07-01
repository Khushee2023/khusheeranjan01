from pathlib import Path
import tempfile
import pytest
from reportlab.pdfgen import canvas
from src.extractors.resume_extractor import extract_resume
from src.models import SourceType


def create_mock_resume(path: Path):
    c = canvas.Canvas(str(path))
    # Draw simple name
    c.drawString(100, 750, "Priya Sharma")
    # Draw contact info
    c.drawString(100, 730, "priya.sharma@example.com | +91 9876543210")
    c.drawString(100, 715, "linkedin.com/in/priyasharma  github.com/priyash")
    
    # Skills
    c.drawString(100, 680, "Skills: Python, Javascript, React, SQL, AWS")
    
    # Experience Section
    c.drawString(100, 640, "Experience")
    c.drawString(100, 620, "Software Engineer at Google | Jan 2021 - Present")
    c.drawString(100, 605, "Developed scalable cloud services using Python and AWS.")
    
    c.drawString(100, 570, "Software Developer at Infosys | Jun 2018 - Dec 2020")
    c.drawString(100, 555, "Maintained enterprise databases and built frontend applications using React.")
    
    # Education Section
    c.drawString(100, 510, "Education")
    c.drawString(100, 490, "Bachelor of Science in Computer Science, Stanford University, 2018")
    
    c.save()


def test_resume_extraction():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "Priya_Sharma_Resume.pdf"
        create_mock_resume(pdf_path)
        
        records = extract_resume(pdf_path)
        assert len(records) == 1
        record = records[0]
        
        assert record.source_type == SourceType.RESUME
        assert record.source_id == "Priya_Sharma_Resume.pdf"
        
        # Name
        assert record.full_name is not None
        assert record.full_name.value == "Priya Sharma"
        
        # Contact info
        assert len(record.emails) == 1
        assert record.emails[0].value == "priya.sharma@example.com"
        
        assert len(record.phones) == 1
        assert record.phones[0].value == "+91 9876543210"
        
        # Links
        assert record.links.linkedin == "https://linkedin.com/in/priyasharma"
        assert record.links.github == "https://github.com/priyash"
        
        # Skills
        extracted_skills = [s.value for s in record.skills_raw]
        assert "python" in extracted_skills
        assert "javascript" in extracted_skills
        assert "react" in extracted_skills
        assert "sql" in extracted_skills
        assert "aws" in extracted_skills
        
        # Experience
        assert len(record.experience_raw) == 2
        exp1 = record.experience_raw[0]
        assert exp1.company == "Google"
        assert exp1.title == "Software Engineer"
        assert exp1.start == "Jan 2021"
        assert exp1.end == "Present"
        
        exp2 = record.experience_raw[1]
        assert exp2.company == "Infosys"
        assert exp2.title == "Software Developer"
        assert exp2.start == "Jun 2018"
        assert exp2.end == "Dec 2020"
        
        # Education
        assert len(record.education_raw) == 1
        edu = record.education_raw[0]
        assert edu.institution == "Stanford University"
        assert edu.degree == "Bachelor of Science"
        assert edu.field == "Computer Science"
        assert edu.end_year == 2018


def test_empty_resume():
    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "empty.pdf"
        c = canvas.Canvas(str(pdf_path))
        c.save()
        
        records = extract_resume(pdf_path)
        assert len(records) == 1
        assert "empty_resume_text" in records[0].parse_errors
