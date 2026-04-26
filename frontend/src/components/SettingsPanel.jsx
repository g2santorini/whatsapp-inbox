import './SettingsPanel.css';

const settingsSections = [
  {
    title: 'Users',
    description: 'Manage team members, access, and basic account settings.',
    status: 'Planned',
    items: ['Add users', 'Edit user info', 'Deactivate users'],
  },
  {
    title: 'Roles & Permissions',
    description: 'Control what each user can see and what actions they can perform.',
    status: 'Core',
    items: ['Admin', 'Power User', 'User'],
  },
  {
    title: 'Active / Blocked Users',
    description: 'Temporarily block users without deleting their account history.',
    status: 'Planned',
    items: ['Active users', 'Blocked users', 'Access control'],
  },
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

function SettingsPanel() {
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
          <strong>3 roles</strong>
          <small>Admin / Power User / User</small>
        </div>

        <div className="settings-overview-card">
          <span>Permissions</span>
          <strong>View vs action</strong>
          <small>Prepared for SaaS logic</small>
        </div>

        <div className="settings-overview-card">
          <span>Templates</span>
          <strong>Coming soon</strong>
          <small>Quick replies foundation</small>
        </div>
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