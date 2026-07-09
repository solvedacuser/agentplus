const state = {
  sessionId: localStorage.getItem("examCoachSessionId") || createSessionId(),
  userId: "demo-user",
};

const elements = {
  healthDot: document.querySelector("#healthDot"),
  healthText: document.querySelector("#healthText"),
  messageList: document.querySelector("#messageList"),
  messageInput: document.querySelector("#messageInput"),
  chatForm: document.querySelector("#chatForm"),
  sendButton: document.querySelector("#sendButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  toolChips: document.querySelectorAll(".tool-chip"),
  indexButton: document.querySelector("#indexButton"),
  sessionButton: document.querySelector("#sessionButton"),
  notice: document.querySelector("#notice"),
  recentQuestion: document.querySelector("#recentQuestion"),
  recentAnswer: document.querySelector("#recentAnswer"),
  weaknessTags: document.querySelector("#weaknessTags"),
  recentQuiz: document.querySelector("#recentQuiz"),
  gradingResults: document.querySelector("#gradingResults"),
};

init();

function init() {
  localStorage.setItem("examCoachSessionId", state.sessionId);

  elements.chatForm.addEventListener("submit", handleChatSubmit);
  elements.indexButton.addEventListener("click", handleIndexPdfs);
  elements.sessionButton.addEventListener("click", loadSessionState);
  elements.clearChatButton.addEventListener("click", clearMessages);
  elements.toolChips.forEach((button) => {
    button.addEventListener("click", handleToolChipClick);
  });
  checkHealth();
  appendMessage(
    "assistant",
    "개념 설명, 예상문제 생성, 답안 채점을 요청할 수 있습니다.",
  );
}

function handleToolChipClick(event) {
  const prompt = event.currentTarget.dataset.prompt || "";
  elements.messageInput.value = prompt;
  elements.messageInput.focus();
}

function createSessionId() {
  return `session-${Date.now().toString(36)}`;
}

function updateIdentity() {
  state.sessionId = state.sessionId || "default";
  state.userId = "demo-user";
  localStorage.setItem("examCoachSessionId", state.sessionId);
}

async function checkHealth() {
  try {
    const data = await requestJson("/health");
    elements.healthDot.className = "status-dot ok";
    elements.healthText.textContent = `${data.status} · ${data.environment}`;
  } catch (error) {
    elements.healthDot.className = "status-dot error";
    elements.healthText.textContent = "Server unavailable";
  }
}

async function handleChatSubmit(event) {
  event.preventDefault();
  updateIdentity();

  const message = elements.messageInput.value.trim();
  if (!message) {
    setNotice("메시지를 입력해주세요.", "error");
    return;
  }

  appendMessage("user", message);
  elements.messageInput.value = "";
  setBusy(elements.sendButton, true, "Sending");

  try {
    const data = await requestJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: state.sessionId,
        user_id: state.userId,
        message,
      }),
    });

    appendMessage("assistant", data.response || "응답이 비어 있습니다.", {
      requestType: data.request_type,
      weaknessTags: data.weakness_tags,
    });
    renderToolResult(data.tool_result);
    await loadSessionState({ silent: true });
  } catch (error) {
    appendMessage("error", error.message);
  } finally {
    setBusy(elements.sendButton, false, "Send");
  }
}

async function handleIndexPdfs() {
  setBusy(elements.indexButton, true, "Indexing");
  setNotice("PDF 인덱싱을 시작했습니다.", "");

  try {
    const data = await requestJson("/api/pdfs/index", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    setNotice(
      `인덱싱 완료: PDF ${data.pdf_count}개, 페이지 ${data.page_count}개, 청크 ${data.chunk_count}개`,
      "success",
    );
  } catch (error) {
    setNotice(error.message, "error");
  } finally {
    setBusy(elements.indexButton, false, "Index PDFs");
  }
}

async function loadSessionState(options = {}) {
  updateIdentity();
  if (!options.silent) {
    setBusy(elements.sessionButton, true, "Loading");
  }

  try {
    const data = await requestJson(`/api/sessions/${encodeURIComponent(state.sessionId)}`);
    renderSession(data);
    if (!options.silent) {
      setNotice("세션 상태를 불러왔습니다.", "success");
    }
  } catch (error) {
    if (!options.silent) {
      setNotice(error.message, "error");
    }
  } finally {
    if (!options.silent) {
      setBusy(elements.sessionButton, false, "Load Session");
    }
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  let data = null;

  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }

  if (!response.ok || data?.success === false) {
    throw new Error(data?.message || `요청 실패 (${response.status})`);
  }

  return data;
}

function appendMessage(role, content, meta = {}) {
  const message = document.createElement("article");
  message.className = `message ${role}`;

  const label = document.createElement("div");
  label.className = "message-meta";
  label.textContent = role === "user" ? "You" : role === "error" ? "Error" : "Agent";
  message.appendChild(label);

  if (meta.requestType) {
    const type = document.createElement("div");
    type.className = "message-meta";
    type.textContent = `request: ${meta.requestType}`;
    message.appendChild(type);
  }

  const body = document.createElement("div");
  body.textContent = content;
  message.appendChild(body);

  if (meta.weaknessTags?.length) {
    const tags = document.createElement("div");
    tags.className = "message-meta";
    tags.textContent = `weakness: ${meta.weaknessTags.join(", ")}`;
    message.appendChild(tags);
  }

  elements.messageList.appendChild(message);
  elements.messageList.scrollTop = elements.messageList.scrollHeight;
}

function clearMessages() {
  elements.messageList.replaceChildren();
}

function renderSession(data) {
  elements.recentQuestion.textContent = data.recent_question || "-";
  elements.recentAnswer.textContent = data.recent_answer || "-";
  elements.weaknessTags.textContent = data.weakness_tags?.length
    ? data.weakness_tags.join(", ")
    : "-";
  elements.recentQuiz.textContent = formatJson(data.recent_quiz);
  elements.gradingResults.textContent = formatJson(data.grading_results);
}

function renderToolResult(result) {
  if (!result || Object.keys(result).length === 0) {
    return;
  }

  if (result.questions) {
    elements.recentQuiz.textContent = formatJson(result);
  }

  if (result.grading_results) {
    elements.gradingResults.textContent = formatJson(result.grading_results);
  }

  if (Object.prototype.hasOwnProperty.call(result, "is_correct")) {
    elements.gradingResults.textContent = formatJson([result]);
  }
}

function setNotice(message, tone) {
  elements.notice.className = tone ? `notice ${tone}` : "notice";
  elements.notice.textContent = message;
}

function setBusy(button, isBusy, label) {
  button.disabled = isBusy;
  button.textContent = label;
}

function formatJson(value) {
  if (!value || (Array.isArray(value) && value.length === 0)) {
    return "-";
  }
  return JSON.stringify(value, null, 2);
}
