/* Рендерер событий чата. Не вставляет данные модели через innerHTML. */
export class ChatRenderer {
  constructor(container) {
    this.container=container; this.nodes=new Map(); this.seen=new Set();
    this.status=document.getElementById('chat-task-status');
    container?.addEventListener('click',async event=>{
      const button=event.target.closest('[data-approval-decision]'); if(!button)return;
      const card=button.closest('[data-approval-id]'); if(!card)return;
      button.disabled=true;
      try {
        const transport=window.PQChatTransport;
        if(!transport)throw new Error('Транспорт чата не подключён');
        await transport.approveTool(card.dataset.approvalId,button.dataset.approvalDecision);
      } catch(error) {
        let note=card.querySelector('.chat-approval-error');
        if(!note){note=document.createElement('p');note.className='chat-approval-error';card.append(note);}
        note.textContent=error.message;button.disabled=false;
      }
    });
  }
  reset(){this.container.replaceChildren();this.nodes.clear();this.seen.clear();}
  _el(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=String(text);return el;}
  applyMany(events){for(const event of events||[])this.apply(event);}
  apply(event){
    if(!event||typeof event!=='object'||!event.event_id||this.seen.has(event.event_id))return;
    this.updateActivity(event);
    this.seen.add(event.event_id);const p=event.payload||{};
    switch(event.type){
      case 'user_message':this._message('user',p.text||'',event);break;
      case 'assistant_delta':this._assistantDelta(event.message_id,p.text||'');break;
      case 'assistant_message':this._assistantFinal(event.message_id,p.content||'');break;
      case 'thinking':this._status('Думает…');break;
      case 'turn_state':this._status(({thinking:'Думает…',streaming:'Генерирует ответ…',waiting_approval:'Ожидает подтверждения',idle:'Готово'})[p.state]||p.state||'');break;
      case 'tool_call':this._toolCall(event.tool_call_id,p);break;
      case 'tool_result':this._toolResult(event.tool_call_id,p);break;
      case 'approval_required':this._approval(p);break;
      case 'approval_resolved':this._approvalResolved(p);break;
      case 'error':this.container.append(this._el('div','chat-event-error',p.message||'Ошибка агента'));break;
      case 'turn_completed':this._status('');window.dispatchEvent(new CustomEvent('pq-chat-turn-completed',{detail:event}));break;
      case 'turn_cancelled':this._status('');window.dispatchEvent(new CustomEvent('pq-chat-turn-cancelled',{detail:event}));break;
    }
  }
  _message(role,text,event){
    const row=this._el('article','chat-msg '+(role==='user'?'user':'bot'));row.dataset.eventId=event.event_id;
    row.append(this._el('div','chat-msg-avatar',role==='user'?'Вы':'AI'));
    const content=this._el('div','chat-msg-content'),meta=this._el('div','chat-msg-meta');
    meta.append(this._el('span','chat-msg-name',role==='user'?'Вы':'Ассистент'));
    const time=this._el('time','chat-msg-time',event.created_at?new Date(event.created_at).toLocaleTimeString():'');
    meta.append(time);const bubble=this._el('div','chat-msg-bubble',text);content.append(meta,bubble);row.append(content);
    this.container.append(row);this._scroll();
  }
  _assistantDelta(id,text){
    if(!id)return;let node=this.nodes.get(id);
    if(!node){this._message('assistant','',{event_id:'assistant-'+id});node=this.container.lastElementChild;node.dataset.messageId=id;this.nodes.set(id,node);}
    const bubble=node.querySelector('.chat-msg-bubble');bubble.textContent+=text;this._scroll();
  }
  _assistantFinal(id,text){
    if(!id)return;let node=this.nodes.get(id);
    if(!node){this._assistantDelta(id,'');node=this.nodes.get(id);}
    node.querySelector('.chat-msg-bubble').textContent=text;this._scroll();
  }
  _toolCall(id,p){
    const row=this.nodes.size?[...this.nodes.values()].at(-1):null;
    const parent=row?.querySelector('.chat-msg-content')||this.container;
    let list=parent.querySelector('.chat-tool-calls');
    if(!list){list=this._el('div','chat-tool-calls');parent.append(list);}
    const card=this._el('section','chat-tool-card');card.dataset.toolCallId=id||'';
    card.append(this._el('span','chat-tool-badge','Инструмент: '+(p.name||'неизвестно')));
    card.append(this._el('pre','',JSON.stringify(p.arguments||{},null,2)));list.append(card);this._scroll();
  }
  _toolResult(id,p){
    const card=[...this.container.querySelectorAll('[data-tool-call-id]')].find(el=>el.dataset.toolCallId===id);
    if(card)card.append(this._el('pre','chat-tool-result',p.result??p.message??p.error??'Готово'));
  }
  _approval(p){
    const card=this._el('section','chat-approval-card');card.dataset.approvalId=p.approval_id||'';
    card.append(this._el('p','',p.description||'Требуется подтверждение: '+(p.tool_name||'инструмент')));
    for(const [decision,label] of [['approved','Разрешить'],['rejected','Отклонить']]){
      const button=this._el('button','btn secondary',label);button.type='button';button.dataset.approvalDecision=decision;card.append(button);
    }
    this.container.append(card);this._scroll();
  }
  _approvalResolved(p){
    const card=[...this.container.querySelectorAll('[data-approval-id]')].find(el=>el.dataset.approvalId===p.approval_id);
    if(card){card.append(this._el('p','',p.decision==='approved'?'Разрешено':'Отклонено'));card.querySelectorAll('button').forEach(button=>button.disabled=true);}
  }
  _status(text){if(this.status)this.status.textContent=text;}
  _scroll(){this.container.scrollTop=this.container.scrollHeight;}
  updateActivity(event) {
    const el = document.getElementById("chat-activity");
    if (!el) return;
    const label = document.getElementById("chat-activity-label");
    const detail = document.getElementById("chat-activity-detail");
    if (!label || !detail) return;

    const type = event.type;
    const payload = event.payload || {};

    const show = (state, text, detailText) => {
      el.hidden = false;
      el.dataset.state = state;
      label.textContent = text;
      detail.textContent = detailText || "";
    };
    const hide = () => {
      el.hidden = true;
      el.dataset.state = "";
      label.textContent = "";
      detail.textContent = "";
    };

    switch (type) {
      case "turn_state": {
        const s = payload.state || payload.status || "";
        if (s === "thinking") show("thinking", "Думает…", "");
        else if (s === "streaming") show("streaming", "Печатает…", "");
        else if (s === "tool_running") show("tool", "Выполняет инструмент…", "");
        else if (s === "waiting_approval") show("approval", "Ждёт подтверждения", "");
        else if (s === "idle") hide();
        break;
      }
      case "assistant_delta":
        show("streaming", "Печатает…", "");
        break;
      case "tool_call": {
        const name = payload.name || payload.tool_name || "tool";
        const args = payload.arguments ? JSON.stringify(payload.arguments).slice(0, 80) : "";
        show("tool", "Инструмент: " + name, args);
        break;
      }
      case "tool_result": {
        const status = payload.status || "done";
        if (status === "denied") show("failed", "Отклонено", "allowed_paths");
        else show("tool", "Результат получен", "");
        break;
      }
      case "approval_required":
        show("approval", "Ждёт вашего подтверждения", payload.tool_name || "");
        break;
      case "approval_resolved":
        show("tool", "Подтверждение принято", payload.decision || "");
        break;
      case "verification": {
        const ok = payload.verified;
        show(ok ? "completed" : "failed", ok ? "Проверено" : "Проверка не пройдена", "");
        break;
      }
      case "turn_completed": {
        const ok = (payload.status || "success") === "success";
        show(ok ? "completed" : "failed", ok ? "Готово" : "Не завершено", "");
        // авто-скрытие через 3 сек
        setTimeout(() => { if (el.dataset.state === "completed") hide(); }, 3000);
        break;
      }
      case "turn_cancelled":
        show("failed", "Отменено", "");
        setTimeout(hide, 3000);
        break;
      case "error":
        show("failed", "Ошибка", payload.message || "");
        break;
    }
  }

}
