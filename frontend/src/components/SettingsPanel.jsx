import { useEffect, useState } from 'react';
import {
  archiveOldConversations,
  createUser,
  getCurrentUser,
  getUsers,
  resetUserPassword,
  updateUser,
} from '../api';
import './SettingsPanel.css';

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'power_user', label: 'Power User' },
  { value: 'user', label: 'User' },
];

const ARCHIVE_OLD_OPTIONS = [
  { value: '36', label: '36 hours' },
  { value: '48', label: '48 hours' },
  { value: '168', label: '7 days' },
];

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function isValidEmail(email) {
  return EMAIL_REGEX.test(String(email || '').trim().toLowerCase());
}

const EMPTY_NEW_USER_FORM = {
  username: '',
  email: '',
  full_name: '',
  password: '',
  role: 'user',
};

const EMPTY_EDIT_USER_FORM = {
  username: '',
  email: '',
  full_name: '',
};

const EMPTY_PASSWORD_RESET_FORM = {
  password: '',
  confirmPassword: '',
};

const settingsSections = [
  {
    title: 'Assignment Colors',
    description: 'Set visual colors for assigned conversations, users, or statuses.',
    status: 'Soon',
    items: ['George', 'Panagiotis', 'Unassigned'],
  },
  {
    title: 'Login Greetings',
    description: 'Customize the internal greeting shown after each user logs in.',
    status: 'Soon',
    items: ['Default greeting', 'Per-user greeting', 'Welcome message'],
  },
  {
    title: 'Templates / Quick Replies',
    description: 'Create reusable replies for faster and more consistent responses.',
    status: 'Important',
    items: ['Pickup reminder', 'Cruise info', 'Payment follow-up'],
  },
  {
    title: 'Knowledge Base',
    description: 'Prepare uploaded files and internal knowledge for future AI assistance.',
    status: 'Later',
    items: ['Files', 'Company knowledge', 'AI context'],
  },
];

function getErrorMessage(err, fallbackMessage) {
  let errorMessage = fallbackMessage;

  try {
    const parsedError = JSON.parse(err.message);
    errorMessage = parsedError.detail || errorMessage;
  } catch {
    errorMessage = err.message || errorMessage;
  }

  return errorMessage;
}

function isSystemUser(user) {
  const username = String(user?.username || '').toLowerCase();
  const email = String(user?.email || '').toLowerCase();

  return (
    username === 'sendro_webhook' ||
    username === 'whatsapp_webhook' ||
    email.endsWith('@sendro.local')
  );
}

function reportsIncludedByRole(user) {
  return user?.role === 'admin' || user?.role === 'power_user';
}

function userCanViewReports(user) {
  return reportsIncludedByRole(user) || Boolean(user?.can_view_reports);
}

function formatRole(role) {
  if (role === 'admin') {
    return 'Admin';
  }

  if (role === 'power_user') {
    return 'Power User';
  }

  if (role === 'user') {
    return 'User';
  }

  return role || 'User';
}

function sortUsers(usersToSort) {
  return [...usersToSort].sort((firstUser, secondUser) => {
    const firstLabel = firstUser.full_name || firstUser.username || '';
    const secondLabel = secondUser.full_name || secondUser.username || '';

    return firstLabel.localeCompare(secondLabel);
  });
}

