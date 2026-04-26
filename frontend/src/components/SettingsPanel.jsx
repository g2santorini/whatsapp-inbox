function SettingsPanel() {
  return (
    <div className="settings-panel">
      <h1>Settings</h1>

      <div className="settings-section">
        <h2>Users</h2>
        <p>Manage users, roles, and permissions</p>
      </div>

      <div className="settings-section">
        <h2>Roles & Permissions</h2>
        <p>Define what each user can see and do</p>
      </div>

      <div className="settings-section">
        <h2>Active / Blocked Users</h2>
        <p>Enable or disable user access</p>
      </div>

      <div className="settings-section">
        <h2>Assignment Colors</h2>
        <p>Color coding for assigned conversations</p>
      </div>

      <div className="settings-section">
        <h2>Login Greetings</h2>
        <p>Custom greeting message per user</p>
      </div>

      <div className="settings-section">
        <h2>Templates / Quick Replies</h2>
        <p>Predefined messages for faster replies</p>
      </div>

      <div className="settings-section">
        <h2>Knowledge Base</h2>
        <p>Upload and manage company knowledge (coming soon)</p>
      </div>
    </div>
  );
}

export default SettingsPanel;