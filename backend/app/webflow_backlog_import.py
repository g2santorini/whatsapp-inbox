"""Idempotent, admin-confirmed import of the supplied Sunset Oia development backlog.

Maps one existing 'Webflow - Ai' project to 12 project-section milestones,
28 parent tasks, 134 subtasks, and 10 specification tasks. Preserves original
Greek wording and PXX-YY/SPEC-XX tracking codes.
"""
import json
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy.orm import Session
from .project_models import Project, ProjectMilestone, ProjectTask

_SOURCE = Path(__file__).resolve().parent / "backlogs" / "webflow_ai_2026.json"


def import_webflow_ai_backlog(db: Session, project: Project, created_by_id: int):
    if project.name.strip().casefold() != "webflow - ai":
        raise HTTPException(status_code=400, detail="Only the Webflow - Ai project accepts this backlog")
    # Reject any import if work already exists: ensures no duplicates and no
    # accidental changes to an established plan.
    if db.query(ProjectMilestone.id).filter_by(project_id=project.id).first() or (
        db.query(ProjectTask.id).filter_by(project_id=project.id).first()
    ):
        raise HTTPException(status_code=409, detail="This project is not empty; import cancelled")

    data = json.loads(_SOURCE.read_text(encoding="utf-8"))
    if data["target_project"] != "Webflow - Ai" or len(data["sections"]) != 12:
        raise HTTPException(status_code=500, detail="Invalid packaged backlog")

    counts = {"sections": 0, "milestones": 0, "tasks": 0, "specifications": 0}
    try:
        for section_index, section in enumerate(data["sections"], start=1):
            category = ProjectMilestone(
                project_id=project.id,
                title=f"PROJECT {section['number']} — {section['title']}",
                position=section_index,
            )
            db.add(category)
            db.flush()
            counts["sections"] += 1

            for milestone_index, milestone in enumerate(section["milestones"], start=1):
                parent = ProjectTask(
                    project_id=project.id,
                    milestone_id=category.id,
                    created_by_id=created_by_id,
                    title=f"Milestone {milestone['number']} — {milestone['title']}",
                    description="Ομάδα εργασιών του development backlog.",
                    status="todo",
                    position=milestone_index,
                )
                db.add(parent)
                db.flush()
                counts["milestones"] += 1

                for task_index, item in enumerate(milestone["tasks"], start=1):
                    db.add(ProjectTask(
                        project_id=project.id,
                        milestone_id=category.id,
                        parent_task_id=parent.id,
                        created_by_id=created_by_id,
                        title=f"{item['code']} — {item['title']}",
                        status="todo",
                        position=task_index,
                    ))
                    counts["tasks"] += 1

        if data["specifications"]:
            specs = ProjectMilestone(
                project_id=project.id,
                title="ΑΝΟΙΧΤΕΣ ΠΡΟΔΙΑΓΡΑΦΕΣ",
                position=13,
            )
            db.add(specs)
            db.flush()
            for position, item in enumerate(data["specifications"], start=1):
                db.add(ProjectTask(
                    project_id=project.id,
                    milestone_id=specs.id,
                    created_by_id=created_by_id,
                    title=f"{item['code']} — {item['title']}",
                    status="todo",
                    position=position,
                ))
                counts["specifications"] += 1

        if counts != {"sections": 12, "milestones": 28, "tasks": 134, "specifications": 10}:
            raise ValueError("Backlog counts do not match expected source")
        db.commit()
        return {"status": "imported", **counts}
    except Exception:
        db.rollback()
        raise
