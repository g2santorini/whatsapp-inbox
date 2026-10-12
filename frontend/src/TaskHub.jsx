import { useCallback, useEffect, useMemo, useState } from 'react';
import { getUsers } from './api';
import { tasksApi } from './tasksApi';
import './TaskHub.css';

const STATUS = { todo: 'To do', in_progress: 'In progress', blocked: 'Blocked', done: 'Done' };
const PRIORITY = { low: 'Low', normal: 'Normal', high: 'High', urgent: 'Urgent' };
const EMPTY = { title: '', description: '', priority: 'normal', due_date: '', assigned_to_id: '' };

const prettyDate = (value) => value ? new Date(value.length === 10 ? `${value}T12:00:00` : value)
  .toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '';

export default function TaskHub({ view, currentUser, onProjectOpen }) {
  const isAdmin = currentUser.role === 'admin';
  const [tasks, setTasks] = useState([]);
  const [users, setUsers] = useState([]);
  const [team, setTeam] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState(EMPTY);
  const [focused, setFocused] = useState(null);
  const [taskDetail, setTaskDetail] = useState(null);
  const [comment, setComment] = useState('');
  const [editDraft, setEditDraft] = useState(null);

  const reload = useCallback(async () => {
    const next = await tasksApi.list();
    setTasks(next);
    if (view === 'team' && isAdmin) setTeam(await tasksApi.team());
  }, [view, isAdmin]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    tasksApi.list().then(async (next) => {
      if (!active) return;
      setTasks(next);
      if (view === 'team' && isAdmin) {
        const list = await tasksApi.team();
        if (active) setTeam(list);
      }
    }).catch((err) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    if (isAdmin) getUsers().then((list) => { if (active) setUsers(list.filter((u) => !u.disabled && u.role !== 'project_viewer')); }).catch(() => {});
    return () => { active = false; };
  }, [view, isAdmin]);

  const act = async (fn) => {
    setSaving(true);
    setError('');
    try {
      await fn();
      await reload();
      if (focused?.kind === 'standalone') {
        setTaskDetail(await tasksApi.detail(focused.task_id));
      }
    } catch (err) {
      setError(err.message || 'Could not save your changes.');
    } finally {
      setSaving(false);
    }
  };

  const openTask = async (task) => {
    if (task.kind === 'project') {
      onProjectOpen(task.project_id, task.task_id);
      return;
    }
    setFocused(task);
    setTaskDetail(null);
    setEditDraft(null);
    setComment('');
    try {
      setTaskDetail(await tasksApi.detail(task.task_id));
    } catch (err) {
      setError(err.message);
    }
  };

  const visible = useMemo(() => tasks.filter((item) => {
    if (view === 'pool' && !item.can_claim) return false;
    if (view === 'tasks') {
      if (filter === 'mine' && item.assigned_to_id !== currentUser.id) return false;
      if (filter === 'pool' && !item.can_claim) return false;
      if (filter === 'active' && item.status === 'done') return false;
      if (filter === 'done' && item.status !== 'done') return false;
    }
    const needle = search.trim().toLowerCase();
    return !needle || `${item.title} ${item.description} ${item.project_name || ''}`.toLowerCase().includes(needle);
  }), [tasks, view, filter, search, currentUser.id]);

  const stats = useMemo(() => ({
    pool: tasks.filter((t) => t.can_claim).length,
    mine: tasks.filter((t) => t.assigned_to_id === currentUser.id && t.status !== 'done').length,
    active: tasks.filter((t) => t.status === 'in_progress').length,
    blocked: tasks.filter((t) => t.status === 'blocked').length,
    done: tasks.filter((t) => t.status === 'done').length,
  }), [tasks, currentUser.id]);

  const submitTask = async (event) => {
    event.preventDefault();
    if (!draft.title.trim()) return;
    setSaving(true);
    setError('');
    try {
      await tasksApi.create({
        title: draft.title.trim(),
        description: draft.description,
        priority: draft.priority,
        due_date: draft.due_date || null,
        assigned_to_id: draft.assigned_to_id ? Number(draft.assigned_to_id) : null,
      });
      await reload();
      setCreating(false);
      setDraft(EMPTY);
    } catch (err) { setError(err.message); } finally { setSaving(false); }
  };

  const taskRows = (rows) => rows.map((task) => (
    <article className="hub-task-row" key={task.id}>
      <button type="button" className="hub-task-open" onClick={() => openTask(task)}>
        <span className="hub-task-name">{task.title}</span>
        <span className="hub-task-meta">
          {task.project_name ? <span className="hub-project-chip">▦ {task.project_name}</span> : <span className="hub-standalone-chip">Simple task</span>}
          <span>{task.assigned_to_name || 'Unassigned'}</span>
          {task.due_date && <span>Due {prettyDate(task.due_date)}</span>}
        </span>
      </button>
      <span className={`hub-priority hub-priority-${task.priority}`}>{PRIORITY[task.priority] || task.priority}</span>
      <span className={`hub-status hub-status-${task.status}`}>{STATUS[task.status] || task.status}</span>
      {task.can_claim ? <button disabled={saving} className="hub-take" type="button" onClick={() => act(() => tasksApi.claim(task))}>Take task</button>
        : task.assigned_to_id === currentUser.id && task.status !== 'done' ? <button disabled={saving} className="hub-quiet" type="button" onClick={() => act(() => tasksApi.release(task))}>Release</button>
          : <span className="hub-row-end">—</span>}
    </article>
  ));

  const form = (
    <form className="hub-create" onSubmit={submitTask}>
      <h3>New simple task</h3>
      <p>Keep this separate from Projects. Leave unassigned to add it to Open Pool.</p>
      <input required maxLength="200" placeholder="What needs to be done?" value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
      <textarea rows="3" maxLength="12000" placeholder="Details and acceptance criteria" value={draft.description} onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
      <div className="hub-create-options">
        <label>Assign to
          <select value={draft.assigned_to_id} onChange={(e) => setDraft((d) => ({ ...d, assigned_to_id: e.target.value }))}>
            <option value="">Open Pool — unassigned</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.display_name || u.full_name || u.username}</option>)}
          </select>
        </label>
        <label>Priority
          <select value={draft.priority} onChange={(e) => setDraft((d) => ({ ...d, priority: e.target.value }))}>{Object.entries(PRIORITY).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </label>
        <label>Due date <input type="date" value={draft.due_date} onChange={(e) => setDraft((d) => ({ ...d, due_date: e.target.value }))} /></label>
      </div>
      <div className="hub-buttons"><button disabled={saving} type="submit">Create task</button><button type="button" className="hub-quiet" onClick={() => setCreating(false)}>Cancel</button></div>
    </form>
  );

  const detailPane = focused && (
    <aside className="hub-task-detail">
      <div className="hub-detail-top"><span>TASK DETAILS</span><button type="button" aria-label="Close details" onClick={() => { setFocused(null); setTaskDetail(null); }}>×</button></div>
      {!taskDetail ? <p>Loading details…</p> : (
        <>
          <h3>{taskDetail.title}</h3>
          <p className="hub-description">{taskDetail.description || 'No description yet.'}</p>
          <p><strong>Status:</strong> {STATUS[taskDetail.status]}</p>
          <p><strong>Assignee:</strong> {taskDetail.assigned_to_name || 'Open Pool'}</p>
          <p><strong>Priority:</strong> {PRIORITY[taskDetail.priority]}</p>
          {taskDetail.due_date && <p><strong>Due:</strong> {prettyDate(taskDetail.due_date)}</p>}
          {(taskDetail.can_manage || focused.can_update_status) && <label className="hub-detail-label">Status
            <select disabled={saving} value={taskDetail.status} onChange={(e) => act(() => tasksApi.update(taskDetail.id, { status: e.target.value }))}>
              {Object.entries(STATUS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>}
          {taskDetail.can_manage && (
            <>
              <button type="button" className="hub-edit-button" onClick={() => setEditDraft({
                title: taskDetail.title, description: taskDetail.description,
                priority: taskDetail.priority, assigned_to_id: String(taskDetail.assigned_to_id || ''),
                due_date: taskDetail.due_date || '',
              })}>Edit task / Reassign</button>
              {editDraft && <form className="hub-edit-fields" onSubmit={async (e) => {
                e.preventDefault();
                await act(() => tasksApi.update(taskDetail.id, { ...editDraft, assigned_to_id: editDraft.assigned_to_id ? Number(editDraft.assigned_to_id) : null, due_date: editDraft.due_date || null }));
                setEditDraft(null);
              }}>
                <input value={editDraft.title} maxLength="200" required onChange={(e) => setEditDraft((d) => ({ ...d, title: e.target.value }))}/>
                <textarea value={editDraft.description} maxLength="12000" onChange={(e) => setEditDraft((d) => ({ ...d, description: e.target.value }))}/>
                <select value={editDraft.assigned_to_id} onChange={(e) => setEditDraft((d) => ({ ...d, assigned_to_id: e.target.value }))}>
                  <option value="">Open Pool — unassigned</option>
                  {users.map((u) => <option key={u.id} value={u.id}>{u.display_name || u.full_name || u.username}</option>)}
                </select>
                <select value={editDraft.priority} onChange={(e) => setEditDraft((d) => ({ ...d, priority: e.target.value }))}>{Object.entries(PRIORITY).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
                <input type="date" value={editDraft.due_date} onChange={(e) => setEditDraft((d) => ({ ...d, due_date: e.target.value }))}/>
                <div className="hub-buttons"><button disabled={saving} type="submit">Save changes</button><button type="button" className="hub-quiet" onClick={() => setEditDraft(null)}>Cancel</button></div>
              </form>}
            </>
          )}
          <h4>Comments & updates</h4>
          {taskDetail.comments.length === 0 && <p className="hub-muted">No comments yet.</p>}
          {taskDetail.comments.map((item) => <div key={item.id} className="hub-comment"><strong>{item.author_name}</strong><small>{prettyDate(item.created_at)}</small><p>{item.body}</p></div>)}
          {taskDetail.can_comment && <form className="hub-comment-form" onSubmit={async (e) => { e.preventDefault(); if (!comment.trim()) return; await act(() => tasksApi.comment(taskDetail.id, comment.trim())); setComment(''); }}>
            <textarea required value={comment} maxLength="6000" onChange={(e) => setComment(e.target.value)} placeholder="Write an update…" rows="3"/>
            <button type="submit" disabled={saving}>Post comment</button>
          </form>}
        </>
      )}
    </aside>
  );

  const sections = {
    overview: { eyebrow: 'YOUR WORKSPACE', title: 'Overview', subtitle: 'Everything that needs attention, in one place.' },
    tasks: { eyebrow: 'WORK MANAGEMENT', title: 'Tasks', subtitle: 'Simple tasks and tasks belonging to Projects.' },
    pool: { eyebrow: 'AVAILABLE TO TAKE', title: 'Open Pool', subtitle: 'Unassigned work you can claim with one click.' },
    team: { eyebrow: 'PEOPLE & WORKLOAD', title: 'Team', subtitle: 'Who is working on what, and what is blocked.' },
  };
  const section = sections[view] || sections.tasks;

  return (
    <div className="hub-root">
      <div className="hub-heading">
        <div><span className="hub-eyebrow">{section.eyebrow}</span><h1>{section.title}</h1><p>{section.subtitle}</p></div>
        {isAdmin && (view === 'tasks' || view === 'overview') && <button type="button" className="hub-main-action" onClick={() => setCreating((v) => !v)}>+ New task</button>}
      </div>
      {error && <div className="hub-error" role="alert">{error}<button type="button" onClick={() => setError('')}>×</button></div>}
      {creating && isAdmin && form}
      {(view === 'overview') && (
        <div className="hub-stats">
          <div className="hub-stat"><span>My active tasks</span><strong>{stats.mine}</strong></div>
          <div className="hub-stat"><span>Open Pool</span><strong>{stats.pool}</strong></div>
          <div className="hub-stat"><span>In progress</span><strong>{stats.active}</strong></div>
          <div className="hub-stat"><span>Blocked</span><strong>{stats.blocked}</strong></div>
          <div className="hub-stat"><span>Completed</span><strong>{stats.done}</strong></div>
        </div>
      )}
      {view === 'team' ? (
        <section className="hub-board">
          {isAdmin ? <>
            <div className="hub-board-header"><h2>Team workload</h2><span>Tasks assigned by user</span></div>
            <div className="hub-team-grid">
              {team.map((person) => <div className="hub-team-member" key={person.user_id}>
                <div className="hub-avatar">{person.name.slice(0,2).toUpperCase()}</div>
                <div><strong>{person.name}</strong><small>{person.role}</small></div>
                <div className="hub-team-count"><strong>{person.active}</strong><span>Active</span></div>
                <div className="hub-team-count"><strong>{person.completed}</strong><span>Done</span></div>
                <div className="hub-team-count"><strong>{person.blocked}</strong><span>Blocked</span></div>
              </div>)}
            </div>
          </> : <p className="hub-empty">Team reporting is available to the manager.</p>}
        </section>
      ) : (
        <>
          {view === 'tasks' && <div className="hub-filters">
            {[['all','All tasks'],['mine','My tasks'],['pool','Open Pool'],['active','Active'],['done','Completed']].map(([key,label]) =>
              <button key={key} type="button" className={filter===key ? 'selected' : ''} onClick={() => setFilter(key)}>{label}</button>)}
          </div>}
          {view === 'overview' && <h2 className="hub-list-heading">Work requiring attention</h2>}
          <section className="hub-board">
            <div className="hub-board-header">
              <h2>{view === 'pool' ? 'Available tasks' : view === 'overview' ? 'Recent work' : 'All tasks'}</h2>
              <input type="search" placeholder="Search tasks…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search tasks"/>
            </div>
            {loading ? <p className="hub-empty">Loading tasks…</p> : visible.length ? taskRows(view === 'overview' ? visible.filter((t) => t.status !== 'done').slice(0,12) : visible) : <p className="hub-empty">{view === 'pool' ? 'No tasks are waiting to be claimed.' : 'No tasks here yet.'}</p>}
          </section>
        </>
      )}
      {detailPane}
    </div>
  );
}
