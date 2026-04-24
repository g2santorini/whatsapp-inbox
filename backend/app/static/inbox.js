const API_BASE = "http://127.0.0.1:8001";
const AUTO_REFRESH_MS = 4000;

let token = localStorage.getItem("whatsapp_inbox_token") || "";
let currentUserId = null;
let currentUser = null;
let usersMap = {};
let selectedConversationId = null;
let selectedConversationMeta = null;
let allConversations = [];
let activeView = "all";
let autoRefreshTimer = null;

function showToast(text) {
    const toast = document.getElementById("toast");
    toast.textContent = text;
    toast.style.display = "block";
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => {
        toast.style.display = "none";
    }, 2600);
}

function updateLoginUI() {
    const loginArea = document.getElementById("loginArea");
    const userArea = document.getElementById("userArea");
    const helloUser = document.getElementById("helloUser");

    if (token && currentUser) {
        loginArea.style.display = "none";
        userArea.style.display = "flex";
        helloUser.textContent = `Hello, ${currentUser.full_name || currentUser.username}`;
    } else {
        loginArea.style.display = "flex";
        userArea.style.display = "none";
        helloUser.textContent = "";
    }
}

function getAuthHeaders() {
    return {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json"
    };
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeQuotes(value) {
    return String(value ?? "").replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

function formatDate(value) {
    if (!value) return "";
    try {
        const date = new Date(value);
        const now = new Date();
        const sameDay = date.toDateString() === now.toDateString();

        if (sameDay) {
            return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        }

        return date.toLocaleDateString([], { month: "short", day: "numeric" });
    } catch {
        return value;
    }
}

function getInitials(nameOrPhone) {
    const value = String(nameOrPhone || "?").trim();

    if (value.startsWith("+")) return "#";

    const parts = value.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
        return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    }

    return value.slice(0, 2).toUpperCase();
}

function getUserName(userId) {
    if (!userId) return "";
    return usersMap[userId] || `User ${userId}`;
}

function getAssignmentLabel(conv) {
    if (!conv) return "";

    if (conv.status === "taken" && conv.assigned_to_user_id === currentUserId) {
        return "Taken by you";
    }

    if (conv.status === "taken" && conv.assigned_to_user_id) {
        return `Taken by ${getUserName(conv.assigned_to_user_id)}`;
    }

    return "Open";
}

function getAssignmentClass(conv) {
    if (!conv) return "open";
    return conv.status === "taken" ? "taken" : "open";
}

function isTakenByOther(conv) {
    return (
        conv &&
        conv.status === "taken" &&
        conv.assigned_to_user_id &&
        conv.assigned_to_user_id !== currentUserId &&
        currentUser?.role !== "admin"
    );
}

function updateActionButtons() {
    const takeBtn = document.getElementById("takeConversationBtn");
    const releaseBtn = document.getElementById("releaseConversationBtn");
    const sendBtn = document.getElementById("sendBtn");
    const input = document.getElementById("messageInput");

    if (!selectedConversationMeta) {
        takeBtn.style.display = "none";
        releaseBtn.style.display = "none";
        sendBtn.disabled = false;
        input.disabled = false;
        return;
    }

    const isOpen =
        selectedConversationMeta.status === "open" ||
        selectedConversationMeta.assigned_to_user_id == null;

    const isTakenByYou =
        selectedConversationMeta.status === "taken" &&
        selectedConversationMeta.assigned_to_user_id === currentUserId;

    const adminCanRelease =
        currentUser?.role === "admin" &&
        selectedConversationMeta.status === "taken";

    takeBtn.style.display = isOpen ? "inline-flex" : "none";
    releaseBtn.style.display = (isTakenByYou || adminCanRelease) ? "inline-flex" : "none";

    const locked = isTakenByOther(selectedConversationMeta);
    sendBtn.disabled = locked;
    input.disabled = locked;
    input.placeholder = locked
        ? `Read-only. ${getAssignmentLabel(selectedConversationMeta)}`
        : "Type a message...";
}

function updateBrowserTitle() {
    const totalUnread = allConversations.reduce((sum, conv) => {
        return sum + (conv.unread_count || 0);
    }, 0);

    document.title = totalUnread > 0
        ? `(${totalUnread}) WhatsApp Inbox`
        : "WhatsApp Inbox";
}

function startAutoRefresh() {
    if (autoRefreshTimer) return;

    autoRefreshTimer = setInterval(async () => {
        if (!token) return;

        try {
            await loadConversations(false);

            if (selectedConversationId) {
                await loadMessages(false);
            }
        } catch (error) {
            console.warn("Auto refresh error:", error);
        }
    }, AUTO_REFRESH_MS);
}

function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}

