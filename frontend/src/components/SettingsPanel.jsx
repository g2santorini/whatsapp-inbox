import { useEffect, useMemo, useState } from 'react';
import {
  archiveOldConversations,
  createQuickReply,
  createQuickReplyCategory,
  createUser,
  deleteQuickReply,
  deleteQuickReplyCategory,
  getCurrentUser,
  getQuickReplies,
  getQuickReplyCategories,
  getUsers,
  resetUserPassword,
  updateQuickReply,
  updateQuickReplyCategory,
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

const TEXT_COLOR_PRESETS = [
  '#ffffff',
  '#10213f',
  '#111827',
  '#1d4ed8',
  '#087f5b',
  '#be123c',
];

const AUTOMATIC_DARK_TEXT_COLOR = '#10213f';
const AUTOMATIC_LIGHT_TEXT_COLOR = '#ffffff';

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
    description: 'Folders, answers and shortcuts',
    icon: 'reply',
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
  assignment_text_color: '',
  password: '',
  role: 'user',
};

const EMPTY_EDIT_USER_FORM = {
  username: '',
  email: '',
  full_name: '',
  display_name: '',
  assignment_color: COLOR_PRESETS[0],
  assignment_text_color: '',
  role: 'user',
  disabled: false,
  can_view_reports: false,
};

const EMPTY_PASSWORD_RESET_FORM = {
  password: '',
  confirmPassword: '',
};

const EMPTY_QUICK_REPLY_FORM = {
  title: '',
  shortcut: '',
  category_id: '',
  content: '',
  scope: 'personal',
  is_favorite: false,
};

