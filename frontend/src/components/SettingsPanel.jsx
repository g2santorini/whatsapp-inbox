import { useEffect, useMemo, useState } from 'react';
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

const COLOR_PRESETS = [
  '#1d4ed8',
  '#c026d3',
  '#6d28d9',
  '#087f5b',
  '#c2410c',
  '#be123c',
  '#047857',
  '#4338ca',
  '#a21caf',
  '#9a3412',
];

const SETTINGS_SECTIONS = [
  {
    id: 'team',
    label: 'Team & access',
    description: 'Users, roles and colors',
    icon: 'users',
  },
  {
    id: 'quick-replies',
    label: 'Quick Replies',
    description: 'Categories and answers',
    icon: 'reply',
    badge: 'Next',
  },
  {
    id: 'automation',
    label: 'Automation',
    description: 'Inbox housekeeping',
    icon: 'sparkles',
  },
];

const ARCHIVE_OLD_OPTIONS = [
  { value: '36', label: '36 hours' },
  { value: '48', label: '48 hours' },
  { value: '168', label: '7 days' },
];

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const HEX_COLOR_REGEX = /^#[0-9a-f]{6}$/i;

const EMPTY_NEW_USER_FORM = {
  username: '',
  email: '',
  full_name: '',
  display_name: '',
  assignment_color: COLOR_PRESETS[0],
  password: '',
  role: 'user',
};

const EMPTY_EDIT_USER_FORM = {
  username: '',
  email: '',
  full_name: '',
  display_name: '',
  assignment_color: COLOR_PRESETS[0],
  role: 'user',
  disabled: false,
  can_view_reports: false,
};

const EMPTY_PASSWORD_RESET_FORM = {
  password: '',
  confirmPassword: '',
};

const SETTINGS_ICONS = {
  users: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  reply: (
    <>
      <path d="m9 17-5-5 5-5" />
      <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
    </>
  ),
  sparkles: (
    <>
      <path d="m12 3-1.4 3.6L7 8l3.6 1.4L12 13l1.4-3.6L17 8l-3.6-1.4L12 3Z" />
      <path d="m5 14-.9 2.1L2 17l2.1.9L5 20l.9-2.1L8 17l-2.1-.9L5 14Z" />
      <path d="m19 13-.9 2.1L16 16l2.1.9L19 19l.9-2.1L22 16l-2.1-.9L19 13Z" />
    </>
  ),
  plus: (
    <>
      <path d="M12 5v14M5 12h14" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.34 5.66" />
      <path d="M20 4v7h-7" />
    </>
  ),
  shield: (
    <>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
      <path d="m9 12 2 2 4-4" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4-4" />
    </>
  ),
  chevron: <path d="m9 18 6-6-6-6" />,
  lock: (
    <>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  folder: (
    <>
      <path d="M3 6h6l2 2h10v11H3z" />
    </>
  ),
};

function SettingsIcon({ name, size = 18 }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {SETTINGS_ICONS[name] || SETTINGS_ICONS.sparkles}
    </svg>
  );
}

function isValidEmail(email) {
  return EMAIL_REGEX.test(String(email || '').trim().toLowerCase());
}

function normalizeColor(value, fallback = COLOR_PRESETS[0]) {
  const normalized = String(value || '').trim().toLowerCase();
  return HEX_COLOR_REGEX.test(normalized) ? normalized : fallback;
}

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

function reportsIncludedByRole(userOrRole) {
  const role = typeof userOrRole === 'string' ? userOrRole : userOrRole?.role;
  return role === 'admin' || role === 'power_user';
}

function formatRole(role) {
  return ROLE_OPTIONS.find((option) => option.value === role)?.label || 'User';
}

function getUserDisplayLabel(user) {
  const customLabel = String(user?.display_name || '').trim();
  if (customLabel) return customLabel;

  const rawName = String(user?.full_name || user?.username || 'User').trim();
  const firstName = rawName.split(/[\s._-]+/).filter(Boolean)[0] || rawName;
  return `${firstName.charAt(0).toUpperCase()}${firstName.slice(1).toLowerCase()}`;
}