function formatArchiveDateTime(value) {
  if (!value) return '-';

  const rawValue = String(value);
  const hasTimezone = /[zZ]$|[+-]\d{2}:\d{2}$/.test(rawValue);
  const safeValue = hasTimezone ? rawValue : `${rawValue}Z`;
  const date = new Date(safeValue);

  if (Number.isNaN(date.getTime())) {
    return rawValue;
  }

  return new Intl.DateTimeFormat('el-GR', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

function SettingsPanel() {
  const [currentUser, setCurrentUser] = useState(null);
  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(true);
  const [updatingUserId, setUpdatingUserId] = useState(null);
  const [settingsError, setSettingsError] = useState('');
  const [settingsSuccess, setSettingsSuccess] = useState('');

  const [showAddUserForm, setShowAddUserForm] = useState(false);
  const [newUserForm, setNewUserForm] = useState(EMPTY_NEW_USER_FORM);
  const [isCreatingUser, setIsCreatingUser] = useState(false);

  const [editingUserId, setEditingUserId] = useState(null);
  const [editUserForm, setEditUserForm] = useState(EMPTY_EDIT_USER_FORM);

  const [resetPasswordUserId, setResetPasswordUserId] = useState(null);
  const [resetPasswordForm, setResetPasswordForm] = useState(
    EMPTY_PASSWORD_RESET_FORM
  );

  const [archiveOldHours, setArchiveOldHours] = useState('36');
  const [archivePreview, setArchivePreview] = useState(null);
  const [isPreviewingArchive, setIsPreviewingArchive] = useState(false);
  const [isArchivingOldConversations, setIsArchivingOldConversations] =
    useState(false);

  const isAdmin = currentUser?.role === 'admin';
  const visibleUsers = users.filter((singleUser) => !isSystemUser(singleUser));
  const activeUsers = users.filter((user) => !user.disabled).length;
  const blockedUsers = users.filter((user) => user.disabled).length;

  async function loadUsers() {
    try {
      setIsLoadingUsers(true);
      setSettingsError('');

      const [currentUserData, usersData] = await Promise.all([
        getCurrentUser(),
        getUsers(),
      ]);

      setCurrentUser(currentUserData);
      setUsers(sortUsers(usersData));
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not load users.'));
    } finally {
      setIsLoadingUsers(false);
    }
  }

  function updateNewUserForm(fieldName, value) {
    setNewUserForm((currentForm) => ({
      ...currentForm,
      [fieldName]: value,
    }));
  }

  function resetAddUserForm() {
    setNewUserForm(EMPTY_NEW_USER_FORM);
  }

  function closeAddUserForm() {
    setShowAddUserForm(false);
    resetAddUserForm();
    setSettingsError('');
  }

  function startEditingUser(userToEdit) {
    setSettingsError('');
    setSettingsSuccess('');
    setResetPasswordUserId(null);

    setEditingUserId(userToEdit.id);
    setEditUserForm({
      username: userToEdit.username || '',
      email: userToEdit.email || '',
      full_name: userToEdit.full_name || '',
    });
  }

  function cancelEditingUser() {
    setEditingUserId(null);
    setEditUserForm(EMPTY_EDIT_USER_FORM);
    setSettingsError('');
  }

  function updateEditUserForm(fieldName, value) {
    setEditUserForm((currentForm) => ({
      ...currentForm,
      [fieldName]: value,
    }));
  }

  function startResetPassword(userToUpdate) {
    setSettingsError('');
    setSettingsSuccess('');
    setEditingUserId(null);

    setResetPasswordUserId(userToUpdate.id);
    setResetPasswordForm(EMPTY_PASSWORD_RESET_FORM);
  }

  function cancelResetPassword() {
    setResetPasswordUserId(null);
    setResetPasswordForm(EMPTY_PASSWORD_RESET_FORM);
    setSettingsError('');
  }

  function updateResetPasswordForm(fieldName, value) {
    setResetPasswordForm((currentForm) => ({
      ...currentForm,
      [fieldName]: value,
    }));
  }

  async function handleCreateUser(event) {
    event.preventDefault();

    const username = newUserForm.username.trim();
    const email = newUserForm.email.trim();
    const fullName = newUserForm.full_name.trim();
    const password = newUserForm.password.trim();
    const role = newUserForm.role;

    if (!username || !email || !password) {
      setSettingsError('Username, email, and temporary password are required.');
      return;
    }

    if (!isValidEmail(email)) {
      setSettingsError('Please enter a valid email address.');
      return;
    }

    try {
      setIsCreatingUser(true);
      setSettingsError('');
      setSettingsSuccess('');

      const createdUser = await createUser({
        username,
        email,
        full_name: fullName || null,
        password,
        role,
      });

      setUsers((currentUsers) => sortUsers([...currentUsers, createdUser]));
      setSettingsSuccess('User created successfully.');

      resetAddUserForm();
      setShowAddUserForm(false);
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not create user.'));
    } finally {
      setIsCreatingUser(false);
    }
  }

  async function handleSaveUserDetails(event, userToUpdate) {
    event.preventDefault();

    const username = editUserForm.username.trim();
    const email = editUserForm.email.trim();
    const fullName = editUserForm.full_name.trim();
    const isCurrentUser = currentUser?.id === userToUpdate.id;

    if (!username || !email) {
      setSettingsError('Username and email are required.');
      return;
    }

    if (!isValidEmail(email)) {
      setSettingsError('Please enter a valid email address.');
      return;
    }

    if (isCurrentUser && username !== userToUpdate.username) {
      setSettingsError('You cannot change your own username.');
      return;
    }

    try {
      setUpdatingUserId(userToUpdate.id);
      setSettingsError('');
      setSettingsSuccess('');

      const updatedUser = await updateUser(userToUpdate.id, {
        username,
        email,
        full_name: fullName || null,
      });

      setUsers((currentUsers) =>
        sortUsers(
          currentUsers.map((user) =>
            user.id === updatedUser.id ? updatedUser : user
          )
        )
      );

      if (currentUser?.id === updatedUser.id) {
        setCurrentUser(updatedUser);
      }

      setEditingUserId(null);
      setEditUserForm(EMPTY_EDIT_USER_FORM);
      setSettingsSuccess('User details updated successfully.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not update user details.'));
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function handleResetPassword(event, userToUpdate) {
    event.preventDefault();

    const password = resetPasswordForm.password.trim();
    const confirmPassword = resetPasswordForm.confirmPassword.trim();

    if (!password || !confirmPassword) {
      setSettingsError('Password and confirmation are required.');
      return;
    }

    if (password.length < 6) {
      setSettingsError('Password must be at least 6 characters long.');
      return;
    }

    if (password !== confirmPassword) {
      setSettingsError('Passwords do not match.');
      return;
    }

    try {
      setUpdatingUserId(userToUpdate.id);
      setSettingsError('');
      setSettingsSuccess('');

      await resetUserPassword(userToUpdate.id, password);

      setResetPasswordUserId(null);
      setResetPasswordForm(EMPTY_PASSWORD_RESET_FORM);
      setSettingsSuccess('Password reset successfully.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not reset password.'));
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function handleRoleChange(userOrId, newRole) {
    const userId =
      typeof userOrId === 'object' && userOrId !== null ? userOrId.id : userOrId;

    if (!userId || !newRole) {
      setSettingsError('Could not update user role: missing user id or role.');
      return;
    }

    try {
      setUpdatingUserId(userId);
      setSettingsError('');
      setSettingsSuccess('');

      await updateUser(userId, { role: newRole });

      const usersData = await getUsers();
      setUsers(sortUsers(usersData));

      const currentUserData = await getCurrentUser();
      setCurrentUser(currentUserData);

      setSettingsSuccess('User role updated successfully.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not update user role.'));
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function handleToggleUserStatus(userToUpdate) {
    try {
      setUpdatingUserId(userToUpdate.id);
      setSettingsError('');
      setSettingsSuccess('');

      const updatedUser = await updateUser(userToUpdate.id, {
        disabled: !userToUpdate.disabled,
      });

      setUsers((currentUsers) =>
        sortUsers(
          currentUsers.map((user) => (user.id === userToUpdate.id ? updatedUser : user))
        )
      );

      if (currentUser?.id === updatedUser.id) {
        setCurrentUser(updatedUser);
      }

      setSettingsSuccess(
        updatedUser.disabled
          ? 'User has been blocked successfully.'
          : 'User has been activated successfully.'
      );
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not update user status.'));
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function handleToggleReportAccess(userToUpdate) {
    if (!userToUpdate?.id) {
      setSettingsError('Could not update report access: missing user id.');
      return;
    }

    try {
      setUpdatingUserId(userToUpdate.id);
      setSettingsError('');
      setSettingsSuccess('');

      await updateUser(userToUpdate.id, {
        can_view_reports: !Boolean(userToUpdate.can_view_reports),
      });

      const usersData = await getUsers();
      setUsers(sortUsers(usersData));

      const currentUserData = await getCurrentUser();
      setCurrentUser(currentUserData);

      setSettingsSuccess('Report access updated successfully.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not update report access.'));
    } finally {
      setUpdatingUserId(null);
    }
  }

  async function handlePreviewArchiveOldConversations() {
    try {
      setIsPreviewingArchive(true);
      setSettingsError('');
      setSettingsSuccess('');

      const previewData = await archiveOldConversations({
        hours: Number(archiveOldHours),
        dryRun: true,
        limit: 200,
      });

      setArchivePreview(previewData);
      setSettingsSuccess(
        `Preview found ${Number(previewData?.matched_count || 0)} old conversations.`
      );
    } catch (err) {
      setSettingsError(
        getErrorMessage(err, 'Could not preview old conversations.')
      );
    } finally {
      setIsPreviewingArchive(false);
    }
  }

  async function handleArchiveOldConversations() {
    const matchedCount = Number(archivePreview?.matched_count || 0);

    if (matchedCount <= 0) {
      setSettingsError('Preview old conversations first.');
      return;
    }

    const confirmed = window.confirm(
      `Archive ${matchedCount} old conversations? This will not delete them.`
    );

    if (!confirmed) {
      return;
    }

    try {
      setIsArchivingOldConversations(true);
      setSettingsError('');
      setSettingsSuccess('');

      const archiveData = await archiveOldConversations({
        hours: Number(archiveOldHours),
        dryRun: false,
        limit: 200,
      });

      setArchivePreview(archiveData);
      setSettingsSuccess(
        `Archived ${Number(archiveData?.archived_count || 0)} conversations.`
      );
    } catch (err) {
      setSettingsError(
        getErrorMessage(err, 'Could not archive old conversations.')
      );
    } finally {
      setIsArchivingOldConversations(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  return (
    <section className="settings-panel">
      <div className="settings-header">
        <div>
          <p className="settings-kicker">Admin area</p>
          <h1>Settings</h1>
          <p>
            Configure users, permissions, assignment rules, quick replies, and future AI
            knowledge tools.
          </p>
        </div>

        <div className="settings-header-card">
          <span>Workspace</span>
          <strong>Sendro Inbox</strong>
          <small>Internal admin setup</small>
        </div>
      </div>

      <div className="settings-overview">
        <div className="settings-overview-card">
          <span>Users</span>
          <strong>{visibleUsers.length}</strong>
          <small>{activeUsers} active users</small>
        </div>

        <div className="settings-overview-card">
          <span>Roles</span>
          <strong>3 roles</strong>
          <small>Admin / Power User / User</small>
        </div>

        <div className="settings-overview-card">
          <span>Blocked</span>
          <strong>{blockedUsers}</strong>
          <small>Disabled user accounts</small>
        </div>
      </div>

      {(settingsError || settingsSuccess) && (
        <div className={`settings-alert ${settingsError ? 'error' : 'success'}`}>
          {settingsError || settingsSuccess}
        </div>
      )}

      {!isAdmin && (
        <div className="settings-alert warning">
          You can view users, but only admins can create users, change roles, or block users.
        </div>
      )}

      {isAdmin && (
        <div className="settings-user-card settings-archive-card">
          <div className="settings-user-card-header">
            <div>
              <h2>Archive old conversations</h2>
              <p>
                Preview and archive inactive conversations without deleting them. Archived
                conversations can still be restored with Back to Inbox.
              </p>
            </div>
          </div>

          <div className="archive-old-controls">
            <label className="archive-old-field">
              <span>Inactive for at least</span>

              <select
                value={archiveOldHours}
                onChange={(event) => {
                  setArchiveOldHours(event.target.value);
                  setArchivePreview(null);
                  setSettingsError('');
                  setSettingsSuccess('');
                }}
                disabled={isPreviewingArchive || isArchivingOldConversations}
              >
                {ARCHIVE_OLD_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className="archive-old-preview-button"
              onClick={handlePreviewArchiveOldConversations}
              disabled={isPreviewingArchive || isArchivingOldConversations}
            >
              {isPreviewingArchive ? 'Checking...' : 'Preview old conversations'}
            </button>

            <button
              type="button"
              className="archive-old-danger-button"
              onClick={handleArchiveOldConversations}
              disabled={
                isPreviewingArchive ||
                isArchivingOldConversations ||
                Number(archivePreview?.matched_count || 0) <= 0
              }
            >
              {isArchivingOldConversations ? 'Archiving...' : 'Archive conversations'}
            </button>
          </div>

          {archivePreview && (
            <div className="archive-old-preview">
              <div className="archive-old-preview-summary">
                <div>
                  <strong>{Number(archivePreview.matched_count || 0)}</strong>
                  <span>matched conversations</span>
                </div>

                <div>
                  <strong>{Number(archivePreview.archived_count || 0)}</strong>
                  <span>archived</span>
                </div>
              </div>

              {archivePreview.conversations?.length > 0 ? (
                <div className="archive-old-list">
                  {archivePreview.conversations.slice(0, 10).map((conversation) => (
                    <div className="archive-old-row" key={conversation.id}>
                      <div>
                        <strong>
                          {conversation.contact_name ||
                            conversation.contact_phone ||
                            `Conversation #${conversation.id}`}
                        </strong>
                        <small>{conversation.contact_phone || '-'}</small>
                      </div>

                      <span>{formatArchiveDateTime(conversation.last_message_at)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="archive-old-empty">
                  No old conversations found for this threshold.
                </p>
              )}

              {archivePreview.conversations?.length > 10 && (
                <p className="archive-old-empty">
                  Showing first 10 of {archivePreview.conversations.length}.
                </p>
              )}
            </div>
          )}

          <p className="archive-old-note">
            Safety rule: Sendro will skip unread, assigned, follow-up, and already
            archived conversations.
          </p>
        </div>
      )}

      <div className="settings-user-card">
        <div className="settings-user-card-header">
          <div>
            <h2>Users, Roles & Access</h2>
            <p>
              Manage team users, assign roles, and block or activate access from one place.
            </p>
          </div>

          <div className="settings-user-card-actions">
            {isAdmin && (
              <button
                type="button"
                className="add-user-button"
                onClick={() => {
                  setSettingsError('');
                  setSettingsSuccess('');
                  setShowAddUserForm((currentValue) => !currentValue);
                }}
              >
                {showAddUserForm ? 'Close form' : 'Add user'}
              </button>
            )}

            <button type="button" onClick={loadUsers} disabled={isLoadingUsers}>
              {isLoadingUsers ? 'Loading...' : 'Refresh'}
            </button>
          </div>
        </div>

        {showAddUserForm && (
          <form className="add-user-form" onSubmit={handleCreateUser}>
            <div className="add-user-form-header">
              <div>
                <h3>Add new user</h3>
                <p>Create a team member with a temporary password and initial role.</p>
              </div>

              <button type="button" onClick={closeAddUserForm}>
                ×
              </button>
            </div>

            <div className="add-user-form-grid">
              <label>
                <span>Username *</span>
                <input
                  value={newUserForm.username}
                  onChange={(event) => updateNewUserForm('username', event.target.value)}
                  placeholder="e.g. maria"
                  disabled={isCreatingUser}
                />
              </label>

              <label>
                <span>Email *</span>
                <input
                  value={newUserForm.email}
                  onChange={(event) => updateNewUserForm('email', event.target.value)}
                  placeholder="maria@example.com"
                  type="email"
                  disabled={isCreatingUser}
                />
              </label>

              <label>
                <span>Full name</span>
                <input
                  value={newUserForm.full_name}
                  onChange={(event) => updateNewUserForm('full_name', event.target.value)}
                  placeholder="Maria Papadopoulou"
                  disabled={isCreatingUser}
                />
              </label>

              <label>
                <span>Temporary password *</span>
                <input
                  value={newUserForm.password}
                  onChange={(event) => updateNewUserForm('password', event.target.value)}
                  placeholder="Temporary password"
                  type="password"
                  disabled={isCreatingUser}
                />
              </label>

              <label>
                <span>Role</span>
                <select
                  value={newUserForm.role}
                  onChange={(event) => updateNewUserForm('role', event.target.value)}
                  disabled={isCreatingUser}
                >
                  {ROLE_OPTIONS.map((role) => (
                    <option value={role.value} key={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="add-user-form-actions">
              <button type="button" onClick={closeAddUserForm} disabled={isCreatingUser}>
                Cancel
              </button>

              <button
                type="submit"
                disabled={
                  isCreatingUser ||
                  !newUserForm.username.trim() ||
                  !newUserForm.email.trim() ||
                  !newUserForm.password.trim()
                }
              >
                {isCreatingUser ? 'Creating...' : 'Create user'}
              </button>
            </div>
          </form>
        )}

        {isLoadingUsers ? (
          <div className="settings-loading">Loading users...</div>
        ) : (
          <div className="settings-user-table">
            {visibleUsers.map((singleUser) => {
              const isUpdating = updatingUserId === singleUser.id;
              const isCurrentUser = currentUser?.id === singleUser.id;
              const roleValue = ROLE_OPTIONS.some((role) => role.value === singleUser.role)
                ? singleUser.role
                : 'user';

              return (
                <div className="settings-user-row" key={singleUser.id}>
                  <div className="settings-user-main">
                    <div className="settings-user-avatar">
                      {(singleUser.full_name || singleUser.username || '?')
                        .charAt(0)
                        .toUpperCase()}
                    </div>

                    <div>
                      <strong>
                        {singleUser.full_name || singleUser.username}
                        {isCurrentUser && <span className="current-user-label">You</span>}
                      </strong>
                      <small>
                        @{singleUser.username} · {singleUser.email}
                      </small>
                    </div>
                  </div>

                  <div className="settings-user-controls">
                    <span
                      className={`settings-status-badge ${singleUser.disabled ? 'blocked' : 'active'
                        }`}
                    >
                      {singleUser.disabled ? 'Blocked' : 'Active'}
                    </span>

                    <select
                      value={roleValue}
                      disabled={!isAdmin || isUpdating}
                      onChange={(event) => handleRoleChange(singleUser.id, event.target.value)}
                    >
                      {ROLE_OPTIONS.map((role) => (
                        <option value={role.value} key={role.value}>
                          {role.label}
                        </option>
                      ))}
                    </select>

                    <span className="settings-role-badge">
                      {formatRole(singleUser.role)}
                    </span>

                    <label
                      className={`settings-report-access-toggle ${reportsIncludedByRole(singleUser) ? 'locked' : ''
                        }`}
                      title={
                        reportsIncludedByRole(singleUser)
                          ? 'Admins and Power Users can always view reports.'
                          : 'Allow this user to view Reports.'
                      }
                    >
                      <input
                        type="checkbox"
                        checked={userCanViewReports(singleUser)}
                        disabled={!isAdmin || isUpdating || reportsIncludedByRole(singleUser)}
                        onChange={() => handleToggleReportAccess(singleUser)}
                      />
                      <span>
                        {reportsIncludedByRole(singleUser)
                          ? 'Reports by role'
                          : 'Can view reports'}
                      </span>
                    </label>

                    {isAdmin && (
                      <>
                        <button
                          type="button"
                          className="edit-user-button"
                          disabled={isUpdating}
                          onClick={() => startEditingUser(singleUser)}
                        >
                          Edit
                        </button>

                        <button
                          type="button"
                          className="reset-password-button"
                          disabled={isUpdating}
                          onClick={() => startResetPassword(singleUser)}
                        >
                          Reset password
                        </button>
                      </>
                    )}

                    <button
                      type="button"
                      className={singleUser.disabled ? 'activate-user-button' : 'block-user-button'}
                      disabled={!isAdmin || isUpdating}
                      onClick={() => handleToggleUserStatus(singleUser)}
                    >
                      {isUpdating
                        ? 'Saving...'
                        : singleUser.disabled
                          ? 'Activate'
                          : 'Block'}
                    </button>
                  </div>
                  {editingUserId === singleUser.id && (
                    <form
                      className="settings-inline-form"
                      onSubmit={(event) => handleSaveUserDetails(event, singleUser)}
                    >
                      <label>
                        <span>Username</span>
                        <input
                          value={editUserForm.username}
                          onChange={(event) => updateEditUserForm('username', event.target.value)}
                          disabled={isUpdating || isCurrentUser}
                        />
                      </label>

                      <label>
                        <span>Email</span>
                        <input
                          value={editUserForm.email}
                          onChange={(event) => updateEditUserForm('email', event.target.value)}
                          type="email"
                          disabled={isUpdating}
                        />
                      </label>

                      <label>
                        <span>Full name</span>
                        <input
                          value={editUserForm.full_name}
                          onChange={(event) => updateEditUserForm('full_name', event.target.value)}
                          disabled={isUpdating}
                        />
                      </label>

                      <div className="settings-inline-form-actions">
                        <button type="button" onClick={cancelEditingUser} disabled={isUpdating}>
                          Cancel
                        </button>

                        <button type="submit" disabled={isUpdating}>
                          {isUpdating ? 'Saving...' : 'Save details'}
                        </button>
                      </div>
                    </form>
                  )}

                  {resetPasswordUserId === singleUser.id && (
                    <form
                      className="settings-inline-form"
                      onSubmit={(event) => handleResetPassword(event, singleUser)}
                    >
                      <label>
                        <span>New password</span>
                        <input
                          value={resetPasswordForm.password}
                          onChange={(event) =>
                            updateResetPasswordForm('password', event.target.value)
                          }
                          type="password"
                          disabled={isUpdating}
                          placeholder="At least 6 characters"
                        />
                      </label>

                      <label>
                        <span>Confirm password</span>
                        <input
                          value={resetPasswordForm.confirmPassword}
                          onChange={(event) =>
                            updateResetPasswordForm('confirmPassword', event.target.value)
                          }
                          type="password"
                          disabled={isUpdating}
                          placeholder="Repeat password"
                        />
                      </label>

                      <div className="settings-inline-form-actions">
                        <button type="button" onClick={cancelResetPassword} disabled={isUpdating}>
                          Cancel
                        </button>

                        <button type="submit" disabled={isUpdating}>
                          {isUpdating ? 'Saving...' : 'Reset password'}
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="settings-grid">
        {settingsSections.map((section) => (
          <article className="settings-section" key={section.title}>
            <div className="settings-section-header">
              <h2>{section.title}</h2>
              <span className="settings-status">{section.status}</span>
            </div>

            <p>{section.description}</p>

            <div className="settings-tags">
              {section.items.map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default SettingsPanel;