const EMPTY_CATEGORY_FORM = {
  name: '',
  parent_id: '',
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
  edit: (
    <>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M9 7V4h6v3M6 7l1 13h10l1-13" />
    </>
  ),
  star: <path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6-5.4-2.9-5.4 2.9 1-6-4.4-4.3 6.1-.9Z" />,
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

function normalizeOptionalColor(value) {
  const normalized = String(value || '').trim().toLowerCase();
  return HEX_COLOR_REGEX.test(normalized) ? normalized : '';
}

function getRelativeLuminance(hexColor) {
  const normalized = normalizeColor(hexColor).slice(1);
  const channels = [0, 2, 4].map((offset) => {
    const channel = Number.parseInt(normalized.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4;
  });

  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function getAutomaticTextColor(backgroundColor) {
  const backgroundLuminance = getRelativeLuminance(backgroundColor);
  const darkLuminance = getRelativeLuminance(AUTOMATIC_DARK_TEXT_COLOR);
  const lightContrast = 1.05 / (backgroundLuminance + 0.05);
  const darkContrast =
    (Math.max(backgroundLuminance, darkLuminance) + 0.05) /
    (Math.min(backgroundLuminance, darkLuminance) + 0.05);

  return lightContrast >= darkContrast
    ? AUTOMATIC_LIGHT_TEXT_COLOR
    : AUTOMATIC_DARK_TEXT_COLOR;
}

function getBadgeTextColor(textColor, backgroundColor) {
  return (
    normalizeOptionalColor(textColor) ||
    getAutomaticTextColor(backgroundColor)
  );
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

function getUserTextColor(user) {
  return getBadgeTextColor(user?.assignment_text_color, getUserColor(user));
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

function SettingsPanel({ onUsersChanged, onQuickRepliesChanged }) {
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

  const [quickReplies, setQuickReplies] = useState([]);
  const [quickReplyCategories, setQuickReplyCategories] = useState([]);
  const [quickReplySearch, setQuickReplySearch] = useState('');
  const [quickReplyCategoryFilter, setQuickReplyCategoryFilter] = useState('all');
  const [isLoadingQuickReplies, setIsLoadingQuickReplies] = useState(true);
  const [isSavingQuickReply, setIsSavingQuickReply] = useState(false);
  const [updatingFavoriteQuickReplyId, setUpdatingFavoriteQuickReplyId] = useState(null);
  const [showQuickReplyForm, setShowQuickReplyForm] = useState(false);
  const [editingQuickReplyId, setEditingQuickReplyId] = useState(null);
  const [quickReplyForm, setQuickReplyForm] = useState(EMPTY_QUICK_REPLY_FORM);
  const [showCategoryForm, setShowCategoryForm] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState(null);
  const [categoryForm, setCategoryForm] = useState(EMPTY_CATEGORY_FORM);

  const [archiveOldHours, setArchiveOldHours] = useState('36');
  const [archivePreview, setArchivePreview] = useState(null);
  const [isPreviewingArchive, setIsPreviewingArchive] = useState(false);
  const [isArchivingOldConversations, setIsArchivingOldConversations] =
    useState(false);

  const isAdmin = currentUser?.role === 'admin';
  const canContributeQuickReplies = Boolean(currentUser);
  const availableSettingsSections = isAdmin
    ? SETTINGS_SECTIONS
    : SETTINGS_SECTIONS.filter((section) => section.id === 'quick-replies');
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
  const rootQuickReplyCategories = useMemo(
    () => quickReplyCategories.filter((category) => !category.parent_id),
    [quickReplyCategories]
  );
  const filteredQuickReplies = useMemo(() => {
    const query = quickReplySearch.trim().toLowerCase();

    return quickReplies.filter((reply) => {
      let matchesCategory = true;

      if (quickReplyCategoryFilter === 'favorites') {
        matchesCategory = Boolean(reply.is_favorite);
      } else if (quickReplyCategoryFilter === 'team') {
        matchesCategory = reply.scope === 'team';
      } else if (quickReplyCategoryFilter === 'mine') {
        matchesCategory = reply.scope === 'personal';
      } else if (quickReplyCategoryFilter !== 'all') {
        const selectedCategoryId = Number(quickReplyCategoryFilter);
        matchesCategory =
          reply.category_id === selectedCategoryId ||
          reply.parent_category_id === selectedCategoryId;
      }

      if (!matchesCategory) return false;
      if (!query) return true;

      return [
        reply.title,
        reply.shortcut,
        reply.category_name,
        reply.parent_category_name,
        reply.content,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    });
  }, [quickReplies, quickReplyCategoryFilter, quickReplySearch]);

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
      if (currentUserData?.role !== 'admin') {
        setActiveSection('quick-replies');
      }
      publishUsers(usersData);
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not load users.'));
    } finally {
      setIsLoadingUsers(false);
    }
  }

  async function loadQuickReplyData() {
    try {
      setIsLoadingQuickReplies(true);
      setSettingsError('');

      const [categoryData, quickReplyData] = await Promise.all([
        getQuickReplyCategories(),
        getQuickReplies(),
      ]);

      setQuickReplyCategories(categoryData);
      setQuickReplies(quickReplyData);
      onQuickRepliesChanged?.(quickReplyData, categoryData);
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not load quick replies.'));
    } finally {
      setIsLoadingQuickReplies(false);
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
      assignment_text_color: normalizeOptionalColor(
        userToEdit.assignment_text_color
      ),
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
        assignment_text_color: normalizeOptionalColor(
          newUserForm.assignment_text_color
        ),
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
        assignment_text_color: normalizeOptionalColor(
          editUserForm.assignment_text_color
        ),
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

  function getQuickReplyCategoryLabel(reply) {
    return [reply.parent_category_name, reply.category_name]
      .filter(Boolean)
      .join(' / ') || 'Uncategorized';
  }

  function resetQuickReplyEditor() {
    setShowQuickReplyForm(false);
    setEditingQuickReplyId(null);
    setQuickReplyForm(EMPTY_QUICK_REPLY_FORM);
  }

  function startCreatingQuickReply() {
    setSettingsError('');
    setSettingsSuccess('');
    setEditingQuickReplyId(null);
    setQuickReplyForm({
      ...EMPTY_QUICK_REPLY_FORM,
      scope:
        isAdmin && quickReplyCategoryFilter !== 'mine' ? 'team' : 'personal',
      category_id:
        !['all', 'team', 'mine', 'favorites'].includes(quickReplyCategoryFilter)
          ? quickReplyCategoryFilter
          : '',
    });
    setShowQuickReplyForm(true);
  }

  function startEditingQuickReply(reply) {
    if (!reply.can_edit) return;

    setSettingsError('');
    setSettingsSuccess('');
    setEditingQuickReplyId(reply.id);
    setQuickReplyForm({
      title: reply.title || '',
      shortcut: reply.shortcut || '',
      category_id: reply.category_id ? String(reply.category_id) : '',
      content: reply.content || '',
      scope: reply.scope || 'personal',
      is_favorite: Boolean(reply.is_favorite),
    });
    setShowQuickReplyForm(true);
  }

  function updateQuickReplyForm(fieldName, value) {
    setQuickReplyForm((currentForm) => ({
      ...currentForm,
      [fieldName]: value,
    }));
  }

  async function handleSaveQuickReply(event) {
    event.preventDefault();

    if (!quickReplyForm.title.trim() || !quickReplyForm.content.trim()) {
      setSettingsError('Add a title and reply text.');
      return;
    }

    try {
      setIsSavingQuickReply(true);
      setSettingsError('');
      setSettingsSuccess('');

      const payload = {
        title: quickReplyForm.title.trim(),
        shortcut: quickReplyForm.shortcut.trim() || null,
        category_id: quickReplyForm.category_id
          ? Number(quickReplyForm.category_id)
          : null,
        content: quickReplyForm.content.trim(),
        scope: quickReplyForm.scope,
        is_favorite: Boolean(quickReplyForm.is_favorite),
      };

      if (editingQuickReplyId) {
        await updateQuickReply(editingQuickReplyId, payload);
        setSettingsSuccess('Quick reply updated.');
      } else {
        await createQuickReply(payload);
        setSettingsSuccess('Quick reply created.');
      }

      resetQuickReplyEditor();
      await loadQuickReplyData();
      setSettingsSuccess(
        editingQuickReplyId ? 'Quick reply updated.' : 'Quick reply created.'
      );
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not save quick reply.'));
    } finally {
      setIsSavingQuickReply(false);
    }
  }

  async function handleDeleteQuickReply(reply) {
    if (!reply.can_delete) return;

    const confirmed = window.confirm(`Delete “${reply.title}”?`);
    if (!confirmed) return;

    try {
      setSettingsError('');
      setSettingsSuccess('');
      await deleteQuickReply(reply.id);
      await loadQuickReplyData();
      setSettingsSuccess('Quick reply deleted.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not delete quick reply.'));
    }
  }

  async function handleToggleQuickReplyFavorite(reply) {
    if (updatingFavoriteQuickReplyId === reply.id) return;

    try {
      setUpdatingFavoriteQuickReplyId(reply.id);
      setSettingsError('');
      setSettingsSuccess('');
      const updatedReply = await updateQuickReply(reply.id, {
        is_favorite: !reply.is_favorite,
      });
      const nextReplies = quickReplies.map((currentReply) =>
        currentReply.id === updatedReply.id ? updatedReply : currentReply
      );
      setQuickReplies(nextReplies);
      onQuickRepliesChanged?.(nextReplies, quickReplyCategories);
      setSettingsSuccess(
        updatedReply.is_favorite
          ? 'Added to your Favorites.'
          : 'Removed from your Favorites.'
      );
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not update your Favorites.'));
    } finally {
      setUpdatingFavoriteQuickReplyId(null);
    }
  }

  function resetCategoryEditor() {
    setShowCategoryForm(false);
    setEditingCategoryId(null);
    setCategoryForm(EMPTY_CATEGORY_FORM);
  }

  function startCreatingCategory() {
    setSettingsError('');
    setSettingsSuccess('');
    setEditingCategoryId(null);
    setCategoryForm(EMPTY_CATEGORY_FORM);
    setShowCategoryForm(true);
  }

  function startEditingCategory(category) {
    setSettingsError('');
    setSettingsSuccess('');
    setEditingCategoryId(category.id);
    setCategoryForm({
      name: category.name || '',
      parent_id: category.parent_id ? String(category.parent_id) : '',
    });
    setShowCategoryForm(true);
  }

  async function handleSaveCategory(event) {
    event.preventDefault();

    if (!categoryForm.name.trim()) {
      setSettingsError('Add a category name.');
      return;
    }

    try {
      setSettingsError('');
      setSettingsSuccess('');
      const payload = {
        name: categoryForm.name.trim(),
        parent_id: categoryForm.parent_id ? Number(categoryForm.parent_id) : null,
      };

      if (editingCategoryId) {
        await updateQuickReplyCategory(editingCategoryId, payload);
      } else {
        await createQuickReplyCategory(payload);
      }

      const successMessage = editingCategoryId
        ? 'Category updated.'
        : 'Category created.';
      resetCategoryEditor();
      await loadQuickReplyData();
      setSettingsSuccess(successMessage);
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not save category.'));
    }
  }

  async function handleDeleteCategory(category) {
    const confirmed = window.confirm(
      `Delete “${category.name}”? Its replies will move to Uncategorized.`
    );
    if (!confirmed) return;

    try {
      setSettingsError('');
      setSettingsSuccess('');
      await deleteQuickReplyCategory(category.id);

      if (quickReplyCategoryFilter === String(category.id)) {
        setQuickReplyCategoryFilter('all');
      }

      await loadQuickReplyData();
      setSettingsSuccess('Category deleted. Replies were kept.');
    } catch (err) {
      setSettingsError(getErrorMessage(err, 'Could not delete category.'));
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
    loadQuickReplyData();
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
            <p>
              {isAdmin
                ? 'Manage the people, permissions and tools behind your Sendro inbox.'
                : 'Create and maintain your private answers and personal Favorites.'}
            </p>
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

            {availableSettingsSections.map((section) => (
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
                <strong>{isAdmin ? 'Admin controls' : 'Personal controls'}</strong>
                <small>
                  {isAdmin
                    ? 'Manage the complete workspace.'
                    : 'Only you can see your personal replies.'}
                </small>
              </span>
            </div>
          </nav>

          <main className="settings-content">
            {(settingsError || settingsSuccess) && (
              <div className={`settings-alert ${settingsError ? 'error' : 'success'}`}>
                {settingsError || settingsSuccess}
              </div>
            )}

            {activeSection === 'team' && isAdmin && (
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
                            style={{
                              backgroundColor: normalizeColor(newUserForm.assignment_color),
                              color: getBadgeTextColor(
                                newUserForm.assignment_text_color,
                                newUserForm.assignment_color
                              ),
                            }}
                          >
                            {newUserForm.display_name.trim() || newUserForm.full_name.trim().split(/\s+/)[0] || newUserForm.username || 'User'}
                          </span>
                        </div>
                      </div>

                      <div className="settings-color-field settings-form-span">
                        <span>Badge text color</span>
                        <div className="settings-color-row">
                          <button
                            type="button"
                            className={`settings-auto-color-button ${!normalizeOptionalColor(newUserForm.assignment_text_color) ? 'selected' : ''}`}
                            onClick={() => updateNewUserForm('assignment_text_color', '')}
                            aria-pressed={!normalizeOptionalColor(newUserForm.assignment_text_color)}
                            disabled={isCreatingUser}
                          >
                            Auto
                          </button>
                          <div className="settings-color-options">
                            {TEXT_COLOR_PRESETS.map((color) => (
                              <button
                                key={color}
                                type="button"
                                className={normalizeOptionalColor(newUserForm.assignment_text_color) === color ? 'selected' : ''}
                                style={{ '--swatch-color': color }}
                                onClick={() => updateNewUserForm('assignment_text_color', color)}
                                aria-label={`Use text color ${color}`}
                                aria-pressed={normalizeOptionalColor(newUserForm.assignment_text_color) === color}
                                disabled={isCreatingUser}
                              />
                            ))}
                          </div>
                          <label className="settings-custom-color">
                            <input
                              type="color"
                              value={
                                normalizeOptionalColor(newUserForm.assignment_text_color) ||
                                getAutomaticTextColor(newUserForm.assignment_color)
                              }
                              onChange={(event) => updateNewUserForm('assignment_text_color', event.target.value)}
                              disabled={isCreatingUser}
                            />
                            Custom
                          </label>
                          <small className="settings-auto-color-note">
                            Auto chooses light or dark text for the background.
                          </small>
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
                        const userTextColor = getUserTextColor(singleUser);

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
                              <span
                                className="settings-badge-preview"
                                style={{ backgroundColor: userColor, color: userTextColor }}
                              >
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
                                    style={{
                                      backgroundColor: normalizeColor(editUserForm.assignment_color),
                                      color: getBadgeTextColor(
                                        editUserForm.assignment_text_color,
                                        editUserForm.assignment_color
                                      ),
                                    }}
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

                                  <div className="settings-color-field settings-form-span">
                                    <span>Badge text color</span>
                                    <div className="settings-color-row">
                                      <button
                                        type="button"
                                        className={`settings-auto-color-button ${!normalizeOptionalColor(editUserForm.assignment_text_color) ? 'selected' : ''}`}
                                        onClick={() => updateEditUserForm('assignment_text_color', '')}
                                        aria-pressed={!normalizeOptionalColor(editUserForm.assignment_text_color)}
                                        disabled={isUpdating}
                                      >
                                        Auto
                                      </button>
                                      <div className="settings-color-options">
                                        {TEXT_COLOR_PRESETS.map((color) => (
                                          <button
                                            key={color}
                                            type="button"
                                            className={normalizeOptionalColor(editUserForm.assignment_text_color) === color ? 'selected' : ''}
                                            style={{ '--swatch-color': color }}
                                            onClick={() => updateEditUserForm('assignment_text_color', color)}
                                            aria-label={`Use text color ${color}`}
                                            aria-pressed={normalizeOptionalColor(editUserForm.assignment_text_color) === color}
                                            disabled={isUpdating}
                                          />
                                        ))}
                                      </div>
                                      <label className="settings-custom-color">
                                        <input
                                          type="color"
                                          value={
                                            normalizeOptionalColor(editUserForm.assignment_text_color) ||
                                            getAutomaticTextColor(editUserForm.assignment_color)
                                          }
                                          onChange={(event) => updateEditUserForm('assignment_text_color', event.target.value)}
                                          disabled={isUpdating}
                                        />
                                        Custom
                                      </label>
                                      <small className="settings-auto-color-note">
                                        Auto chooses light or dark text for the background.
                                      </small>
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
                    <span className="settings-section-eyebrow">Answer library</span>
                    <h2>Quick Replies</h2>
                    <p>Use shared Team Replies, keep private My Replies and choose your own Favorites.</p>
                  </div>
                  <div className="settings-heading-actions">
                    <button
                      type="button"
                      className="settings-icon-button"
                      onClick={loadQuickReplyData}
                      disabled={isLoadingQuickReplies}
                      aria-label="Refresh quick replies"
                      title="Refresh quick replies"
                    >
                      <SettingsIcon name="refresh" />
                    </button>
                    {canContributeQuickReplies && (
                      <button
                        type="button"
                        className="settings-primary-button"
                        onClick={showQuickReplyForm ? resetQuickReplyEditor : startCreatingQuickReply}
                      >
                        <SettingsIcon name="plus" size={17} />
                        {showQuickReplyForm ? 'Close editor' : 'New quick reply'}
                      </button>
                    )}
                  </div>
                </div>

                <div className="settings-stat-strip quick-reply-stats">
                  <div>
                    <span className="settings-stat-icon blue"><SettingsIcon name="reply" /></span>
                    <span><strong>{quickReplies.filter((reply) => reply.scope === 'team').length}</strong><small>Team replies</small></span>
                  </div>
                  <div>
                    <span className="settings-stat-icon green"><SettingsIcon name="reply" /></span>
                    <span><strong>{quickReplies.filter((reply) => reply.scope === 'personal').length}</strong><small>My replies</small></span>
                  </div>
                  <div>
                    <span className="settings-stat-icon orange"><SettingsIcon name="star" /></span>
                    <span><strong>{quickReplies.filter((reply) => reply.is_favorite).length}</strong><small>My Favorites</small></span>
                  </div>
                </div>

                {showQuickReplyForm && (
                  <form className="quick-reply-editor-card" onSubmit={handleSaveQuickReply}>
                    <div className="quick-reply-editor-heading">
                      <div>
                        <span className="settings-section-eyebrow">
                          {editingQuickReplyId ? 'Edit answer' : 'New answer'}
                        </span>
                        <h3>{editingQuickReplyId ? 'Update quick reply' : 'Create quick reply'}</h3>
                      </div>
                      <button type="button" onClick={resetQuickReplyEditor} aria-label="Close editor">×</button>
                    </div>

                    <div className="quick-reply-editor-grid">
                      <label>
                        <span>Title</span>
                        <input
                          value={quickReplyForm.title}
                          onChange={(event) => updateQuickReplyForm('title', event.target.value)}
                          placeholder="e.g. Sunset cruise price"
                          maxLength="100"
                          disabled={isSavingQuickReply}
                        />
                      </label>
                      <label>
                        <span>Shortcut</span>
                        <div className="quick-reply-shortcut-input">
                          <strong>/</strong>
                          <input
                            value={quickReplyForm.shortcut}
                            onChange={(event) => updateQuickReplyForm('shortcut', event.target.value.replace(/^\/+/, '').toLowerCase())}
                            placeholder="sunset-price"
                            maxLength="40"
                            disabled={isSavingQuickReply}
                          />
                        </div>
                      </label>
                      <label>
                        <span>Visibility</span>
                        <select
                          value={quickReplyForm.scope}
                          onChange={(event) => updateQuickReplyForm('scope', event.target.value)}
                          disabled={isSavingQuickReply || !isAdmin || Boolean(editingQuickReplyId)}
                        >
                          {isAdmin && <option value="team">Team reply · visible to everyone</option>}
                          <option value="personal">My reply · visible only to me</option>
                        </select>
                      </label>
                      <label>
                        <span>Category</span>
                        <select
                          value={quickReplyForm.category_id}
                          onChange={(event) => updateQuickReplyForm('category_id', event.target.value)}
                          disabled={isSavingQuickReply}
                        >
                          <option value="">Uncategorized</option>
                          {quickReplyCategories.map((category) => {
                            const parent = quickReplyCategories.find((item) => item.id === category.parent_id);
                            return (
                              <option key={category.id} value={category.id}>
                                {parent ? `${parent.name} / ` : ''}{category.name}
                              </option>
                            );
                          })}
                        </select>
                      </label>
                      <label className="quick-reply-favorite-toggle">
                        <input
                          type="checkbox"
                          checked={quickReplyForm.is_favorite}
                          onChange={(event) => updateQuickReplyForm('is_favorite', event.target.checked)}
                          disabled={isSavingQuickReply}
                        />
                        <span><SettingsIcon name="star" size={17} /> Add to my Favorites</span>
                      </label>
                    </div>

                    <label className="quick-reply-content-field">
                      <span>Reply text</span>
                      <textarea
                        value={quickReplyForm.content}
                        onChange={(event) => updateQuickReplyForm('content', event.target.value)}
                        placeholder="Write the complete answer exactly as the team should see it..."
                        rows="7"
                        maxLength="4000"
                        disabled={isSavingQuickReply}
                      />
                      <small>{quickReplyForm.content.length} / 4000</small>
                    </label>

                    <div className="quick-reply-editor-actions">
                      <span>It will be inserted into the composer — never sent automatically.</span>
                      <button type="button" className="settings-secondary-button" onClick={resetQuickReplyEditor} disabled={isSavingQuickReply}>Cancel</button>
                      <button type="submit" className="settings-primary-button" disabled={isSavingQuickReply || !quickReplyForm.title.trim() || !quickReplyForm.content.trim()}>
                        {isSavingQuickReply ? 'Saving...' : editingQuickReplyId ? 'Save changes' : 'Create reply'}
                      </button>
                    </div>
                  </form>
                )}

                <div className="quick-reply-manager">
                  <aside className="quick-reply-folder-panel">
                    <div className="quick-reply-folder-heading">
                      <div>
                        <span className="settings-section-eyebrow">Folders</span>
                        <h3>Categories</h3>
                      </div>
                      {isAdmin && (
                        <button type="button" onClick={showCategoryForm ? resetCategoryEditor : startCreatingCategory} aria-label="Add category" title="Add category">
                          {showCategoryForm ? '×' : <SettingsIcon name="plus" size={17} />}
                        </button>
                      )}
                    </div>

                    {showCategoryForm && isAdmin && (
                      <form className="quick-reply-category-form" onSubmit={handleSaveCategory}>
                        <input
                          value={categoryForm.name}
                          onChange={(event) => setCategoryForm((current) => ({ ...current, name: event.target.value }))}
                          placeholder="Category name"
                          maxLength="60"
                          autoFocus
                        />
                        <select
                          value={categoryForm.parent_id}
                          onChange={(event) => setCategoryForm((current) => ({ ...current, parent_id: event.target.value }))}
                        >
                          <option value="">Top-level folder</option>
                          {rootQuickReplyCategories
                            .filter((category) => category.id !== editingCategoryId)
                            .map((category) => <option key={category.id} value={category.id}>Inside {category.name}</option>)}
                        </select>
                        <div>
                          <button type="button" onClick={resetCategoryEditor}>Cancel</button>
                          <button type="submit" disabled={!categoryForm.name.trim()}>
                            {editingCategoryId ? 'Save' : 'Add'}
                          </button>
                        </div>
                      </form>
                    )}

                    <div className="quick-reply-folder-list">
                      <button
                        type="button"
                        className={quickReplyCategoryFilter === 'all' ? 'active' : ''}
                        onClick={() => setQuickReplyCategoryFilter('all')}
                      >
                        <span><SettingsIcon name="reply" size={16} />All replies</span>
                        <strong>{quickReplies.length}</strong>
                      </button>
                      <button
                        type="button"
                        className={quickReplyCategoryFilter === 'team' ? 'active' : ''}
                        onClick={() => setQuickReplyCategoryFilter('team')}
                      >
                        <span><SettingsIcon name="users" size={16} />Team replies</span>
                        <strong>{quickReplies.filter((reply) => reply.scope === 'team').length}</strong>
                      </button>
                      <button
                        type="button"
                        className={quickReplyCategoryFilter === 'mine' ? 'active' : ''}
                        onClick={() => setQuickReplyCategoryFilter('mine')}
                      >
                        <span><SettingsIcon name="reply" size={16} />My replies</span>
                        <strong>{quickReplies.filter((reply) => reply.scope === 'personal').length}</strong>
                      </button>
                      <button
                        type="button"
                        className={quickReplyCategoryFilter === 'favorites' ? 'active favorite' : 'favorite'}
                        onClick={() => setQuickReplyCategoryFilter('favorites')}
                      >
                        <span><SettingsIcon name="star" size={16} />My Favorites</span>
                        <strong>{quickReplies.filter((reply) => reply.is_favorite).length}</strong>
                      </button>

                      {quickReplyCategories.map((category) => (
                        <div className={`quick-reply-folder-row ${category.parent_id ? 'child' : ''}`} key={category.id}>
                          <button
                            type="button"
                            className={quickReplyCategoryFilter === String(category.id) ? 'active' : ''}
                            onClick={() => setQuickReplyCategoryFilter(String(category.id))}
                          >
                            <span><SettingsIcon name="folder" size={16} />{category.name}</span>
                            <strong>{quickReplies.filter((reply) => reply.category_id === category.id || reply.parent_category_id === category.id).length}</strong>
                          </button>
                          {isAdmin && (
                            <span className="quick-reply-folder-actions">
                              <button type="button" onClick={() => startEditingCategory(category)} title="Edit category" aria-label={`Edit ${category.name}`}><SettingsIcon name="edit" size={14} /></button>
                              <button type="button" onClick={() => handleDeleteCategory(category)} title="Delete category" aria-label={`Delete ${category.name}`}><SettingsIcon name="trash" size={14} /></button>
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </aside>

                  <section className="quick-reply-library-panel">
                    <div className="quick-reply-library-toolbar">
                      <label>
                        <SettingsIcon name="search" size={18} />
                        <input
                          value={quickReplySearch}
                          onChange={(event) => setQuickReplySearch(event.target.value)}
                          placeholder="Search title, shortcut, category or reply text..."
                        />
                        {quickReplySearch && <button type="button" onClick={() => setQuickReplySearch('')} aria-label="Clear search">×</button>}
                      </label>
                      <span>{filteredQuickReplies.length} replies</span>
                    </div>

                    {isLoadingQuickReplies ? (
                      <div className="quick-reply-settings-empty">Loading quick replies...</div>
                    ) : filteredQuickReplies.length === 0 ? (
                      <div className="quick-reply-settings-empty">
                        <SettingsIcon name="reply" size={24} />
                        <strong>No quick replies found</strong>
                        <span>Create the first answer or change your filters.</span>
                      </div>
                    ) : (
                      <div className="quick-reply-settings-list">
                        {filteredQuickReplies.map((reply) => (
                          <article key={reply.id}>
                            <div className="quick-reply-settings-card-heading">
                              <button
                                type="button"
                                className={reply.is_favorite ? 'favorite active' : 'favorite'}
                                onClick={() => handleToggleQuickReplyFavorite(reply)}
                                disabled={updatingFavoriteQuickReplyId === reply.id}
                                aria-label={reply.is_favorite ? 'Remove from my Favorites' : 'Add to my Favorites'}
                                aria-pressed={Boolean(reply.is_favorite)}
                                title={reply.is_favorite ? 'Remove from my Favorites' : 'Add to my Favorites'}
                              >
                                <SettingsIcon name="star" size={17} />
                              </button>
                              <div>
                                <h3>{reply.title}</h3>
                                <span>{getQuickReplyCategoryLabel(reply)}</span>
                              </div>
                              <span className={`quick-reply-scope-badge ${reply.scope}`}>
                                {reply.scope === 'personal' ? 'Mine' : 'Team'}
                              </span>
                              {reply.shortcut && <code>/{reply.shortcut}</code>}
                            </div>
                            <p>{reply.content}</p>
                            <footer>
                              <small>
                                {reply.scope === 'personal'
                                  ? 'Private · visible only to you'
                                  : `Team reply · by ${reply.created_by_name || 'Sendro team'}`}
                              </small>
                              <span>
                                {reply.can_edit && (
                                  <button type="button" onClick={() => startEditingQuickReply(reply)}><SettingsIcon name="edit" size={15} />Edit</button>
                                )}
                                {reply.can_delete && (
                                  <button type="button" className="danger" onClick={() => handleDeleteQuickReply(reply)}><SettingsIcon name="trash" size={15} />Delete</button>
                                )}
                              </span>
                            </footer>
                          </article>
                        ))}
                      </div>
                    )}
                  </section>
                </div>
              </div>
            )}

            {activeSection === 'automation' && isAdmin && (
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
