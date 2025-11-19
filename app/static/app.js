// Cook Islands Legislation RAG - Chat Interface

let ws = null;
let currentAssistantMessage = null;
let isWaitingForResponse = false;
let isAuthenticated = false;
let sessionId = null;
let pingInterval = null;
let reconnectTimeout = null;
let manualReconnectPending = false;
let conversationId = null;
let conversations = [];
let userHasScrolledUp = false;
const DEMO_DISCLAIMER_KEY = 'demo_disclaimer_dismissed';
const LAST_CONVERSATION_KEY = 'last_conversation_id';

function getStoredConversationId() {
    if (typeof localStorage === 'undefined') {
        return null;
    }
    try {
        return localStorage.getItem(LAST_CONVERSATION_KEY);
    } catch (error) {
        console.warn('Unable to read stored conversation preference:', error);
        return null;
    }
}

function persistConversationId(id) {
    if (typeof localStorage === 'undefined') {
        return;
    }
    try {
        if (id) {
            localStorage.setItem(LAST_CONVERSATION_KEY, id);
        } else {
            localStorage.removeItem(LAST_CONVERSATION_KEY);
        }
    } catch (error) {
        console.warn('Unable to persist conversation preference:', error);
    }
}

function setConversationId(newId) {
    conversationId = newId;
    persistConversationId(newId);
}

// Check for existing session on page load
window.addEventListener('DOMContentLoaded', async () => {
    // Initialize sidebar state based on screen size
    const mainApp = document.getElementById('main-app');
    const syncSidebarLayout = () => {
        if (!mainApp) {
            return;
        }
        if (window.innerWidth <= 1300) {
            mainApp.classList.add('sidebar-collapsed');
            mainApp.classList.add('right-sidebar-collapsed');
        } else {
            mainApp.classList.remove('sidebar-collapsed');
            mainApp.classList.remove('right-sidebar-collapsed');
        }
    };

    syncSidebarLayout();

    // Handle window resize
    window.addEventListener('resize', syncSidebarLayout);

    const storedSession = localStorage.getItem('session_id');
    const storedExpiry = localStorage.getItem('session_expires_at');

    if (storedSession && storedExpiry) {
        // Check if session is still valid
        const expiryDate = new Date(storedExpiry);
        if (expiryDate > new Date()) {
            sessionId = storedSession;
            isAuthenticated = true;
            document.getElementById('auth-gate').style.display = 'none';
            document.getElementById('main-app').style.display = 'flex';

            // Load conversations list
            await loadConversations({ preserveSelection: false });

            // Connect to WebSocket
            initWebSocket();
        } else {
            // Session expired, clear storage
            localStorage.removeItem('session_id');
            localStorage.removeItem('session_expires_at');
        }
    }
});

// Authentication function
async function authenticate() {
    const input = document.getElementById('auth-code');
    const errorDiv = document.getElementById('auth-error');
    const code = input.value.trim();

    try {
        // Call server login endpoint
        const response = await fetch('/auth/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ code: code })
        });

        if (response.ok) {
            const data = await response.json();
            sessionId = data.session_id;

            // Store session in localStorage
            localStorage.setItem('session_id', sessionId);
            localStorage.setItem('session_expires_at', data.expires_at);

            isAuthenticated = true;
            document.getElementById('auth-gate').style.display = 'none';
            document.getElementById('main-app').style.display = 'flex';

            // Load conversations before initializing WebSocket
            await loadConversations({ preserveSelection: false });
            initWebSocket();
        } else {
            errorDiv.textContent = 'Invalid access code';
            input.value = '';
            input.focus();
        }
    } catch (error) {
        console.error('Authentication error:', error);
        errorDiv.textContent = 'Connection error. Please try again.';
    }
}