function getFallbackColor(user) {
  const stableValue = String(user?.username || user?.id || 'sendro').toLowerCase();
  const colorIndex = Array.from(stableValue).reduce(
    (total, character) => (total + character.charCodeAt(0)) % COLOR_PRESETS.length,
    0
  );

  return COLOR_PRESETS[colorIndex];
}

function getUserColor(user) {
  return normalizeColor(user?.assignment_color, getFallbackColor(user));
}

function getInitials(user) {
  const label = String(user?.full_name || user?.display_name || user?.username || '?');
  const words = label.split(/[\s._-]+/).filter(Boolean);

  if (words.length >= 2) {
    return `${words[0][0]}${words[1][0]}`.toUpperCase();
  }

  return label.slice(0, 2).toUpperCase();
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

function SettingsPanel({ onUsersChanged }) {
  const [activeSection, setActiveSection] = useState('team');
  const [currentUser, setCurrentUser] = useState(null);
  const [users, setUsers] = useState([]);
  const [userSearch, setUserSearch] = useState('');
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
  const visibleUsers = useMemo(
    () => users.filter((singleUser) => !isSystemUser(singleUser)),
    [users]
  );
  const filteredUsers = useMemo(() => {
    const query = userSearch.trim().toLowerCase();
    if (!query) return visibleUsers;

    return visibleUsers.filter((singleUser) =>
      [
        singleUser.full_name,
        singleUser.display_name,
        singleUser.username,
        singleUser.email,
        formatRole(singleUser.role),
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query))
    );
  }, [userSearch, visibleUsers]);

  const activeUsers = visibleUsers.filter((singleUser) => !singleUser.disabled).length;
  const blockedUsers = visibleUsers.filter((singleUser) => singleUser.disabled).length;

  function publishUsers(nextUsers) {
    const sortedUsers = sortUsers(nextUsers);
    setUsers(sortedUsers);
    onUsersChanged?.(sortedUsers);
    return sortedUsers;
  }

  function replaceUser(updatedUser) {
    const nextUsers = users.map((singleUser) =>
      singleUser.id === updatedUser.id ? updatedUser : singleUser
    );
    publishUsers(nextUsers);

    if (currentUser?.id === updatedUser.id) {
      setCurrentUser(updatedUser);
    }
  }

  async function loadUsers() {
    try {
      setIsLoadingUsers(true);
      setSettingsError('');

      const [currentUserData, usersData] = await Promise.all([
        getCurrentUser(),
        getUsers(),
      ]);

      setCurrentUser(currentUserData);
      publishUsers(usersData);
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

    if (editingUserId === userToEdit.id) {
      setEditingUserId(null);
      setEditUserForm(EMPTY_EDIT_USER_FORM);
      return;
    }

    setEditingUserId(userToEdit.id);
    setEditUserForm({
      username: userToEdit.username || '',
      email: userToEdit.email || '',
      full_name: userToEdit.full_name || '',
      display_name: userToEdit.display_name || getUserDisplayLabel(userToEdit),
      assignment_color: getUserColor(userToEdit),
      role: ROLE_OPTIONS.some((role) => role.value === userToEdit.role)
        ? userToEdit.role
        : 'user',
      disabled: Boolean(userToEdit.disabled),
      can_view_reports: Boolean(userToEdit.can_view_reports),
    });
  }

  function cancelEditingUser() {
    setEditingUserId(null);
    setEditUserForm(EMPTY_EDIT_USER_FORM);
    setResetPasswordUserId(null);
    setResetPasswordForm(EMPTY_PASSWORD_RESET_FORM);
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
    setResetPasswordUserId(
      resetPasswordUserId === userToUpdate.id ? null : userToUpdate.id
    );
    setResetPasswordForm(EMPTY_PASSWORD_RESET_FORM);
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
    const displayName = newUserForm.display_name.trim();
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

    if (displayName.length > 24) {
      setSettingsError('Badge name must be 24 characters or fewer.');
      return;
    }

    try {
      setIsCreatingUser(true);
      setSettingsError('');
      setSettingsSuccess('');

      const createdUser = await createUser({
        username,
        email,
        full_name: fullName,
        display_name: displayName,
        assignment_color: normalizeColor(newUserForm.assignment_color),
        password,
        role,
      });

      publishUsers([...users, createdUser]);
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
    const displayName = editUserForm.display_name.trim();
    const isCurrentUser = currentUser?.id === userToUpdate.id;

    if (!username || !email) {
      setSettingsError('Username and email are required.');
      return;
    }

    if (!isValidEmail(email)) {
      setSettingsError('Please enter a valid email address.');
      return;
    }

    if (displayName.length > 24) {
      setSettingsError('Badge name must be 24 characters or fewer.');
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
        full_name: fullName,
        display_name: displayName,
        assignment_color: normalizeColor(editUserForm.assignment_color),
        role: editUserForm.role,
        disabled: Boolean(editUserForm.disabled),
        can_view_reports: reportsIncludedByRole(editUserForm.role)
          ? Boolean(userToUpdate.can_view_reports)
          : Boolean(editUserForm.can_view_reports),
      });

      replaceUser(updatedUser);
      setEditingUserId(null);
      setEditUserForm(EMPTY_EDIT_USER_FORM);
      setResetPasswordUserId(null);
      setSettingsSuccess('User settings updated successfully.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not update user settings.'));
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

    if (!confirmed) return;

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

  const editingPreviewUser = {
    ...users.find((singleUser) => singleUser.id === editingUserId),
    ...editUserForm,
  };

  return (
    <section className="settings-panel">
      <div className="settings-page">
        <header className="settings-page-header">
          <div>
            <span className="settings-kicker">Workspace settings</span>
            <h1>Settings</h1>
            <p>Manage the people, permissions and tools behind your Sendro inbox.</p>
          </div>

          <div className="settings-workspace-pill">
            <span className="settings-workspace-mark">S</span>
            <span>
              <strong>Sunset Oia</strong>
              <small><i /> Workspace online</small>
            </span>
          </div>
        </header>

        <div className="settings-shell">
          <nav className="settings-navigation" aria-label="Settings sections">
            <span className="settings-navigation-label">Settings</span>

            {SETTINGS_SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                className={activeSection === section.id ? 'active' : ''}
                onClick={() => {
                  setActiveSection(section.id);
                  setSettingsError('');
                  setSettingsSuccess('');
                }}
              >
                <span className="settings-navigation-icon">
                  <SettingsIcon name={section.icon} />
                </span>
                <span className="settings-navigation-copy">
                  <strong>{section.label}</strong>
                  <small>{section.description}</small>
                </span>
                {section.badge ? (
                  <span className="settings-navigation-badge">{section.badge}</span>
                ) : (
                  <SettingsIcon name="chevron" size={15} />
                )}
              </button>
            ))}

            <div className="settings-navigation-note">
              <SettingsIcon name="shield" size={17} />
              <span>
                <strong>Admin protected</strong>
                <small>Only admins can save changes.</small>
              </span>
            </div>
          </nav>

          <main className="settings-content">
            {(settingsError || settingsSuccess) && (
              <div className={`settings-alert ${settingsError ? 'error' : 'success'}`}>
                {settingsError || settingsSuccess}
              </div>
            )}

            {activeSection === 'team' && (
              <div className="settings-view">
                <div className="settings-view-heading">
                  <div>
                    <span className="settings-section-eyebrow">People</span>
                    <h2>Team & access</h2>
                    <p>Control who can use Sendro and how they appear in conversations.</p>
                  </div>

                  <div className="settings-heading-actions">
                    <button
                      type="button"
                      className="settings-icon-button"
                      onClick={loadUsers}
                      disabled={isLoadingUsers}
                      aria-label="Refresh users"
                      title="Refresh users"
                    >
                      <SettingsIcon name="refresh" />
                    </button>

                    {isAdmin && (
                      <button
                        type="button"
                        className="settings-primary-button"
                        onClick={() => {
                          setSettingsError('');
                          setSettingsSuccess('');
                          setShowAddUserForm((currentValue) => !currentValue);
                        }}
                      >
                        <SettingsIcon name="plus" size={17} />
                        {showAddUserForm ? 'Close' : 'Add teammate'}
                      </button>
                    )}
                  </div>
                </div>

                <div className="settings-stat-strip">
                  <div>
                    <span className="settings-stat-icon blue"><SettingsIcon name="users" /></span>
                    <span><strong>{visibleUsers.length}</strong><small>Team members</small></span>
                  </div>
                  <div>
                    <span className="settings-stat-icon green"><SettingsIcon name="shield" /></span>
                    <span><strong>{activeUsers}</strong><small>Active</small></span>
                  </div>
                  <div>
                    <span className="settings-stat-icon orange"><SettingsIcon name="lock" /></span>
                    <span><strong>{blockedUsers}</strong><small>Blocked</small></span>
                  </div>
                </div>

                {showAddUserForm && (
                  <form className="settings-form-card" onSubmit={handleCreateUser}>
                    <div className="settings-form-card-header">
                      <div>
                        <span className="settings-section-eyebrow">New teammate</span>
                        <h3>Create user</h3>
                        <p>Add login details, role and the badge shown in conversations.</p>
                      </div>
                      <button type="button" onClick={closeAddUserForm} aria-label="Close form">×</button>
                    </div>

                    <div className="settings-form-grid">
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
                        <span>Name on badge</span>
                        <input
                          value={newUserForm.display_name}
                          onChange={(event) => updateNewUserForm('display_name', event.target.value)}
                          placeholder="Maria"
                          maxLength="24"
                          disabled={isCreatingUser}
                        />
                      </label>

                      <label>
                        <span>Username *</span>
                        <input
                          value={newUserForm.username}
                          onChange={(event) => updateNewUserForm('username', event.target.value)}
                          placeholder="maria"
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
                        <span>Temporary password *</span>
                        <input
                          value={newUserForm.password}
                          onChange={(event) => updateNewUserForm('password', event.target.value)}
                          placeholder="At least 6 characters"
                          type="password"
                          minLength="6"
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
                            <option value={role.value} key={role.value}>{role.label}</option>
                          ))}
                        </select>
                      </label>

                      <div className="settings-color-field settings-form-span">
                        <span>Conversation color</span>
                        <div className="settings-color-row">
                          <div className="settings-color-options">
                            {COLOR_PRESETS.map((color) => (
                              <button
                                key={color}
                                type="button"
                                className={normalizeColor(newUserForm.assignment_color) === color ? 'selected' : ''}
                                style={{ '--swatch-color': color }}
                                onClick={() => updateNewUserForm('assignment_color', color)}
                                aria-label={`Use color ${color}`}
                                aria-pressed={normalizeColor(newUserForm.assignment_color) === color}
                              />
                            ))}
                          </div>
                          <label className="settings-custom-color">
                            <input
                              type="color"
                              value={normalizeColor(newUserForm.assignment_color)}
                              onChange={(event) => updateNewUserForm('assignment_color', event.target.value)}
                              disabled={isCreatingUser}
                            />
                            Custom
                          </label>
                          <span
                            className="settings-badge-preview"
                            style={{ backgroundColor: normalizeColor(newUserForm.assignment_color) }}
                          >
                            {newUserForm.display_name.trim() || newUserForm.full_name.trim().split(/\s+/)[0] || newUserForm.username || 'User'}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="settings-form-actions">
                      <button type="button" className="settings-secondary-button" onClick={closeAddUserForm} disabled={isCreatingUser}>Cancel</button>
                      <button
                        type="submit"
                        className="settings-primary-button"
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

                <section className="settings-team-card">
                  <div className="settings-team-toolbar">
                    <div>
                      <h3>Team members</h3>
                      <span>{filteredUsers.length} shown</span>
                    </div>
                    <label className="settings-user-search">
                      <SettingsIcon name="search" size={17} />
                      <input
                        value={userSearch}
                        onChange={(event) => setUserSearch(event.target.value)}
                        placeholder="Search team..."
                      />
                    </label>
                  </div>

                  {isLoadingUsers ? (
                    <div className="settings-empty-state">Loading team members...</div>
                  ) : filteredUsers.length === 0 ? (
                    <div className="settings-empty-state">No team members match your search.</div>
                  ) : (
                    <div className="settings-user-list">
                      {filteredUsers.map((singleUser) => {
                        const isUpdating = updatingUserId === singleUser.id;
                        const isCurrentUser = currentUser?.id === singleUser.id;
                        const isEditing = editingUserId === singleUser.id;
                        const userColor = getUserColor(singleUser);

                        return (
                          <article className={`settings-user-row ${isEditing ? 'editing' : ''}`} key={singleUser.id}>
                            <div className="settings-user-summary">
                              <span className="settings-user-avatar" style={{ backgroundColor: userColor }}>
                                {getInitials(singleUser)}
                                {!singleUser.disabled && <i />}
                              </span>

                              <span className="settings-user-identity">
                                <strong>
                                  {singleUser.full_name || singleUser.username}
                                  {isCurrentUser && <small>You</small>}
                                </strong>
                                <span>@{singleUser.username} · {singleUser.email}</span>
                              </span>
                            </div>

                            <div className="settings-user-summary-actions">
                              <span className="settings-badge-preview" style={{ backgroundColor: userColor }}>
                                {getUserDisplayLabel(singleUser)}
                              </span>
                              <span className="settings-role-label">{formatRole(singleUser.role)}</span>
                              <span className={`settings-account-status ${singleUser.disabled ? 'blocked' : 'active'}`}>
                                <i /> {singleUser.disabled ? 'Blocked' : 'Active'}
                              </span>
                              <button
                                type="button"
                                className="settings-manage-button"
                                onClick={() => startEditingUser(singleUser)}
                                disabled={!isAdmin || isUpdating}
                              >
                                {isEditing ? 'Close' : 'Manage'}
                                <SettingsIcon name="chevron" size={15} />
                              </button>
                            </div>

                            {isEditing && (
                              <form className="settings-user-editor" onSubmit={(event) => handleSaveUserDetails(event, singleUser)}>
                                <div className="settings-editor-title">
                                  <div>
                                    <span className="settings-section-eyebrow">User setup</span>
                                    <h4>{singleUser.full_name || singleUser.username}</h4>
                                  </div>
                                  <span
                                    className="settings-badge-preview large"
                                    style={{ backgroundColor: normalizeColor(editUserForm.assignment_color) }}
                                  >
                                    {editUserForm.display_name.trim() || getUserDisplayLabel(editingPreviewUser)}
                                  </span>
                                </div>

                                <div className="settings-form-grid">
                                  <label>
                                    <span>Full name</span>
                                    <input value={editUserForm.full_name} onChange={(event) => updateEditUserForm('full_name', event.target.value)} disabled={isUpdating} />
                                  </label>
                                  <label>
                                    <span>Name on badge</span>
                                    <input value={editUserForm.display_name} onChange={(event) => updateEditUserForm('display_name', event.target.value)} maxLength="24" disabled={isUpdating} />
                                    <small>Shown as George, Daphne, Maria — without “Taken by”.</small>
                                  </label>
                                  <label>
                                    <span>Username</span>
                                    <input value={editUserForm.username} onChange={(event) => updateEditUserForm('username', event.target.value)} disabled={isUpdating || isCurrentUser} />
                                  </label>
                                  <label>
                                    <span>Email</span>
                                    <input value={editUserForm.email} onChange={(event) => updateEditUserForm('email', event.target.value)} type="email" disabled={isUpdating} />
                                  </label>

                                  <div className="settings-color-field settings-form-span">
                                    <span>Conversation color</span>
                                    <div className="settings-color-row">
                                      <div className="settings-color-options">
                                        {COLOR_PRESETS.map((color) => (
                                          <button
                                            key={color}
                                            type="button"
                                            className={normalizeColor(editUserForm.assignment_color) === color ? 'selected' : ''}
                                            style={{ '--swatch-color': color }}
                                            onClick={() => updateEditUserForm('assignment_color', color)}
                                            aria-label={`Use color ${color}`}
                                            aria-pressed={normalizeColor(editUserForm.assignment_color) === color}
                                            disabled={isUpdating}
                                          />
                                        ))}
                                      </div>
                                      <label className="settings-custom-color">
                                        <input type="color" value={normalizeColor(editUserForm.assignment_color)} onChange={(event) => updateEditUserForm('assignment_color', event.target.value)} disabled={isUpdating} />
                                        Custom
                                      </label>
                                    </div>
                                  </div>
                                </div>

                                <div className="settings-permission-grid">
                                  <label>
                                    <span>Role</span>
                                    <select value={editUserForm.role} onChange={(event) => updateEditUserForm('role', event.target.value)} disabled={isUpdating || isCurrentUser}>
                                      {ROLE_OPTIONS.map((role) => <option value={role.value} key={role.value}>{role.label}</option>)}
                                    </select>
                                    <small>{reportsIncludedByRole(editUserForm.role) ? 'Reports included by role.' : 'Standard inbox access.'}</small>
                                  </label>

                                  <label className="settings-toggle-card">
                                    <span>
                                      <strong>Reports</strong>
                                      <small>{reportsIncludedByRole(editUserForm.role) ? 'Always available for this role' : 'Allow Reports access'}</small>
                                    </span>
                                    <input
                                      type="checkbox"
                                      checked={reportsIncludedByRole(editUserForm.role) || Boolean(editUserForm.can_view_reports)}
                                      onChange={(event) => updateEditUserForm('can_view_reports', event.target.checked)}
                                      disabled={isUpdating || reportsIncludedByRole(editUserForm.role)}
                                    />
                                  </label>

                                  <label className="settings-toggle-card danger">
                                    <span>
                                      <strong>Account active</strong>
                                      <small>{editUserForm.disabled ? 'Login is blocked' : 'User can sign in'}</small>
                                    </span>
                                    <input
                                      type="checkbox"
                                      checked={!editUserForm.disabled}
                                      onChange={(event) => updateEditUserForm('disabled', !event.target.checked)}
                                      disabled={isUpdating || isCurrentUser}
                                    />
                                  </label>
                                </div>

                                {resetPasswordUserId === singleUser.id && (
                                  <div className="settings-password-panel">
                                    <div>
                                      <strong>Reset password</strong>
                                      <small>Set a new temporary password with at least 6 characters.</small>
                                    </div>
                                    <label>
                                      <span>New password</span>
                                      <input value={resetPasswordForm.password} onChange={(event) => updateResetPasswordForm('password', event.target.value)} type="password" minLength="6" disabled={isUpdating} />
                                    </label>
                                    <label>
                                      <span>Confirm password</span>
                                      <input value={resetPasswordForm.confirmPassword} onChange={(event) => updateResetPasswordForm('confirmPassword', event.target.value)} type="password" minLength="6" disabled={isUpdating} />
                                    </label>
                                    <button type="button" className="settings-secondary-button" onClick={(event) => handleResetPassword(event, singleUser)} disabled={isUpdating}>
                                      {isUpdating ? 'Saving...' : 'Update password'}
                                    </button>
                                  </div>
                                )}

                                <div className="settings-editor-actions">
                                  <button type="button" className="settings-text-button" onClick={() => startResetPassword(singleUser)} disabled={isUpdating}>
                                    <SettingsIcon name="lock" size={16} />
                                    {resetPasswordUserId === singleUser.id ? 'Close password reset' : 'Reset password'}
                                  </button>
                                  <span />
                                  <button type="button" className="settings-secondary-button" onClick={cancelEditingUser} disabled={isUpdating}>Cancel</button>
                                  <button type="submit" className="settings-primary-button" disabled={isUpdating}>
                                    {isUpdating ? 'Saving...' : 'Save changes'}
                                  </button>
                                </div>
                              </form>
                            )}
                          </article>
                        );
                      })}
                    </div>
                  )}
                </section>
              </div>
            )}

            {activeSection === 'quick-replies' && (
              <div className="settings-view">
                <div className="settings-view-heading">
                  <div>
                    <span className="settings-section-eyebrow">Coming next</span>
                    <h2>Quick Replies</h2>
                    <p>The permanent home for every company answer, category and shortcut.</p>
                  </div>
                  <span className="settings-phase-badge">Next batch</span>
                </div>

                <section className="settings-feature-hero">
                  <div className="settings-feature-orbit">
                    <span><SettingsIcon name="reply" size={28} /></span>
                  </div>
                  <div>
                    <span className="settings-section-eyebrow">Planned workflow</span>
                    <h3>One answer library, everywhere</h3>
                    <p>
                      Admins will organize categories and answers here. The team will use
                      them from the desktop panel, the mobile drawer or by typing “/”.
                    </p>
                  </div>
                </section>

                <div className="settings-feature-grid">
                  <article>
                    <span><SettingsIcon name="folder" /></span>
                    <h3>Categories</h3>
                    <p>Pricing, availability, booking, policies and any custom folder.</p>
                  </article>
                  <article>
                    <span><SettingsIcon name="search" /></span>
                    <h3>Fast search</h3>
                    <p>Find the right answer instantly from desktop or mobile.</p>
                  </article>
                  <article>
                    <span><SettingsIcon name="shield" /></span>
                    <h3>Role controlled</h3>
                    <p>Admins manage, Power Users contribute, Users insert and send.</p>
                  </article>
                  <article>
                    <span><SettingsIcon name="reply" /></span>
                    <h3>Insert, then edit</h3>
                    <p>“Use” fills the composer without sending automatically.</p>
                  </article>
                </div>
              </div>
            )}

            {activeSection === 'automation' && (
              <div className="settings-view">
                <div className="settings-view-heading">
                  <div>
                    <span className="settings-section-eyebrow">Inbox care</span>
                    <h2>Automation</h2>
                    <p>Keep the inbox focused without deleting conversation history.</p>
                  </div>
                </div>

                <section className="settings-automation-card">
                  <div className="settings-automation-heading">
                    <span className="settings-automation-icon"><SettingsIcon name="clock" size={22} /></span>
                    <div>
                      <h3>Archive old conversations</h3>
                      <p>Preview inactive conversations first, then archive only the safe matches.</p>
                    </div>
                  </div>

                  <div className="archive-old-controls">
                    <label>
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
                        {ARCHIVE_OLD_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                      </select>
                    </label>

                    <button type="button" className="settings-secondary-button" onClick={handlePreviewArchiveOldConversations} disabled={isPreviewingArchive || isArchivingOldConversations}>
                      {isPreviewingArchive ? 'Checking...' : 'Preview conversations'}
                    </button>

                    <button
                      type="button"
                      className="settings-warning-button"
                      onClick={handleArchiveOldConversations}
                      disabled={isPreviewingArchive || isArchivingOldConversations || Number(archivePreview?.matched_count || 0) <= 0}
                    >
                      {isArchivingOldConversations ? 'Archiving...' : 'Archive matches'}
                    </button>
                  </div>

                  <div className="settings-safety-note">
                    <SettingsIcon name="shield" size={18} />
                    <span>
                      <strong>Safety rule</strong>
                      <small>Unread, assigned, follow-up and already archived conversations are always skipped.</small>
                    </span>
                  </div>

                  {archivePreview && (
                    <div className="archive-old-preview">
                      <div className="archive-old-preview-summary">
                        <div><strong>{Number(archivePreview.matched_count || 0)}</strong><span>Matched</span></div>
                        <div><strong>{Number(archivePreview.archived_count || 0)}</strong><span>Archived</span></div>
                      </div>

                      {archivePreview.conversations?.length > 0 ? (
                        <div className="archive-old-list">
                          {archivePreview.conversations.slice(0, 10).map((conversation) => (
                            <div className="archive-old-row" key={conversation.id}>
                              <div>
                                <strong>{conversation.contact_name || conversation.contact_phone || `Conversation #${conversation.id}`}</strong>
                                <small>{conversation.contact_phone || '-'}</small>
                              </div>
                              <span>{formatArchiveDateTime(conversation.last_message_at)}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="archive-old-empty">No old conversations found for this threshold.</p>
                      )}

                      {archivePreview.conversations?.length > 10 && (
                        <p className="archive-old-empty">Showing first 10 of {archivePreview.conversations.length}.</p>
                      )}
                    </div>
                  )}
                </section>
              </div>
            )}
          </main>
        </div>
      </div>
    </section>
  );
}

export default SettingsPanel;
