/* SSE transport; the server replays the durable journal after the supplied sequence. */
export class ChatTransport {
  constructor({conversationId,onEvent,onStatus}) {
    this.conversationId=conversationId; this.onEvent=onEvent; this.onStatus=onStatus;
    this.source=null; this.lastSequence=0; this.epoch=null; this.closed=true;
    this.retryDelay=1000; this.reconnectTimer=null;
  }
  connect({lastSequence=this.lastSequence,epoch=this.epoch}={}) {
    this.lastSequence=Number.isInteger(lastSequence)&&lastSequence>=0?lastSequence:0;
    this.epoch=epoch??null; this.closed=false; this.retryDelay=1000; this._open();
  }
  _open() {
    if(this.closed)return;
    const q=new URLSearchParams({conversation_id:this.conversationId,after:String(this.lastSequence)});
    const source=new EventSource('/api/chat/events?'+q); this.source=source;
    source.onopen=()=>{this.retryDelay=1000;this.onStatus?.('connected');};
    source.onmessage=(msg)=>{
      let event;
      try{event=JSON.parse(msg.data);}catch(_){this.onStatus?.('invalid_event');this._retry();return;}
      if(event.conversation_id!==this.conversationId){this.onStatus?.('invalid_conversation');this.close();return;}
      if(!Number.isInteger(event.sequence)||event.sequence<1){this.onStatus?.('invalid_sequence');this._retry();return;}
      if(this.epoch!==null&&event.epoch!==this.epoch){this.onStatus?.('epoch_changed');this.lastSequence=0;this.epoch=event.epoch;this._retry();return;}
      if(this.epoch===null)this.epoch=event.epoch;
      if(event.sequence<=this.lastSequence)return;
      if(event.sequence!==this.lastSequence+1){this.onStatus?.('sequence_gap');this._retry();return;}
      this.lastSequence=event.sequence;this.onEvent?.(event);
    };
    source.onerror=()=>{if(!this.closed){this.onStatus?.('reconnecting');this._retry();}};
  }
  _retry() {
    this.source?.close();this.source=null;if(this.closed)return;
    clearTimeout(this.reconnectTimer);const delay=this.retryDelay;
    this.retryDelay=Math.min(this.retryDelay*2,30000);
    this.reconnectTimer=setTimeout(()=>this._open(),delay);
  }
  async _post(path,payload) {
    const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation_id:this.conversationId,...payload})});
    let body={};try{body=await response.json();}catch(_){}
    if(!response.ok)throw new Error(body.error||'HTTP '+response.status);return body;
  }
  sendMessage(text,commandId=(window.crypto&&crypto.randomUUID?crypto.randomUUID():'cmd-'+Date.now()),agentId='',projectId=''){return this._post('/api/chat/send',{text,command_id:commandId,agent_id:agentId,project_id:projectId});}
  approveTool(approvalId,decision,commandId=crypto.randomUUID()){
    if(!['approved','rejected'].includes(decision))return Promise.reject(new Error('Недопустимое решение подтверждения'));
    return this._post('/api/chat/approve',{approval_id:approvalId,decision,command_id:commandId});
  }
  cancelTask(commandId=crypto.randomUUID()){return this._post('/api/chat/cancel',{command_id:commandId});}
  async loadHistory(after=0){
    const q=new URLSearchParams({conversation_id:this.conversationId,after:String(after)});
    const response=await fetch('/api/chat/history?'+q);
    if(!response.ok)throw new Error('Не удалось загрузить историю: HTTP '+response.status);
    return response.json();
  }
  close(){this.closed=true;clearTimeout(this.reconnectTimer);this.source?.close();this.source=null;}
}