// Initialize WebSocket connection
function initWebSocket() {
    if (!isAuthenticated || !sessionId) return;

    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected - legislation search service ready');
        // Send session ID and conversation ID
        ws.send(JSON.stringify({
            session_id: sessionId,
            conversation_id: conversationId
        }));

        // Start ping interval to keep connection alive (every 30 seconds)
        if (pingInterval) {
            clearInterval(pingInterval);
        }
        pingInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 30000);
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        addSystemMessage('Connection error. Please refresh the page.', true);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        // Clear ping interval
        if (pingInterval) {
            clearInterval(pingInterval);
            pingInterval = null;
        }
        ws = null;

        if (manualReconnectPending) {
            manualReconnectPending = false;
            initWebSocket();
            return;
        }

        addSystemMessage('Disconnected from server. Reconnecting...', true);
        // Attempt to reconnect after 2 seconds, but avoid stacking timers
        if (!reconnectTimeout) {
            reconnectTimeout = setTimeout(() => {
                reconnectTimeout = null;
                initWebSocket();
            }, 2000);
        }
    };
}

function resetWebSocketConnection() {
    if (!isAuthenticated || !sessionId) {
        return;
    }

    if (reconnectTimeout) {
        clearTimeout(reconnectTimeout);
        reconnectTimeout = null;
    }

    if (ws && ws.readyState !== WebSocket.CLOSED) {
        manualReconnectPending = true;
        ws.close();
        return;
    }

    initWebSocket();
}

// Handle different types of WebSocket messages
function handleWebSocketMessage(data) {
    const type = data.type;

    switch (type) {
        case 'pong':
            // Keep-alive response, no action needed
            break;

        case 'conversation_created':
            // New conversation created by server
            setConversationId(data.conversation_id);
            // Only reload conversations if we don't already have this one
            if (!conversations.find(c => c.conversation_id === conversationId)) {
                loadConversations();
            }
            break;

        case 'history_restored':
            // Restore conversation history from previous session
            restoreConversationHistory(data.messages);
            break;

        case 'content':
            // Complete response without streaming
            appendAssistantMessage(data.content);
            break;

        case 'content_delta':
            // Streaming chunk
            if (!currentAssistantMessage) {
                currentMessageText = '';  // Reset buffer for new message
                removeTypingIndicator();  // Remove typing indicator when AI starts responding
                currentAssistantMessage = createAssistantMessageElement();
                appendToChat(currentAssistantMessage);
            }
            appendToCurrentMessage(data.content);
            break;

        case 'tool_use':
            // Tool is being called
            showToolNotification(data.content);
            break;

        case 'search_results':
            // Search results from legislation RAG
            displaySearchResults(data.content);
            break;

        case 'done':
            // Response complete
            currentAssistantMessage = null;
            currentMessageText = '';  // Reset buffer
            isWaitingForResponse = false;
            removeTypingIndicator();
            enableInput();
            break;

        case 'error':
            // Error occurred
            addSystemMessage(data.content, true);
            currentAssistantMessage = null;
            currentMessageText = '';
            isWaitingForResponse = false;
            removeTypingIndicator();
            enableInput();
            break;

        case 'stopped':
            // Generation cancelled by user
            const wasWaiting = isWaitingForResponse;
            currentAssistantMessage = null;
            currentMessageText = '';
            isWaitingForResponse = false;
            removeTypingIndicator();
            enableInput();
            if (wasWaiting) {
                addSystemMessage('Response stopped', false);
            }
            break;

        default:
            console.warn('Unknown message type:', type);
    }
}

function extractTextContent(rawContent) {
    if (rawContent === null || rawContent === undefined) {
        return '';
    }

    if (typeof rawContent === 'string') {
        return rawContent;
    }

    if (Array.isArray(rawContent)) {
        return rawContent.map(part => {
            if (typeof part === 'string') {
                return part;
            }
            if (part && typeof part.text === 'string') {
                return part.text;
            }
            return '';
        }).join('');
    }

    if (typeof rawContent === 'object' && typeof rawContent.text === 'string') {
        return rawContent.text;
    }

    return '';
}

