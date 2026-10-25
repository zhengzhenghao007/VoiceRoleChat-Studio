/* Audio assets and explicit microphone capture. No request on microphone init. */
export function createAudioLibrary(callbacks) {
  const $ = (id) => document.getElementById(id);
  const state = {assets:[],selected:null,request:0,phase:"idle",token:0,stream:null,recorder:null,
    blob:null,objectUrl:null,mime:"",started:0,timer:null,limit:null,disposed:false};
  const formats = ["audio/webm;codecs=opus","audio/ogg;codecs=opus","audio/mp4"];
  const mime = window.MediaRecorder ? formats.find((type) => MediaRecorder.isTypeSupported(type)) : null;
  const supported = Boolean(mime && navigator.mediaDevices?.getUserMedia);
  const element = (tag,cls,text) => {
    const node=document.createElement(tag); if(cls) node.className=cls;
    if(text !== undefined) node.textContent=text; return node;
  };
  const active = () => ["requesting","recording","stopping"].includes(state.phase);
  const selected = () => state.assets.find((asset) => asset.stored_filename === state.selected);
  const assetUrl = (url) => /^\/api\/voices\/[0-9a-f]{32}\.(wav|mp3|m4a|flac|ogg|webm)\/audio$/.test(url);
  const referencePath = (path) => /^uploads\/[0-9a-f]{32}\.wav$/.test(path);
  const direct = (asset) => asset && asset.validation_status === "validated" && asset.stored_filename.endsWith(".wav") &&
    asset.file_size <= 10*1024*1024 && asset.channels <= 2 && asset.duration_seconds >= 3 && asset.duration_seconds <= 10 &&
    ["pcm_u8","pcm_s16le","pcm_s24le","pcm_s32le"].includes(asset.codec);
  function phase(value) {
    state.phase=value;
    $("record-status").textContent = {idle:supported?"尚未录音":"当前浏览器不支持录音，请上传已有音频。",
      requesting:"正在请求麦克风",recording:"正在录音",stopping:"正在完成录音",preview:"录音完成",importing:"正在导入录音"}[value];
    callbacks.onRecordingChange(active()); renderControls();
  }
  function renderControls() {
    const locked=callbacks.isBusy() || active();
    for(const id of ["audio-upload","refresh-audio","inspect-audio","clip-start","clip-end","create-reference","use-reference"]) $(id).disabled=locked;
    for(const button of $("audio-library-list").querySelectorAll("button")) button.disabled=locked;
    $("inspect-audio").disabled=locked || !selected();
    $("transcribe-audio").disabled=locked || !selected();
    $("create-reference").disabled=locked || !selected() || (selected().duration_seconds !== null && selected().duration_seconds < 3);
    $("use-reference").disabled=locked || !direct(selected());
    $("record-start").disabled=!supported || locked || state.phase === "importing" || state.disposed;
    $("record-start").hidden=active();
    $("record-stop").hidden=!["recording","stopping"].includes(state.phase);
    $("record-stop").disabled=state.phase !== "recording";
    $("record-cancel").hidden=state.phase !== "requesting";
    $("record-import").disabled=callbacks.isBusy() || !state.blob || active();
    $("record-discard").disabled=callbacks.isBusy() || active();
  }
  function renderList() {
    const list=$("audio-library-list"); list.replaceChildren();
    for(const asset of state.assets) {
      const button=element("button","audio-select"); button.type="button";
      button.setAttribute("aria-label",asset.original_filename);
      button.setAttribute("aria-pressed",String(asset.stored_filename === state.selected));
      button.append(element("strong","",asset.original_filename));
      const detail=asset.validation_status === "validated" ? Number(asset.duration_seconds).toFixed(2)+" 秒，"+
        asset.sample_rate/1000+" kHz，"+asset.channels+" 声道" : "未检查，请检查后确认时长和格式";
      button.append(element("span","",detail+"，"+(asset.file_size/1024/1024).toFixed(2)+" MiB"));
      button.addEventListener("click",() => select(asset.stored_filename,true)); list.append(button);
    }
    $("audio-library-empty").hidden=state.assets.length>0 || !$("audio-library-error").hidden;
    renderControls();
  }
  function renderDetail(reset=false) {
    const asset=selected();
    $("source-empty").hidden=Boolean(asset); $("source-detail").hidden=!asset;
    if(!asset) {$("source-audio").pause();$("source-audio").removeAttribute("src");$("source-audio").load();return;}
    $("source-name").textContent=asset.original_filename;
    $("source-info").textContent=asset.file_path;
    if(assetUrl(asset.audio_url) && $("source-audio").getAttribute("src") !== asset.audio_url) {
      $("source-audio").pause(); $("source-audio").src=asset.audio_url;
    }
    $("source-validation").textContent=asset.validation_status === "validated" ?
      "已通过本地解码检查，时长 "+Number(asset.duration_seconds).toFixed(2)+" 秒。" : "旧音频尚未检查，原文件保持不变。";
    $("clip-hint").textContent=asset.duration_seconds !== null && asset.duration_seconds<3 ?
      "音频不足 3 秒，不能生成参考片段。" : "选择 3–10 秒的范围。片段会另存为新的 WAV。";
    if(reset) {$("clip-start").value="0";$("clip-end").value=String(Math.min(5,asset.duration_seconds || 5));}
    renderControls();
  }
  function select(filename,reset=false) {
    if(callbacks.isBusy() || active()) return;
    state.selected=filename; renderList();renderDetail(reset);
  }
  async function refresh() {
    const token=++state.request; $("audio-loading").hidden=false;
    try {
      const data=await callbacks.api("/api/voices");
      if(token !== state.request || state.disposed) return;
      state.assets=data.items; $("audio-library-error").hidden=true;
      if(state.selected && !selected()) state.selected=null;
      renderList();renderDetail();
    } catch(error) {
      if(token !== state.request || state.disposed) return;
      $("audio-library-error").hidden=false;$("audio-library-empty").hidden=true;
    } finally {if(token === state.request) $("audio-loading").hidden=true;}
  }
  async function storeFile(file,recording=false) {
    if(callbacks.isBusy() || active()) return;
    if(!file || !/\.(wav|mp3|m4a|flac|ogg|webm)$/i.test(file.name) || file.size<=0 || file.size>50*1024*1024) {
      callbacks.notice("请选择不超过 50 MiB 的非空音频文件。",true);return;
    }
    if(recording) phase("importing");
    await callbacks.busy("audio-upload",async () => {
      const body=new FormData();body.append("file",file);
      const result=await callbacks.api("/api/voices/upload",{method:"POST",body},180000);
      await refresh();state.selected=result.stored_filename;renderList();renderDetail(true);
      if(recording) {discard();callbacks.notice("录音已导入音频库");}
      else callbacks.notice("音频已通过解码检查并保存到音频库。");
    },error => {if(recording) phase("preview");callbacks.notice("音频导入失败："+error.message,true);});
  }
  async function inspect() {
    const asset=selected();if(!asset || callbacks.isBusy() || active()) return;
    await callbacks.busy("audio-inspect",async () => {
      await callbacks.api("/api/voices/"+asset.stored_filename+"/inspect",{method:"POST"},180000);
      await refresh();renderDetail(true);callbacks.notice("音频检查完成，原文件未改写。");
    },error=>callbacks.notice("检查失败："+error.message,true));
  }
  async function clip() {
    const asset=selected();if(!asset || callbacks.isBusy() || active()) return;
    const start=Number($("clip-start").value),end=Number($("clip-end").value);
    if(!Number.isFinite(start) || !Number.isFinite(end) || start<0 || end-start<3 || end-start>10 ||
        (asset.duration_seconds !== null && end>asset.duration_seconds)) {
      callbacks.notice("请在原音频时长内选择 3–10 秒的有限时间范围。",true);return;
    }
    await callbacks.busy("audio-reference",async () => {
      const result=await callbacks.api("/api/voices/"+asset.stored_filename+"/reference",
        callbacks.jsonRequest("POST",{start_seconds:start,end_seconds:end}),180000);
      if(!referencePath(result.reference_audio)) throw new Error("参考片段返回的路径无效");
      await refresh();state.selected=result.stored_filename;renderList();renderDetail(true);
      callbacks.notice("参考片段已生成，点击用于当前角色填入草稿。");
    },error=>callbacks.notice("生成片段失败："+error.message,true));
  }
  function useReference() {
    const asset=selected();
    if(callbacks.isBusy() || active() || !direct(asset) || !referencePath(asset.file_path)) return;
    callbacks.useReference(asset.file_path);
  }
  function release(stream=state.stream) {
    if(stream) for(const track of stream.getTracks()) track.stop();
    if(stream === state.stream) state.stream=null;
  }
  function timersOff() {clearInterval(state.timer);clearTimeout(state.limit);state.timer=state.limit=null;}
  function clearPreview() {
    $("record-preview").pause();$("record-preview").removeAttribute("src");$("record-preview").load();
    if(state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl=null;state.blob=null;$("record-preview-container").hidden=true;
  }
  function discard() {clearPreview();$("record-timer").textContent="";phase("idle");}
  function stop() {
    if(state.phase === "requesting") {
      state.token+=1;timersOff();release();phase("idle");callbacks.notice("已取消麦克风请求。");return;
    }
    if(state.phase !== "recording") return;
    phase("stopping");timersOff();
    try {if(state.recorder?.state !== "inactive") state.recorder.stop();}
    catch(error) {release();phase("idle");callbacks.notice("无法完成录音，请重新录制。",true);}
    finally {release();}
  }
  async function start() {
    if(!supported || callbacks.isBusy() || active() || state.disposed) return;
    if(state.blob && !window.confirm("放弃尚未导入的录音，重新录制？")) return;
    clearPreview();const token=++state.token;phase("requesting");
    let stream=null;
    try {
      stream=await navigator.mediaDevices.getUserMedia({audio:true});
      if(token !== state.token || state.disposed) {release(stream);return;}
      state.stream=stream;state.mime=mime;
      const recorder=new MediaRecorder(stream,{mimeType:mime});state.recorder=recorder;
      const chunks=[];let size=0,oversize=false;
      recorder.ondataavailable=(event)=>{
        if(event.data.size && token === state.token) {
          size+=event.data.size;
          if(size>50*1024*1024) {oversize=true;chunks.length=0;stop();return;}
          chunks.push(event.data);
        }
      };
      recorder.onerror=()=>{
        if(token !== state.token) return;
        state.token+=1;timersOff();release(stream);
        try {if(recorder.state !== "inactive") recorder.stop();} catch(error) { /* release already done */ }
        state.recorder=null;phase("idle");callbacks.notice("录音失败，请检查设备后重试。",true);
      };
      recorder.onstop=()=>{
        timersOff();release(stream);state.recorder=null;
        if(token !== state.token || state.disposed) return;
        if(oversize || !chunks.length || !size) {
          phase("idle");callbacks.notice(oversize ? "录音超过 50 MiB 限制，请缩短后重试。" : "录音为空，请重新录制。",true);return;
        }
        state.blob=new Blob(chunks,{type:recorder.mimeType || mime});
        state.objectUrl=URL.createObjectURL(state.blob);
        $("record-preview").src=state.objectUrl;$("record-preview-container").hidden=false;
        phase("preview");callbacks.notice("录音完成。可先试听，点击导入录音后才会保存。");
      };
      state.started=performance.now();recorder.start(250);phase("recording");
      $("record-timer").textContent="0 秒，最长 180 秒";
      state.timer=setInterval(()=>{$("record-timer").textContent=Math.min(180,Math.floor((performance.now()-state.started)/1000))+" 秒，最长 180 秒";},1000);
      state.limit=setTimeout(()=>{stop();callbacks.notice("已达到 180 秒上限，录音已自动停止。");},180000);
    } catch(error) {
      release(stream);
      if(token !== state.token || state.disposed) return;
      phase("idle");callbacks.notice(error.name === "NotAllowedError" ? "麦克风权限被拒绝，可上传已有音频。" : "无法使用麦克风，请检查设备或上传音频。",true);
    }
  }
  async function importRecording() {
    if(!state.blob || callbacks.isBusy() || active()) return;
    const extension=state.blob.type.startsWith("audio/ogg") ? "ogg" : state.blob.type.startsWith("audio/mp4") ? "m4a" : "webm";
    await storeFile(new File([state.blob],"recording."+extension,{type:state.blob.type}),true);
  }
  function dispose() {
    state.disposed=true;state.token+=1;timersOff();
    try {if(state.recorder && state.recorder.state !== "inactive") state.recorder.stop();} catch(error) { /* tracks still released */ }
    release();clearPreview();callbacks.onRecordingChange(false);
  }
  $("audio-upload").addEventListener("change",event=>{const file=event.target.files[0];event.target.value="";if(file)storeFile(file);});
  $("refresh-audio").addEventListener("click",refresh);
  $("inspect-audio").addEventListener("click",inspect);
  $("transcribe-audio").addEventListener("click",()=>{if(selected() && !callbacks.isBusy() && !active())callbacks.transcribe(selected());});
  $("create-reference").addEventListener("click",clip);
  $("use-reference").addEventListener("click",useReference);
  $("record-start").addEventListener("click",start);
  $("record-stop").addEventListener("click",stop);
  $("record-cancel").addEventListener("click",stop);
  $("record-import").addEventListener("click",importRecording);
  $("record-discard").addEventListener("click",discard);
  $("source-audio").addEventListener("error",()=>{if(selected())callbacks.notice("浏览器暂时无法直接播放此格式，可生成 WAV 参考片段试听。",true);});
  window.addEventListener("pagehide",dispose);
  phase("idle");renderList();renderDetail();
  return {refresh,renderControls,dispose,hasPendingRecording:()=>active() || Boolean(state.blob)};
}
