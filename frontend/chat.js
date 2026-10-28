(function () {
  'use strict';

  const STORAGE_KEY = 'pqlocalagentosv3.chat-workspace.v1';
  const state = { agents: [], agent: '', messages: [], sending: false, projects: [], systemProjects: [], conversations: [], activeConversationId: '', activeProjectId: '', modelAvailable: false, iconSettings: {}, transport: null, renderer: null, transportConversationId: '' };
  const elements = {};

  async function chatApi(path, options) {
    const settings = options || {};
    const response = await fetch('/api' + path, {
      ...settings,
      headers: { 'Content-Type': 'application/json', ...(settings.headers || {}) }
    });
    let data;
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data.error || data.message || 'Ошибка запроса к серверу.');
    return data;
  }

  function chatMenuIcon(id, fallback) { return window.PQRenderIcon?.(id, state.iconSettings?.[id], 24) || fallback; }

  function createElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function setChatHeaderStatus(text, kind) {
    const node = document.getElementById('chat-task-status');
    if (!node) return;
    node.textContent = text || '';
    node.classList.remove('warning', 'running', 'ok', 'fail');
    if (kind) node.classList.add(kind);
  }

  function buildUI() {
    const root = createElement('section', 'panel chat-layout');
    root.id = 'chat-root';

    const toolbar = createElement('div', 'chat-toolbar');
    const modelInfo = createElement('div', 'chat-model-info');
    const label = createElement('span', 'chat-model-label', 'Текущий агент');
    const modelName = createElement('b', 'chat-model-name', 'Загрузка агентов…');
    modelName.id = 'chat-agent-name';
    const modelAvatar = createElement('div', 'chat-current-agent-avatar', 'AI');
    modelAvatar.id = 'chat-current-agent-avatar';
    modelAvatar.setAttribute('aria-hidden', 'true');
    modelAvatar.style.cursor = 'pointer';
    modelAvatar.title = 'Настройки агента';
    modelAvatar.addEventListener('click', () => {
      if (!state.agent) return;
      window.location.href = '/?edit_agent=' + encodeURIComponent(state.agent) + '&return_to_chat=1';
    });
    const taskStatus = createElement('span', 'chat-task-status', ''); taskStatus.id = 'chat-task-status'; taskStatus.setAttribute('role', 'status');
    const availability = createElement('span', 'chat-model-availability is-unavailable');
    availability.id = 'chat-model-availability';availability.title = 'Доступность модели не проверена';availability.setAttribute('role','status');availability.setAttribute('aria-label','Доступность модели не проверена');
    const activityTemplate = document.getElementById('chat-activity-template');
    const activity = activityTemplate?.content?.firstElementChild?.cloneNode(true);
    modelInfo.append(label, modelAvatar, modelName, taskStatus);
    if (activity) modelInfo.append(activity);
    modelInfo.append(availability);

    const controls = createElement('div', 'chat-toolbar-controls');
    const modelSelect = document.createElement('select');
    modelSelect.id = 'chat-agent';
    modelSelect.setAttribute('aria-label', 'Выбрать агента');
    const clearButton = createElement('button', 'btn secondary', 'Очистить чат');
    clearButton.type = 'button';
    clearButton.id = 'chat-clear';
    controls.append(modelSelect, clearButton);
    toolbar.append(modelInfo, controls);

    const messages = createElement('div', 'chat-messages');
    messages.id = 'chat-messages';
    messages.setAttribute('role', 'log');
    messages.setAttribute('aria-live', 'polite');
    messages.setAttribute('aria-label', 'История сообщений');

    const composer = createElement('div', 'chat-composer');
    const typing = createElement('div', 'chat-typing');
    typing.id = 'chat-typing';
    typing.hidden = true;
    typing.append(createElement('span'), createElement('span'), createElement('span'), createElement('b', '', 'Печатает…'));

    const form = document.createElement('form');
    form.id = 'chat-form';
    form.className = 'chat-input-row';
    const input = document.createElement('textarea');
    input.id = 'chat-input';
    input.rows = 2;
    input.placeholder = 'Напишите сообщение…';
    input.setAttribute('aria-label', 'Сообщение');
    input.autocomplete = 'off';
    const send = createElement('button', 'btn primary', 'Отправить');
    send.type = 'submit';
    send.id = 'chat-send';
    form.append(input, send);
    composer.append(typing, form);

    root.append(toolbar, messages, composer);
    document.getElementById('content').replaceChildren(root);

    elements.root = root;
    elements.modelName = modelName; elements.availability = availability;
    elements.agent = modelSelect;
    elements.messages = messages;
    elements.form = form;
    elements.input = input;
    elements.send = send;
    elements.clear = clearButton;
    elements.typing = typing;
    buildChatWorkspace();
  }

  function readWorkspace() {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
      state.projects = Array.isArray(saved.projects) ? saved.projects : [];
      state.conversations = Array.isArray(saved.conversations) ? saved.conversations : [];
      state.activeConversationId = saved.activeConversationId || '';
      state.activeProjectId = saved.activeProjectId || '';
    } catch (_) {
      state.projects = [];
      state.conversations = [];
    }
  }

  function saveWorkspace() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        projects: state.projects,
        conversations: state.conversations,
        activeConversationId: state.activeConversationId,
        activeProjectId: state.activeProjectId
      }));
    } catch (_) {
      showNotice('Браузер не разрешил сохранить историю чатов. Проверьте настройки хранилища сайта.', 'warning');
    }
  }

  function activeConversation() {
    return state.conversations.find((item) => item.id === state.activeConversationId) || null;
  }

  function persistActiveConversation() {
    const conversation = activeConversation();
    if (!conversation) return;
    conversation.messages = state.messages;
    conversation.agentId = state.agent;
    conversation.updatedAt = new Date().toISOString();
    const firstUser = state.messages.find((message) => message.role === 'user');
    if (firstUser && (!conversation.title || conversation.title === 'Новый чат')) {
      conversation.title = firstUser.content.trim().replace(/\s+/g, ' ').split(' ').slice(0,3).join(' ').slice(0,48) || 'Новый чат';
    }
    saveWorkspace();renderChatWorkspace();syncProjectChatMemory(conversation);
  }

  function makeId(prefix) {
    return prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
  }

  function buildChatWorkspace() {
    const nav = document.getElementById('nav');
    if (!nav || document.getElementById('chat-workspace')) return;
    const workspace = createElement('section', 'sidebar-chat-workspace'); workspace.id = 'chat-workspace';
    const group = createElement('section', 'nav-group nav-group-fixed'); group.dataset.navGroup = 'group-0';
    const title = createElement('div', 'nav-group-label', 'РАБОЧЕЕ ПРОСТРАНСТВО');
    const items = createElement('div', 'nav-group-items');
    const dashboard = createElement('a', 'nav-item', ''); dashboard.href='/';
    dashboard.insertAdjacentHTML('beforeend','<span class="nav-icon" aria-hidden="true">'+chatMenuIcon('dashboard','▦')+'</span>');dashboard.append(createElement('span','nav-label','Рабочий стол'));
    const chatLink = createElement('a','nav-item active',''); chatLink.href='/chat.html'; chatLink.setAttribute('aria-current','page');
    chatLink.insertAdjacentHTML('beforeend','<span class="nav-icon" aria-hidden="true">'+chatMenuIcon('chat','▤')+'</span>');chatLink.append(createElement('span','nav-label','Чат'));
    items.append(dashboard,chatLink); group.append(title,items);
    const actions=createElement('div','sidebar-chat-actions'),newChat=createElement('button','btn primary','Новый чат');
    newChat.insertAdjacentHTML('afterbegin','<img class="chat-action-icon" src="/icons/start.svg" alt="">');
    newChat.type='button';newChat.onclick=()=>createConversation('');actions.append(newChat);
    const projectsHeader=createElement('div','nav-group-label chat-tree-heading','');
    projectsHeader.append(document.createTextNode('ПРОЕКТЫ'));
    const addProject=createElement('button','icon-btn chat-add-project-btn','');
    addProject.type='button';addProject.id='chat-add-project-btn';addProject.title='Добавить проект';addProject.setAttribute('aria-label','Добавить проект');
    addProject.innerHTML='<img src="/icons/start.svg" alt="+">';
    addProject.onclick=openProjectModal;projectsHeader.append(addProject);
    const projectsList=createElement('div','sidebar-chat-list');projectsList.id='chat-project-list';
    const historyHeader=createElement('div','nav-group-label chat-tree-heading','НЕДАВНИЕ');
    const historyToggle=createElement('button','icon-btn chat-history-toggle','⌄');historyToggle.type='button';historyToggle.title='Свернуть историю чатов';historyToggle.setAttribute('aria-label','Свернуть историю чатов');
    historyToggle.style.cssText='margin-left:auto;padding:0 6px;min-width:24px;height:24px;border:0;background:transparent;color:inherit;cursor:pointer;font:inherit';historyHeader.append(historyToggle);
    const historyList=createElement('div','sidebar-chat-list');historyList.id='chat-history-list';
    const collapsed=localStorage.getItem('pqlocalagentosv3.chat-history-collapsed')==='true';historyList.hidden=collapsed;historyToggle.setAttribute('aria-expanded',String(!collapsed));historyToggle.classList.toggle('is-collapsed',collapsed);
    historyToggle.onclick=()=>{const close=historyToggle.getAttribute('aria-expanded')==='true';historyToggle.setAttribute('aria-expanded',String(!close));historyToggle.classList.toggle('is-collapsed',close);historyList.hidden=close;localStorage.setItem('pqlocalagentosv3.chat-history-collapsed',String(close))};
    workspace.append(group,actions,projectsHeader,projectsList,historyHeader,historyList);
    workspace.insertAdjacentHTML('beforeend','<div class="modal-overlay" id="chat-project-modal" hidden><div class="modal-backdrop" data-chat-project-close></div><section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="chat-project-title"><div class="section-title modal-card-head"><div><h2 id="chat-project-title">Проект для чата</h2><p>Выберите существующий или создайте новый.</p></div><button type="button" class="btn secondary" data-chat-project-close>Закрыть</button></div><div class="modal-card-body"><div class="field"><label for="chat-project-select">Существующий проект</label><select id="chat-project-select"><option value="">— Не выбран —</option></select></div><div class="divider"></div><div class="field"><label for="chat-project-name">Новый проект</label><input id="chat-project-name" maxlength="120" placeholder="Название нового проекта"></div><div class="field"><label for="chat-project-path">Путь (необязательно)</label><input id="chat-project-path" maxlength="1000" placeholder="C:\\Projects\\MyProject"></div><div class="field"><label for="chat-project-description">Описание (необязательно)</label><textarea id="chat-project-description" rows="2" maxlength="1000"></textarea></div><div class="notice" id="chat-project-status" hidden></div></div><div class="modal-card-actions"><button type="button" class="btn secondary" data-chat-project-close>Отмена</button><button type="button" class="btn primary" id="chat-project-submit">Добавить в чат</button></div></section></div>');
    document.body.append(document.getElementById('chat-project-modal'));
    nav.replaceChildren(workspace);elements.workspace=workspace;elements.projectsList=projectsList;elements.historyList=historyList;bindProjectModal();
  }

  async function openProjectModal() {
    const modal=document.getElementById('chat-project-modal'),select=document.getElementById('chat-project-select'),status=document.getElementById('chat-project-status');if(!modal||!select)return;
    status.hidden=true;status.textContent='';select.replaceChildren(new Option('— Не выбран —',''));
    try{const result=await chatApi('/projects');state.systemProjects=Array.isArray(result.items)?result.items:[];state.systemProjects.forEach(p=>select.add(new Option(p.name||'Без названия',p.id)))}catch(e){state.systemProjects=[];status.textContent='Не удалось загрузить проекты: '+e.message;status.hidden=false}
    modal.hidden=false;document.getElementById('chat-project-name')?.focus();
  }

  function bindProjectModal() {
    const modal=document.getElementById('chat-project-modal');if(!modal||modal.dataset.bound==='true')return;modal.dataset.bound='true';
    modal.querySelectorAll('[data-chat-project-close]').forEach(b=>b.onclick=()=>{modal.hidden=true});
    document.getElementById('chat-project-submit').onclick=async()=>{
      const select=document.getElementById('chat-project-select'),nameInput=document.getElementById('chat-project-name'),pathInput=document.getElementById('chat-project-path'),descInput=document.getElementById('chat-project-description'),status=document.getElementById('chat-project-status'),submit=document.getElementById('chat-project-submit'),name=nameInput.value.trim();
      status.hidden=true;status.textContent='';submit.disabled=true;
      try{let project;if(name){project=await chatApi('/projects',{method:'POST',body:JSON.stringify({name:name.slice(0,120),path:pathInput.value.trim(),description:descInput.value.trim()})});state.systemProjects=[project,...(state.systemProjects||[]).filter(p=>p.id!==project.id)]}else if(select.value){project=(state.systemProjects||[]).find(p=>p.id===select.value);if(!project)throw new Error('Выбранный проект больше не найден. Откройте список заново.')}else throw new Error('Выберите проект или введите название');
      if(!state.projects.some(p=>p.id===project.id))state.projects.unshift({id:project.id,name:project.name||'Без названия',createdAt:project.created_at||new Date().toISOString(),expanded:true});
      state.activeProjectId=project.id;saveWorkspace();renderChatWorkspace();modal.hidden=true;nameInput.value='';pathInput.value='';descInput.value='';select.value='';createConversation(project.id)
      }catch(e){status.textContent=e.message||'Не удалось добавить проект.';status.hidden=false}finally{submit.disabled=false}
    };
  }
  function createConversation(projectId) {
    if (state.sending) return;
    state.transport?.close(); state.transport = null; state.renderer = null; state.transportConversationId = ''; window.PQChatTransport = null;
    const conversation = {
      id: makeId('chat'),
      title: 'Новый чат',
      projectId: projectId || '',
      agentId: state.agent,
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString()
    };
    state.conversations.unshift(conversation);
    state.activeConversationId = conversation.id;
    state.activeProjectId = conversation.projectId;
    state.messages = [];
    renderHistory();
    saveWorkspace();
    renderChatWorkspace();
    syncProjectChatMemory(conversation);
    elements.input.value = '';
    resizeInput();
    elements.input.focus();
  }

  function openConversation(id) {
    if (state.sending || id === state.activeConversationId) return;
    state.transport?.close(); state.transport = null; state.renderer = null; state.transportConversationId = ''; window.PQChatTransport = null;
    const conversation = state.conversations.find((item) => item.id === id);
    if (!conversation) return;
    state.activeConversationId = id;
    state.activeProjectId = conversation.projectId || '';
    state.messages = Array.isArray(conversation.messages) ? conversation.messages.slice() : [];
    if (conversation.agentId && state.agents.some((agent) => agent.id === conversation.agentId)) {
      state.agent = conversation.agentId;
      elements.agent.value = state.agent;
      const selected = state.agents.find((agent) => agent.id === state.agent);
      elements.modelName.textContent = selected ? selected.name : 'Агент не выбран';
    }
    renderHistory();
    saveWorkspace();
    renderChatWorkspace();
    void restoreEventConversation();
    elements.input.value = '';
    resizeInput();
  }

  function renameConversation(id) {
    const conversation=state.conversations.find(item=>item.id===id);if(!conversation)return;
    const next=window.prompt('Название чата',conversation.title||'Новый чат');if(next===null)return;
    const title=next.trim().replace(/\s+/g,' ').slice(0,120);if(!title){showNotice('Название чата не может быть пустым.','warning');return}
    conversation.title=title;conversation.updatedAt=new Date().toISOString();saveWorkspace();renderChatWorkspace();syncProjectChatMemory(conversation);
  }
  async function syncProjectChatMemory(conversation) {
    if(!conversation?.projectId)return;
    try{const projectChats=state.conversations.filter(item=>item.projectId===conversation.projectId).sort((a,b)=>(b.updatedAt||'').localeCompare(a.updatedAt||'')).slice(0,40).map(item=>({id:item.id,title:item.title||'Новый чат',updated_at:item.updatedAt||'',agent_id:item.agentId||'',messages:(item.messages||[]).slice(-30).map(m=>({role:m.role,content:String(m.content||'').slice(0,3000),time:m.time||''}))}));await chatApi('/projects/'+encodeURIComponent(conversation.projectId)+'/memory',{method:'POST',body:JSON.stringify({chats:projectChats})})}catch(error){showNotice('История сохранена в браузере, но память проекта не обновилась: '+error.message,'warning')}
  }

  function deleteConversation(id) {
    if (state.sending) return;
    state.conversations = state.conversations.filter((item) => item.id !== id);
    if (state.activeConversationId === id) {
      state.activeConversationId = '';
      state.messages = [];
      const next = state.conversations[0];
      if (next) openConversation(next.id);
      else createConversation(state.activeProjectId);
    }
    saveWorkspace();
    renderChatWorkspace();
  }

  function renderChatWorkspace() {
    if (!elements.projectsList || !elements.historyList) return;
    elements.projectsList.replaceChildren();
    if (!state.projects.length) {
      elements.projectsList.append(createElement('div', 'sidebar-chat-empty', 'Нет проектов'));
    }
    state.projects.forEach((project) => {
      const row = createElement('div', 'chat-tree-item chat-tree-project' + (state.activeProjectId === project.id ? ' active' : ''));
      const label = createElement('button', 'chat-tree-project-label', '');
      label.type = 'button';
      label.title = project.name || 'Без названия';
      label.dataset.projectToggle = project.id;
      label.setAttribute('aria-expanded', String(!!project.expanded));
      label.innerHTML = '<span class="chat-tree-chevron" aria-hidden="true">' + (project.expanded ? '▾' : '▸') + '</span><img class="chat-tree-folder" src="/icons/folder.svg" alt="">';
      label.append(createElement('span', 'chat-title', project.name || 'Без названия'));
      label.addEventListener('click', () => {
        project.expanded = !project.expanded;
        state.activeProjectId = project.id;
        saveWorkspace();
        renderChatWorkspace();
      });
      const add = createElement('button', 'icon-btn chat-tree-action', '');
      add.type = 'button'; add.title = 'Создать чат в проекте'; add.setAttribute('aria-label', 'Создать чат в проекте ' + (project.name || ''));
      add.innerHTML = '<img src="/icons/start.svg" alt="+">';
      add.onclick = (event) => { event.stopPropagation(); createConversation(project.id); };
      const remove = createElement('button', 'icon-btn chat-tree-action danger', '');
      remove.type = 'button'; remove.title = 'Убрать из чата'; remove.setAttribute('aria-label', 'Убрать из чата ' + (project.name || ''));
      remove.innerHTML = '<img src="/icons/remove.svg" alt="×">';
      remove.onclick = (event) => {
        event.stopPropagation();
        if (!window.confirm('Убрать проект «' + (project.name || 'Без названия') + '» из чата? Чаты останутся в истории без привязки к проекту.')) return;
        state.projects = state.projects.filter(item => item.id !== project.id);
        state.conversations.forEach(item => { if (item.projectId === project.id) item.projectId = ''; });
        if (state.activeProjectId === project.id) state.activeProjectId = '';
        saveWorkspace();
        renderChatWorkspace();
      };
      row.append(label, add, remove);
      elements.projectsList.append(row);
      if (project.expanded) {
        const nested = createElement('div', 'sidebar-chat-project-chats');
        state.conversations.filter(chat => chat.projectId === project.id).sort((a,b)=>(b.updatedAt||'').localeCompare(a.updatedAt||'')).forEach(chat => nested.append(makeConversationRow(chat)));
        if (!nested.childElementCount) nested.append(createElement('div', 'sidebar-chat-empty', 'Пока нет чатов'));
        elements.projectsList.append(nested);
      }
    });

    elements.historyList.replaceChildren();
    const ungrouped = state.conversations.filter(chat => !chat.projectId).sort((a,b)=>(b.updatedAt||'').localeCompare(a.updatedAt||''));
    if (!ungrouped.length) elements.historyList.append(createElement('div', 'sidebar-chat-empty', 'Новые диалоги появятся здесь.'));
    ungrouped.forEach(chat => elements.historyList.append(makeConversationRow(chat)));
  }

  function makeConversationRow(chat) {
    const row = createElement('div', 'chat-tree-item chat-tree-conversation' + (chat.id === state.activeConversationId ? ' active' : ''));
    const label = createElement('button', 'chat-title chat-tree-conversation-title', chat.title || 'Новый чат');
    label.type = 'button'; label.title = chat.title || 'Новый чат';
    label.addEventListener('click', () => openConversation(chat.id));
    const actions = createElement('div', 'chat-tree-actions');
    const rename = createElement('button', 'icon-btn chat-tree-action', '');
    rename.type='button'; rename.title='Переименовать чат'; rename.setAttribute('aria-label','Переименовать чат');
    rename.innerHTML='<img src="/icons/edit.svg" alt="Переименовать">'; rename.onclick=()=>renameConversation(chat.id);
    const remove = createElement('button', 'icon-btn chat-tree-action danger', '');
    remove.type='button'; remove.title='Удалить чат'; remove.setAttribute('aria-label','Удалить чат');
    remove.innerHTML='<img src="/icons/remove.svg" alt="Удалить">'; remove.onclick=()=>{if(window.confirm('Удалить этот чат и его историю?'))deleteConversation(chat.id)};
    actions.append(rename, remove); row.append(label, actions);
    return row;
  }

  function clearNotice() {
    elements.messages.querySelectorAll('.notice').forEach((notice) => notice.remove());
  }

  function showNotice(message, type) {
    clearNotice();
    const notice = createElement('div', 'notice' + (type ? ' ' + type : ''), message);
    notice.setAttribute('role', 'alert');
    elements.messages.prepend(notice);
    scrollToBottom();
  }

  function formatTime(date) {
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
  }

  function scrollToBottom() {
    elements.messages.scrollTop = elements.messages.scrollHeight;
  }

  function renderMessage(message) {
    const isUser = message.role === 'user';
    const row = createElement('article', 'chat-msg ' + (isUser ? 'user' : 'bot'));
    const avatar = createElement('div', 'chat-msg-avatar', isUser ? 'Вы' : 'AI');
    avatar.setAttribute('aria-hidden', 'true');

    const content = createElement('div', 'chat-msg-content');
    const meta = createElement('div', 'chat-msg-meta');
    meta.append(
      createElement('span', 'chat-msg-name', isUser ? 'Вы' : 'Ассистент'),
      createElement('time', 'chat-msg-time', message.time || formatTime(new Date()))
    );

    const bubble = createElement('div', 'chat-msg-bubble', message.content);
    content.append(meta, bubble);
    if (!isUser && Array.isArray(message.tool_calls) && message.tool_calls.length) {
      const toolsDiv = createElement('div', 'chat-tool-calls');
      message.tool_calls.forEach((tc) => {
        if (!tc || typeof tc.name !== 'string') return;
        toolsDiv.append(createElement('span', 'chat-tool-badge', '🛠 ' + tc.name + (tc.status === 'error' ? ' · ошибка' : '')));
      });
      if (toolsDiv.childElementCount) content.append(toolsDiv);
    }
    row.append(avatar, content);
    elements.messages.append(row);
    scrollToBottom();
  }

  function renderHistory() {
    elements.messages.replaceChildren();
    if (!state.messages.length) {
      elements.messages.append(createElement('div', 'empty chat-empty', 'Начните диалог: задайте вопрос выбранному агенту.'));
      return;
    }
    state.messages.forEach(renderMessage);
  }

  function setSending(sending) {
    state.sending = sending;
    elements.send.disabled = sending || !state.agent;
    elements.input.disabled = sending || !state.agent;
    elements.agent.disabled = sending || !state.agents.length;
    elements.clear.disabled = sending;
    elements.send.textContent = sending ? 'Ожидайте…' : 'Отправить';
    elements.typing.hidden = !sending;
    if (sending) scrollToBottom();
  }

  function renderAgents() {
    elements.agent.replaceChildren();
    state.agents.sort((a,b) => { const rank = agent => (agent.id === 'manager' || agent.name === 'Агент №1') ? 0 : 1; return rank(a) - rank(b); });
    state.agents.forEach((agent) => {
      const option = document.createElement('option');
      option.value = agent.id;
      option.textContent = agent.name + (agent.model ? ' · ' + agent.model : ' · модель по умолчанию');
      elements.agent.append(option);
    });

    if (state.agent && state.agents.some((agent) => agent.id === state.agent)) {
      elements.agent.value = state.agent;
    } else {
      const preferred = state.agents.find((agent) => agent.id === 'manager' || agent.name === 'Агент №1');
      state.agent = preferred ? preferred.id : (state.agents.length ? state.agents[0].id : '');
      elements.agent.value = state.agent;
    }

    const selected = state.agents.find((agent) => agent.id === state.agent);
    elements.modelName.textContent = selected ? selected.name : 'Агент не выбран';
    updateCurrentAgentAvatar(selected);void updateModelAvailability(selected);
    elements.agent.disabled = !state.agents.length;
    elements.send.disabled = !state.agent;
    elements.input.disabled = !state.agent;
  }

  function adjustAvColor(col,amt){let num=parseInt(col.replace("#",""),16);if(isNaN(num))return "#142b3d";let r=(num>>16)+amt,b=((num>>8)&0xff)+amt,g=(num&0xff)+amt;return "#"+(0x1000000+(r<255?r<0?0:r:255)*0x10000+(b<255?b<0?0:b:255)*0x100+(g<255?g<0?0:g:255)).toString(16).slice(1)}
  function renderAvatar(s,opts){opts=opts||{};const size=opts.size||64,pulse=!!opts.pulse,blink=opts.blink!==false,talking=!!opts.talking,live=opts.live!==false;const accent=s.accent||"#3b9dff",bg2=adjustAvColor(accent,-40),bg3=adjustAvColor(accent,-60),radius=size>=100?"32px":size>=40?"11px":"8px";
  const headShapes={round:'<circle cx="32" cy="32" r="17"/>',square:'<rect x="15" y="15" width="34" height="34" rx="9"/>',hex:'<path d="M32 14 L48 23 L48 41 L32 50 L16 41 L16 23 Z"/>',squircle:'<rect x="15" y="15" width="34" height="34" rx="14"/>',drop:'<path d="M32 13 Q47 13 47 28 Q47 43 32 50 Q17 43 17 28 Q17 13 32 13 Z"/>'};
  const eyes={dots:'<circle cx="25" cy="30" r="2.2" fill="'+s.eyesColor+'"/><circle cx="39" cy="30" r="2.2" fill="'+s.eyesColor+'"/>',wide:'<ellipse cx="25" cy="30" rx="3.5" ry="4" fill="#fff"/><ellipse cx="39" cy="30" rx="3.5" ry="4" fill="#fff"/><circle cx="25" cy="30.5" r="1.8" fill="'+s.eyesColor+'"/><circle cx="39" cy="30.5" r="1.8" fill="'+s.eyesColor+'"/>',line:'<path d="M22 30h6M36 30h6" stroke="'+s.eyesColor+'" stroke-width="2.2" stroke-linecap="round" fill="none"/>',anime:'<ellipse cx="25" cy="30" rx="3.5" ry="4.5" fill="#fff"/><ellipse cx="39" cy="30" rx="3.5" ry="4.5" fill="#fff"/><circle cx="25.5" cy="31" r="2.2" fill="'+s.eyesColor+'"/><circle cx="39.5" cy="31" r="2.2" fill="'+s.eyesColor+'"/><circle cx="26.2" cy="29.8" r=".9" fill="#fff"/><circle cx="40.2" cy="29.8" r=".9" fill="#fff"/>',visor:'<rect x="17" y="26" width="30" height="8" rx="4" fill="#111" opacity=".9"/><path d="M19 30h26" stroke="'+s.eyesColor+'" stroke-width="2" stroke-linecap="round" stroke-dasharray="3 2"/>'};
  const mouths={smile:'<path d="M26 39q6 5 12 0" stroke="'+s.mouthColor+'" stroke-width="2" stroke-linecap="round" fill="none"/>',line:'<path d="M27 40h10" stroke="'+s.mouthColor+'" stroke-width="2" stroke-linecap="round"/>',open:'<ellipse cx="32" cy="40" rx="3.5" ry="2.5" fill="'+s.mouthColor+'"/><ellipse cx="32" cy="41" rx="2" ry="1.2" fill="#e06b6b"/>',smirk:'<path d="M26 40q6 2 12 -2" stroke="'+s.mouthColor+'" stroke-width="2" stroke-linecap="round" fill="none"/>',grin:'<path d="M25 38 q7 6 14 0" fill="none" stroke="'+s.mouthColor+'" stroke-width="2" stroke-linecap="round"/><path d="M27 39 h10" stroke="#fff" stroke-width="1.5"/>'};
  const hairShapes={none:"",punk:'<path d="M14 21 L20 8 L24 18 L28 6 L32 16 L36 6 L40 18 L44 8 L50 21 Q44 16 32 16 Q20 16 14 21Z" fill="'+s.hairColor+'"/>',short:'<path d="M15 22 Q16 11 32 11 Q48 11 49 22 Q44 16 32 16 Q20 16 15 22Z" fill="'+s.hairColor+'"/>',long:'<path d="M14 22 Q14 9 32 9 Q50 9 50 22 L50 44 Q46 42 45 34 L45 22 Q43 16 32 16 Q21 16 19 22 L19 34 Q18 42 14 44Z" fill="'+s.hairColor+'"/>',mohawk:'<path d="M28 8 L32 2 L36 8 L38 5 L38 18 L26 18 L26 5 Z" fill="'+s.hairColor+'"/>',bun:'<circle cx="32" cy="8" r="6" fill="'+s.hairColor+'"/><path d="M15 22 Q16 12 32 12 Q48 12 49 22 Q44 16 32 16 Q20 16 15 22Z" fill="'+s.hairColor+'"/>',afro:'<circle cx="32" cy="18" r="15" fill="'+s.hairColor+'"/><circle cx="18" cy="22" r="9" fill="'+s.hairColor+'"/><circle cx="46" cy="22" r="9" fill="'+s.hairColor+'"/>'};
  const clothesShapes={hoodie:'<path d="M14 64 C14 47 18 45 32 45 C46 45 50 47 50 64 Z" fill="'+s.clothesColor+'"/><path d="M24 45 Q32 53 40 45" fill="none" stroke="#10131d" stroke-width="1.5"/>',jacket:'<path d="M14 64 C14 47 18 45 32 45 C46 45 50 47 50 64 Z" fill="'+s.clothesColor+'"/><path d="M32 45 L32 64" stroke="#10131d" stroke-width="2"/><path d="M21 47 L29 54 M43 47 L35 54" stroke="#10131d" stroke-width="1.5"/>',uniform:'<path d="M14 64 C14 47 18 45 32 45 C46 45 50 47 50 64 Z" fill="'+s.clothesColor+'"/><rect x="23" y="48" width="18" height="4" rx="1" fill="#fff" opacity=".5"/>',tshirt:'<path d="M14 64 C14 47 18 45 32 45 C46 45 50 47 50 64 Z" fill="'+s.clothesColor+'"/>'};
  const accessories={none:"",glasses:'<g fill="none" stroke="'+s.accessoryColor+'" stroke-width="2"><rect x="18" y="26" width="11" height="8" rx="2.5"/><rect x="35" y="26" width="11" height="8" rx="2.5"/><path d="M29 29h6"/></g>',headphones:'<g fill="'+s.accessoryColor+'"><rect x="10" y="24" width="5" height="14" rx="2.5"/><rect x="49" y="24" width="5" height="14" rx="2.5"/><path d="M12 26 Q12 10 32 10 Q52 10 52 26" fill="none" stroke="'+s.accessoryColor+'" stroke-width="3.5" stroke-linecap="round"/></g>',crown:'<path d="M19 16 L23 6 L28 14 L32 4 L36 14 L41 6 L45 16 Z" fill="'+s.accessoryColor+'" stroke="#a88024" stroke-width="1"/><circle cx="23" cy="14" r="1" fill="#ff5f56"/><circle cx="32" cy="12" r="1" fill="#5eead4"/><circle cx="41" cy="14" r="1" fill="#ff5f56"/>',halo:'<ellipse cx="32" cy="8" rx="14" ry="3.5" fill="none" stroke="'+s.accessoryColor+'" stroke-width="2.5"/>',mask:'<path d="M20 32 Q32 28 44 32 L44 41 Q32 47 20 41 Z" fill="#151722" opacity=".95"/><path d="M24 36h16" stroke="'+s.accessoryColor+'" stroke-width="1.5" stroke-dasharray="2 2"/>',antenna:'<line x1="32" y1="14" x2="32" y2="3" stroke="'+s.accessoryColor+'" stroke-width="2"/><circle cx="32" cy="3" r="3" fill="'+s.accessoryColor+'"/>'};
  const pulseClass=pulse?" av-pulse":"",talkingClass=talking?" av-talking":"",liveClass=live?" av-live":"",blinkAttr=blink?"":' style="animation:none"';
  return '<div class="av'+pulseClass+talkingClass+liveClass+'" style="--av-bg:'+accent+';--av-bg2:'+bg2+';--av-bg3:'+bg3+';width:'+size+'px;height:'+size+'px;border-radius:'+radius+'"><div class="av-bg '+s.bg+'"></div>'+(s.pattern!=="none"?'<div class="av-pattern '+s.pattern+'"></div>':"")+'<div class="av-person-wrap"><svg class="av-person" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg"><g class="av-body">'+(clothesShapes[s.clothes]||clothesShapes.hoodie)+'</g><rect x="28" y="40" width="8" height="6" fill="'+s.skin+'" opacity=".85"/><g class="av-head" fill="'+s.skin+'">'+(headShapes[s.head]||headShapes.round)+'</g><g class="av-hair">'+(hairShapes[s.hair]||"")+'</g><g class="av-eye"'+blinkAttr+'>'+(eyes[s.eyes]||eyes.dots)+'</g><g class="av-mouth">'+(mouths[s.mouth]||mouths.smile)+'</g><g class="av-acc">'+(accessories[s.accessory]||"")+'</g><ellipse cx="23" cy="21" rx="4" ry="2.5" fill="#fff" opacity=".15"/></svg></div>'+(talking?'<div class="av-sound"><span></span><span></span><span></span></div>':"")+'</div>'}

  function updateCurrentAgentAvatar(agent) {
    const avatar = document.getElementById('chat-current-agent-avatar');
    if (!avatar) return;
    avatar.replaceChildren();
    let config = null;
    try { config = typeof agent?.avatar === 'string' ? JSON.parse(agent.avatar) : agent?.avatar; } catch (_) {}
    if (config && typeof config === 'object') {
      avatar.innerHTML = renderAvatar(config, { size: 36, live: false, blink: false });
      avatar.classList.add('has-agent-avatar');
    } else {
      avatar.classList.remove('has-agent-avatar');
      avatar.textContent = agent ? String(agent.name || 'AI').trim().slice(0, 2).toUpperCase() : 'AI';
      avatar.style.setProperty('--agent-avatar-accent', '#3b9dff');
    }
    avatar.title = agent ? agent.name : 'Агент не выбран';
  }


  window.PQOnAgentSaved = async () => {
    try {
      const data = await chatApi('/agents', { method: 'GET', cache: 'no-store' });
      state.agents = Array.isArray(data.items) ? data.items : [];
      renderAgents();
      const selected = state.agents.find(agent => agent.id === state.agent);
      if (selected) {
        elements.modelName.textContent = selected.name || 'Агент не выбран';
        updateCurrentAgentAvatar(selected);
      }
    } catch (_) {}
  };

  async function updateModelAvailability(agent) {
    if(!elements.availability)return;elements.availability.classList.remove('is-available','is-unavailable');elements.availability.classList.add('is-unavailable');
    if(!agent||!agent.model){elements.availability.title='У агента не назначена модель';elements.availability.setAttribute('aria-label','Модель не назначена');return}
    try{const [modelsResult,providersResult]=await Promise.all([chatApi('/models',{cache:'no-store'}),chatApi('/providers',{cache:'no-store'})]);const found=(modelsResult.models||[]).some(m=>m.name===agent.model)||(providersResult.models||[]).some(m=>m.name===agent.model&&m.connected);state.modelAvailable=!!found;elements.availability.classList.toggle('is-available',!!found);elements.availability.classList.toggle('is-unavailable',!found);elements.availability.title=found?'Модель доступна':'Модель не найдена или провайдер недоступен';elements.availability.setAttribute('aria-label',found?'Модель доступна':'Модель недоступна')}catch(_){state.modelAvailable=false;elements.availability.title='Не удалось проверить доступность модели';elements.availability.setAttribute('aria-label','Доступность модели не подтверждена')}
  }

  async function loadAgents() {
    try {
      const data = await chatApi('/agents', { method: 'GET', cache: 'no-store' });
      state.agents = Array.isArray(data.items)
        ? data.items.filter((agent) => agent && typeof agent.id === 'string' && typeof agent.name === 'string')
        : [];
      const urlParams = new URLSearchParams(window.location.search);
      const requestedAgentId = urlParams.get('agent_id');
      if (requestedAgentId && state.agents.some((agent) => agent.id === requestedAgentId)) {
        state.agent = requestedAgentId;
        if (elements.agent) elements.agent.value = requestedAgentId;
      }
      renderAgents();
      if (!state.agents.length) {
        showNotice('Нет доступных агентов. Создайте или настройте агента в разделе «AI-агенты».', 'warning');
      } else {
        clearNotice();
      }
    } catch (error) {
      state.agents = [];
      state.agent = '';
      renderAgents();
      showNotice(error.message || 'Не удалось загрузить список агентов.', 'warning');
    }
  }

  function saveEventConversation() {
    const conversation = activeConversation();
    if (!conversation) return;
    conversation.messages = state.messages;
    conversation.agentId = state.agent;
    conversation.updatedAt = new Date().toISOString();
    const firstUser = state.messages.find(message => message.role === 'user');
    if (firstUser && (!conversation.title || conversation.title === 'Новый чат')) {
      conversation.title = firstUser.content.trim().replace(/\\s+/g, ' ').split(' ').slice(0, 3).join(' ').slice(0, 48) || 'Новый чат';
    }
    saveWorkspace(); renderChatWorkspace();
    void syncProjectChatMemory(conversation);
  }

  function handleChatEvent(event, replay = false) {
    const payload = event.payload || {};
    if (state.renderer) state.renderer.apply(event);
    if (event.type === 'user_message') {
      const commandId = payload.command_id || '';
      if (!state.messages.some(message => commandId && message.commandId === commandId)) {
        state.messages.push({ role: 'user', content: String(payload.text || ''), commandId, eventId: event.event_id, time: formatTime(new Date(event.created_at || Date.now())) });
      }
    } else if (event.type === 'assistant_delta') {
      let message = state.messages.find(item => item.messageId === event.message_id);
      if (!message) {
        message = { role: 'assistant', content: '', messageId: event.message_id, time: formatTime(new Date(event.created_at || Date.now())) };
        state.messages.push(message);
      }
      message.content += String(payload.text || '');
    } else if (event.type === 'assistant_message') {
      let message = state.messages.find(item => item.messageId === event.message_id);
      if (!message) {
        message = { role: 'assistant', content: '', messageId: event.message_id, time: formatTime(new Date(event.created_at || Date.now())) };
        state.messages.push(message);
      }
      message.content = String(payload.content || '');
      if (Array.isArray(payload.tool_calls)) message.tool_calls = payload.tool_calls.map(call => ({ name: call?.function?.name || call?.name || 'Инструмент', id: call?.id || '' }));
    } else if (event.type === 'tool_call') {
      const message = [...state.messages].reverse().find(item => item.role === 'assistant');
      if (message) {
        message.tool_calls = Array.isArray(message.tool_calls) ? message.tool_calls : [];
        if (!message.tool_calls.some(item => item.id === event.tool_call_id)) message.tool_calls.push({ id: event.tool_call_id, name: payload.name || 'Инструмент', status: 'running' });
      }
    } else if (event.type === 'tool_result') {
      for (const message of state.messages) {
        for (const call of message.tool_calls || []) if (call.id === event.tool_call_id) call.status = payload.error ? 'error' : 'completed';
      }
    } else if (event.type === 'error') {
      if (payload.code === 'verification_required') { setSending(false); elements.input?.focus(); }
      showNotice(payload.message || 'Ошибка выполнения агента.', 'warning');
    } else if (event.type === 'turn_completed' || event.type === 'turn_cancelled') {
      setSending(false); if (!replay) saveEventConversation(); elements.input?.focus();
    }
    if (!replay && event.type !== 'assistant_delta') saveWorkspace();
  }

  async function setupEventTransport(conversation) {
    if (!conversation) throw new Error('Не выбран диалог.');
    if (!conversation.serverConversationId) {
      const created = await chatApi('/chat/conversations', { method: 'POST', body: JSON.stringify({ title: conversation.title || 'Новый чат' }) });
      conversation.serverConversationId = created.conversation_id;
      const legacyMessages = Array.isArray(state.messages) ? state.messages.slice() : [];
      if (legacyMessages.length) {
        await chatApi('/chat/import', { method: 'POST', body: JSON.stringify({ conversation_id: conversation.serverConversationId, messages: legacyMessages.map(message => ({ role: message.role, content: String(message.content || '') })) }) });
      }
      saveWorkspace();
    }
    if (state.transport && state.transportConversationId === conversation.serverConversationId) return state.transport;
    state.transport?.close();
    const [{ ChatTransport }, { ChatRenderer }] = await Promise.all([
      import('/chat-transport.js'), import('/chat-renderer.js')
    ]);
    elements.messages.replaceChildren();
    state.messages = [];
    state.renderer = new ChatRenderer(elements.messages);
    const activityEl = document.getElementById('chat-activity');
    if (activityEl) { activityEl.hidden = true; activityEl.dataset.state = ''; }
    const transport = new ChatTransport({
      conversationId: conversation.serverConversationId,
      onEvent: event => handleChatEvent(event, false),
      onStatus: status => {
        const statusNode = document.getElementById('chat-task-status');
        if (!statusNode) return;
        if (status === 'sequence_gap') setChatHeaderStatus('Восстанавливаю пропущенные события…', 'warning');
        else if (status === 'reconnecting') setChatHeaderStatus('Переподключение…', 'running');
        else if (status === 'connected' && /^(Переподключение…|Восстанавливаю пропущенные события…)$/.test(statusNode.textContent)) setChatHeaderStatus('', null);
      }
    });
    const history = await transport.loadHistory(0);
    state.renderer.reset();
    state.messages = [];
    for (const event of (history.events || [])) handleChatEvent(event, true);
    const lastSequence = (history.events || []).reduce((max, event) => Math.max(max, Number(event.sequence) || 0), 0);
    state.transport = transport; state.transportConversationId = conversation.serverConversationId; window.PQChatTransport = transport;
    transport.connect({ lastSequence, epoch: history.meta?.epoch ?? null });
    if (activeConversation()?.id === conversation.id) {
      conversation.messages = state.messages; conversation.agentId = state.agent;
    }
    saveWorkspace();
    return transport;
  }

  async function restoreEventConversation() {
    const conversation = activeConversation();
    if (!conversation?.serverConversationId) return;
    try { await setupEventTransport(conversation); }
    catch (error) { showNotice('Не удалось восстановить историю событий: ' + error.message, 'warning'); }
  }

  async function sendMessage() {
    const content = elements.input.value.trim();
    if (!content || state.sending || !state.agent) return;
    clearNotice();
    setSending(true);
    elements.input.value = ''; resizeInput();
    try {
      const conversation = activeConversation();
      const transport = await setupEventTransport(conversation);
      const commandId = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : ('cmd-' + Date.now() + '-' + Math.random().toString(16).slice(2));
      await transport.sendMessage(content, commandId, state.agent, conversation?.projectId || '');
    } catch (error) {
      setSending(false);
      showNotice(error.message || 'Не удалось отправить сообщение.', 'warning');
      elements.input.value = content; resizeInput();
    } finally {
      elements.input.focus();
    }
  }

  function resizeInput() {
    elements.input.style.height = 'auto';
    elements.input.style.height = Math.min(elements.input.scrollHeight, 200) + 'px';
  }

  function clearChat() {
    if (state.sending) return;
    state.transport?.close(); state.transport = null; state.renderer = null; state.transportConversationId = ''; window.PQChatTransport = null;
    const conversation = activeConversation();
    if (conversation) conversation.serverConversationId = '';
    state.messages = [];
    persistActiveConversation();
    clearNotice();
    renderHistory();
    elements.input.value = '';
    resizeInput();
    elements.input.focus();
  }

  function bindEvents() {
    elements.form.addEventListener('submit', (event) => {
      event.preventDefault();
      sendMessage();
    });
    elements.input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        sendMessage();
      }
    });
    elements.input.addEventListener('input', resizeInput);
    elements.agent.addEventListener('change', () => {
      state.agent = elements.agent.value;
      const selected = state.agents.find((agent) => agent.id === state.agent);
      elements.modelName.textContent = selected ? selected.name : 'Агент не выбран';
      updateCurrentAgentAvatar(selected);void updateModelAvailability(selected);
      elements.send.disabled = state.sending || !state.agent; elements.input.disabled = state.sending || !state.agent; persistActiveConversation();
    });
    elements.clear.addEventListener('click', clearChat);
  }


  function bindShellEvents() {
    const shell = document.querySelector('.app-shell');
    const left = document.getElementById('toggle-left-panel');
    const right = document.getElementById('toggle-right-panel');
    if (!shell) return;

    if (left) {
      left.addEventListener('click', () => {
        shell.classList.toggle('left-hidden');
        left.setAttribute('aria-expanded', String(!shell.classList.contains('left-hidden')));
      });
    }
    if (right) {
      right.addEventListener('click', () => {
        shell.classList.toggle('right-hidden');
        right.setAttribute('aria-expanded', String(!shell.classList.contains('right-hidden')));
      });
    }
  }

  async function applySidebarWidthFromApi() {
    let panelWidth = 322;
    try {
      const settings = await chatApi('/settings');
      const configuredWidth = Number(settings?.appearance?.sidebarWidth);
      if (Number.isFinite(configuredWidth) && configuredWidth > 0) panelWidth = Math.round(configuredWidth);
    } catch (_) {
      // Keep the shared 322px default if settings cannot be loaded.
    }
    const root = document.documentElement;
    if (window.matchMedia('(max-width:720px)').matches) {
      root.style.removeProperty('--sidebar');
      root.style.removeProperty('--right-sidebar');
      return;
    }
    root.style.setProperty('--sidebar', panelWidth + 'px');
    root.style.setProperty('--right-sidebar', panelWidth + 'px');
  }

  async function init() {
    const content = document.getElementById('content');
    if (!content || document.getElementById('chat-root')) return;
    readWorkspace();
    try{const projects=await chatApi('/projects',{cache:'no-store'});state.systemProjects=Array.isArray(projects.items)?projects.items:[];state.projects=state.systemProjects.map(p=>({id:p.id,name:p.name||'Без названия',createdAt:p.created_at||'',expanded:state.projects.find(old=>old.id===p.id)?.expanded??true}));saveWorkspace()}catch(_){/* use cached project list */}
    try{const settings=await chatApi('/settings',{cache:'no-store'});state.iconSettings=settings.icons||{}}catch(_){state.iconSettings={}}
    buildUI();
    bindShellEvents();
    bindEvents();
    renderChatWorkspace();
    void applySidebarWidthFromApi();
    const chatSidebarWidthMediaQuery = window.matchMedia('(max-width:720px)');
    chatSidebarWidthMediaQuery.addEventListener('change', () => { void applySidebarWidthFromApi(); });
    const existing = state.conversations.find((item) => item.id === state.activeConversationId);
    if (existing) {
      state.messages = Array.isArray(existing.messages) ? existing.messages.slice() : [];
      state.agent = existing.agentId || '';
    } else {
      createConversation('');
    }
    renderHistory();
    const migratedProjects=[...new Set(state.conversations.map(chat=>chat.projectId).filter(Boolean))];migratedProjects.forEach(projectId=>{const conversation=state.conversations.find(chat=>chat.projectId===projectId);if(conversation)void syncProjectChatMemory(conversation)});
    loadAgents();
    void restoreEventConversation();
  }

  if (window.PQDomainModal?.configure) {
    window.PQDomainModal.configure({
      getState: () => ({ agents: state.agents, models: state.models || { models: [] }, projects: [], tasks: [] }),
      api: chatApi,
      esc: value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char])),
      toast: message => showNotice(message, 'info'),
      refresh: async () => {}
    });
  }

  window.ChatPage = { init };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();