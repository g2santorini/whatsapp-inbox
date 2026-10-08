import { useCallback, useEffect, useMemo, useState } from 'react';
import sendroLogo from './assets/sendro_logo_reversed.png';
import { getUsers } from './api';
import { projectApi } from './projectApi';
import './ProjectWorkspace.css';

const STATUSES = [
  { value: 'todo', label: 'To do' },
  { value: 'in_progress', label: 'In progress' },
  { value: 'blocked', label: 'Blocked' },
  { value: 'done', label: 'Done' },
];
const EMPTY_TASK = { title: '', description: '', priority: 'normal', due_date: '', assigned_to_id: '' };
const isManagerRole = (role) => role === 'admin' || role === 'power_user';

function Progress({ progress }) {
  return (
    <div className="pm-progress">
      <div className="pm-progress-track" role="progressbar" aria-label="Project completion" aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100">
        <span style={{ width: `${progress}%` }} />
      </div>
      <strong>{progress}%</strong>
    </div>
  );
}

function formatDate(value) {
  if (!value) return '';
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

export default function ProjectWorkspace({ currentUser, onBack, onLogout }) {
  const [projects, setProjects] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [allUsers, setAllUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [projectDraft, setProjectDraft] = useState({ name: '', description: '' });
  const [newMilestone, setNewMilestone] = useState('');
  const [taskTarget, setTaskTarget] = useState(null);
  const [taskDraft, setTaskDraft] = useState(EMPTY_TASK);
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [comment, setComment] = useState('');
  const [memberId, setMemberId] = useState('');
  const [memberPermission, setMemberPermission] = useState('editor');
  const isManager = isManagerRole(currentUser.role);

  const refreshList = useCallback(async () => {
    const list = await projectApi.list();
    setProjects(list);
    setActiveId((previous) => previous && list.some((p) => p.id === previous) ? previous : list[0]?.id ?? null);
    return list;
  }, []);

  const refreshDetail = useCallback(async (id) => {
    if (!id) {
      setDetail(null);
      return;
    }
    const result = await projectApi.get(id);
    setDetail(result);
  }, []);

  useEffect(() => {
    let cancelled = false;
    projectApi.list()
      .then((list) => {
        if (cancelled) return;
        setProjects(list);
        setActiveId(list[0]?.id ?? null);
      })
      .catch((err) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    if (isManager) {
      getUsers().then((list) => { if (!cancelled) setAllUsers(list); }).catch(() => {});
    }
    return () => { cancelled = true; };
  }, [isManager]);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setSelectedTaskId(null);
    setComment('');
    if (activeId) {
      projectApi.get(activeId)
        .then((result) => { if (!cancelled) setDetail(result); })
        .catch((err) => { if (!cancelled) setError(err.message); });
    }
    return () => { cancelled = true; };
  }, [activeId]);

  const act = async (callback, nextId = activeId) => {
    setWorking(true);
    setError('');
    try {
      await callback();
      await Promise.all([refreshList(), refreshDetail(nextId)]);
    } catch (err) {
      setError(err.message || 'Could not save changes.');
    } finally {
      setWorking(false);
    }
  };

  const taskMap = useMemo(() => new Map((detail?.tasks || []).map((t) => [t.id, t])), [detail]);
  const focusedTask = selectedTaskId ? taskMap.get(selectedTaskId) : null;
  const focusedComments = (detail?.comments || []).filter((c) => c.task_id === selectedTaskId);

  const createProject = async (event) => {
    event.preventDefault();
    if (!projectDraft.name.trim()) return;
    setWorking(true);
    setError('');
    try {
      const created = await projectApi.create(projectDraft);
      await refreshList();
      setActiveId(created.id);
      setProjectDraft({ name: '', description: '' });
      setCreateOpen(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setWorking(false);
    }
  };

  const createTask = async (event) => {
    event.preventDefault();
    if (!detail || !taskDraft.title.trim() || !taskTarget) return;
    const payload = {
      title: taskDraft.title.trim(),
      description: taskDraft.description,
      priority: taskDraft.priority,
      due_date: taskDraft.due_date || null,
      assigned_to_id: taskDraft.assigned_to_id ? Number(taskDraft.assigned_to_id) : null,
      milestone_id: taskTarget.milestoneId,
      parent_task_id: taskTarget.parentId,
    };
    await act(() => projectApi.addTask(detail.id, payload));
    setTaskTarget(null);
    setTaskDraft(EMPTY_TASK);
  };

  const renderTask = (task, depth = 0) => {
    if (depth > 12) return null;
    const children = (detail.tasks || []).filter((t) => t.parent_task_id === task.id);
    return (
      <div className="pm-task-group" key={task.id}>
        <div className={`pm-task ${selectedTaskId === task.id ? 'selected' : ''}`} style={{ paddingLeft: `${Math.min(depth, 5) * 18 + 12}px` }}>
          <input
            type="checkbox"
            aria-label={`Mark ${task.title} complete`}
            checked={task.status === 'done'}
            disabled={!detail.can_edit || working}
            onChange={(event) => act(() => projectApi.updateTask(detail.id, task.id, { status: event.target.checked ? 'done' : 'todo' }))}
          />
          <button className="pm-task-title" type="button" onClick={() => setSelectedTaskId(task.id)}>
            <span className={task.status === 'done' ? 'pm-done-text' : ''}>{task.title}</span>
            <small>{task.assigned_to_name || 'Unassigned'} {task.due_date ? `· Due ${formatDate(task.due_date)}` : ''}</small>
          </button>
          <select
            className={`pm-task-status status-${task.status}`}
            value={task.status}
            disabled={!detail.can_edit || working}
            aria-label={`Status for ${task.title}`}
            onChange={(event) => act(() => projectApi.updateTask(detail.id, task.id, { status: event.target.value }))}
          >
            {STATUSES.map((status) => <option key={status.value} value={status.value}>{status.label}</option>)}
          </select>
          {detail.can_manage && <button className="pm-subtask-button" type="button" title="Add subtask" onClick={() => { setTaskTarget({ milestoneId: task.milestone_id, parentId: task.id }); setTaskDraft(EMPTY_TASK); }}>+</button>}
        </div>
        {children.map((child) => renderTask(child, depth + 1))}
      </div>
    );
  };

  const taskForm = () => (
    <form className="pm-task-form" onSubmit={createTask}>
      <input autoFocus required maxLength="200" placeholder={taskTarget?.parentId ? 'Subtask title' : 'Task title'} value={taskDraft.title} onChange={(e) => setTaskDraft((old) => ({ ...old, title: e.target.value }))} />
      <textarea rows="2" maxLength="12000" placeholder="Description and acceptance criteria" value={taskDraft.description} onChange={(e) => setTaskDraft((old) => ({ ...old, description: e.target.value }))} />
      <div className="pm-form-row">
        <select value={taskDraft.assigned_to_id} onChange={(e) => setTaskDraft((old) => ({ ...old, assigned_to_id: e.target.value }))}>
          <option value="">Unassigned</option>
          {detail.members.map((member) => <option key={member.user_id} value={member.user_id}>{member.name}</option>)}
        </select>
        <select value={taskDraft.priority} onChange={(e) => setTaskDraft((old) => ({ ...old, priority: e.target.value }))}>
          <option value="low">Low</option>
          <option value="normal">Normal</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </select>
        <input type="date" aria-label="Due date" value={taskDraft.due_date} onChange={(e) => setTaskDraft((old) => ({ ...old, due_date: e.target.value }))} />
      </div>
      <div className="pm-form-actions">
        <button type="submit" disabled={working}>Save task</button>
        <button type="button" className="pm-secondary" onClick={() => setTaskTarget(null)}>Cancel</button>
      </div>
    </form>
  );

  const unassignedUsers = allUsers.filter((u) => !u.disabled && !(detail?.members || []).some((m) => m.user_id === u.id));

  return (
    <div className="pm-shell">
      <aside className="pm-sidebar">
        <div className="pm-brand"><img src={sendroLogo} alt="Sendro" /><span>PROJECTS</span></div>
        <div className="pm-side-heading">Workspace</div>
        {loading ? <p className="pm-sidebar-muted">Loading projects…</p> : (
          <div className="pm-project-list">
            {projects.map((project) => (
              <button type="button" key={project.id} className={`pm-project-link ${project.id === activeId ? 'active' : ''}`} onClick={() => setActiveId(project.id)}>
                <span className="pm-project-symbol">▦</span>
                <span className="pm-project-info"><strong>{project.name}</strong><small>{project.progress}% complete</small></span>
              </button>
            ))}
          </div>
        )}
        {isManager && <button className="pm-new-project" type="button" onClick={() => setCreateOpen((v) => !v)}>+ New project</button>}
        <div className="pm-sidebar-footer">
          <div className="pm-account"><strong>{currentUser.display_name || currentUser.full_name || currentUser.username}</strong><small>{currentUser.role === 'project_viewer' ? 'Project Viewer' : currentUser.role === 'developer' ? 'Developer' : currentUser.role}</small></div>
          {onBack && <button type="button" onClick={onBack}>← Back to Inbox</button>}
          <button type="button" onClick={onLogout}>Sign out</button>
        </div>
      </aside>

      <main className="pm-main">
        <header className="pm-topbar"><div><span>SENDRO / WORKSPACE</span><strong>Project Manager</strong></div><span className="pm-topbar-role">{currentUser.role === 'project_viewer' ? 'Read only' : 'Projects'}</span></header>
        {error && <div className="pm-error" role="alert">{error}<button type="button" onClick={() => setError('')}>×</button></div>}
        {createOpen && isManager && (
          <form className="pm-create-project" onSubmit={createProject}>
            <h3>Create project</h3>
            <input required maxLength="160" placeholder="Project name" value={projectDraft.name} onChange={(e) => setProjectDraft((old) => ({ ...old, name: e.target.value }))} />
            <textarea maxLength="12000" rows="2" placeholder="What will this project deliver?" value={projectDraft.description} onChange={(e) => setProjectDraft((old) => ({ ...old, description: e.target.value }))} />
            <button type="submit" disabled={working}>Create project</button>
          </form>
        )}
        {!activeId && !loading && <div className="pm-empty">No projects available yet. {isManager ? 'Create your first project to get started.' : 'Ask a manager to give you access to a project.'}</div>}
        {activeId && !detail && <div className="pm-empty">Loading project…</div>}
        {detail && (
          <>
            <div className="pm-project-header">
              <div className="pm-title-group"><span className="pm-eyebrow">PROJECT OVERVIEW</span><h1>{detail.name}</h1><p>{detail.description || 'Track tasks, milestones and progress in one place.'}</p></div>
              {detail.can_manage ? (
                <select
                  className={`pm-project-state state-${detail.status}`}
                  aria-label="Project status"
                  value={detail.status}
                  disabled={working}
                  onChange={(e) => act(() => projectApi.update(detail.id, { status: e.target.value }))}
                >
                  <option value="active">Active</option>
                  <option value="paused">Paused</option>
                  <option value="completed">Completed</option>
                </select>
              ) : <span className={`pm-project-state state-${detail.status}`}>{detail.status}</span>}
            </div>
            <div className="pm-overview">
              <div className="pm-stat"><span>Overall progress</span><Progress progress={detail.progress} /></div>
              <div className="pm-stat"><span>Completed</span><strong>{detail.completed_tasks} <small>/ {detail.total_tasks} tasks</small></strong></div>
              <div className="pm-stat"><span>Blocked</span><strong>{detail.blocked_tasks}</strong></div>
              <div className="pm-stat"><span>Team</span><strong>{detail.members.length}</strong></div>
            </div>
            <div className="pm-layout">
              <section className="pm-board">
                <div className="pm-section-heading"><h2>Milestones & tasks</h2><span>{detail.milestones.length} milestones</span></div>
                {detail.milestones.map((milestone) => {
                  const roots = detail.tasks.filter((task) => task.milestone_id === milestone.id && (!task.parent_task_id || !taskMap.has(task.parent_task_id) || taskMap.get(task.parent_task_id).milestone_id !== milestone.id));
                  return <article className="pm-milestone" key={milestone.id}>
                    <div className="pm-milestone-head"><div><h3>{milestone.title}</h3><small>{milestone.progress}% complete</small></div>{detail.can_manage && <button type="button" onClick={() => { setTaskTarget({ milestoneId: milestone.id, parentId: null }); setTaskDraft(EMPTY_TASK); }}>+ Add task</button>}</div>
                    {roots.length ? roots.map((task) => renderTask(task)) : <p className="pm-empty-tasks">No tasks yet.</p>}
                    {taskTarget?.milestoneId === milestone.id && <div className="pm-form-wrap">{taskForm()}</div>}
                  </article>;
                })}
                {detail.can_manage && (
                  <form className="pm-add-milestone" onSubmit={async (e) => { e.preventDefault(); if (!newMilestone.trim()) return; await act(() => projectApi.addMilestone(detail.id, { title: newMilestone.trim() })); setNewMilestone(''); }}>
                    <input value={newMilestone} onChange={(e) => setNewMilestone(e.target.value)} maxLength="160" placeholder="New milestone name" required />
                    <button type="submit" disabled={working}>+ Add milestone</button>
                  </form>
                )}
                {detail.milestones.length === 0 && !detail.can_manage && <p className="pm-empty">This project has no milestones yet.</p>}
              </section>
              <aside className="pm-details">
                {focusedTask ? (
                  <>
                    <div className="pm-details-header"><span>TASK DETAILS</span><button type="button" onClick={() => setSelectedTaskId(null)} aria-label="Close task details">×</button></div>
                    <h3>{focusedTask.title}</h3><p>{focusedTask.description || 'No description added.'}</p>
                    <div className="pm-detail-item"><strong>Status</strong><span>{STATUSES.find((s) => s.value === focusedTask.status)?.label}</span></div>
                    <div className="pm-detail-item"><strong>Assignee</strong><span>{focusedTask.assigned_to_name || 'Unassigned'}</span></div>
                    <div className="pm-detail-item"><strong>Priority</strong><span>{focusedTask.priority}</span></div>
                    {focusedTask.due_date && <div className="pm-detail-item"><strong>Due date</strong><span>{formatDate(focusedTask.due_date)}</span></div>}
                    {detail.can_manage && <button type="button" className="pm-edit-task" onClick={async () => { const title = window.prompt('Task title', focusedTask.title); if (title?.trim()) await act(() => projectApi.updateTask(detail.id, focusedTask.id, { title: title.trim() })); }}>Edit title</button>}
                    <h4>Updates & comments</h4>
                    <div className="pm-comments">{focusedComments.length ? focusedComments.map((item) => <div className="pm-comment" key={item.id}><strong>{item.author_name}</strong><small>{formatDate(item.created_at)}</small><p>{item.body}</p></div>) : <p className="pm-muted">No updates yet.</p>}</div>
                    {detail.can_edit && <form className="pm-comment-form" onSubmit={async (e) => { e.preventDefault(); if (!comment.trim()) return; await act(() => projectApi.addComment(detail.id, focusedTask.id, { body: comment.trim() })); setComment(''); }}>
                      <textarea value={comment} maxLength="6000" onChange={(e) => setComment(e.target.value)} rows="3" placeholder="Write an update or explain a blocker…" required />
                      <button type="submit" disabled={working}>Post update</button>
                    </form>}
                  </>
                ) : (
                  <>
                    <div className="pm-details-header"><span>PROJECT TEAM</span></div>
                    <h3>Members & access</h3>
                    <p className="pm-muted">Only project members can view this workspace.</p>
                    {detail.members.map((member) => <div className="pm-member" key={member.user_id}><span>{member.name}</span><small>{member.permission}</small>{detail.can_manage && <button type="button" aria-label={`Remove ${member.name}`} onClick={() => { if (window.confirm(`Remove ${member.name} from this project?`)) act(() => projectApi.removeMember(detail.id, member.user_id)); }}>×</button>}</div>)}
                    {detail.can_manage && unassignedUsers.length > 0 && <form className="pm-add-member" onSubmit={async (e) => { e.preventDefault(); if (!memberId) return; await act(() => projectApi.addMember(detail.id, { user_id: Number(memberId), permission: memberPermission })); setMemberId(''); }}>
                      <select aria-label="Select team member" required value={memberId} onChange={(e) => setMemberId(e.target.value)}>
                        <option value="">Select a user</option>
                        {unassignedUsers.map((person) => <option value={person.id} key={person.id}>{person.display_name || person.full_name || person.username} ({person.role})</option>)}
                      </select>
                      <select aria-label="Project permission" value={memberPermission} onChange={(e) => setMemberPermission(e.target.value)}><option value="editor">Editor</option><option value="viewer">Viewer</option></select>
                      <button type="submit" disabled={working}>Add member</button>
                    </form>}
                    <div className="pm-tip">Select a task to view its description and project updates.</div>
                  </>
                )}
              </aside>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