// Restore conversation history from previous session
function restoreConversationHistory(messages) {
    console.log('Restoring conversation history:', messages.length, 'messages');

    // Skip system message
    for (let i = 1; i < messages.length; i++) {
        const msg = messages[i];

        if (msg.role === 'user') {
            const userText = extractTextContent(msg.content);
            if (!userText || !userText.trim()) {
                continue;
            }
            addUserMessage(userText);
        } else if (msg.role === 'assistant') {
            const assistantText = extractTextContent(msg.content);
            const hasToolCalls = Array.isArray(msg.tool_calls)
                ? msg.tool_calls.length > 0
                : Boolean(msg.tool_calls);

            // Tool call turns have no useful content when replayed, so skip them to avoid blank bubbles
            if (hasToolCalls || !assistantText.trim()) {
                continue;
            }

            appendAssistantMessage(assistantText);
        }
        // Skip tool messages as they're internal
    }

    addSystemMessage('Previous conversation restored');
}

function handleSendButtonClick() {
    if (isWaitingForResponse) {
        stopGeneration();
    } else {
        sendMessage();
    }
}

// Send user message
function sendMessage() {
    const input = document.getElementById('user-input');
    const message = input.value.trim();
    const modelSelect = document.getElementById('model-select');
    const selectedModel = modelSelect.value;

    if (!message || isWaitingForResponse) {
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addSystemMessage('Not connected to server. Please wait...', true);
        return;
    }

    // Add user message to chat
    addUserMessage(message);

    // Clear input
    input.value = '';

    // Reset scroll flag when user sends a message
    userHasScrolledUp = false;

    // Send to WebSocket with selected model
    ws.send(JSON.stringify({
        content: message,
        model: selectedModel
    }));

    // Disable input while waiting
    isWaitingForResponse = true;
    disableInput();

    // Show typing indicator
    showTypingIndicator();
}

function stopGeneration() {
    if (!isWaitingForResponse) {
        return;
    }

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        return;
    }

    ws.send(JSON.stringify({ type: 'stop' }));
}

// UI Helper Functions

function addUserMessage(text) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message user-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = text;

    messageDiv.appendChild(contentDiv);
    appendToChat(messageDiv);
}

function appendAssistantMessage(text) {
    const messageDiv = createAssistantMessageElement();
    const contentDiv = messageDiv.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(text);
    contentDiv.dataset.rawText = text; // Store raw text for copying
    appendToChat(messageDiv);
}

function createAssistantMessageElement() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'copy-message-btn';
    copyBtn.innerHTML = '📋';
    copyBtn.title = 'Copy message';
    copyBtn.onclick = (e) => {
        e.stopPropagation();
        copyMessageToClipboard(contentDiv);
    };

    messageDiv.appendChild(contentDiv);
    messageDiv.appendChild(copyBtn);
    return messageDiv;
}

// Keep track of raw unformatted text
let currentMessageText = '';

function appendToCurrentMessage(text) {
    if (!currentAssistantMessage) return;

    // Append to raw text buffer
    currentMessageText += text;

    // Format the complete text and update display
    const contentDiv = currentAssistantMessage.querySelector('.message-content');
    contentDiv.innerHTML = formatMarkdown(currentMessageText);
    contentDiv.dataset.rawText = currentMessageText; // Store raw text for copying

    scrollToBottom();
}

function showToolNotification(text) {
    const notificationDiv = document.createElement('div');
    notificationDiv.className = 'message assistant-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content tool-notification';
    contentDiv.textContent = `🔍 ${text}`;

    notificationDiv.appendChild(contentDiv);
    appendToChat(notificationDiv);
}

// Remove act name prefixes (e.g., "Compa ", "Iga12 ", "Eleca ")
function cleanActNamePrefix(headingPath) {
    if (!headingPath) return headingPath;

    // Match pattern: word characters followed by digits (optional), then space, then the actual act name
    // Examples: "Compa Companies Act", "Iga12 Island Government Act", "Eleca Electoral Act"
    return headingPath.replace(/^[A-Za-z]+\d*\s+/, '');
}

