// Cook Islands Legislation RAG - Chat Interface

let ws = null;
let currentAssistantMessage = null;
let isWaitingForResponse = false;
let isAuthenticated = false;
const AUTH_CODE = 'strategyday';  // This will be checked client-side for presentation

// Authentication function
function authenticate() {
    const input = document.getElementById('auth-code');
    const errorDiv = document.getElementById('auth-error');
    const code = input.value.trim();

    if (code === AUTH_CODE) {
        isAuthenticated = true;
        document.getElementById('auth-gate').style.display = 'none';
        document.getElementById('main-app').style.display = 'block';
        initWebSocket();
    } else {
        errorDiv.textContent = 'Invalid access code';
        input.value = '';
        input.focus();
    }
}

// Initialize WebSocket connection
function initWebSocket() {
    if (!isAuthenticated) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        addSystemMessage('Connected to legislation search service');
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
        addSystemMessage('Disconnected from server. Reconnecting...', true);
        // Attempt to reconnect after 2 seconds
        setTimeout(initWebSocket, 2000);
    };
}

// Handle different types of WebSocket messages
function handleWebSocketMessage(data) {
    const type = data.type;

    switch (type) {
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

        const heading = document.createElement('div');
        heading.className = 'search-result-heading';
        heading.textContent = result.heading_path || 'Unknown Section';

        const score = document.createElement('div');
        score.className = 'search-result-score';
        // Handle missing or invalid scores gracefully
        const scoreValue = result.score != null && !isNaN(result.score)
            ? (result.score * 100).toFixed(1)
            : 'N/A';
        score.textContent = `Relevance: ${scoreValue}${scoreValue !== 'N/A' ? '%' : ''}`;

        const text = document.createElement('div');
        text.className = 'search-result-text';
        text.textContent = result.text || '';

        item.appendChild(heading);
        item.appendChild(score);
        item.appendChild(text);
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
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.scrollTop = chatMessages.scrollHeight;
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
});
