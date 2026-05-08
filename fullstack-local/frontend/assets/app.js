const chatBox = document.getElementById('chatBox');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const promptInput = document.getElementById('promptInput');
const styleInput = document.getElementById('styleInput');
const imageBtn = document.getElementById('imageBtn');
const imageResult = document.getElementById('imageResult');
const sessionId = localStorage.getItem('cn_session') || crypto.randomUUID();
localStorage.setItem('cn_session', sessionId);

function addLine(role, text) {
  const el = document.createElement('div');
  el.className = `msg ${role}`;
  el.textContent = `${role.toUpperCase()}: ${text}`;
  chatBox.appendChild(el);
  chatBox.scrollTop = chatBox.scrollHeight;
}

sendBtn.onclick = async () => {
  const message = messageInput.value.trim();
  if (!message) return;
  addLine('user', message);
  messageInput.value = '';
  const res = await fetch('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId })
  });
  const data = await res.json();
  addLine('assistant', data.reply || data.detail || 'No response');
};

imageBtn.onclick = async () => {
  const prompt = promptInput.value.trim();
  const style = styleInput.value.trim() || 'realistic';
  if (!prompt) return;
  const res = await fetch('/api/image', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, style, session_id: sessionId })
  });
  const data = await res.json();
  if (data.image_url) {
    imageResult.innerHTML = `<img src="${data.image_url}" alt="generated"/><p><b>Effective prompt:</b> ${data.effective_prompt}</p>`;
    addLine('assistant', `Image generated: ${data.image_url}`);
  } else {
    imageResult.textContent = data.detail || 'Image generation failed';
  }
};