function displaySearchResults(results) {
    if (!results || results.length === 0) return;

    const resultsDiv = document.createElement('div');
    resultsDiv.className = 'message assistant-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    const searchResultsContainer = document.createElement('div');
    searchResultsContainer.className = 'search-results';

    const header = document.createElement('div');
    header.className = 'search-results-header';
    header.innerHTML = `📚 Retrieved ${results.length} relevant section(s):`;
    searchResultsContainer.appendChild(header);

    results.forEach((result, index) => {
        const item = document.createElement('div');
        item.className = 'search-result-item';

        const headingRow = document.createElement('div');
        headingRow.className = 'search-result-heading-row';

        const heading = document.createElement('span');
        heading.className = 'search-result-heading';
        // Prefer server-cleaned name, fallback to client-side cleaning for backward compatibility
        heading.textContent = result.heading_path_clean || cleanActNamePrefix(result.heading_path) || 'Unknown Section';

        const score = document.createElement('span');
        score.className = 'search-result-score';
        // Handle missing or invalid scores gracefully
        const scoreValue = result.score != null && !isNaN(result.score)
            ? (result.score * 100).toFixed(1)
            : 'N/A';
        score.textContent = `${scoreValue}${scoreValue !== 'N/A' ? '%' : ''}`;

        headingRow.appendChild(heading);
        headingRow.appendChild(score);
        item.appendChild(headingRow);
        searchResultsContainer.appendChild(item);
    });

    contentDiv.appendChild(searchResultsContainer);
    resultsDiv.appendChild(contentDiv);
    appendToChat(resultsDiv);
}

function showTypingIndicator() {
    const indicatorDiv = document.createElement('div');
    indicatorDiv.className = 'message assistant-message';
    indicatorDiv.id = 'typing-indicator';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator';
    typingDiv.innerHTML = '<span></span><span></span><span></span>';

    contentDiv.appendChild(typingDiv);
    indicatorDiv.appendChild(contentDiv);
    appendToChat(indicatorDiv);
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) {
        indicator.remove();
    }
}

function addSystemMessage(text, isError = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = `message-content ${isError ? 'error-message' : 'tool-notification'}`;
    contentDiv.textContent = text;

    messageDiv.appendChild(contentDiv);
    appendToChat(messageDiv);
}

function appendToChat(element) {
    const chatMessages = document.getElementById('chat-messages');
    const typingIndicator = document.getElementById('typing-indicator');

    // If typing indicator exists, insert new elements before it
    // This keeps the typing indicator at the bottom
    if (typingIndicator && element.id !== 'typing-indicator') {
        chatMessages.insertBefore(element, typingIndicator);
    } else {
        chatMessages.appendChild(element);
    }

    scrollToBottom();
}

function scrollToBottom() {
    if (userHasScrolledUp) return;

    const chatMessages = document.getElementById('chat-messages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function checkScrollPosition() {
    const chatMessages = document.getElementById('chat-messages');
    const threshold = 50; // pixels from bottom
    const isAtBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < threshold;
    userHasScrolledUp = !isAtBottom;
}

function enableInput() {
    const input = document.getElementById('user-input');
    input.disabled = false;
    updateSendButtonState(false);
}

function disableInput() {
    const input = document.getElementById('user-input');
    input.disabled = true;
    updateSendButtonState(true);
}

function updateSendButtonState(isRunning) {
    const button = document.getElementById('send-btn');
    if (!button) {
        return;
    }

    button.disabled = false;

    if (isRunning) {
        button.classList.add('stop');
        button.textContent = 'Stop';
        button.setAttribute('aria-label', 'Stop response');
    } else {
        button.classList.remove('stop');
        button.textContent = 'Send';
        button.setAttribute('aria-label', 'Send message');
    }
}

// Configure marked.js for proper markdown rendering
function initializeMarked() {
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,        // Convert \n to <br>
            gfm: true,           // GitHub Flavored Markdown (tables, strikethrough, task lists)
            headerIds: false,    // Don't add IDs to headers
            mangle: false,       // Don't mangle email addresses
        });

        // Custom renderer to make links open in new tab
        const renderer = new marked.Renderer();
        const originalLinkRenderer = renderer.link;
        renderer.link = function(href, title, text) {
            const html = originalLinkRenderer.call(this, href, title, text);
            return html.replace(/^<a /, '<a target="_blank" rel="noopener noreferrer" ');
        };
        marked.use({ renderer });
    }
}

