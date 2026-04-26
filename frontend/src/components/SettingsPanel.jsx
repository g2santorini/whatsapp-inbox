import { useEffect, useState } from 'react';
import { createUser, getCurrentUser, getUsers, updateUser } from '../api';
import './SettingsPanel.css';

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'power_user', label: 'Power User' },
  { value: 'user', label: 'User' },
];

const EMPTY_NEW_USER_FORM = {
  username: '',
  email: '',
  full_name: '',
  password: '',
  role: 'user',
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

  const isAdmin = currentUser?.role === 'admin';
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

  async function handleRoleChange(userId, newRole) {
    try {
      setUpdatingUserId(userId);
      setSettingsError('');
      setSettingsSuccess('');

      const updatedUser = await updateUser(userId, { role: newRole });

      setUsers((currentUsers) =>
        sortUsers(
          currentUsers.map((user) => (user.id === userId ? updatedUser : user))
        )
      );

      if (currentUser?.id === updatedUser.id) {
        setCurrentUser(updatedUser);
      }

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
          <strong>{users.length}</strong>
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
            {users.map((singleUser) => {
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
                      className={`settings-status-badge ${
                        singleUser.disabled ? 'blocked' : 'active'
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