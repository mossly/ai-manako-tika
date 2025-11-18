// Cook Islands Legislation RAG - Chat Interface

let ws = null;
let currentAssistantMessage = null;
let isWaitingForResponse = false;
let isAuthenticated = false;
let sessionId = null;
let pingInterval = null;
let conversationId = null;
let conversations = [];
let userHasScrolledUp = false;

// Check for existing session on page load
window.addEventListener('DOMContentLoaded', async () => {
    // Initialize sidebar state based on screen size
    const mainApp = document.getElementById('main-app');
    if (window.innerWidth <= 768) {
        mainApp.classList.add('sidebar-collapsed');
    }

    // Handle window resize
    window.addEventListener('resize', () => {
        if (window.innerWidth <= 768) {
            mainApp.classList.add('sidebar-collapsed');
        } else {
            mainApp.classList.remove('sidebar-collapsed');
        }
    });

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
            await loadConversations();

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
            await loadConversations();
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

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        // Send session ID and conversation ID
        ws.send(JSON.stringify({
            session_id: sessionId,
            conversation_id: conversationId
        }));
        addSystemMessage('Connected to legislation search service');

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
        addSystemMessage('Disconnected from server. Reconnecting...', true);
        // Attempt to reconnect after 2 seconds
        setTimeout(initWebSocket, 2000);
    };
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
            conversationId = data.conversation_id;
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
            isWaitingForResponse = false;
            removeTypingIndicator();
            enableInput();
            break;

        default:
            console.warn('Unknown message type:', type);
    }
}

// Restore conversation history from previous session
function restoreConversationHistory(messages) {
    console.log('Restoring conversation history:', messages.length, 'messages');

    // Skip system message
    for (let i = 1; i < messages.length; i++) {
        const msg = messages[i];

        if (msg.role === 'user') {
            addUserMessage(msg.content);
        } else if (msg.role === 'assistant') {
            appendAssistantMessage(msg.content);
        }
        // Skip tool messages as they're internal
    }

    addSystemMessage('Previous conversation restored');
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
    appendToChat(messageDiv);
}

function createAssistantMessageElement() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    messageDiv.appendChild(contentDiv);
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
        heading.textContent = result.heading_path || 'Unknown Section';

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
    const button = document.getElementById('send-btn');
    input.disabled = false;
    button.disabled = false;
}

function disableInput() {
    const input = document.getElementById('user-input');
    const button = document.getElementById('send-btn');
    input.disabled = true;
    button.disabled = true;
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

async function loadConversations() {
    try {
        const response = await fetch(`/conversations?session_id=${sessionId}`);
        if (response.ok) {
            const data = await response.json();
            conversations = data.conversations;
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

async function createNewConversation() {
    // Check if current conversation is empty (only has welcome message)
    const chatMessages = document.getElementById('chat-messages');
    const messageCount = chatMessages.querySelectorAll('.message').length;

    // If current conversation is empty, just clear it instead of creating new
    if (messageCount <= 1) {
        clearChatMessages();
        return;
    }

    // Close existing WebSocket
    if (ws) {
        ws.close();
    }

    // Clear current conversation ID - server will create new one when WebSocket connects
    conversationId = null;
    clearChatMessages();

    // Connect with new conversation (server creates it automatically)
    initWebSocket();
}

async function switchConversation(newConversationId) {
    if (newConversationId === conversationId) return;

    // Close existing WebSocket
    if (ws) {
        ws.close();
    }

    // Set new conversation ID
    conversationId = newConversationId;

    // Clear chat
    clearChatMessages();

    // Update UI
    renderConversations();

    // Reconnect with new conversation
    initWebSocket();
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
    mainApp.classList.toggle('sidebar-collapsed');
}

function clearChatMessages() {
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.innerHTML = `
        <div class="message assistant-message">
            <div class="message-content">
                <p>Welcome! I can help you search and understand Cook Islands legislation.</p>
                <p>Ask me questions like:</p>
                <ul>
                    <li>"What are the capital requirements for banks?"</li>
                    <li>"Tell me about licensing requirements in the Banking Act"</li>
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

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
    initializeMarked();

    // Focus on auth input on load
    document.getElementById('auth-code').focus();

    // Enter key to authenticate
    document.getElementById('auth-code').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            authenticate();
        }
    });

    // Send button click
    document.getElementById('send-btn').addEventListener('click', sendMessage);

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