// Enhanced markdown formatting using marked.js
function formatMarkdown(text) {
    if (typeof marked === 'undefined') {
        // Fallback: basic escaping if marked.js fails to load
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, '<br>');
    }

    try {
        return marked.parse(text);
    } catch (e) {
        console.error('Markdown parsing error:', e);
        // Fallback to plain text with line breaks
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, '<br>');
    }
}

// Conversation Management Functions

async function loadConversations(options = {}) {
    const { preserveSelection = true } = options;
    try {
        const response = await fetch(`/conversations?session_id=${sessionId}`);
        if (response.ok) {
            const data = await response.json();
            conversations = data.conversations;
            const activeConversationExists = conversationId && conversations.some(c => c.conversation_id === conversationId);
            if (!preserveSelection || !activeConversationExists) {
                ensureConversationSelected();
            }
            renderConversations();
        }
    } catch (error) {
        console.error('Failed to load conversations:', error);
    }
}

function renderConversations() {
    const list = document.getElementById('conversations-list');
    list.innerHTML = '';

    if (conversations.length === 0) {
        list.innerHTML = '<div style="padding: 20px; text-align: center; opacity: 0.5;">No conversations yet</div>';
        return;
    }

    conversations.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'conversation-item';
        if (conv.conversation_id === conversationId) {
            item.classList.add('active');
        }

        const title = document.createElement('div');
        title.className = 'conversation-title';
        title.textContent = conv.title || 'New Conversation';

        const date = document.createElement('div');
        date.className = 'conversation-date';
        date.textContent = formatDate(conv.updated_at);

        const actions = document.createElement('div');
        actions.className = 'conversation-actions';

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'conversation-action-btn';
        deleteBtn.textContent = '×';
        deleteBtn.title = 'Delete';
        deleteBtn.onclick = (e) => {
            e.stopPropagation();
            deleteConversation(conv.conversation_id);
        };

        actions.appendChild(deleteBtn);

        item.appendChild(title);
        item.appendChild(date);
        item.appendChild(actions);

        item.onclick = () => switchConversation(conv.conversation_id);

        list.appendChild(item);
    });
}

function ensureConversationSelected() {
    if (conversationId && conversations.some(c => c.conversation_id === conversationId)) {
        return;
    }

    const storedId = getStoredConversationId();
    if (storedId && conversations.some(c => c.conversation_id === storedId)) {
        setConversationId(storedId);
        return;
    }

    if (conversations.length > 0) {
        setConversationId(conversations[0].conversation_id);
    } else {
        setConversationId(null);
    }
}

async function createNewConversation() {
    // Check if current conversation is empty (only has welcome message)
    const chatMessages = document.getElementById('chat-messages');
    const messageCount = chatMessages.querySelectorAll('.message').length;

    // If current conversation is empty, just clear it instead of creating new
    if (messageCount <= 1) {
        clearChatMessages();
        return;
    }

    // Clear current conversation ID - server will create new one when WebSocket connects
    setConversationId(null);
    clearChatMessages();

    // Connect with new conversation (server creates it automatically)
    resetWebSocketConnection();
}

async function switchConversation(newConversationId) {
    if (newConversationId === conversationId) return;

    // Set new conversation ID
    setConversationId(newConversationId);

    // Clear chat
    clearChatMessages();

    // Update UI
    renderConversations();

    // Reconnect with new conversation
    resetWebSocketConnection();
}

