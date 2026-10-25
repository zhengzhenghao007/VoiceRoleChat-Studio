/* Build only from saved reviews; no training or implicit saves. */
export function createDatasetPanel(callbacks){
  const $=id=>document.getElementById(id);
  const state={roleKey:"",building:false,request:0,disposed:false};
  const node=(tag,cls,text)=>{const result=document.createElement(tag);if(cls)result.className=cls;if(text!==undefined)result.textContent=text;return result;};
  const eligible=()=>{const record=callbacks.review();return record?.editable && !record.dirty && !record.pending;};
  function renderControls(){
    const roles=callbacks.characters(),key=JSON.stringify(roles.map(role=>[role.id,role.name]));
    if(key!==state.roleKey){
      const selected=$("dataset-character").value;$("dataset-character").replaceChildren(new Option("请选择角色",""));
      for(const role of roles)$("dataset-character").add(new Option(role.name,role.id));
      $("dataset-character").value=selected;state.roleKey=key;
    }
    const ready=eligible(),busy=callbacks.isBusy();
    $("dataset-character").disabled=busy || !ready;$("dataset-name").disabled=busy || !ready;$("refresh-datasets").disabled=busy;
    $("build-segmented-dataset").disabled=busy || !ready || !$("dataset-character").value || !/^[A-Za-z0-9_-]{1,100}$/.test($("dataset-name").value.trim());
    $("build-segmented-dataset").textContent=state.building?"正在生成切片…":"生成分段数据集";
    const record=callbacks.review();$("dataset-eligibility").textContent=!record?.editable?"请先保存独立校对副本。":!ready?"请先保存当前校对修改。":"使用已保存校对修订 "+record.revision+"；本操作不启动训练。";
  }
  function warningText(value){
    const words={short_clip:"短于1秒",long_clip:"长于10秒",quiet_clip:"音量偏低",clipping:"峰值接近削波",legacy_unverified:"旧数据集尚未按新规范验证"};
    const [part,reason]=String(value).split(":");return reason?part.replace("segment_","片段 ")+"："+(words[reason] || reason):words[part] || part;
  }
  async function refresh(){
    const request=++state.request;
    try{
      const data=await callbacks.api("/api/datasets");if(state.disposed || request!==state.request)return;
      $("dataset-library-error").hidden=true;$("dataset-library-diagnostics").textContent=data.diagnostics.length?data.diagnostics.length+" 份异常或未知版本记录已保留。":"";
      const list=$("dataset-library-list");list.replaceChildren();
      for(const dataset of data.items){
        const card=node("article","dataset-card");card.dataset.datasetName=dataset.dataset_name;card.append(node("strong","",dataset.dataset_name));
        const count=Number.isInteger(dataset.entry_count)?dataset.entry_count+" 个片段":"旧数据集，条目未验证";
        const duration=typeof dataset.total_duration==="number" && Number.isFinite(dataset.total_duration)?" · "+dataset.total_duration.toFixed(3)+" 秒":"";
        card.append(node("p","small muted",count+duration+" · "+(dataset.language || "语言未验证")));
        for(const value of Array.isArray(dataset.warnings)?dataset.warnings:[])card.append(node("p","small muted",warningText(value)));
        list.append(card);
      }
      $("dataset-library-empty").hidden=data.items.length>0;
    }catch(error){if(!state.disposed && request===state.request)$("dataset-library-error").hidden=false;}
  }
  async function build(){
    if(!eligible() || callbacks.isBusy() || $("build-segmented-dataset").disabled)return;
    const review=callbacks.review(),name=$("dataset-name").value.trim(),character=$("dataset-character").value;
    state.building=true;$("dataset-build-status").className="small muted";$("dataset-build-status").textContent=name+"：正在解码并生成切片…";$("dataset-build-result").hidden=true;
    try{await callbacks.busy("build-dataset",async()=>{
      const manifest=await callbacks.api("/api/datasets/segments",callbacks.jsonRequest("POST",{character_id:character,review_id:review.id,expected_revision:review.revision,expected_sha256:review.sha256,dataset_name:name}),660000);
      if(state.disposed)return;
      $("dataset-build-status").textContent=manifest.dataset_name+"：已生成 "+manifest.entry_count+" 个片段，总时长 "+manifest.total_duration.toFixed(3)+" 秒。";
      const result=$("dataset-build-result");result.replaceChildren(node("p","small muted",manifest.annotation_file));
      for(const value of manifest.warnings)result.append(node("p","small muted",warningText(value)));
      result.hidden=false;callbacks.notice("分段数据集已生成，原音与已有数据集保持不变。");await refresh();
    },error=>{
      if(state.disposed)return;
      $("dataset-build-status").className="error-text";$("dataset-build-status").textContent=name+"：构建失败，"+error.message;
      callbacks.notice("数据集构建失败，校对内容已保留。",true);
    });}finally{state.building=false;renderControls();}
  }
  $("dataset-character").addEventListener("change",renderControls);$("dataset-name").addEventListener("input",renderControls);
  $("build-segmented-dataset").addEventListener("click",build);$("refresh-datasets").addEventListener("click",refresh);
  window.addEventListener("pagehide",()=>{state.disposed=true;state.request+=1;});renderControls();return {renderControls,refresh};
}