async function fetchCurrentUser() {
    const response = await fetch(`${API_BASE}/users/me/`, {
        headers: {
            "Authorization": `Bearer ${token}`
        }
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(JSON.stringify(data));
    }

    currentUser = data;
    currentUserId = data.id;
    return data;
}

async function loadUsers() {
    const response = await fetch(`${API_BASE}/users/`, {
        headers: {
            "Authorization": `Bearer ${token}`
        }
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(JSON.stringify(data));
    }

    usersMap = {};
    data.forEach(user => {
        usersMap[user.id] = user.full_name || user.username || `User ${user.id}`;
    });

    return data;
}

async function login() {
    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value.trim();

    const formData = new URLSearchParams();
    formData.append("username", username);
    formData.append("password", password);

    try {
        const response = await fetch(`${API_BASE}/token`, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded"
            },
            body: formData
        });

        const data = await response.json();

        if (!response.ok) {
            showToast("Login failed.");
            return;
        }

        token = data.access_token;
        localStorage.setItem("whatsapp_inbox_token", token);

        await fetchCurrentUser();
        await loadUsers();
        await loadConversations();
        updateLoginUI();

        startAutoRefresh();
        showToast(`Logged in as ${currentUser.full_name || currentUser.username}.`);
    } catch (error) {
        showToast("Login error.");
    }
}

function logout() {
    token = "";
    currentUserId = null;
    currentUser = null;
    usersMap = {};
    selectedConversationId = null;
    selectedConversationMeta = null;
    allConversations = [];

    localStorage.removeItem("whatsapp_inbox_token");
    stopAutoRefresh();

    document.title = "WhatsApp Inbox";
    document.getElementById("conversationList").innerHTML = `
        <div class="empty-state">
          <div>
            <strong>No conversations yet</strong>
            Log in and refresh your inbox.
          </div>
        </div>
      `;

    document.getElementById("messages").innerHTML = `
        <div class="empty-state">
          <div>
            <strong>Welcome</strong>
            Choose a conversation from the left panel.
          </div>
        </div>
      `;

    document.getElementById("chatAvatar").textContent = "?";
    document.getElementById("chatTitle").textContent = "Select a conversation";
    document.getElementById("chatSubtitle").textContent = "Messages will appear here.";
    document.getElementById("lastUpdated").textContent = "Not updated yet";

    updateActionButtons();
    updateLoginUI();
    showToast("Logged out.");
}

function setView(view) {
    activeView = view;

    ["All", "Unread", "Mine"].forEach(name => {
        const el = document.getElementById(`tab${name}`);
        if (el) el.classList.remove("active");
    });

    if (view === "all") document.getElementById("tabAll").classList.add("active");
    if (view === "unread") document.getElementById("tabUnread").classList.add("active");
    if (view === "mine") document.getElementById("tabMine").classList.add("active");

    renderConversations();
}

function getFilteredConversations() {
    let filtered = [...allConversations];

    if (activeView === "unread") {
        filtered = filtered.filter(conv =>
            (conv.unread_count || 0) > 0 ||
            conv.status === "open" ||
            conv.assigned_to_user_id == null
        );
    }

    if (activeView === "mine") {
        filtered = filtered.filter(conv => conv.assigned_to_user_id === currentUserId);
    }

    const search = document.getElementById("searchInput").value.trim().toLowerCase();

    if (search) {
        filtered = filtered.filter(conv => {
            const label = `${conv.contact_name || ""} ${conv.contact_phone || ""}`.toLowerCase();
            return label.includes(search);
        });
    }

    return filtered;
}

async function loadConversations(showToastMessage = true) {
    if (!token) {
        if (showToastMessage) showToast("Please log in first.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/conversations/`, {
            headers: {
                "Authorization": `Bearer ${token}`
            }
        });

        const data = await response.json();

        if (!response.ok) {
            if (showToastMessage) showToast("Could not load conversations.");
            return;
        }

        allConversations = data;

        if (selectedConversationId) {
            selectedConversationMeta =
                allConversations.find(conv => conv.id === selectedConversationId) || null;
        }

        updateBrowserTitle();
        await renderConversations();
        updateChatHeaderFromSelected();
        document.getElementById("lastUpdated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;

        if (showToastMessage) showToast(`Loaded ${data.length} conversation(s).`);
    } catch (error) {
        if (showToastMessage) showToast("Load conversations error.");
    }
}