async function deleteConversation(convId) {
    if (!confirm('Delete this conversation?')) return;

    try {
        const response = await fetch(`/conversations/${convId}?session_id=${sessionId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            // If deleting current conversation, create new one
            if (convId === conversationId) {
                await createNewConversation();
            } else {
                // Just reload list
                await loadConversations();
            }
        }
    } catch (error) {
        console.error('Failed to delete conversation:', error);
        addSystemMessage('Failed to delete conversation', true);
    }
}

function toggleSidebar() {
    const mainApp = document.getElementById('main-app');
    if (!mainApp) {
        return;
    }

    // On small screens, close the right sidebar when opening left sidebar
    if (window.innerWidth <= 1300) {
        const isOpening = mainApp.classList.contains('sidebar-collapsed');
        if (isOpening) {
            // About to open left sidebar, so close right sidebar
            mainApp.classList.add('right-sidebar-collapsed');
        }
    }

    mainApp.classList.toggle('sidebar-collapsed');
}

function toggleRightSidebar() {
    const mainApp = document.getElementById('main-app');
    if (!mainApp) {
        return;
    }

    // On small screens, close the left sidebar when opening right sidebar
    if (window.innerWidth <= 1300) {
        const isOpening = mainApp.classList.contains('right-sidebar-collapsed');
        if (isOpening) {
            // About to open right sidebar, so close left sidebar
            mainApp.classList.add('sidebar-collapsed');
        }
    }

    mainApp.classList.toggle('right-sidebar-collapsed');
}

function dismissDisclaimer() {
    const disclaimer = document.getElementById('demo-disclaimer');
    if (!disclaimer) {
        return;
    }
    disclaimer.style.display = 'none';
    try {
        localStorage.setItem(DEMO_DISCLAIMER_KEY, 'true');
    } catch (error) {
        console.warn('Unable to persist disclaimer preference:', error);
    }
}

function clearChatMessages() {
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.innerHTML = `
        <div class="message assistant-message">
            <div class="message-content">
                <p>Kia orana, I can help you search and understand Cook Islands legislation. Ask me questions like:</p>
                <ul>
                    <li>"What are the capital requirements for banks?"</li>
                    <li>"What does the law say about corporate governance?"</li>
                </ul>
            </div>
        </div>
    `;
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) {
        const hours = Math.floor(diff / (1000 * 60 * 60));
        if (hours === 0) {
            const minutes = Math.floor(diff / (1000 * 60));
            return minutes === 0 ? 'Just now' : `${minutes}m ago`;
        }
        return `${hours}h ago`;
    } else if (days === 1) {
        return 'Yesterday';
    } else if (days < 7) {
        return `${days}d ago`;
    } else {
        return date.toLocaleDateString();
    }
}

function copyMessageToClipboard(contentDiv) {
    // Get raw text from data attribute if available, otherwise extract from HTML
    const text = contentDiv.dataset.rawText || contentDiv.innerText;

    navigator.clipboard.writeText(text).then(() => {
        // Visual feedback - briefly change button appearance
        const btn = contentDiv.parentElement.querySelector('.copy-message-btn');
        if (btn) {
            const originalText = btn.innerHTML;
            btn.innerHTML = '✓';
            btn.classList.add('copied');
            setTimeout(() => {
                btn.innerHTML = originalText;
                btn.classList.remove('copied');
            }, 1500);
        }
    }).catch(err => {
        console.error('Failed to copy:', err);
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            const btn = contentDiv.parentElement.querySelector('.copy-message-btn');
            if (btn) {
                const originalText = btn.innerHTML;
                btn.innerHTML = '✓';
                btn.classList.add('copied');
                setTimeout(() => {
                    btn.innerHTML = originalText;
                    btn.classList.remove('copied');
                }, 1500);
            }
        } catch (e) {
            console.error('Fallback copy failed:', e);
        }
        document.body.removeChild(textarea);
    });
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    initializeMarked();
    const disclaimer = document.getElementById('demo-disclaimer');
    try {
        if (disclaimer && localStorage.getItem(DEMO_DISCLAIMER_KEY) === 'true') {
            disclaimer.style.display = 'none';
        }
    } catch (error) {
        console.warn('Unable to read disclaimer preference:', error);
    }

    // Focus on auth input on load
    document.getElementById('auth-code').focus();

    // Enter key to authenticate
    document.getElementById('auth-code').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            authenticate();
        }
    });

    // Initialize send button state and click handler
    updateSendButtonState(false);
    document.getElementById('send-btn').addEventListener('click', handleSendButtonClick);

    // Enter key to send (Shift+Enter for new line)
    document.getElementById('user-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Track scroll position to prevent auto-scroll when user has scrolled up
    document.getElementById('chat-messages').addEventListener('scroll', checkScrollPosition);
});
