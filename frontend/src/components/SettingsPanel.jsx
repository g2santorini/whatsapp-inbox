import { useEffect, useState } from 'react';
import { getCurrentUser, getUsers, updateUser } from '../api';
import './SettingsPanel.css';

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'power_user', label: 'Power User' },
  { value: 'user', label: 'User' },
];

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

function SettingsPanel() {
  const [currentUser, setCurrentUser] = useState(null);
  const [users, setUsers] = useState([]);
  const [isLoadingUsers, setIsLoadingUsers] = useState(true);
  const [updatingUserId, setUpdatingUserId] = useState(null);
  const [settingsError, setSettingsError] = useState('');
  const [settingsSuccess, setSettingsSuccess] = useState('');

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
      setUsers(usersData);
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not load users.'));
    } finally {
      setIsLoadingUsers(false);
    }
  }

  async function handleRoleChange(userId, newRole) {
    try {
      setUpdatingUserId(userId);
      setSettingsError('');
      setSettingsSuccess('');

      const updatedUser = await updateUser(userId, { role: newRole });

      setUsers((currentUsers) =>
        currentUsers.map((user) => (user.id === userId ? updatedUser : user))
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
        currentUsers.map((user) => (user.id === userToUpdate.id ? updatedUser : user))
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
          You can view users, but only admins can change roles or block users.
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

          <button type="button" onClick={loadUsers} disabled={isLoadingUsers}>
            {isLoadingUsers ? 'Loading...' : 'Refresh'}
          </button>
        </div>

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