async function renderConversations() {
    const list = document.getElementById("conversationList");
    const filtered = getFilteredConversations();

    if (!filtered.length) {
        list.innerHTML = `
          <div class="empty-state">
            <div>
              <strong>No results</strong>
              No conversations match this view.
            </div>
          </div>
        `;
        return;
    }

    const conversationsWithMeta = await Promise.all(
        filtered.map(async (conv) => {
            try {
                const res = await fetch(`${API_BASE}/conversations/${conv.id}/messages/`, {
                    headers: {
                        "Authorization": `Bearer ${token}`
                    }
                });

                const messages = await res.json();

                let lastMessage = "";
                let lastMessageIsUnreadInbound = false;

                if (Array.isArray(messages) && messages.length > 0) {
                    const last = messages[messages.length - 1];
                    lastMessage = last.content || "";
                    lastMessageIsUnreadInbound =
                        last.direction === "inbound" && last.is_read === false;
                }

                return { ...conv, lastMessage, lastMessageIsUnreadInbound };
            } catch {
                return {
                    ...conv,
                    lastMessage: "",
                    lastMessageIsUnreadInbound: false
                };
            }
        })
    );

    list.innerHTML = conversationsWithMeta.map(conv => {
        const label = conv.contact_name || conv.contact_phone;
        const activeClass = conv.id === selectedConversationId ? "active" : "";
        const unreadCount = conv.unread_count || 0;
        const unreadBadge = unreadCount > 0 ? `<div class="unread-badge">${unreadCount}</div>` : "";
        const assignmentLabel = getAssignmentLabel(conv);
        const assignmentClass = getAssignmentClass(conv);

        return `
          <div class="conversation-item ${activeClass}" onclick="selectConversation(${conv.id}, '${escapeQuotes(label)}')">
            <div class="avatar">${escapeHtml(getInitials(label))}</div>

            <div class="conv-main">
              <div class="conv-name">
                <span>${escapeHtml(label)}</span>
                <span class="verified">●</span>
              </div>

              <div class="conv-preview">
                ${escapeHtml(conv.lastMessage || "No messages yet")}
              </div>

              <div class="pill ${assignmentClass}">
                ${escapeHtml(assignmentLabel)}
              </div>
            </div>

            <div class="conv-meta">
              <div>${escapeHtml(formatDate(conv.last_message_at || conv.updated_at))}</div>
              ${unreadBadge}
            </div>
          </div>
        `;
    }).join("");
}

function updateChatHeaderFromSelected() {
    if (!selectedConversationMeta) {
        updateActionButtons();
        return;
    }

    const label = selectedConversationMeta.contact_name || selectedConversationMeta.contact_phone;
    document.getElementById("chatAvatar").textContent = getInitials(label);
    document.getElementById("chatTitle").innerHTML = `${escapeHtml(label)} <span class="verified">●</span>`;
    document.getElementById("chatSubtitle").textContent =
        `${selectedConversationMeta.contact_phone || ""} · ${getAssignmentLabel(selectedConversationMeta)}`;

    updateActionButtons();
}

async function markConversationAsRead(conversationId) {
    const response = await fetch(`${API_BASE}/conversations/${conversationId}/mark-as-read/`, {
        method: "POST",
        headers: {
            "Authorization": `Bearer ${token}`
        }
    });

    const data = await response.json();

    if (!response.ok) {
        throw new Error(JSON.stringify(data));
    }

    return data;
}

async function selectConversation(conversationId, label) {
    selectedConversationId = conversationId;
    selectedConversationMeta =
        allConversations.find(conv => conv.id === conversationId) || null;

    updateChatHeaderFromSelected();

    try {
        await markConversationAsRead(conversationId);
    } catch {
        showToast("Could not mark as read.");
    }

    await loadMessages();
    await loadConversations(false);
}

async function loadMessages(showToastMessage = false) {
    if (!token || !selectedConversationId) return;

    try {
        const response = await fetch(`${API_BASE}/conversations/${selectedConversationId}/messages/`, {
            headers: {
                "Authorization": `Bearer ${token}`
            }
        });

        const data = await response.json();

        if (!response.ok) {
            if (showToastMessage) showToast("Could not load messages.");
            return;
        }

        renderMessages(data);
    } catch {
        if (showToastMessage) showToast("Load messages error.");
    }
}

function renderMessages(messages) {
    const box = document.getElementById("messages");

    if (!messages.length) {
        box.innerHTML = `
          <div class="empty-state">
            <div>
              <strong>No messages yet</strong>
              Send the first message below.
            </div>
          </div>
        `;
        return;
    }

    box.innerHTML = `
        <div class="day-divider">Today</div>
        ${messages.map(msg => `
          <div class="message ${msg.direction || 'outbound'}">
            <div>${escapeHtml(msg.content)}</div>
            <span class="message-meta">
                ${escapeHtml(formatDate(msg.created_at))}
            </span>
          </div>
        `).join("")}
      `;

    box.scrollTop = box.scrollHeight;
}

