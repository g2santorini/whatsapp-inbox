"""Unified task views: standalone work and authorized project tasks, with atomic Take Task."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .database import get_db
from . import models
from .project_models import Project, ProjectMember, ProjectTask
from .task_models import StandaloneTask, StandaloneTaskComment
from .project_api import TASK_STATUSES, TASK_PRIORITIES

class WorkItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=12000)
    priority: str = "normal"
    due_date: Optional[date] = None
    assigned_to_id: Optional[int] = None

class WorkItemUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=12000)
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[date] = None
    assigned_to_id: Optional[int] = None

class WorkCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=6000)

def _admin(user):
    return user.role == "admin"

def _editable(user):
    return user.role != "project_viewer"

def _active_assignee(db, assignee_id):
    if assignee_id is None:
        return
    person = db.get(models.User, assignee_id)
    if not person or person.disabled or person.role == "project_viewer":
        raise HTTPException(status_code=400, detail="Assignee is not an active editable user")

def _member_permissions(db, user):
    if _admin(user):
        return None
    return {m.project_id: m.permission for m in db.query(ProjectMember).filter_by(user_id=user.id)}

def _pool_eligible(user, permissions):
    return _editable(user) and (
        _admin(user)
        or user.role == "developer"
        or any(p in {"editor", "manager"} for p in (permissions or {}).values())
    )

def _standalone(db, task_id, user, permissions=None):
    task = db.get(StandaloneTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if permissions is None:
        permissions = _member_permissions(db, user)
    if not (
        _admin(user)
        or task.assigned_to_id == user.id
        or (task.assigned_to_id is None and task.status != "done" and _pool_eligible(user, permissions))
    ):
        raise HTTPException(status_code=404, detail="Task not found")
    return task

def _project_task(db, task_id, user, permissions=None):
    task = db.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if permissions is None:
        permissions = _member_permissions(db, user)
    if not _admin(user) and task.project_id not in permissions:
        raise HTTPException(status_code=404, detail="Task not found")
    return task

def _summary(task, kind, users, project_names, user, can_claim):
    project_id = task.project_id if kind == "project" else None
    return {
        "id": f"{'p' if kind == 'project' else 's'}:{task.id}",
        "task_id": task.id, "kind": kind,
        "project_id": project_id,
        "project_name": project_names.get(project_id) if project_id else None,
        "title": task.title, "description": task.description,
        "priority": task.priority, "status": task.status, "due_date": task.due_date,
        "assigned_to_id": task.assigned_to_id,
        "assigned_to_name": users.get(task.assigned_to_id),
        "created_at": task.created_at,
        "can_claim": bool(can_claim),
        "can_update_status": bool(_admin(user) or (
            _editable(user) and task.assigned_to_id == user.id
        )),
        "can_manage": _admin(user),
    }

def _tasks_for_user(db, user):
    permissions = _member_permissions(db, user)
    query = db.query(ProjectTask)
    if not _admin(user):
        if not permissions:
            project_tasks = []
        else:
            project_tasks = query.filter(ProjectTask.project_id.in_(list(permissions))).all()
    else:
        project_tasks = query.all()

    standalone_query = db.query(StandaloneTask)
    if not _admin(user):
        if _pool_eligible(user, permissions):
            standalone_query = standalone_query.filter(
                or_(StandaloneTask.assigned_to_id == user.id,
                    (StandaloneTask.assigned_to_id.is_(None)) & (StandaloneTask.status != "done"))
            )
        else:
            standalone_query = standalone_query.filter(StandaloneTask.assigned_to_id == user.id)
    standalone = standalone_query.all()
    return project_tasks, standalone, permissions

def _all_summaries(db, user):
    project_tasks, standalone, permissions = _tasks_for_user(db, user)
    ids = {t.assigned_to_id for t in [*project_tasks, *standalone] if t.assigned_to_id}
    users = {u.id: (u.display_name or u.full_name or u.username) for u in (
        db.query(models.User).filter(models.User.id.in_(ids)).all() if ids else []
    )}
    project_ids = {t.project_id for t in project_tasks}
    project_names = {p.id: p.name for p in (
        db.query(Project).filter(Project.id.in_(project_ids)).all() if project_ids else []
    )}
    result = [
        _summary(t, "project", users, project_names, user,
                 t.assigned_to_id is None and t.status != "done"
                 and _editable(user) and (
                     _admin(user) or permissions.get(t.project_id) in {"editor", "manager"}
                 ))
        for t in project_tasks
    ]
    result.extend([
        _summary(t, "standalone", users, project_names, user,
                 t.assigned_to_id is None and t.status != "done" and _pool_eligible(user, permissions))
        for t in standalone
    ])
    return sorted(result, key=lambda t: (t["status"] == "done", t["due_date"] is None,
                                       str(t["due_date"] or ""), t["id"]))

def create_tasks_router(active_user_dependency):
    router = APIRouter(prefix="/tasks", tags=["tasks"])

    @router.get("/")
    def tasks(db: Session = Depends(get_db), user: models.User = Depends(active_user_dependency)):
        return _all_summaries(db, user)

    @router.get("/overview")
    def overview(db: Session = Depends(get_db), user: models.User = Depends(active_user_dependency)):
        visible = _all_summaries(db, user)
        return {
            "total": len(visible),
            "open_pool": sum(1 for t in visible if t["can_claim"]),
            "mine": sum(1 for t in visible if t["assigned_to_id"] == user.id and t["status"] != "done"),
            "in_progress": sum(1 for t in visible if t["status"] == "in_progress"),
            "blocked": sum(1 for t in visible if t["status"] == "blocked"),
            "done": sum(1 for t in visible if t["status"] == "done"),
        }

    @router.get("/team")
    def team(db: Session = Depends(get_db), user: models.User = Depends(active_user_dependency)):
        if not _admin(user):
            raise HTTPException(status_code=403, detail="Team report requires admin")
        all_tasks = _all_summaries(db, user)
        users = db.query(models.User).filter(models.User.disabled.is_(False)).all()
        return [
            {
                "user_id": person.id,
                "name": person.display_name or person.full_name or person.username,
                "role": person.role,
                "active": sum(1 for t in all_tasks if t["assigned_to_id"] == person.id and t["status"] != "done"),
                "completed": sum(1 for t in all_tasks if t["assigned_to_id"] == person.id and t["status"] == "done"),
                "blocked": sum(1 for t in all_tasks if t["assigned_to_id"] == person.id and t["status"] == "blocked"),
            } for person in users
        ]

    @router.post("/standalone", status_code=201)
    def create(
        payload: WorkItemCreate, db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        if not _admin(user):
            raise HTTPException(status_code=403, detail="Only task managers can create tasks")
        if payload.priority not in TASK_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        _active_assignee(db, payload.assigned_to_id)
        name = payload.title.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Title required")
        task = StandaloneTask(**{**payload.model_dump(), "title": name}, created_by_id=user.id)
        db.add(task)
        db.commit()
        db.refresh(task)
        return {"id": task.id, "task_key": f"s:{task.id}"}

    @router.get("/standalone/{task_id}")
    def get_standalone(
        task_id: int, db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        task = _standalone(db, task_id, user)
        author_ids = {task.assigned_to_id} if task.assigned_to_id else set()
        comments = db.query(StandaloneTaskComment).filter_by(task_id=task.id).order_by(
            StandaloneTaskComment.created_at, StandaloneTaskComment.id).all()
        author_ids.update(c.author_id for c in comments)
        name_by_id = {p.id: p.display_name or p.full_name or p.username for p in (
            db.query(models.User).filter(models.User.id.in_(author_ids)).all()
            if author_ids else []
        )}
        return {
            "id": task.id, "title": task.title, "description": task.description,
            "status": task.status, "priority": task.priority,
            "due_date": task.due_date, "assigned_to_id": task.assigned_to_id,
            "assigned_to_name": name_by_id.get(task.assigned_to_id),
            "can_manage": _admin(user),
            "can_comment": _editable(user) and (_admin(user) or task.assigned_to_id == user.id),
            "comments": [{
                "id": c.id, "body": c.body, "author_name": name_by_id.get(c.author_id, "Unknown"),
                "created_at": c.created_at,
            } for c in comments],
        }

    @router.patch("/standalone/{task_id}")
    def update(
        task_id: int, payload: WorkItemUpdate,
        db: Session = Depends(get_db), user: models.User = Depends(active_user_dependency),
    ):
        task = _standalone(db, task_id, user)
        values = payload.model_dump(exclude_unset=True)
        if not _admin(user):
            if not _editable(user) or task.assigned_to_id != user.id or set(values) - {"status"}:
                raise HTTPException(status_code=403, detail="Only your task status can be changed")
        if "status" in values and values["status"] not in TASK_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        if "priority" in values and values["priority"] not in TASK_PRIORITIES:
            raise HTTPException(status_code=400, detail="Invalid priority")
        if "assigned_to_id" in values:
            _active_assignee(db, values["assigned_to_id"])
        if "title" in values:
            values["title"] = (values["title"] or "").strip()
            if not values["title"]:
                raise HTTPException(status_code=400, detail="Title required")
        for k,v in values.items():
            setattr(task,k,v)
        task.updated_at = datetime.utcnow()
        db.commit()
        return {"id": task.id, "status": task.status}

    @router.post("/standalone/{task_id}/claim")
    def claim_standalone(
        task_id: int, db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        permissions = _member_permissions(db, user)
        if not _pool_eligible(user, permissions):
            raise HTTPException(status_code=403, detail="No permission to take tasks")
        _standalone(db, task_id, user, permissions)
        updated = db.query(StandaloneTask).filter(
            StandaloneTask.id == task_id,
            StandaloneTask.assigned_to_id.is_(None),
            StandaloneTask.status != "done",
        ).update({"assigned_to_id": user.id, "status": "in_progress",
                  "updated_at": datetime.utcnow()}, synchronize_session=False)
        if not updated:
            db.rollback()
            raise HTTPException(status_code=409, detail="Task already taken")
        db.commit()
        return {"status": "claimed", "assigned_to_id": user.id}

    @router.post("/standalone/{task_id}/release")
    def release_standalone(
        task_id: int, db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        task = _standalone(db, task_id, user)
        if not _admin(user) and (not _editable(user) or task.assigned_to_id != user.id):
            raise HTTPException(status_code=403, detail="Only assignee or manager may release")
        if task.status == "done":
            raise HTTPException(status_code=409, detail="Completed task cannot be released")
        task.assigned_to_id = None
        task.status = "todo"
        task.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "released"}

    @router.post("/standalone/{task_id}/comments", status_code=201)
    def comment(
        task_id: int, payload: WorkCommentCreate,
        db: Session = Depends(get_db), user: models.User = Depends(active_user_dependency),
    ):
        task = _standalone(db, task_id, user)
        if not _editable(user) or (not _admin(user) and task.assigned_to_id != user.id):
            raise HTTPException(status_code=403, detail="Only task members may comment")
        body = payload.body.strip()
        if not body:
            raise HTTPException(status_code=400, detail="Comment required")
        row = StandaloneTaskComment(task_id=task_id, author_id=user.id, body=body)
        db.add(row)
        db.commit()
        return {"id": row.id}

    @router.post("/project/{task_id}/claim")
    def claim_project_task(
        task_id: int, db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        permissions = _member_permissions(db, user)
        task = _project_task(db, task_id, user, permissions)
        if not _editable(user) or not (
            _admin(user) or permissions.get(task.project_id) in {"editor", "manager"}
        ):
            raise HTTPException(status_code=403, detail="No permission to take this project task")
        updated = db.query(ProjectTask).filter(
            ProjectTask.id == task.id,
            ProjectTask.assigned_to_id.is_(None),
            ProjectTask.status != "done",
        ).update({"assigned_to_id": user.id, "status": "in_progress",
                  "updated_at": datetime.utcnow()}, synchronize_session=False)
        if not updated:
            db.rollback()
            raise HTTPException(status_code=409, detail="Task already taken")
        db.commit()
        return {"status": "claimed", "assigned_to_id": user.id}

    @router.post("/project/{task_id}/release")
    def release_project_task(
        task_id: int, db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        task = _project_task(db, task_id, user)
        if not _admin(user) and (
            not _editable(user) or task.assigned_to_id != user.id
        ):
            raise HTTPException(status_code=403, detail="Only assignee or manager may release")
        if task.status == "done":
            raise HTTPException(status_code=409, detail="Completed task cannot be released")
        task.assigned_to_id = None
        task.status = "todo"
        task.updated_at = datetime.utcnow()
        db.commit()
        return {"status": "released"}

    return router
