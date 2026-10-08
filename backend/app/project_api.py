"""Project Manager REST endpoints with per-project membership checks."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .database import get_db
from . import models
from .project_models import Project, ProjectMember, ProjectMilestone, ProjectTask, ProjectTaskComment


TASK_STATUSES = {"todo", "in_progress", "blocked", "done"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
PROJECT_STATUSES = {"active", "paused", "completed"}
MANAGER_ROLES = {"admin"}


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=12000)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=12000)
    status: Optional[str] = None


class MembershipCreate(BaseModel):
    user_id: int
    permission: str = "editor"


class MembershipUpdate(BaseModel):
    permission: str


class MilestoneCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class MilestoneUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=12000)
    milestone_id: Optional[int] = None
    parent_task_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    priority: str = "normal"
    due_date: Optional[date] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=12000)
    milestone_id: Optional[int] = None
    parent_task_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    priority: Optional[str] = None
    due_date: Optional[date] = None
    status: Optional[str] = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=6000)


def _manager(user):
    return user.role in MANAGER_ROLES


def _project(db, project_id, user, edit=False, manager=False):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if _manager(user):
        return project
    member = db.query(ProjectMember).filter_by(project_id=project_id, user_id=user.id).first()
    if not member:
        # Do not disclose existence of projects outside the user's membership.
        raise HTTPException(status_code=404, detail="Project not found")
    if manager or (edit and (user.role == "project_viewer" or member.permission != "editor")):
        raise HTTPException(status_code=403, detail="Read-only project access")
    return project


def _manager_only(user):
    if not _manager(user):
        raise HTTPException(status_code=403, detail="Project management permission required")


def _task(db, project_id, task_id):
    task = db.get(ProjectTask, task_id)
    if not task or task.project_id != project_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _validate_task_links(db, project_id, values, task=None):
    if "milestone_id" in values and values["milestone_id"] is not None:
        milestone = db.get(ProjectMilestone, values["milestone_id"])
        if not milestone or milestone.project_id != project_id:
            raise HTTPException(status_code=400, detail="Milestone must belong to project")
    if "assigned_to_id" in values and values["assigned_to_id"] is not None:
        member = db.query(ProjectMember).filter_by(
            project_id=project_id, user_id=values["assigned_to_id"]
        ).first()
        if not member:
            raise HTTPException(status_code=400, detail="Assignee must be a project member")
    if "parent_task_id" in values and values["parent_task_id"] is not None:
        parent_id = values["parent_task_id"]
        parent = _task(db, project_id, parent_id)
        seen = {task.id} if task else set()
        while parent:
            if parent.id in seen:
                raise HTTPException(status_code=400, detail="Circular subtask hierarchy")
            seen.add(parent.id)
            parent = db.get(ProjectTask, parent.parent_task_id) if parent.parent_task_id else None
            if parent and parent.project_id != project_id:
                raise HTTPException(status_code=400, detail="Invalid subtask hierarchy")
    if values.get("status") is not None and values["status"] not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid task status")
    if values.get("priority") is not None and values["priority"] not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid task priority")


def _project_summary(project, tasks):
    parent_ids = {t.parent_task_id for t in tasks if t.parent_task_id is not None}
    leaves = [t for t in tasks if t.id not in parent_ids]
    done = sum(1 for t in leaves if t.status == "done")
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "created_by_id": project.created_by_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "progress": round(done * 100 / len(leaves)) if leaves else 0,
        "completed_tasks": done,
        "total_tasks": len(leaves),
        "blocked_tasks": sum(1 for t in leaves if t.status == "blocked"),
    }


def _display_name(user):
    return user.display_name or user.full_name or user.username


def create_project_router(active_user_dependency):
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.get("/")
    def list_projects(
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        query = db.query(Project)
        if not _manager(user):
            query = query.join(ProjectMember).filter(ProjectMember.user_id == user.id)
        projects = query.order_by(Project.updated_at.desc(), Project.id.desc()).all()
        if not projects:
            return []
        ids = [p.id for p in projects]
        all_tasks = db.query(ProjectTask).filter(ProjectTask.project_id.in_(ids)).all()
        return [
            _project_summary(project, [t for t in all_tasks if t.project_id == project.id])
            for project in projects
        ]

    @router.post("/", status_code=201)
    def create_project(
        payload: ProjectCreate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        project = Project(
            name=payload.name.strip(), description=payload.description,
            created_by_id=user.id,
        )
        if not project.name:
            raise HTTPException(status_code=400, detail="Project name required")
        db.add(project)
        db.commit()
        db.refresh(project)
        return _project_summary(project, [])

    @router.get("/{project_id}")
    def get_project(
        project_id: int,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        project = _project(db, project_id, user)
        tasks = db.query(ProjectTask).filter_by(project_id=project.id).order_by(
            ProjectTask.position, ProjectTask.id
        ).all()
        milestones = db.query(ProjectMilestone).filter_by(project_id=project.id).order_by(
            ProjectMilestone.position, ProjectMilestone.id
        ).all()
        members = db.query(ProjectMember).filter_by(project_id=project.id).all()
        comments = db.query(ProjectTaskComment).filter_by(project_id=project.id).order_by(
            ProjectTaskComment.created_at, ProjectTaskComment.id
        ).all()
        ids = {m.user_id for m in members}
        ids.update(t.assigned_to_id for t in tasks if t.assigned_to_id is not None)
        ids.update(c.author_id for c in comments)
        user_lookup = {
            u.id: u for u in db.query(models.User).filter(models.User.id.in_(ids)).all()
        } if ids else {}
        response = _project_summary(project, tasks)
        response["can_manage"] = _manager(user)
        response["can_edit"] = _manager(user) or (
            user.role != "project_viewer"
            and any(m.user_id == user.id and m.permission == "editor" for m in members)
        )
        response["members"] = [
            {
                "user_id": m.user_id,
                "name": _display_name(user_lookup[m.user_id]) if m.user_id in user_lookup else "Unknown",
                "permission": m.permission,
            } for m in members
        ]
        response["milestones"] = [{
            "id": m.id, "title": m.title, "position": m.position,
            "progress": _project_summary(project, [t for t in tasks if t.milestone_id == m.id])["progress"],
        } for m in milestones]
        response["tasks"] = [{
            "id": t.id, "project_id": t.project_id, "milestone_id": t.milestone_id,
            "parent_task_id": t.parent_task_id, "title": t.title,
            "description": t.description, "status": t.status, "priority": t.priority,
            "assigned_to_id": t.assigned_to_id,
            "assigned_to_name": _display_name(user_lookup[t.assigned_to_id]) if t.assigned_to_id in user_lookup else None,
            "due_date": t.due_date, "position": t.position,
            "created_at": t.created_at, "updated_at": t.updated_at,
        } for t in tasks]
        response["comments"] = [{
            "id": c.id, "task_id": c.task_id, "author_id": c.author_id,
            "author_name": _display_name(user_lookup[c.author_id]) if c.author_id in user_lookup else "Unknown",
            "body": c.body, "created_at": c.created_at,
        } for c in comments]
        return response

    @router.patch("/{project_id}")
    def update_project(
        project_id: int,
        payload: ProjectUpdate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        project = _project(db, project_id, user)
        values = payload.model_dump(exclude_unset=True)
        if "name" in values:
            values["name"] = (values["name"] or "").strip()
            if not values["name"]:
                raise HTTPException(status_code=400, detail="Project name required")
        if "status" in values and values["status"] not in PROJECT_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid project status")
        for key, value in values.items():
            setattr(project, key, value)
        project.updated_at = datetime.utcnow()
        db.commit()
        return _project_summary(project, db.query(ProjectTask).filter_by(project_id=project_id).all())

    @router.post("/{project_id}/members", status_code=201)
    def add_member(
        project_id: int,
        payload: MembershipCreate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        _project(db, project_id, user)
        if payload.permission not in {"editor", "viewer"}:
            raise HTTPException(status_code=400, detail="Invalid project permission")
        member_user = db.get(models.User, payload.user_id)
        if not member_user or member_user.disabled:
            raise HTTPException(status_code=404, detail="User not found")
        existing = db.query(ProjectMember).filter_by(
            project_id=project_id, user_id=payload.user_id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="Already a member")
        db.add(ProjectMember(
            project_id=project_id,
            user_id=payload.user_id,
            permission="viewer" if member_user.role == "project_viewer" else payload.permission,
        ))
        db.commit()
        return {"status": "added"}

    @router.patch("/{project_id}/members/{member_id}")
    def update_member(
        project_id: int,
        member_id: int,
        payload: MembershipUpdate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        _project(db, project_id, user)
        if payload.permission not in {"editor", "viewer"}:
            raise HTTPException(status_code=400, detail="Invalid permission")
        member = db.query(ProjectMember).filter_by(project_id=project_id, user_id=member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        member_user = db.get(models.User, member_id)
        member.permission = "viewer" if member_user.role == "project_viewer" else payload.permission
        db.commit()
        return {"status": "updated"}

    @router.delete("/{project_id}/members/{member_id}")
    def remove_member(
        project_id: int,
        member_id: int,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        _project(db, project_id, user)
        member = db.query(ProjectMember).filter_by(project_id=project_id, user_id=member_id).first()
        if not member:
            raise HTTPException(status_code=404, detail="Member not found")
        db.delete(member)
        db.commit()
        return {"status": "removed"}

    @router.post("/{project_id}/milestones", status_code=201)
    def add_milestone(
        project_id: int,
        payload: MilestoneCreate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        _project(db, project_id, user)
        milestone = ProjectMilestone(project_id=project_id, title=payload.title.strip())
        if not milestone.title:
            raise HTTPException(status_code=400, detail="Milestone title required")
        db.add(milestone)
        db.commit()
        db.refresh(milestone)
        return {"id": milestone.id, "title": milestone.title}

    @router.patch("/{project_id}/milestones/{milestone_id}")
    def rename_milestone(
        project_id: int,
        milestone_id: int,
        payload: MilestoneUpdate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        _project(db, project_id, user)
        milestone = db.get(ProjectMilestone, milestone_id)
        if not milestone or milestone.project_id != project_id:
            raise HTTPException(status_code=404, detail="Milestone not found")
        milestone.title = payload.title.strip()
        if not milestone.title:
            raise HTTPException(status_code=400, detail="Milestone title required")
        db.commit()
        return {"id": milestone.id, "title": milestone.title}

    @router.post("/{project_id}/tasks", status_code=201)
    def add_task(
        project_id: int,
        payload: TaskCreate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _manager_only(user)
        _project(db, project_id, user)
        values = payload.model_dump()
        _validate_task_links(db, project_id, values)
        values["title"] = values["title"].strip()
        if not values["title"]:
            raise HTTPException(status_code=400, detail="Task title required")
        task = ProjectTask(project_id=project_id, created_by_id=user.id, **values)
        db.add(task)
        db.commit()
        db.refresh(task)
        return {"id": task.id, "status": task.status}

    @router.patch("/{project_id}/tasks/{task_id}")
    def update_task(
        project_id: int,
        task_id: int,
        payload: TaskUpdate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _project(db, project_id, user, edit=True)
        task = _task(db, project_id, task_id)
        values = payload.model_dump(exclude_unset=True)
        if not _manager(user) and set(values) - {"status"}:
            raise HTTPException(status_code=403, detail="Only managers can change task details")
        _validate_task_links(db, project_id, values, task)
        if "title" in values:
            values["title"] = (values["title"] or "").strip()
            if not values["title"]:
                raise HTTPException(status_code=400, detail="Task title required")
        for key, value in values.items():
            setattr(task, key, value)
        task.updated_at = datetime.utcnow()
        db.commit()
        return {"id": task.id, "status": task.status}

    @router.post("/{project_id}/tasks/{task_id}/comments", status_code=201)
    def add_comment(
        project_id: int,
        task_id: int,
        payload: CommentCreate,
        db: Session = Depends(get_db),
        user: models.User = Depends(active_user_dependency),
    ):
        _project(db, project_id, user, edit=True)
        _task(db, project_id, task_id)
        comment_body = payload.body.strip()
        if not comment_body:
            raise HTTPException(status_code=400, detail="Comment cannot be empty")
        comment = ProjectTaskComment(
            project_id=project_id, task_id=task_id, author_id=user.id, body=comment_body
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)
        return {"id": comment.id, "created_at": comment.created_at}

    return router