async function takeConversation() {
    if (!token) {
        showToast("Please log in first.");
        return;
    }

    if (!selectedConversationId) {
        showToast("Please select a conversation first.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/conversations/${selectedConversationId}/take/`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`
            }
        });

        if (!response.ok) {
            showToast("Could not take conversation.");
            await loadConversations(false);
            return;
        }

        showToast("Conversation taken.");
        await loadConversations();
    } catch {
        showToast("Take conversation error.");
    }
}

async function releaseConversation() {
    if (!token) {
        showToast("Please log in first.");
        return;
    }

    if (!selectedConversationId) {
        showToast("Please select a conversation first.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/conversations/${selectedConversationId}/release/`, {
            method: "POST",
            headers: {
                "Authorization": `Bearer ${token}`
            }
        });

        if (!response.ok) {
            showToast("Could not release conversation.");
            await loadConversations(false);
            return;
        }

        showToast("Conversation released.");
        await loadConversations();
    } catch {
        showToast("Release conversation error.");
    }
}

async function sendMessage() {
    if (!token) {
        showToast("Please log in first.");
        return;
    }

    if (!selectedConversationId) {
        showToast("Please select a conversation first.");
        return;
    }

    if (isTakenByOther(selectedConversationMeta)) {
        showToast(`Cannot send. ${getAssignmentLabel(selectedConversationMeta)}.`);
        return;
    }

    const content = document.getElementById("messageInput").value.trim();

    if (!content) {
        showToast("Message is empty.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/conversations/${selectedConversationId}/messages/`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({ content })
        });

        if (!response.ok) {
            showToast("Could not send message.");
            await loadConversations(false);
            return;
        }

        document.getElementById("messageInput").value = "";
        showToast("Message sent.");
        await loadMessages();
        await loadConversations();
    } catch {
        showToast("Send message error.");
    }
}

function openNewChatModal() {
    document.getElementById("newChatModal").style.display = "flex";
    setTimeout(() => document.getElementById("newChatPhone").focus(), 50);
}

function closeNewChatModal() {
    document.getElementById("newChatModal").style.display = "none";
}

function isValidPhone(phone) {
    return /^\+[1-9]\d{7,14}$/.test(phone);
}

function validateNewChatPhone() {
    const phone = document.getElementById("newChatPhone").value.trim();
    const status = document.getElementById("phoneStatus");

    if (!phone) {
        status.className = "phone-status";
        status.textContent = "Use international format, e.g. +306900000000";
        return false;
    }

    if (isValidPhone(phone)) {
        status.className = "phone-status valid";
        status.textContent = "✓ Valid phone format. WhatsApp verification will be added later.";
        return true;
    }

    status.className = "phone-status invalid";
    status.textContent = "Invalid format. Use + country code and number, e.g. +306900000000";
    return false;
}

async function createNewChat() {
    if (!token) {
        showToast("Please log in first.");
        return;
    }

    const contact_name = document.getElementById("newChatName").value.trim();
    const contact_phone = document.getElementById("newChatPhone").value.trim();
    const message = document.getElementById("newChatMessage").value.trim();

    if (!validateNewChatPhone()) {
        showToast("Please enter a valid telephone number.");
        return;
    }

    try {
        const response = await fetch(`${API_BASE}/conversations/`, {
            method: "POST",
            headers: getAuthHeaders(),
            body: JSON.stringify({
                contact_name,
                contact_phone
            })
        });

        const conversation = await response.json();

        if (!response.ok) {
            showToast("Could not create chat.");
            return;
        }

        if (message) {
            await fetch(`${API_BASE}/conversations/${conversation.id}/messages/`, {
                method: "POST",
                headers: getAuthHeaders(),
                body: JSON.stringify({ content: message })
            });
        }

        document.getElementById("newChatName").value = "";
        document.getElementById("newChatPhone").value = "";
        document.getElementById("newChatMessage").value = "";
        validateNewChatPhone();
        closeNewChatModal();

        await loadConversations(false);
        await selectConversation(conversation.id, contact_name || contact_phone);

        showToast("New chat created.");
    } catch {
        showToast("New chat error.");
    }
}

window.onload = async () => {
    updateLoginUI();

    if (!token) return;

    try {
        await fetchCurrentUser();
        await loadUsers();
        await loadConversations(false);
        updateLoginUI();
        startAutoRefresh();
        showToast(`Welcome back, ${currentUser.full_name || currentUser.username}.`);
    } catch {
        localStorage.removeItem("whatsapp_inbox_token");
        token = "";
        currentUser = null;
        updateLoginUI();
        showToast("Saved login expired. Please log in again.");
    }
};
