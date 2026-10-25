/* Local transcription jobs and independent, versioned correction drafts. */
import { createDatasetPanel } from "./datasets.js";
export function createTranscriptionWorkbench(callbacks) {
  const $=id=>document.getElementById(id);
  const state={visible:false,disposed:false,timer:null,pollToken:0,records:[],jobs:[],source:"",selected:null,
    saved:null,draft:null,base:null,dirty:false,epoch:0,request:0,loading:false,saving:false,conflict:false,stopAt:null};
  let datasetPanel=null;
  const kind={legacy:"原始转写",job:"任务识别",review:"校对副本"};
  const statuses={queued:"排队中",running:"运行中",succeeded:"已完成",failed:"失败",cancelled:"已取消",timed_out:"已超时",interrupted:"已中断"};
  const phases={loading:"加载本地模型",transcribing:"正在转写",publishing:"正在保存",cleanup_failed:"进程清理失败",cancelling:"取消中"};
  const validId=id=>typeof id==="string" && /^[0-9a-f]{32}$/.test(id);
  const validSource=name=>typeof name==="string" && /^[0-9a-f]{32}\.(wav|mp3|m4a|flac|ogg|webm)$/.test(name);
  const audioUrl=url=>typeof url==="string" && /^\/api\/voices\/[0-9a-f]{32}\.(wav|mp3|m4a|flac|ogg|webm)\/audio$/.test(url);
  const copy=value=>JSON.parse(JSON.stringify(value));
  const element=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=text;return node;};
  const draftFrom=doc=>({language:doc.transcript.language,segments:doc.transcript.segments.map(row=>({start:String(row.start),end:String(row.end),text:row.text}))});
  function stopAudio(){state.stopAt=null;$("transcript-audio").pause();}
  function validation(){
    if(!state.draft)return "";
    if(!/^[a-z]{2,3}$/.test(state.draft.language.trim()))return "请填写语言代码，例如 ja、zh 或 en。";
    if(!state.draft.segments.length)return "至少需要一个非空片段。";
    let previous=0;
    for(const [index,row] of state.draft.segments.entries()){
      const start=Number(row.start),end=Number(row.end);
      if(!row.start.trim() || !row.end.trim() || !Number.isFinite(start) || !Number.isFinite(end) || start<0 || end<=start || end>state.saved.transcript.duration+.01)
        return "第 "+(index+1)+" 段的起止时间无效或超出音频时长。";
      if(start<previous)return "第 "+(index+1)+" 段与上一段重叠或顺序不正确。";
      if(!row.text.trim())return "第 "+(index+1)+" 段的文字不能为空。";
      previous=end;
    }
    return "";
  }
  function sync(changed=false){
    if(changed)state.epoch+=1;
    state.dirty=Boolean(state.draft && JSON.stringify(state.draft)!==JSON.stringify(state.base));
    renderControls();
  }
  function renderControls(){
    const locked=callbacks.isBusy(),issue=validation();
    $("submit-transcription").disabled=locked || !validSource(state.source);
    $("transcribe-source").disabled=locked;$("transcribe-language").disabled=locked;
    $("refresh-transcriptions").disabled=locked;
    $("save-transcript").disabled=locked || state.loading || !state.saved || Boolean(issue) || (state.saved.editable && !state.dirty);
    $("save-transcript").textContent=state.saving?"正在保存…":state.saved?.editable?"保存校对修改":"保存校对副本";
    $("reload-transcript").disabled=locked || !state.saved;
    $("add-transcript-segment").disabled=state.loading || (locked && !state.saving) || !state.saved;
    $("review-language").disabled=state.loading || (locked && !state.saving);
    $("review-validation").textContent=state.conflict?"保存冲突：草稿已保留。请先复制需要的修改，再明确重新加载。":issue;
    $("transcript-draft").textContent=state.loading?"读取中…":state.dirty?"有未保存修改":state.saved?.editable?"已保存":"原始识别只读，保存为新副本";
    $("transcript-draft").className="draft-state"+(state.dirty?" dirty":"");
    $("transcript-loading").hidden=!state.loading;
    for(const control of $("transcript-segments").querySelectorAll("input,textarea"))control.disabled=state.loading || (locked && !state.saving);
    for(const button of $("transcription-record-list").querySelectorAll("button"))button.disabled=locked;
    for(const button of $("transcription-job-list").querySelectorAll("button"))button.disabled=locked;
    for(const button of $("transcript-segments").querySelectorAll("button"))button.disabled=state.loading || (locked && !state.saving) || (button.dataset.audio==="true" && !audioUrl(state.saved?.audio_url));
    datasetPanel?.renderControls();
  }
  function renderRecords(){
    const list=$("transcription-record-list");list.replaceChildren();
    for(const record of state.records){
      if(!validId(record.id))continue;
      const button=element("button","transcript-card"+(record.id===state.selected?" active":""));button.type="button";button.dataset.recordId=record.id;
      button.append(element("strong","",kind[record.kind]+" · "+record.language),element("span","small muted",record.text_preview || "（无文字）"),element("span","small muted",record.kind==="review"?"修订 "+record.revision:record.segment_count+" 个片段"));
      button.addEventListener("click",()=>openRecord(record.id));list.append(button);
    }
    $("transcription-records-empty").hidden=state.records.length>0;renderControls();
  }
  function renderJobs(){
    const list=$("transcription-job-list");list.replaceChildren();
    for(const job of state.jobs){
      if(!validId(job.id))continue;
      const card=element("article","transcription-job");card.dataset.jobId=job.id;
      const terminal=["succeeded","failed","cancelled","timed_out","interrupted"].includes(job.state);
      const label=job.decision && !terminal?"取消中":statuses[job.state] || "未知状态";
      card.append(element("strong","",label+" · "+job.id.slice(0,8)),element("p","small muted",phases[job.phase] || job.error_code || job.source_filename));
      if(!terminal){
        const cancel=element("button","quiet","取消转写");cancel.type="button";cancel.disabled=Boolean(job.decision);
        cancel.addEventListener("click",()=>cancelJob(job.id));card.append(cancel);
      }
      if(job.state==="succeeded" && validId(job.result_id)){
        const open=element("button","quiet","打开识别结果");open.type="button";open.addEventListener("click",()=>openRecord(job.result_id));card.append(open);
      }
      list.append(card);
    }
    $("transcription-jobs-empty").hidden=state.jobs.length>0;renderControls();
  }
  function renderRows(){
    const container=$("transcript-segments");container.replaceChildren();
    if(!state.draft)return;
    for(const [index,row] of state.draft.segments.entries()){
      const section=element("section","segment-row");section.dataset.segmentIndex=String(index);
      const heading=element("div","segment-heading"),actions=element("div","segment-actions");heading.append(element("strong","","片段 "+(index+1)));
      const action=(label,text,fn,audio=false)=>{const button=element("button","quiet",text);button.type="button";button.setAttribute("aria-label",label);if(audio)button.dataset.audio="true";button.addEventListener("click",fn);actions.append(button);};
      action("试听第"+(index+1)+"段","试听",()=>{
        if(!audioUrl(state.saved?.audio_url))return;
        const start=Number(row.start),end=Number(row.end);
        if(!Number.isFinite(start) || !Number.isFinite(end) || end<=start)return;
        const player=$("transcript-audio");player.currentTime=start;state.stopAt=end;player.play().catch(()=>callbacks.notice("浏览器未能播放片段，请使用播放器重试。",true));
      },true);
      const mutate=fn=>{stopAudio();fn();state.conflict=false;sync(true);renderRows();};
      action("上移第"+(index+1)+"段","上移",()=>{if(index>0)mutate(()=>[state.draft.segments[index-1],state.draft.segments[index]]=[row,state.draft.segments[index-1]]);});
      action("下移第"+(index+1)+"段","下移",()=>{if(index<state.draft.segments.length-1)mutate(()=>[state.draft.segments[index+1],state.draft.segments[index]]=[row,state.draft.segments[index+1]]);});
      action("删除第"+(index+1)+"段","删除",()=>mutate(()=>state.draft.segments.splice(index,1)));
      heading.append(actions);section.append(heading);
      const times=element("div","paired-fields");
      for(const [key,label] of [["start","开始秒"],["end","结束秒"]]){
        const wrapper=element("label","",label),input=element("input");input.type="number";input.min="0";input.step="any";input.value=row[key];input.setAttribute("aria-label","第"+(index+1)+"段"+label);
        input.addEventListener("input",()=>{row[key]=input.value;state.conflict=false;sync(true);});wrapper.append(input);times.append(wrapper);
      }
      const textLabel=element("label","","识别文字"),text=element("textarea");text.value=row.text;text.setAttribute("aria-label","第"+(index+1)+"段文字");text.maxLength=1048576;
      text.addEventListener("input",()=>{row.text=text.value;state.conflict=false;sync(true);});textLabel.append(text);section.append(times,textLabel);container.append(section);
    }
    renderControls();
  }
  function renderDocument(reset=true){
    const doc=state.saved;$("transcript-empty").hidden=Boolean(doc);$("transcript-detail").hidden=!doc;
    if(!doc)return;
    $("transcript-kind").textContent=kind[doc.kind];$("transcript-title").textContent=doc.editable?"校对副本 · 修订 "+doc.revision:"逐段校对";
    $("transcript-meta").textContent=doc.transcript.stored_filename+" · "+Number(doc.transcript.duration).toFixed(3)+" 秒";
    $("review-language").value=state.draft.language;
    const player=$("transcript-audio");stopAudio();
    if(audioUrl(doc.audio_url)){if(player.getAttribute("src")!==doc.audio_url)player.src=doc.audio_url;player.hidden=false;}
    else{player.removeAttribute("src");player.load();player.hidden=true;}
    $("transcript-audio-missing").hidden=audioUrl(doc.audio_url);renderRows();
  }
  async function openRecord(id,force=false){
    if(!validId(id) || callbacks.isBusy() || (!force && id===state.selected && !state.loading))return;
    if(state.dirty && !window.confirm("放弃尚未保存的转写修改？"))return;
    const token=++state.request;state.selected=id;state.loading=true;stopAudio();renderRecords();renderControls();
    try{
      const doc=await callbacks.api("/api/transcriptions/records/"+id);
      if(state.disposed || token!==state.request || id!==state.selected)return;
      state.saved=doc;state.draft=draftFrom(doc);state.base=copy(state.draft);state.conflict=false;state.epoch+=1;sync();renderDocument();callbacks.notice("转写已读取，可编辑并保存校对副本。");
    }catch(error){if(token===state.request){state.selected=state.saved?.id || null;renderRecords();callbacks.notice("转写读取失败："+error.message,true);}}
    finally{if(token===state.request){state.loading=false;renderControls();}}
  }
  async function refreshRecords(token=null){
    try{
      const data=await callbacks.api("/api/transcriptions/records");if(state.disposed || (token!==null && token!==state.pollToken))return;
      state.records=data.items;$("transcription-records-error").hidden=true;$("transcription-diagnostics").textContent=data.diagnostics.length?data.diagnostics.length+" 份异常或未知版本记录已保留，请检查本地文件。":"";renderRecords();
    }catch(error){if(!state.disposed)$("transcription-records-error").hidden=false;}
  }
  async function refreshJobs(token=null){
    try{
      const data=await callbacks.api("/api/transcriptions/jobs");if(state.disposed || (token!==null && token!==state.pollToken))return;
      const changed=JSON.stringify(data.items)!==JSON.stringify(state.jobs);state.jobs=data.items;$("transcription-jobs-error").hidden=true;renderJobs();
      if(changed)await refreshRecords(token);
    }catch(error){if(!state.disposed)$("transcription-jobs-error").hidden=false;}
  }
  async function refreshSources(){
    try{
      const data=await callbacks.api("/api/voices");if(state.disposed)return;
      const select=$("transcribe-source");select.replaceChildren(new Option("请选择音频",""));
      for(const asset of data.items)if(validSource(asset.stored_filename))select.add(new Option(asset.original_filename,asset.stored_filename));
      select.value=state.source;renderControls();
    }catch(error){callbacks.notice("音频列表读取失败，请刷新转写重试。",true);}
  }
  async function refresh(){await Promise.allSettled([refreshSources(),refreshRecords(),refreshJobs(),datasetPanel?.refresh()]);}
  async function submit(){
    if(!validSource(state.source) || callbacks.isBusy())return;
    await callbacks.busy("transcribe",async()=>{
      const body={stored_filename:state.source,language:$("transcribe-language").value || null};
      await callbacks.api("/api/transcriptions/jobs",callbacks.jsonRequest("POST",body));callbacks.notice("已提交后台转写，可查询进度或取消。");await refreshJobs();
    },error=>callbacks.notice("转写提交失败："+error.message,true));
  }
  async function cancelJob(id){
    await callbacks.busy("cancel-transcription",async()=>{
      const job=await callbacks.api("/api/transcriptions/jobs/"+id+"/cancel",{method:"POST"});
      callbacks.notice(job.state==="cancelled"?"转写任务已取消。":job.state==="succeeded"?"结果已提交，任务已完成。":"取消请求已接受，正在等待进程清理。");await refreshJobs();
    },error=>callbacks.notice("取消失败："+error.message,true));
  }
  async function save(){
    if(callbacks.isBusy() || !state.saved || validation() || state.loading)return;
    const saved=state.saved,epoch=state.epoch,token=state.request,draft=copy(state.draft);
    const content={language:draft.language.trim(),segments:draft.segments.map(row=>({start:Number(row.start),end:Number(row.end),text:row.text.trim()}))};
    const body=saved.editable?{...content,expected_revision:saved.revision,expected_sha256:saved.sha256}:{...content,source_id:saved.id,expected_source_sha256:saved.sha256};
    state.saving=true;
    try{await callbacks.busy("save-transcript",async()=>{
      const doc=await callbacks.api(saved.editable?"/api/transcriptions/reviews/"+saved.id:"/api/transcriptions/reviews",callbacks.jsonRequest(saved.editable?"PATCH":"POST",body));
      if(state.disposed || token!==state.request || state.selected!==saved.id)return;
      state.saved=doc;state.selected=doc.id;state.base=draftFrom(doc);state.conflict=false;
      if(epoch===state.epoch)state.draft=copy(state.base);
      sync();renderDocument();renderRecords();refreshRecords();
      callbacks.notice(state.dirty?"已保存提交的版本；后续编辑仍在草稿中。":"校对已保存，原始识别保持不变。");
    },error=>{state.conflict=error.status===409;renderControls();callbacks.notice((state.conflict?"保存冲突，草稿已保留：":"校对保存失败：")+error.message,true);});}
    finally{state.saving=false;renderControls();}
  }
  function schedule(){
    clearTimeout(state.timer);
    if(!state.visible || state.disposed)return;
    const token=state.pollToken;
    state.timer=setTimeout(async()=>{await refreshJobs(token);if(token===state.pollToken)schedule();},1200);
  }
  function setVisible(visible){
    state.visible=visible;state.pollToken+=1;clearTimeout(state.timer);
    if(visible && !state.disposed){refresh();schedule();}else stopAudio();
  }
  function setSource(asset){
    if(!validSource(asset.stored_filename))return;
    state.source=asset.stored_filename;const select=$("transcribe-source");
    if(![...select.options].some(option=>option.value===state.source))select.add(new Option(asset.original_filename,state.source));
    select.value=state.source;renderControls();
  }
  $("transcribe-source").addEventListener("change",event=>{state.source=event.target.value;renderControls();});
  $("submit-transcription").addEventListener("click",submit);
  $("refresh-transcriptions").addEventListener("click",refresh);
  $("review-language").addEventListener("input",event=>{if(state.draft){state.draft.language=event.target.value;state.conflict=false;sync(true);}});
  $("add-transcript-segment").addEventListener("click",()=>{if(state.draft){const start=state.draft.segments.length?Number(state.draft.segments.at(-1).end):0;state.draft.segments.push({start:String(start),end:String(Math.min(start+1,state.saved.transcript.duration)),text:""});sync(true);renderRows();}});
  $("save-transcript").addEventListener("click",save);
  $("reload-transcript").addEventListener("click",()=>state.saved && openRecord(state.saved.id,true));
  $("transcript-audio").addEventListener("timeupdate",()=>{if(state.stopAt!==null && $("transcript-audio").currentTime>=state.stopAt)stopAudio();});
  window.addEventListener("pagehide",()=>{state.disposed=true;state.pollToken+=1;clearTimeout(state.timer);stopAudio();});
  datasetPanel=createDatasetPanel({...callbacks,review:()=>state.saved?{...state.saved,dirty:state.dirty,pending:state.loading || state.saving}:null});
  renderControls();
  return {renderControls,setVisible,setSource,hasDraft:()=>state.dirty,refresh};
}
